from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from sqlalchemy import case, false, func, select, true
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.entities import Agency, Agent, DailyMetric, ImportBatch, LoanRaw, User
from app.models.enums import ImportBatchType, UserRole
from app.api.v1.metrics import client_potentially_radiable_subquery, calculate_potentially_radiable_threshold
from app.schemas.domain import SnapshotOptionRead
from app.services.agent_identity import normalized_agent_name_expression
from app.services.data_scope import get_user_data_scope, region_scope_condition
from app.services.committee_access import normalize_committee_historical_request
from app.services.portfolio_identity import matching_agent_ids_query, user_portfolio_identity_key
from app.services.selection import normalize_agency_ids

try:
    import arabic_reshaper
except Exception:  # pragma: no cover - optional dependency
    arabic_reshaper = None

try:
    from bidi.algorithm import get_display as bidi_get_display
except Exception:  # pragma: no cover - optional dependency
    bidi_get_display = None

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)])

PortfolioReportType = Literal["arrears_list", "renewal_candidates", "future_schedules", "potential_radiation"]
ColumnSpec = tuple[str, str, str]

HEADER_BG = PatternFill("solid", fgColor="1E3A8A")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FILL = PatternFill("solid", fgColor="0B1220")
TITLE_FONT = Font(color="FFFFFF", bold=True, size=14)
ALT_ROW_FILL = PatternFill("solid", fgColor="F8FAFC")
THIN_BORDER = Border(
    left=Side(style="thin", color="D1D5DB"),
    right=Side(style="thin", color="D1D5DB"),
    top=Side(style="thin", color="D1D5DB"),
    bottom=Side(style="thin", color="D1D5DB"),
)
_PDF_ARABIC_FONT_CACHE: str | None = None
_PDF_ARABIC_FONT_NAME = "MicroCredArabic"
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
ARABIC_WORD_RE = re.compile(r"^[\u0600-\u06FF]+$")
ARABIC_SUSPICIOUS_STARTS = {"ة", "ى", "ئ", "ؤ", "ء"}
ARABIC_COMMON_PREFIXES = ("ال", "لل", "ب", "و", "ف", "ك", "ل", "م", "ت", "ي", "ن", "ا")
ARABIC_COMMON_SUFFIXES = ("ة", "ات", "ية", "ون", "ين", "ي", "ى", "ه", "ها", "هم", "كم", "نا")
CATEGORY_DESC_CORRECTIONS = {
    "ةيليمجتلا تامدخلل يعورشم": "مشروعي للخدمات التجميلية",
    "ةيشاملا ةيبرتل يعورشم": "مشروعي للخدمات médicales",
}


def _agent_join_condition():
    return (
        (normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name))
        & (Agent.agency_id == Agency.id)
    )


def _active_metrics_snapshot_scope(db: Session) -> tuple[date | None, object | None]:
    current_batch = _latest_current_batch(db)
    if current_batch:
        return current_batch.snapshot_date, LoanRaw.import_batch_id == current_batch.id

    has_batch_metadata = (db.scalar(select(func.count(ImportBatch.id))) or 0) > 0
    if has_batch_metadata:
        return None, None

    latest_snapshot = db.scalar(select(func.max(LoanRaw.snapshot_date)))
    if latest_snapshot is None:
        return None, None
    return latest_snapshot, LoanRaw.snapshot_date == latest_snapshot


def _metrics_flow_condition(date_from: date | None, date_to: date | None):
    condition = true()
    if date_from:
        condition = condition & (LoanRaw.disbursement_date >= date_from)
    if date_to:
        condition = condition & (LoanRaw.disbursement_date <= date_to)
    return condition


def _metrics_stock_condition(date_to: date | None):
    condition = true()
    if date_to:
        condition = condition & (LoanRaw.disbursement_date <= date_to)
    return condition


def _metrics_scope_filters(
    db: Session,
    user: User,
    scope_filter: object,
    agency_id: int | None,
    agent_id: int | None,
) -> list[object]:
    scope = get_user_data_scope(user)
    filters: list[object] = [scope_filter]
    regional_condition = region_scope_condition(Agency.name, scope.region)
    if regional_condition is not None:
        filters.append(regional_condition)

    if scope.role == UserRole.AGENCY_MANAGER:
        if scope.agency_id is None:
            return [false()]
        filters.append(Agency.id == scope.agency_id)
    elif scope.role == UserRole.PORTFOLIO_MANAGER:
        if scope.agent_id is None:
            return [false()]
        identity_key = user_portfolio_identity_key(db, user)
        if not identity_key:
            return [false()]
        filters.append(Agent.id.in_(matching_agent_ids_query(identity_key)))

    if agency_id and scope.role != UserRole.PORTFOLIO_MANAGER:
        if not db.get(Agency, agency_id):
            return [false()]
        filters.append(Agency.id == agency_id)

    if agent_id:
        selected_agent = db.get(Agent, agent_id)
        if not selected_agent:
            return [false()]
        if scope.role == UserRole.PORTFOLIO_MANAGER:
            identity_key = user_portfolio_identity_key(db, user)
            is_allowed = db.scalar(
                select(func.count(Agent.id)).where(
                    Agent.id == selected_agent.id,
                    normalized_agent_name_expression(Agent.name) == identity_key,
                )
            )
            if not is_allowed:
                return [false()]
        else:
            filters.append(Agent.id == agent_id)
    return filters


def _to_decimal_safe(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _ratio_decimal(numerator: Decimal | int | float, denominator: Decimal | int | float) -> Decimal:
    den = _to_decimal_safe(denominator)
    if not den:
        return Decimal("0")
    return (_to_decimal_safe(numerator) / den).quantize(Decimal("0.0001"))


def _metric_payload_from_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    outstanding = _to_decimal_safe(mapping.get("outstanding"))
    payload = {
        "disbursement_count": int(mapping.get("disbursement_count") or 0),
        "nb_clients": int(mapping.get("nb_clients") or 0),
        "disbursement_volume": _to_decimal_safe(mapping.get("disbursement_volume")),
        "outstanding": outstanding,
        "healthy_outstanding": _to_decimal_safe(mapping.get("healthy_outstanding")),
        "par_0": _to_decimal_safe(mapping.get("par_0")),
        "par_1_30": _to_decimal_safe(mapping.get("par_1_30")),
        "par_31_60": _to_decimal_safe(mapping.get("par_31_60")),
        "par_61_90": _to_decimal_safe(mapping.get("par_61_90")),
        "par_91_120": _to_decimal_safe(mapping.get("par_91_120")),
        "par_120": _to_decimal_safe(mapping.get("par_120")),
        "par_30": _to_decimal_safe(mapping.get("par_30")),
    }
    payload["healthy_rate"] = _ratio_decimal(payload["healthy_outstanding"], outstanding)
    payload["par_0_rate"] = _ratio_decimal(payload["par_0"], outstanding)
    payload["par_1_30_rate"] = _ratio_decimal(payload["par_1_30"], outstanding)
    payload["par_31_60_rate"] = _ratio_decimal(payload["par_31_60"], outstanding)
    payload["par_61_90_rate"] = _ratio_decimal(payload["par_61_90"], outstanding)
    payload["par_91_120_rate"] = _ratio_decimal(payload["par_91_120"], outstanding)
    payload["par_120_rate"] = _ratio_decimal(payload["par_120"], outstanding)
    payload["par_30_rate"] = _ratio_decimal(payload["par_30"], outstanding)
    return payload


def _metrics_export_sections(
    db: Session,
    user: User,
    agency_id: int | None,
    agent_id: int | None,
    date_from: date | None,
    date_to: date | None,
) -> list[dict[str, Any]]:
    if user.role == UserRole.COMMITTEE_MEMBER:
        date_from, date_to, batch = normalize_committee_historical_request(
            db,
            user,
            date_from,
            date_to,
        )
        if batch is None or batch.snapshot_date is None:
            return []
        snapshot_date = batch.snapshot_date
        scope_filter = LoanRaw.import_batch_id == batch.id
    else:
        snapshot_date, scope_filter = _active_metrics_snapshot_scope(db)
        if snapshot_date is None or scope_filter is None:
            return []

    filters = _metrics_scope_filters(
        db=db,
        user=user,
        scope_filter=scope_filter,
        agency_id=agency_id,
        agent_id=agent_id,
    )
    if not filters:
        return []

    exposure = LoanRaw.principal_outstanding + LoanRaw.principal_due
    flow_condition = _metrics_flow_condition(date_from, date_to)
    stock_condition = _metrics_stock_condition(date_to)
    is_healthy = LoanRaw.days_overdue == 0
    is_par_0 = LoanRaw.days_overdue > 0
    is_par_1_30 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 30)
    is_par_31_60 = (LoanRaw.days_overdue >= 31) & (LoanRaw.days_overdue <= 60)
    is_par_61_90 = (LoanRaw.days_overdue > 60) & (LoanRaw.days_overdue <= 90)
    is_par_91_120 = (LoanRaw.days_overdue > 90) & (LoanRaw.days_overdue <= 120)
    is_par_120 = (LoanRaw.days_overdue > 120) & (LoanRaw.days_overdue < 365)
    is_par_30 = LoanRaw.days_overdue > 30

    aggregate_columns = [
        func.coalesce(func.sum(case((flow_condition, 1), else_=0)), 0).label("disbursement_count"),
        func.count(func.distinct(case((stock_condition, LoanRaw.client_id), else_=None))).label("nb_clients"),
        func.coalesce(func.sum(case((flow_condition, LoanRaw.disbursement_amount), else_=0)), 0).label("disbursement_volume"),
        func.coalesce(func.sum(case((stock_condition, exposure), else_=0)), 0).label("outstanding"),
        func.coalesce(func.sum(case((stock_condition & is_healthy, exposure), else_=0)), 0).label("healthy_outstanding"),
        func.coalesce(func.sum(case((stock_condition & is_par_0, exposure), else_=0)), 0).label("par_0"),
        func.coalesce(func.sum(case((stock_condition & is_par_1_30, exposure), else_=0)), 0).label("par_1_30"),
        func.coalesce(func.sum(case((stock_condition & is_par_31_60, exposure), else_=0)), 0).label("par_31_60"),
        func.coalesce(func.sum(case((stock_condition & is_par_61_90, exposure), else_=0)), 0).label("par_61_90"),
        func.coalesce(func.sum(case((stock_condition & is_par_91_120, exposure), else_=0)), 0).label("par_91_120"),
        func.coalesce(func.sum(case((stock_condition & is_par_120, exposure), else_=0)), 0).label("par_120"),
        func.coalesce(func.sum(case((stock_condition & is_par_30, exposure), else_=0)), 0).label("par_30"),
    ]

    base_query = (
        select()
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(*filters)
    )

    agency_rows = db.execute(
        base_query.with_only_columns(
            Agency.id.label("agency_id"),
            Agency.name.label("agency_name"),
            *aggregate_columns,
        )
        .group_by(Agency.id, Agency.name)
        .order_by(Agency.name.asc())
    ).mappings().all()

    agent_rows = db.execute(
        base_query.with_only_columns(
            Agency.id.label("agency_id"),
            Agency.name.label("agency_name"),
            Agent.id.label("agent_id"),
            Agent.name.label("agent_name"),
            *aggregate_columns,
        )
        .group_by(Agency.id, Agency.name, Agent.id, Agent.name)
        .order_by(Agency.name.asc(), Agent.name.asc())
    ).mappings().all()

    sections_by_agency: dict[int, dict[str, Any]] = {}
    for row in agency_rows:
        agency_id_value = int(row["agency_id"])
        sections_by_agency[agency_id_value] = {
            "agency_id": agency_id_value,
            "agency_name": row["agency_name"],
            "summary": _metric_payload_from_mapping(dict(row)),
            "agents": [],
        }

    for row in agent_rows:
        agency_id_value = int(row["agency_id"])
        section = sections_by_agency.get(agency_id_value)
        if section is None:
            section = {
                "agency_id": agency_id_value,
                "agency_name": row["agency_name"],
                "summary": _metric_payload_from_mapping(dict(row)),
                "agents": [],
            }
            sections_by_agency[agency_id_value] = section

        payload = _metric_payload_from_mapping(dict(row))
        payload["agent_name"] = row["agent_name"]
        section["agents"].append(payload)

    sections = sorted(sections_by_agency.values(), key=lambda item: str(item["agency_name"]).lower())
    for section in sections:
        section["agents"] = sorted(section["agents"], key=lambda item: str(item.get("agent_name") or "").lower())
    return sections


def _metrics_export_columns() -> list[ColumnSpec]:
    return [
        ("scope_label", "NIVEAU", "text"),
        ("agency_name", "AGENCE", "text"),
        ("agent_name", "AGENT", "text"),
        ("nb_clients", "CLIENT ACTIF", "int"),
        ("disbursement_count", "NB DE CREDITS", "int"),
        ("disbursement_volume", "VOLUME DECAISSE", "money"),
        ("outstanding", "ENCOURS", "money"),
        ("healthy_outstanding", "ENCOURS SAIN", "money"),
        ("healthy_rate", "ENCOURS SAIN %", "percent"),
        ("par_0", "PAR0", "money"),
        ("par_0_rate", "PAR0 %", "percent"),
        ("par_1_30", "1-30", "money"),
        ("par_1_30_rate", "1-30 %", "percent"),
        ("par_31_60", "31-60", "money"),
        ("par_31_60_rate", "31-60 %", "percent"),
        ("par_61_90", "61-90", "money"),
        ("par_61_90_rate", "61-90 %", "percent"),
        ("par_91_120", "91-120", "money"),
        ("par_91_120_rate", "91-120 %", "percent"),
        ("par_120", "PAR120", "money"),
        ("par_120_rate", "PAR120 %", "percent"),
        ("par_30", "PAR30", "money"),
        ("par_30_rate", "PAR30 %", "percent"),
    ]


def _styled_excel_metrics_by_agency_buffer(
    title: str,
    subtitle: str,
    columns: list[ColumnSpec],
    sections: list[dict[str, Any]],
) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Metrics Dashboard"

    max_col = len(columns)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
    sheet["A1"] = title
    sheet["A1"].fill = TITLE_FILL
    sheet["A1"].font = TITLE_FONT
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 28

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max_col)
    sheet["A2"] = subtitle
    sheet["A2"].font = Font(size=10, color="334155")
    sheet["A2"].alignment = Alignment(horizontal="left", vertical="center")

    sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=max_col)
    sheet["A3"] = f"Generation: {datetime_to_string(datetime=date.today())}"
    sheet["A3"].font = Font(size=9, color="64748B")
    sheet["A3"].alignment = Alignment(horizontal="left", vertical="center")

    if not sections:
        sheet.merge_cells(start_row=5, start_column=1, end_row=5, end_column=max_col)
        sheet["A5"] = "Aucune donnee disponible pour les filtres selectionnes."
        sheet["A5"].font = Font(color="64748B", italic=True)
        sheet["A5"].alignment = Alignment(horizontal="left", vertical="center")
        _fit_column_widths(sheet)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return buffer

    section_fill = PatternFill("solid", fgColor="DBEAFE")
    section_font = Font(color="0F172A", bold=True, size=11)
    summary_fill = PatternFill("solid", fgColor="EEF2FF")
    summary_font = Font(color="1E3A8A", bold=True)

    row_index = 5
    header_positions: list[int] = []
    for section in sections:
        sheet.merge_cells(start_row=row_index, start_column=1, end_row=row_index, end_column=max_col)
        section_cell = sheet.cell(row=row_index, column=1, value=f"Agence: {section['agency_name']}")
        section_cell.fill = section_fill
        section_cell.font = section_font
        section_cell.alignment = Alignment(horizontal="left", vertical="center")
        row_index += 1

        header_positions.append(row_index)
        for col_index, (_key, label, _value_type) in enumerate(columns, start=1):
            cell = sheet.cell(row=row_index, column=col_index, value=label)
            cell.fill = HEADER_BG
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = THIN_BORDER
        sheet.row_dimensions[row_index].height = 24
        row_index += 1

        section_rows = [
            {
                "scope_label": "AGENCE",
                "agency_name": section["agency_name"],
                "agent_name": "-",
                **section["summary"],
            },
            *[
                {
                    "scope_label": "AGENT",
                    "agency_name": section["agency_name"],
                    "agent_name": agent_row.get("agent_name") or "-",
                    **agent_row,
                }
                for agent_row in section["agents"]
            ],
        ]

        for row_offset, payload in enumerate(section_rows):
            is_summary = row_offset == 0
            for col_index, (key, _label, value_type) in enumerate(columns, start=1):
                value = payload.get(key)
                cell = sheet.cell(row=row_index, column=col_index, value=value)
                cell.border = THIN_BORDER
                if is_summary:
                    cell.fill = summary_fill
                    cell.font = summary_font
                elif row_index % 2 == 0:
                    cell.fill = ALT_ROW_FILL

                if value_type == "money":
                    cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif value_type == "int":
                    cell.number_format = "0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif value_type == "percent":
                    cell.number_format = "0.00%"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif value_type == "date":
                    cell.number_format = "DD/MM/YYYY"
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")
            row_index += 1

        row_index += 1

    first_header_row = header_positions[0] if header_positions else 6
    sheet.freeze_panes = f"A{first_header_row + 1}"
    _fit_column_widths(sheet)
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def _styled_pdf_metrics_by_agency_buffer(
    title: str,
    subtitle: str,
    columns: list[ColumnSpec],
    sections: list[dict[str, Any]],
) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=18,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MetricsTitleStyle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "MetricsSubtitleStyle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "MetricsSectionStyle",
        parent=styles["Heading4"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=8,
        spaceAfter=6,
    )
    elements: list[Any] = [
        Paragraph(title, title_style),
        Paragraph(subtitle, subtitle_style),
        Paragraph(f"Generation: {datetime_to_string(date.today())}", subtitle_style),
        Spacer(1, 8),
    ]

    if not sections:
        elements.append(
            Paragraph(
                "Aucune donnee disponible pour les filtres selectionnes.",
                subtitle_style,
            )
        )
        doc.build(elements)
        buffer.seek(0)
        return buffer

    percent_keys = {key for key, _label, value_type in columns if value_type == "percent"}

    def _display_value(key: str, raw_value: Any, value_type: str) -> str:
        if value_type == "money":
            return _format_money(raw_value)
        if value_type == "int":
            try:
                return str(int(raw_value or 0))
            except (TypeError, ValueError):
                return "0"
        if value_type == "percent":
            ratio = float(raw_value or 0)
            return f"{ratio * 100:,.2f}%".replace(",", " ").replace(".", ",")
        if value_type == "date":
            return _format_date(raw_value)
        if raw_value is None or raw_value == "":
            return "-"
        return " ".join(str(raw_value).split())

    def _metrics_column_chunks() -> list[list[ColumnSpec]]:
        # Keep identity columns always visible and split wide metric sets horizontally.
        if len(columns) <= 12:
            return [columns]
        identity = columns[:3]
        metrics = columns[3:]
        chunk_size = 8
        chunks: list[list[ColumnSpec]] = []
        for idx in range(0, len(metrics), chunk_size):
            chunks.append([*identity, *metrics[idx : idx + chunk_size]])
        return chunks

    def _chunk_col_widths(total_width: float, chunk_columns: list[ColumnSpec]) -> list[float]:
        # Weights tuned for readability while forcing exact fit in page width.
        weights: list[float] = []
        for key, _label, value_type in chunk_columns:
            if key == "scope_label":
                weights.append(0.9)
            elif key == "agency_name":
                weights.append(1.9)
            elif key == "agent_name":
                weights.append(1.9)
            elif value_type == "money":
                weights.append(1.2)
            elif value_type == "percent":
                weights.append(0.95)
            elif value_type == "int":
                weights.append(0.9)
            else:
                weights.append(1.0)
        total_weight = sum(weights) or 1.0
        return [total_width * (weight / total_weight) for weight in weights]

    column_chunks = _metrics_column_chunks()
    for section in sections:
        elements.append(Paragraph(f"Agence: {section['agency_name']}", section_style))

        section_rows = [
            {
                "scope_label": "AGENCE",
                "agency_name": section["agency_name"],
                "agent_name": "-",
                **section["summary"],
            },
            *[
                {
                    "scope_label": "AGENT",
                    "agency_name": section["agency_name"],
                    "agent_name": agent_row.get("agent_name") or "-",
                    **agent_row,
                }
                for agent_row in section["agents"]
            ],
        ]

        for chunk_index, chunk_columns in enumerate(column_chunks, start=1):
            if len(column_chunks) > 1:
                elements.append(
                    Paragraph(
                        f"Bloc colonnes {chunk_index}/{len(column_chunks)}",
                        ParagraphStyle(
                            "ChunkHint",
                            parent=styles["BodyText"],
                            fontName="Helvetica-Bold",
                            fontSize=8,
                            textColor=colors.HexColor("#64748B"),
                            spaceAfter=4,
                        ),
                    )
                )

            # Admin/Super Admin requirement: PDF headers in lowercase for wide tables.
            table_data = [[str(label).lower() for _key, label, _value_type in chunk_columns]]
            for payload in section_rows:
                table_data.append(
                    [
                        _display_value(key, payload.get(key), value_type)
                        for key, _label, value_type in chunk_columns
                    ]
                )

            # Slightly smaller headers/body to improve fit without harming readability.
            header_font_size = 7.6 if len(chunk_columns) > 10 else 8.4
            body_font_size = 7.0 if len(chunk_columns) > 10 else 7.8
            table = Table(
                table_data,
                repeatRows=1,
                colWidths=_chunk_col_widths(doc.width, chunk_columns),
            )
            style_commands = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), header_font_size),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), body_font_size),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#EEF2FF")),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#1E3A8A")),
            ]
            for idx, (key, _label, value_type) in enumerate(chunk_columns):
                if value_type in {"money", "int"} or key in percent_keys:
                    style_commands.append(("ALIGN", (idx, 1), (idx, -1), "RIGHT"))
                else:
                    style_commands.append(("ALIGN", (idx, 1), (idx, -1), "LEFT"))

            for data_row_idx in range(2, len(table_data)):
                if data_row_idx % 2 == 0:
                    style_commands.append(("BACKGROUND", (0, data_row_idx), (-1, data_row_idx), colors.HexColor("#F8FAFC")))
            table.setStyle(TableStyle(style_commands))
            elements.append(table)
            elements.append(Spacer(1, 8))

        elements.append(Spacer(1, 4))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def _latest_current_batch(db: Session) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch)
        .where(ImportBatch.batch_type == ImportBatchType.CURRENT_STATE)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )


def _current_mcr_filter(db: Session):
    current_batch = _latest_current_batch(db)
    if current_batch:
        return LoanRaw.import_batch_id == current_batch.id

    latest_snapshot = db.scalar(select(func.max(LoanRaw.snapshot_date)))
    if latest_snapshot is None:
        return None
    return LoanRaw.snapshot_date == latest_snapshot


def _portfolio_scope_filters(
    db: Session,
    user: User,
    agency_id: int | None = None,
    agent_id: int | None = None,
    agency_ids: list[int] | None = None,
) -> list[object]:
    scope = get_user_data_scope(user)
    filters: list[object] = []
    regional_condition = region_scope_condition(Agency.name, scope.region)
    if regional_condition is not None:
        filters.append(regional_condition)

    if scope.role == UserRole.AGENCY_MANAGER:
        if scope.agency_id is None:
            return [false()]
        filters.append(Agency.id == scope.agency_id)
    elif scope.role == UserRole.PORTFOLIO_MANAGER:
        if scope.agent_id is None:
            return [false()]
        identity_key = user_portfolio_identity_key(db, user)
        if not identity_key:
            return [false()]
        filters.append(Agent.id.in_(matching_agent_ids_query(identity_key)))

    selected_agency_ids = list(agency_ids) if agency_ids else ([agency_id] if agency_id else [])
    if selected_agency_ids and scope.role != UserRole.PORTFOLIO_MANAGER:
        if any(not db.get(Agency, agency_id_item) for agency_id_item in selected_agency_ids):
            return [false()]
        if len(selected_agency_ids) == 1:
            filters.append(Agency.id == selected_agency_ids[0])
        else:
            filters.append(Agency.id.in_(selected_agency_ids))

    if agent_id:
        selected_agent = db.get(Agent, agent_id)
        if not selected_agent:
            return [false()]
        if scope.role == UserRole.PORTFOLIO_MANAGER and scope.agent_id is not None:
            identity_key = user_portfolio_identity_key(db, user)
            is_allowed = db.scalar(
                select(func.count(Agent.id)).where(
                    Agent.id == selected_agent.id,
                    normalized_agent_name_expression(Agent.name) == identity_key,
                )
            )
            if not is_allowed:
                return [false()]
        else:
            filters.append(Agent.id == agent_id)

    return filters


def _regional_default_agency_ids(db: Session, user: User) -> list[int]:
    """Resolve the report's implicit “all agencies” within a regional role."""
    scope = get_user_data_scope(user)
    regional_condition = region_scope_condition(Agency.name, scope.region)
    if regional_condition is None:
        return []
    return db.scalars(select(Agency.id).where(regional_condition).order_by(Agency.id)).all()


def _portfolio_report_base_rows(
    db: Session,
    user: User,
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    agency_ids: list[int] | None = None,
) -> list[LoanRaw]:
    current_scope_filter = _current_mcr_filter(db)
    if current_scope_filter is None:
        return []

    filters = [current_scope_filter]
    filters.extend(_portfolio_scope_filters(db, user, agency_id, agent_id, agency_ids=agency_ids))
    if date_from:
        filters.append(LoanRaw.disbursement_date >= date_from)
    if date_to:
        filters.append(LoanRaw.disbursement_date <= date_to)

    query = (
        select(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(*filters)
        .order_by(LoanRaw.agent_name.asc(), LoanRaw.disbursement_date.asc(), LoanRaw.contract_no.asc())
    )
    return db.scalars(query).all()


def _normalized_rating(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _is_renewal_rating(value: str | None) -> bool:
    normalized = _normalized_rating(value)
    return normalized in {"classe 0", "classe0", "class 0", "class0", "0", "classe 1", "classe1", "class 1", "class1", "1"}


def _portfolio_report_definition(
    report_type: PortfolioReportType,
    future_days: int | None,
) -> tuple[str, str, list[ColumnSpec], callable]:
    today = date.today()
    if report_type == "arrears_list":
        return (
            "Liste des impayees",
            "Criteres: TOTAL_CUR_NO_OF_DAYS_OVERDUE > 2 (MCR actuel)",
            [
                ("client_id", "CLIENT NO", "text"),
                ("client_name", "CLIENT NAME", "text"),
                ("client_first_name", "CLIENT FIRST NAME", "text"),
                ("total_due_amt", "TOTAL DUE AMT", "money"),
                ("total_scheduled_amount", "Échéance principal", "money"),
                ("total_principal_due_amt", "TOTAL PRINCIPAL DUE AMT", "money"),
                ("total_interest_due_amt", "TOTAL INTEREST DUE AMT", "money"),
                ("days_overdue", "JOURS DE RETARD", "int"),
                ("encours", "ENCOURS", "money"),
                ("repayment_rate", "TAUX DE REMBOURSEMENT", "percent_raw"),
            ],
            lambda row: int(row.days_overdue or 0) > 0,
        )

    if report_type == "renewal_candidates":
        limit_date = today + timedelta(days=90)
        return (
            "Liste possibilite de renouvellement",
            "Criteres: MATURITY_DATE dans 3 mois et CLIENT_RATING Classe 0/1 (MCR actuel)",
            [
                ("client_id", "CLIENT NO", "text"),
                ("client_name", "CLIENT NAME", "text"),
                ("client_first_name", "CLIENT FIRST NAME", "text"),
                ("category_desc", "CATEGORY DESC", "text"),
                ("disbursement_amount", "DISBURSEMENT AMOUNT", "money"),
                ("maturity_date", "MATURITY DATE", "date"),
                ("encours", "ENCOURS", "money"),
            ],
            lambda row: (
                row.maturity_date is not None
                and today <= row.maturity_date <= limit_date
                and _is_renewal_rating(row.client_rating)
            ),
        )

    if report_type == "future_schedules":
        if future_days is None or future_days < 1 or future_days > 10:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_future_days",
                    "message": "future_days must be between 1 and 10 for future schedules report",
                },
            )
        threshold = today + timedelta(days=future_days)
        return (
            "Liste des echeances futures",
            f"Criteres: NEXT_SCHEDULE_DATE entre aujourd'hui et aujourd'hui + {future_days} jour(s) (MCR actuel)",
            [
                ("client_id", "CLIENT NO", "text"),
                ("client_name", "CLIENT NAME", "text"),
                ("client_first_name", "CLIENT FIRST NAME", "text"),
                ("next_schedule_date", "NEXT SCHEDULE DATE", "date"),
                ("total_scheduled_amount", "TOTAL SCHEDULED AMOUNT", "money"),
                ("encours", "ENCOURS", "money"),
            ],
            lambda row: (
                row.next_schedule_date is not None
                and today <= row.next_schedule_date <= threshold
            ),
        )

    if report_type == "potential_radiation":
        raise HTTPException(
            status_code=400,
            detail={"code": "snapshot_required", "message": "snapshot_batch_id is required for potential radiation report"},
        )

    raise HTTPException(
        status_code=400,
        detail={"code": "invalid_report_type", "message": "Unknown report type"},
    )


def _to_decimal(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0")


def _sanitize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    # Remove bidi control marks that can visually flip Arabic text in exports.
    text = text.translate(
        {
            ord("\u200e"): None,  # LRM
            ord("\u200f"): None,  # RLM
            ord("\u202a"): None,  # LRE
            ord("\u202b"): None,  # RLE
            ord("\u202c"): None,  # PDF
            ord("\u202d"): None,  # LRO
            ord("\u202e"): None,  # RLO
            ord("\u2066"): None,  # LRI
            ord("\u2067"): None,  # RLI
            ord("\u2068"): None,  # FSI
            ord("\u2069"): None,  # PDI
        }
    )
    return " ".join(text.strip().split())


def _contains_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text))


def _arabic_count(text: str) -> int:
    return len(ARABIC_RE.findall(text))


def _repair_possible_mojibake(text: str) -> str:
    if not text:
        return text

    candidates = [text]
    if any(marker in text for marker in ("Ø", "Ù", "Ã", "Â")):
        for source_encoding in ("latin-1", "cp1252"):
            try:
                candidate = text.encode(source_encoding, errors="ignore").decode("utf-8", errors="ignore")
            except Exception:
                continue
            if candidate and candidate != text:
                candidates.append(candidate)

    def candidate_score(candidate: str) -> tuple[int, int]:
        # Prefer candidates with more Arabic characters and fewer mojibake markers.
        return (_arabic_count(candidate), -sum(candidate.count(marker) for marker in ("Ø", "Ù", "Ã", "Â")))

    return max(candidates, key=candidate_score)


def _collapse_fragmented_arabic_tokens(text: str) -> str:
    tokens = text.split()
    if len(tokens) < 2:
        return text
    arabic_single_letter = sum(1 for token in tokens if ARABIC_WORD_RE.match(token) and len(token) == 1)
    if arabic_single_letter >= max(2, int(len(tokens) * 0.6)):
        return "".join(tokens)
    return text


def _arabic_orientation_score(text: str) -> float:
    tokens = [token for token in text.split() if ARABIC_RE.search(token)]
    if not tokens:
        return -10_000.0

    score = 0.0
    for token in tokens:
        arabic_only = re.sub(r"[^\u0600-\u06FF]", "", token)
        if not arabic_only:
            continue
        if arabic_only[0] in ARABIC_SUSPICIOUS_STARTS:
            score -= 2.0
        if any(arabic_only.startswith(prefix) for prefix in ARABIC_COMMON_PREFIXES):
            score += 0.8
        if any(arabic_only.endswith(suffix) for suffix in ARABIC_COMMON_SUFFIXES):
            score += 0.5
        if len(arabic_only) == 1:
            score -= 0.7
    score += 0.3 * len(tokens)
    return score


def _fix_arabic_orientation(text: str) -> str:
    if not _contains_arabic(text):
        return text

    collapsed = _collapse_fragmented_arabic_tokens(text)
    candidates_with_cost: list[tuple[str, int]] = [
        (collapsed, 0),
        (" ".join(reversed(collapsed.split())), 1),
        (collapsed[::-1], 2),
    ]

    # For fragmented texts this can recover valid words, but we keep higher transform costs.
    tokens = collapsed.split()
    if tokens:
        candidates_with_cost.append((" ".join(token[::-1] for token in reversed(tokens)), 3))
        candidates_with_cost.append((" ".join(token[::-1] for token in tokens), 4))

    unique_candidates: dict[str, int] = {}
    for candidate, cost in candidates_with_cost:
        if candidate not in unique_candidates or cost < unique_candidates[candidate]:
            unique_candidates[candidate] = cost

    best_candidate = max(
        unique_candidates.items(),
        key=lambda item: (_arabic_orientation_score(item[0]), -item[1]),
    )
    return best_candidate[0]


def _shape_rtl_for_pdf(text: str) -> str:
    if not _contains_arabic(text):
        return text
    if arabic_reshaper is None or bidi_get_display is None:
        return text
    try:
        return bidi_get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _normalize_category_desc(value: str | None) -> str:
    cleaned = _sanitize_text(value)
    if not cleaned:
        return "-"

    repaired = _repair_possible_mojibake(cleaned)
    normalized = _fix_arabic_orientation(repaired)
    return normalized


def _portfolio_rows_for_report(
    loans: list[LoanRaw],
    report_type: PortfolioReportType,
    future_days: int | None,
) -> tuple[str, str, list[ColumnSpec], list[dict[str, Any]]]:
    title, subtitle, columns, predicate = _portfolio_report_definition(report_type, future_days)
    items: list[dict[str, Any]] = []
    for row in loans:
        if not predicate(row):
            continue

        encours = _to_decimal(row.principal_outstanding) + _to_decimal(row.principal_due)
        items.append(
            {
                "agence": row.agency_name or "-",
                "agent_name": row.agent_name or "-",
                "client_id": row.client_id or "-",
                "client_name": row.client_name or "-",
                "client_first_name": row.client_first_name or "-",
                "total_due_amt": _to_decimal(row.total_due),
                "total_principal_due_amt": _to_decimal(row.principal_due),
                "total_interest_due_amt": _to_decimal(row.interest_due_amt),
                "days_overdue": int(row.days_overdue or 0),
                "encours": encours,
                "repayment_rate": (
                    Decimal("100") * (Decimal("1") - _ratio_decimal(encours, row.disbursement_amount))
                    if _to_decimal(row.disbursement_amount)
                    else Decimal("0")
                ),
                "category_desc": _normalize_category_desc(row.category_desc),
                "disbursement_amount": _to_decimal(row.disbursement_amount),
                "maturity_date": row.maturity_date,
                "next_schedule_date": row.next_schedule_date,
                "total_scheduled_amount": _to_decimal(row.total_scheduled_amount),
            }
        )
    return title, subtitle, columns, items


def _portfolio_rows_for_report_multi(
    loans: list[LoanRaw],
    report_type: PortfolioReportType,
    future_days: int | None,
) -> tuple[str, str, list[ColumnSpec], list[dict[str, Any]]]:
    """Consolidated multi-agency payload: one flat table with AGENCE / AGENT columns first.

    Business rules, predicates and calculations are strictly the same as the
    single-agency report; only the structure (grouping in one table) changes.
    """
    title, subtitle, columns, items = _portfolio_rows_for_report(
        loans=loans,
        report_type=report_type,
        future_days=future_days,
    )
    items.sort(key=lambda item: (str(item.get("agence") or ""), str(item.get("agent_name") or "")))
    multi_columns: list[ColumnSpec] = [
        ("agence", "AGENCE", "text"),
        ("agent_name", "AGENT", "text"),
    ] + columns
    return title, subtitle, multi_columns, items


def _safe_file_slug(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _potential_radiation_columns() -> list[ColumnSpec]:
    return [
        ("contract_no", "CONTRACT_NO", "text"),
        ("client_name", "CLIENT_NAME", "text"),
        ("client_first_name", "CLIENT_FIRST_NAME", "text"),
        ("client_id", "CLIENT_NO", "text"),
        ("branche", "BRANCHE", "text"),
        ("days_overdue", "TOTAL_CUR_NO_OF_DAYS_OVERDUE", "int"),
        ("total_due_amt", "TOTAL_DUE_AMT", "money"),
        ("total_interest_due_amt", "TOTAL_INTEREST_DUE_AMT", "money"),
        ("total_principal_due_amt", "TOTAL_PRINCIPAL_DUE_AMT", "money"),
        ("glp", "GLP", "money"),
    ]


def _potential_radiation_rows(
    db: Session,
    user: User,
    *,
    snapshot_batch_id: int,
    agency_ids: list[int],
) -> tuple[ImportBatch, list[dict[str, Any]]]:
    batch = db.get(ImportBatch, snapshot_batch_id)
    if batch is None or batch.snapshot_date is None or batch.batch_type not in {
        ImportBatchType.CURRENT_STATE,
        ImportBatchType.SNAPSHOT,
        ImportBatchType.HISTORICAL_MONTH,
    }:
        raise HTTPException(
            status_code=404,
            detail={"code": "snapshot_not_found", "message": "Selected snapshot was not found"},
        )

    snapshot_filter = LoanRaw.import_batch_id == batch.id
    filters = [snapshot_filter, *_portfolio_scope_filters(
        db=db,
        user=user,
        agency_ids=agency_ids,
    )]
    client_ids = client_potentially_radiable_subquery(filters, batch.snapshot_date)
    glp_expression = (
        func.coalesce(LoanRaw.principal_outstanding, 0)
        + func.coalesce(LoanRaw.principal_due, 0)
    ).label("glp")
    rows = db.execute(
        select(
            LoanRaw.contract_no,
            LoanRaw.client_name,
            LoanRaw.client_first_name,
            LoanRaw.client_id,
            LoanRaw.agency_name,
            LoanRaw.days_overdue,
            LoanRaw.total_due,
            LoanRaw.interest_due_amt,
            LoanRaw.principal_due,
            glp_expression,
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(
            *filters,
            LoanRaw.client_id.in_(select(client_ids.c.client_id)),
        )
        .order_by(LoanRaw.contract_no.asc())
    ).mappings().all()
    return batch, [
        {
            "contract_no": row["contract_no"] or "",
            "client_name": row["client_name"] or "",
            "client_first_name": row["client_first_name"] or "",
            "client_id": row["client_id"] or "",
            "branche": row["agency_name"] or "",
            "days_overdue": int(row["days_overdue"] or 0),
            "total_due_amt": _to_decimal(row["total_due"]),
            "total_interest_due_amt": _to_decimal(row["interest_due_amt"]),
            "total_principal_due_amt": _to_decimal(row["principal_due"]),
            "glp": _to_decimal(row["glp"]),
        }
        for row in rows
    ]


@router.get(
    "/potential-radiation/snapshots",
    response_model=list[SnapshotOptionRead],
    dependencies=[Depends(require_roles([UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD]))],
)
def list_potential_radiation_snapshots(
    agency_id: int | None = None,
    agency_ids: str | None = None,
    agent_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    selected_agency_ids = normalize_agency_ids(
        agency_id=str(agency_id) if agency_id is not None else None,
        agency_ids=agency_ids,
    )
    filters = _portfolio_scope_filters(
        db=db,
        user=user,
        agency_id=agency_id,
        agent_id=agent_id,
        agency_ids=selected_agency_ids,
    )
    batches = db.scalars(
        select(ImportBatch)
        .join(LoanRaw, LoanRaw.import_batch_id == ImportBatch.id)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(
            ImportBatch.batch_type.in_([
                ImportBatchType.CURRENT_STATE,
                ImportBatchType.SNAPSHOT,
                ImportBatchType.HISTORICAL_MONTH,
            ]),
            ImportBatch.snapshot_date.is_not(None),
            *filters,
        )
        .group_by(ImportBatch.id)
        .order_by(ImportBatch.snapshot_date.desc(), ImportBatch.imported_at.desc(), ImportBatch.id.desc())
    ).all()
    return [
        SnapshotOptionRead(
            batch_id=batch.id,
            snapshot_date=batch.snapshot_date,
            label=_format_date(batch.snapshot_date),
        )
        for batch in batches
    ]


def _group_payload_by_agent(
    payload: list[dict[str, Any]],
    agent_names: list[str] | None = None,
) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for name in agent_names or []:
        grouped[name] = []

    for item in payload:
        name = str(item.get("agent_name") or "-")
        grouped.setdefault(name, []).append(item)

    return [(name, grouped[name]) for name in sorted(grouped.keys())]


def _agency_manager_agent_names(
    db: Session,
    user: User,
    agency_id: int | None,
    agent_id: int | None,
) -> list[str]:
    scope = get_user_data_scope(user)
    if scope.role != UserRole.AGENCY_MANAGER or scope.agency_id is None:
        return []

    effective_agency_id = scope.agency_id
    query = select(Agent.name).where(Agent.agency_id == effective_agency_id)
    if agency_id and agency_id != effective_agency_id:
        return []
    if agent_id:
        query = query.where(Agent.id == agent_id)

    names = [str(name).strip() for name in db.scalars(query).all() if str(name).strip()]
    return sorted(dict.fromkeys(names))


def _admin_agent_names_for_agency(
    db: Session,
    agency_id: int,
    agent_id: int | None,
) -> list[str]:
    """Return sorted agent names for *agency_id*, optionally filtered to a single agent.

    Used by Admin / Super Admin roles when generating grouped portfolio reports
    (one section per GP) scoped to a specific agency.
    """
    query = select(Agent.name).where(Agent.agency_id == agency_id)
    if agent_id:
        query = query.where(Agent.id == agent_id)
    names = [str(name).strip() for name in db.scalars(query).all() if str(name).strip()]
    return sorted(dict.fromkeys(names))


def _resolve_pdf_arabic_font() -> str | None:
    global _PDF_ARABIC_FONT_CACHE
    if _PDF_ARABIC_FONT_CACHE is not None:
        return _PDF_ARABIC_FONT_CACHE

    fonts_dir = Path(__file__).resolve().parents[2] / "assets" / "fonts"
    normal_candidates = [
        str(fonts_dir / "tahoma.ttf"),
        str(fonts_dir / "arial.ttf"),
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    normal_path = next((path for path in normal_candidates if os.path.exists(path)), None)
    if not normal_path:
        _PDF_ARABIC_FONT_CACHE = None
        return None

    try:
        if _PDF_ARABIC_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(_PDF_ARABIC_FONT_NAME, normal_path))
    except Exception:
        _PDF_ARABIC_FONT_CACHE = None
        return None

    _PDF_ARABIC_FONT_CACHE = _PDF_ARABIC_FONT_NAME
    return _PDF_ARABIC_FONT_CACHE


def _fit_column_widths(sheet, header_row: int = 5) -> None:
    # Row 1..3 includes merged title/subtitle cells; iterate by index to avoid MergedCell issues.
    column_overrides: dict[int, float] = {}
    for column_index in range(1, sheet.max_column + 1):
        header_value = str(sheet.cell(row=header_row, column=column_index).value or "").strip().upper()
        if header_value in {"CATEGORY_DESC", "CATEGORY DESC"}:
            column_overrides[column_index] = 46

    for column_index in range(1, sheet.max_column + 1):
        max_length = 0
        column_letter = get_column_letter(column_index)
        for row_index in range(1, sheet.max_row + 1):
            value = sheet.cell(row=row_index, column=column_index).value
            text = "" if value is None else str(value)
            max_length = max(max_length, len(text))
        auto_width = min(42, max(12, max_length + 2))
        sheet.column_dimensions[column_letter].width = max(auto_width, column_overrides.get(column_index, 0))


def _pdf_column_widths(total_width: float, columns: list[ColumnSpec]) -> list[float]:
    weights: list[float] = []
    for key, _label, _value_type in columns:
        if key == "category_desc":
            weights.append(3.4)
        elif key == "client_id":
            weights.append(1.2)
        elif key in {"client_name", "client_first_name"}:
            weights.append(1.4)
        else:
            weights.append(1.0)

    total_weight = sum(weights) or 1.0
    return [total_width * (weight / total_weight) for weight in weights]


def _styled_excel_buffer(
    title: str,
    subtitle: str,
    columns: list[ColumnSpec],
    rows: list[dict[str, Any]],
) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Rapport"

    max_col = len(columns)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
    sheet["A1"] = title
    sheet["A1"].fill = TITLE_FILL
    sheet["A1"].font = TITLE_FONT
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 28

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max_col)
    sheet["A2"] = subtitle
    sheet["A2"].font = Font(size=10, color="334155")
    sheet["A2"].alignment = Alignment(horizontal="left", vertical="center")

    sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=max_col)
    sheet["A3"] = f"Generation: {datetime_to_string(datetime=date.today())}"
    sheet["A3"].font = Font(size=9, color="64748B")
    sheet["A3"].alignment = Alignment(horizontal="left", vertical="center")

    header_row = 5
    for col_index, (_, label, _) in enumerate(columns, start=1):
        cell = sheet.cell(row=header_row, column=col_index, value=label)
        cell.fill = HEADER_BG
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    sheet.row_dimensions[header_row].height = 24

    data_start = header_row + 1
    for row_index, record in enumerate(rows, start=data_start):
        for col_index, (key, _label, value_type) in enumerate(columns, start=1):
            raw = record.get(key)
            cell = sheet.cell(row=row_index, column=col_index, value=raw)
            cell.border = THIN_BORDER
            if row_index % 2 == 0:
                cell.fill = ALT_ROW_FILL
            if value_type == "money":
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif value_type == "int":
                cell.number_format = "0"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif value_type == "date":
                cell.number_format = "DD/MM/YYYY"
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif value_type == "percent":
                cell.number_format = "0.00%"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif value_type == "percent_raw":
                cell.number_format = '0.00"%"'
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                if key == "category_desc":
                    cell.alignment = Alignment(
                        horizontal="right",
                        vertical="top",
                        wrap_text=True,
                        readingOrder=2,
                    )
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

    sheet.freeze_panes = f"A{data_start}"
    _fit_column_widths(sheet)
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def _styled_excel_grouped_buffer(
    title: str,
    subtitle: str,
    columns: list[ColumnSpec],
    grouped_rows: list[tuple[str, list[dict[str, Any]]]],
) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Rapport"

    max_col = len(columns)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
    sheet["A1"] = title
    sheet["A1"].fill = TITLE_FILL
    sheet["A1"].font = TITLE_FONT
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 28

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max_col)
    sheet["A2"] = subtitle
    sheet["A2"].font = Font(size=10, color="334155")
    sheet["A2"].alignment = Alignment(horizontal="left", vertical="center")

    sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=max_col)
    sheet["A3"] = f"Generation: {datetime_to_string(datetime=date.today())}"
    sheet["A3"].font = Font(size=9, color="64748B")
    sheet["A3"].alignment = Alignment(horizontal="left", vertical="center")

    if not grouped_rows:
        grouped_rows = [("Aucun GP", [])]

    row_index = 5
    section_fill = PatternFill("solid", fgColor="E2E8F0")
    section_font = Font(color="0F172A", bold=True, size=11)
    for agent_name, rows in grouped_rows:
        sheet.merge_cells(start_row=row_index, start_column=1, end_row=row_index, end_column=max_col)
        section_cell = sheet.cell(row=row_index, column=1, value=f"GP: {agent_name}")
        section_cell.fill = section_fill
        section_cell.font = section_font
        section_cell.alignment = Alignment(horizontal="left", vertical="center")
        row_index += 1

        for col_index, (_key, label, _value_type) in enumerate(columns, start=1):
            cell = sheet.cell(row=row_index, column=col_index, value=label)
            cell.fill = HEADER_BG
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = THIN_BORDER
        sheet.row_dimensions[row_index].height = 24
        row_index += 1

        if not rows:
            for col_index in range(1, max_col + 1):
                cell = sheet.cell(row=row_index, column=col_index, value="-" if col_index == 1 else "")
                cell.border = THIN_BORDER
                cell.alignment = Alignment(horizontal="left", vertical="center")
            row_index += 1
        else:
            for row_payload in rows:
                for col_index, (key, _label, value_type) in enumerate(columns, start=1):
                    raw = row_payload.get(key)
                    cell = sheet.cell(row=row_index, column=col_index, value=raw)
                    cell.border = THIN_BORDER
                    if row_index % 2 == 0:
                        cell.fill = ALT_ROW_FILL
                    if value_type == "money":
                        cell.number_format = "#,##0.00"
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    elif value_type == "int":
                        cell.number_format = "0"
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    elif value_type == "date":
                        cell.number_format = "DD/MM/YYYY"
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    elif value_type == "percent":
                        cell.number_format = "0.00%"
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    elif value_type == "percent_raw":
                        cell.number_format = '0.00"%"'
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    else:
                        if key == "category_desc":
                            cell.alignment = Alignment(
                                horizontal="right",
                                vertical="top",
                                wrap_text=True,
                                readingOrder=2,
                            )
                        else:
                            cell.alignment = Alignment(horizontal="left", vertical="center")
                row_index += 1

        row_index += 1

    _fit_column_widths(sheet)
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def _format_date(value: date | None) -> str:
    if not value:
        return "-"
    return value.strftime("%d/%m/%Y")


def _format_money(value: Decimal | float | int | None) -> str:
    amount = float(value or 0)
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


def datetime_to_string(datetime: date) -> str:
    return datetime.strftime("%d/%m/%Y")


def _pdf_display_value(value: Any, value_type: str) -> str:
    if value_type == "money":
        return _format_money(value)
    if value_type == "date":
        return _format_date(value)
    if value_type == "int":
        try:
            return str(int(value or 0))
        except (TypeError, ValueError):
            return "0"
    if value_type == "percent":
        try:
            ratio = float(value or 0)
        except (TypeError, ValueError):
            return "0,00%"
        return f"{ratio * 100:,.2f}%".replace(",", " ").replace(".", ",")
    if value_type == "percent_raw":
        try:
            amount = float(value or 0)
        except (TypeError, ValueError):
            return "0,00%"
        return f"{amount:,.2f}%".replace(",", " ").replace(".", ",")
    if value is None or value == "":
        return "-"
    return " ".join(str(value).split())


def _styled_pdf_buffer(
    title: str,
    subtitle: str,
    columns: list[ColumnSpec],
    rows: list[dict[str, Any]],
) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12,
    )
    arabic_font_name = _resolve_pdf_arabic_font() or "Helvetica"
    rtl_text_style = ParagraphStyle(
        "RtlTextStyle",
        parent=styles["BodyText"],
        fontName=arabic_font_name,
        fontSize=9,
        leading=11,
        alignment=2,
        wordWrap="RTL",
    )
    elements: list[Any] = [
        Paragraph(title, title_style),
        Paragraph(subtitle, subtitle_style),
        Paragraph(f"Generation: {datetime_to_string(date.today())}", subtitle_style),
        Spacer(1, 8),
    ]

    table_data = [[label for _key, label, _value_type in columns]]
    for row in rows:
        rendered_row: list[Any] = []
        for key, _label, value_type in columns:
            display_value = _pdf_display_value(row.get(key), value_type)
            if key == "category_desc" and display_value != "-":
                rendered_row.append(Paragraph(_shape_rtl_for_pdf(display_value), rtl_text_style))
            else:
                rendered_row.append(display_value)
        table_data.append(rendered_row)

    table = Table(table_data, repeatRows=1, colWidths=_pdf_column_widths(doc.width, columns))
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for index, (_key, _label, value_type) in enumerate(columns):
        if value_type in {"money", "int"}:
            style_commands.append(("ALIGN", (index, 1), (index, -1), "RIGHT"))
        elif value_type == "date":
            style_commands.append(("ALIGN", (index, 1), (index, -1), "CENTER"))
        else:
            style_commands.append(("ALIGN", (index, 1), (index, -1), "LEFT"))
    for index, (key, _label, _value_type) in enumerate(columns):
        if key == "category_desc":
            style_commands.append(("ALIGN", (index, 1), (index, -1), "RIGHT"))
            style_commands.append(("FONTNAME", (index, 1), (index, -1), arabic_font_name))

    for idx in range(1, len(table_data)):
        if idx % 2 == 0:
            style_commands.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#F8FAFC")))
    table.setStyle(TableStyle(style_commands))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def _styled_pdf_grouped_buffer(
    title: str,
    subtitle: str,
    columns: list[ColumnSpec],
    grouped_rows: list[tuple[str, list[dict[str, Any]]]],
) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyleGrouped",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyleGrouped",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "SectionStyleGrouped",
        parent=styles["Heading4"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=8,
        spaceAfter=6,
    )
    arabic_font_name = _resolve_pdf_arabic_font() or "Helvetica"
    rtl_text_style = ParagraphStyle(
        "RtlTextStyleGrouped",
        parent=styles["BodyText"],
        fontName=arabic_font_name,
        fontSize=9,
        leading=11,
        alignment=2,
        wordWrap="RTL",
    )

    elements: list[Any] = [
        Paragraph(title, title_style),
        Paragraph(subtitle, subtitle_style),
        Paragraph(f"Generation: {datetime_to_string(date.today())}", subtitle_style),
        Spacer(1, 8),
    ]
    if not grouped_rows:
        grouped_rows = [("Aucun GP", [])]

    for agent_name, rows in grouped_rows:
        elements.append(Paragraph(f"GP: {agent_name}", section_style))

        table_data = [[label for _key, label, _value_type in columns]]
        if not rows:
            table_data.append(["-"] + [""] * (len(columns) - 1))
        else:
            for row in rows:
                rendered_row: list[Any] = []
                for key, _label, value_type in columns:
                    display_value = _pdf_display_value(row.get(key), value_type)
                    if key == "category_desc" and display_value != "-":
                        rendered_row.append(Paragraph(_shape_rtl_for_pdf(display_value), rtl_text_style))
                    else:
                        rendered_row.append(display_value)
                table_data.append(rendered_row)

        table = Table(table_data, repeatRows=1, colWidths=_pdf_column_widths(doc.width, columns))
        style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        for index, (key, _label, value_type) in enumerate(columns):
            if value_type in {"money", "int"}:
                style_commands.append(("ALIGN", (index, 1), (index, -1), "RIGHT"))
            elif value_type == "date":
                style_commands.append(("ALIGN", (index, 1), (index, -1), "CENTER"))
            else:
                style_commands.append(("ALIGN", (index, 1), (index, -1), "LEFT"))
            if key == "category_desc":
                style_commands.append(("ALIGN", (index, 1), (index, -1), "RIGHT"))
                style_commands.append(("FONTNAME", (index, 1), (index, -1), arabic_font_name))

        for idx in range(1, len(table_data)):
            if idx % 2 == 0:
                style_commands.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#F8FAFC")))
        table.setStyle(TableStyle(style_commands))
        elements.append(table)
        elements.append(Spacer(1, 10))

    doc.build(elements)
    buffer.seek(0)
    return buffer


@router.get("/metrics.xlsx")
def export_metrics_excel(
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD])),
):
    sections = _metrics_export_sections(
        db=db,
        user=user,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
    )
    columns = _metrics_export_columns()
    subtitle = "Synthese dashboard par agence (ligne agence + lignes agents)"
    if agency_id:
        subtitle += f" | Filtre agence #{agency_id}"
    if agent_id:
        subtitle += f" | Filtre agent #{agent_id}"
    if date_from or date_to:
        subtitle += f" | Periode: {date_from or '-'} -> {date_to or '-'}"
    buffer = _styled_excel_metrics_by_agency_buffer(
        title="MicroCred - Rapport Metrics Dashboard",
        subtitle=subtitle,
        columns=columns,
        sections=sections,
    )
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=microcred_metrics.xlsx"},
    )


@router.get("/metrics.pdf")
def export_metrics_pdf(
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD])),
):
    sections = _metrics_export_sections(
        db=db,
        user=user,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
    )
    columns = _metrics_export_columns()
    subtitle = "Synthese dashboard par agence (ligne agence + lignes agents)"
    if agency_id:
        subtitle += f" | Filtre agence #{agency_id}"
    if agent_id:
        subtitle += f" | Filtre agent #{agent_id}"
    if date_from or date_to:
        subtitle += f" | Periode: {date_from or '-'} -> {date_to or '-'}"
    buffer = _styled_pdf_metrics_by_agency_buffer(
        title="MicroCred - Rapport Metrics Dashboard",
        subtitle=subtitle,
        columns=columns,
        sections=sections,
    )
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=microcred_metrics.pdf"},
    )


@router.get("/portfolio.xlsx")
def export_portfolio_report_excel(
    report_type: PortfolioReportType = Query(...),
    future_days: int | None = Query(default=None, ge=1, le=10),
    snapshot_batch_id: int | None = Query(default=None, ge=1),
    agency_id: int | None = None,
    agency_ids: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_roles([UserRole.PORTFOLIO_MANAGER, UserRole.AGENCY_MANAGER, UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD])
    ),
):
    effective_agency_ids = normalize_agency_ids(
        agency_id=str(agency_id) if agency_id is not None else None,
        agency_ids=agency_ids,
    )
    if not effective_agency_ids:
        effective_agency_ids = _regional_default_agency_ids(db, user)
    is_admin_export = user.role in {
        UserRole.ADMIN,
        UserRole.SUPER_ADMIN,
        UserRole.REGIONAL_MANAGER_NORD,
        UserRole.REGIONAL_MANAGER_SUD,
    }

    # Admin / Super Admin: at least one agency is mandatory to produce a meaningful report.
    if is_admin_export:
        if not effective_agency_ids:
            raise HTTPException(
                status_code=400,
                detail={"code": "agency_required", "message": "agency_id is required for Admin portfolio exports"},
            )
        missing_agency_ids = [agency_id_item for agency_id_item in effective_agency_ids if not db.get(Agency, agency_id_item)]
        if missing_agency_ids:
            raise HTTPException(
                status_code=404,
                detail={"code": "agency_not_found", "message": f"Agency #{missing_agency_ids[0]} not found"},
            )

    if report_type == "potential_radiation":
        if user.role not in {
            UserRole.ADMIN,
            UserRole.SUPER_ADMIN,
            UserRole.AGENCY_MANAGER,
            UserRole.PORTFOLIO_MANAGER,
        }:
            raise HTTPException(
                status_code=403,
                detail={"code": "report_forbidden", "message": "Potential Radiation report is restricted to Admin / Super Admin / Agency Manager / Portfolio Manager users"},
            )
        if snapshot_batch_id is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "snapshot_required", "message": "Select a reference snapshot before generating this report"},
            )
        # Non-admin scoped roles rely on their effective scope (handled inside
        # _portfolio_scope_filters -> _potential_radiation_rows). Admins must
        # still explicitly select one or more agencies.
        if is_admin_export and not effective_agency_ids:
            raise HTTPException(
                status_code=400,
                detail={"code": "agency_required", "message": "agency_id is required for Admin portfolio exports"},
            )
        batch, rows = _potential_radiation_rows(
            db=db,
            user=user,
            snapshot_batch_id=snapshot_batch_id,
            agency_ids=effective_agency_ids,
        )
        subtitle = (
            f"Snapshot de reference: {_format_date(batch.snapshot_date)} | "
            f"Seuil: {calculate_potentially_radiable_threshold(batch.snapshot_date)} jours"
        )
        buffer = _styled_excel_buffer(
            title="POTENTIEL RADIATION",
            subtitle=subtitle,
            columns=_potential_radiation_columns(),
            rows=rows,
        )
        filename = f"Potentiel_Radiation_{batch.snapshot_date.isoformat()}.xlsx"
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    if len(effective_agency_ids) > 1 and is_admin_export:
        # Multi-agency export: new dedicated template, one consolidated table
        # with AGENCE / AGENT columns; historical single-agency template untouched.
        loans = _portfolio_report_base_rows(
            db=db,
            user=user,
            agent_id=agent_id,
            date_from=date_from,
            date_to=date_to,
            agency_ids=effective_agency_ids,
        )
        title, subtitle, columns, payload = _portfolio_rows_for_report_multi(
            loans=loans,
            report_type=report_type,
            future_days=future_days,
        )
        agency_labels = [
            str(db.get(Agency, agency_id_item).name)
            for agency_id_item in effective_agency_ids
            if db.get(Agency, agency_id_item)
        ]
        buffer = _styled_excel_buffer(
            title=title,
            subtitle=f"{subtitle} - Agences: {', '.join(agency_labels)} (tableau consolide multi-agences)",
            columns=columns,
            rows=payload,
        )
        filename = f"portfolio_{_safe_file_slug(report_type)}_multi_agences.xlsx"
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    single_agency_id = effective_agency_ids[0] if effective_agency_ids else agency_id

    loans = _portfolio_report_base_rows(
        db=db,
        user=user,
        agency_id=single_agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
    )
    title, subtitle, columns, payload = _portfolio_rows_for_report(
        loans=loans,
        report_type=report_type,
        future_days=future_days,
    )

    if user.role in {
        UserRole.ADMIN,
        UserRole.SUPER_ADMIN,
        UserRole.REGIONAL_MANAGER_NORD,
        UserRole.REGIONAL_MANAGER_SUD,
    }:
        # Grouped view: one table per GP, scoped to the selected agency.
        agency_obj = db.get(Agency, single_agency_id)
        agency_label = agency_obj.name if agency_obj else f"#{single_agency_id}"
        agent_names = _admin_agent_names_for_agency(db=db, agency_id=single_agency_id, agent_id=agent_id)
        grouped_payload = _group_payload_by_agent(payload, agent_names=agent_names)
        buffer = _styled_excel_grouped_buffer(
            title=title,
            subtitle=f"{subtitle} - Agence: {agency_label} (tableau par GP)",
            columns=columns,
            grouped_rows=grouped_payload,
        )
    elif user.role == UserRole.AGENCY_MANAGER:
        agent_names = _agency_manager_agent_names(
            db=db,
            user=user,
            agency_id=single_agency_id,
            agent_id=agent_id,
        )
        grouped_payload = _group_payload_by_agent(payload, agent_names=agent_names)
        buffer = _styled_excel_grouped_buffer(
            title=title,
            subtitle=f"{subtitle} - Vue chef d'agence (tableau par GP)",
            columns=columns,
            grouped_rows=grouped_payload,
        )
    else:
        buffer = _styled_excel_buffer(title=title, subtitle=subtitle, columns=columns, rows=payload)
    filename = f"portfolio_{_safe_file_slug(report_type)}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/portfolio.pdf")
def export_portfolio_report_pdf(
    report_type: PortfolioReportType = Query(...),
    future_days: int | None = Query(default=None, ge=1, le=10),
    agency_id: int | None = None,
    agency_ids: str | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_roles([UserRole.PORTFOLIO_MANAGER, UserRole.AGENCY_MANAGER, UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD])
    ),
):
    effective_agency_ids = normalize_agency_ids(
        agency_id=str(agency_id) if agency_id is not None else None,
        agency_ids=agency_ids,
    )
    if not effective_agency_ids:
        effective_agency_ids = _regional_default_agency_ids(db, user)
    is_admin_export = user.role in {
        UserRole.ADMIN,
        UserRole.SUPER_ADMIN,
        UserRole.REGIONAL_MANAGER_NORD,
        UserRole.REGIONAL_MANAGER_SUD,
    }

    # Admin / Super Admin: at least one agency is mandatory to produce a meaningful report.
    if is_admin_export:
        if not effective_agency_ids:
            raise HTTPException(
                status_code=400,
                detail={"code": "agency_required", "message": "agency_id is required for Admin portfolio exports"},
            )
        missing_agency_ids = [agency_id_item for agency_id_item in effective_agency_ids if not db.get(Agency, agency_id_item)]
        if missing_agency_ids:
            raise HTTPException(
                status_code=404,
                detail={"code": "agency_not_found", "message": f"Agency #{missing_agency_ids[0]} not found"},
            )

    if len(effective_agency_ids) > 1 and is_admin_export:
        # Multi-agency export: new dedicated template, one consolidated table
        # with AGENCE / AGENT columns; historical single-agency template untouched.
        loans = _portfolio_report_base_rows(
            db=db,
            user=user,
            agent_id=agent_id,
            date_from=date_from,
            date_to=date_to,
            agency_ids=effective_agency_ids,
        )
        title, subtitle, columns, payload = _portfolio_rows_for_report_multi(
            loans=loans,
            report_type=report_type,
            future_days=future_days,
        )
        agency_labels = [
            str(db.get(Agency, agency_id_item).name)
            for agency_id_item in effective_agency_ids
            if db.get(Agency, agency_id_item)
        ]
        buffer = _styled_pdf_buffer(
            title=title,
            subtitle=f"{subtitle} - Agences: {', '.join(agency_labels)} (tableau consolide multi-agences)",
            columns=columns,
            rows=payload,
        )
        filename = f"portfolio_{_safe_file_slug(report_type)}_multi_agences.pdf"
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    single_agency_id = effective_agency_ids[0] if effective_agency_ids else agency_id

    loans = _portfolio_report_base_rows(
        db=db,
        user=user,
        agency_id=single_agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
    )
    title, subtitle, columns, payload = _portfolio_rows_for_report(
        loans=loans,
        report_type=report_type,
        future_days=future_days,
    )

    if user.role in {
        UserRole.ADMIN,
        UserRole.SUPER_ADMIN,
        UserRole.REGIONAL_MANAGER_NORD,
        UserRole.REGIONAL_MANAGER_SUD,
    }:
        # Grouped view: one table per GP, scoped to the selected agency.
        agency_obj = db.get(Agency, single_agency_id)
        agency_label = agency_obj.name if agency_obj else f"#{single_agency_id}"
        agent_names = _admin_agent_names_for_agency(db=db, agency_id=single_agency_id, agent_id=agent_id)
        grouped_payload = _group_payload_by_agent(payload, agent_names=agent_names)
        buffer = _styled_pdf_grouped_buffer(
            title=title,
            subtitle=f"{subtitle} - Agence: {agency_label} (tableau par GP)",
            columns=columns,
            grouped_rows=grouped_payload,
        )
    elif user.role == UserRole.AGENCY_MANAGER:
        agent_names = _agency_manager_agent_names(
            db=db,
            user=user,
            agency_id=single_agency_id,
            agent_id=agent_id,
        )
        grouped_payload = _group_payload_by_agent(payload, agent_names=agent_names)
        buffer = _styled_pdf_grouped_buffer(
            title=title,
            subtitle=f"{subtitle} - Vue chef d'agence (tableau par GP)",
            columns=columns,
            grouped_rows=grouped_payload,
        )
    else:
        buffer = _styled_pdf_buffer(title=title, subtitle=subtitle, columns=columns, rows=payload)
    filename = f"portfolio_{_safe_file_slug(report_type)}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
