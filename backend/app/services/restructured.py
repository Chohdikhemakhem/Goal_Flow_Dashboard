from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
from time import perf_counter
import csv
import logging
import math
import tempfile
import threading
import tracemalloc
import unicodedata

import pandas as pd
from openpyxl import load_workbook
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import case, delete, false, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.entities import (
    Agency,
    Agent,
    ImportBatch,
    LoanRaw,
    PendingRestructuredContract,
    RestructuredAnalysisResult,
    RestructuredContract,
    RestructuredGapResult,
    RestructuredImportLog,
    RestructuredScheduleRow,
    User,
)
from app.models.enums import ImportBatchType, UserRole
from app.schemas.common import Page
from app.schemas.restructured import (
    PendingRestructuredContractRead,
    PendingRestructuredContractSaveResult,
    PendingRestructuredContractUpdate,
    RestructuredChartRead,
    RestructuredChartSliceRead,
    RestructuredContractRead,
    RestructuredGapRead,
    RestructuredImportResult,
    RestructuredKpiRead,
    RestructuredSyncDeletionRead,
    RestructuredSyncPreviewRead,
    RestructuredTrendChartRead,
    RestructuredTrendPointRead,
)
from app.services.data_scope import get_user_data_scope
from app.services.selection import normalize_agency_ids

logger = logging.getLogger(__name__)

CONTRACT_COLUMN_ALIASES = {
    "source_contract_no": ("Numero contrat", "Numéro contrat"),
    "contract_no": ("No' contrat", "N contrat", "No contrat"),
    "restructure_label": ("Colonne1",),
    "delay_date": ("date de décalage", "date de decalage"),
    "in_mcr": ("dans MCR", " dans MCR"),
    "category_desc": ("CATEGORY_DESC", "CATEGORY DESC"),
    "total_due": ("Total_Due", "Total Due"),
    "loan_duration": ("LOAN_DURATION", "Loan Duration"),
}

SCHEDULE_COLUMN_ALIASES = {
    "agency_code": ("Code Agence",),
    "agency_name": ("Nom Agence",),
    "agent_name": ("Nom du GP",),
    "client_name": ("Nom Client",),
    "client_first_name": ("Prénom du client", "Prenom du client", "Prenom Client"),
    "account_number": (
        "Numéro Contrat Abacus (AccountNumber)",
        "Numéro Contrat Abacus (AccountNumber)",
        "Numero Contrat Abacus (AccountNumber)",
        "Numero Contrat Abacus AccountNumber",
        "AccountNumber",
    ),
    "t24_reference_number": (
        "Numéro Contrat T24 (Reference Number)",
        "Numéro Contrat T24 (Reference Number)",
        "Numero Contrat T24 (Reference Number)",
    ),
    "culoanpart_reference": ("ReferenceNumber CULoanPart",),
    "customer_id": (
        "Numéro Client Abacus(CustomerID)",
        "Numéro Client Abacus(CustomerID)",
        "Numero Client Abacus(CustomerID)",
    ),
    "is_active": ("Active",),
    "issue_date": ("IssueDate",),
    "installment_no": (
        "NÂ° d'Echéance",
        "NÂ° d'Echéance",
        "NÂ° d'Echeance",
        "N° d'Echéance",
        "N° d'Echeance",
        "N d'Echeance",
        "No d'Echeance",
    ),
    "due_date": (
        "Date d'échéance",
        "Date d'echeance",
        "Date d'Echéance",
        "Date d'Echéance",
        "Date d'Echeance",
    ),
    "total_installment": ("Total échéance", "Total Echéance", "Total Echeance"),
    "principal_paid": (
        "échéance payée en capital",
        "Echéance payée en capital",
        "Échéance payée en capital",
        "Echeance payee en capital",
    ),
    "interest_due": ("Intéret dù»", "Interet du"),
    "interest_paid": ("Intéret payé", "Interet paye"),
    "principal_due": ("Capital dù»", "Capital du"),
    "outstanding_after_payment": ("Encours principal aprù¨s paiement échéance",),
    "total_penalty_amt": ("TOTAL PENALTY AMT",),
    "penalty_interest_amount": ("PenalityIntAmount",),
    "unpaid_interest": ("UnpaidInterest",),
    "unpaid_penalty_interest": ("UnpaidPenaltyInterest",),
    "all_paid": ("AllPaid",),
    "value_date": ("value_date",),
    "receipt_no": ("ReceiptNo",),
    "transaction_id": ("TransactionID",),
    "schedule_id": ("ScheduleID",),
    "delay_days": ("delayday",),
}

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

CONSECUTIVE_BUCKETS = {
    "0": {"min": 0, "max": 0, "color": "#9ca3af"},
    "1-2": {"min": 1, "max": 2, "color": "#dc2626"},
    "3": {"min": 3, "max": 3, "color": "#f59e0b"},
    "4+": {"min": 4, "max": 10**9, "color": "#16a34a"},
}
STATUS_COLORS = {
    "Suppos\u00e9 cl\u00f4tur\u00e9": "#16a34a",
    "En cours": "#2563eb",
    "N/A": "#94a3b8",
    "Oui": "#16a34a",
    "Non": "#dc2626",
}
ANALYSIS_GAP_THRESHOLD_DAYS = 35
PAID_TOLERANCE = 0.01
CLOSURE_STATUS_ASSUMED_CLOSED = "Suppos\u00e9 cl\u00f4tur\u00e9"
CLOSURE_STATUS_IN_PROGRESS = "En cours"
CLOSURE_STATUS_NA = "N/A"
TARGET_CLOSURE_DEBUG_CONTRACT = "1000-00047746"
TARGET_PAID_LAST_FOUR_DEBUG_CONTRACT = "1100-00002654"
RESTRUCTURED_FAMILY = "restructured"
CONSOLIDATED_FAMILY = "consolidated"
LIST_IMPORT_SOURCE = "LIST_IMPORT"
MANUAL_COMPLETION_SOURCE = "MCR_COMPLETED_MANUALLY"
PENDING_STATUS_TO_COMPLETE = "pending"
PENDING_STATUS_READY = "ready"
TRACKED_RESTRUCTURED_CATEGORIES = {
    "credits consolides": CONSOLIDATED_FAMILY,
    "credits restructures": RESTRUCTURED_FAMILY,
}
PENDING_FIELD_LABELS = {
    "shift_date": "Date de decalage",
    "total_due": "Total Due",
    "loan_duration": "LOAN_DURATION",
}
IMPORT_PHASE_WEIGHTS = {
    "queued": 0,
    "reading": 0,
    "filtering": 60,
    "staging": 75,
    "upsert": 90,
    "recalculate": 95,
    "completed": 100,
}
IMPORT_PROGRESS_ROW_INTERVAL = 10000
IMPORT_PROGRESS_TIME_INTERVAL_SECONDS = 5.0
IMPORT_HEARTBEAT_INTERVAL_SECONDS = 15.0
IMPORT_STALL_TIMEOUT_SECONDS = 180.0
IMPORT_DIAGNOSTIC_SAMPLE_ROWS = 50000
SCHEDULE_COLUMNS = [
    "agency_code",
    "agency_name",
    "agent_name",
    "client_name",
    "client_first_name",
    "account_number",
    "t24_reference_number",
    "culoanpart_reference",
    "customer_id",
    "is_active",
    "issue_date",
    "installment_no",
    "due_date",
    "total_installment",
    "principal_paid",
    "interest_due",
    "interest_paid",
    "principal_due",
    "outstanding_after_payment",
    "total_penalty_amt",
    "penalty_interest_amount",
    "unpaid_interest",
    "unpaid_penalty_interest",
    "all_paid",
    "value_date",
    "receipt_no",
    "transaction_id",
    "schedule_id",
    "delay_days",
]
SCHEDULE_TEXT_FIELDS = {
    "agency_code",
    "agency_name",
    "agent_name",
    "client_name",
    "client_first_name",
    "account_number",
    "t24_reference_number",
    "culoanpart_reference",
    "customer_id",
    "receipt_no",
    "transaction_id",
    "schedule_id",
}
SCHEDULE_DATE_FIELDS = {"issue_date", "due_date", "value_date"}
SCHEDULE_DECIMAL_FIELDS = {
    "total_installment",
    "principal_paid",
    "interest_due",
    "interest_paid",
    "principal_due",
    "outstanding_after_payment",
    "total_penalty_amt",
    "penalty_interest_amount",
    "unpaid_interest",
    "unpaid_penalty_interest",
}


def _normalize_header(value: str) -> str:
    text_value = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    return "".join(ch for ch in ascii_value.upper() if ch.isalnum())


def _normalize_contract_key(value) -> str | None:
    text_value = _optional_text(value)
    if not text_value:
        return None
    compact = "".join(text_value.split())
    while compact.endswith(".0"):
        compact = compact[:-2]
    if compact.endswith("."):
        compact = compact[:-1]
    compact = compact.strip()
    return compact.upper() or None


def _normalize_family_label(value: str | None) -> str:
    text_value = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    compact = " ".join(ascii_value.lower().split())
    return compact


def _credit_family_from_category(value: str | None) -> str:
    return (
        CONSOLIDATED_FAMILY
        if _normalize_family_label(value) == "credits consolides"
        else RESTRUCTURED_FAMILY
    )


def _tracked_mcr_credit_family(value: str | None) -> str | None:
    """
    Map a CATEGORY_DESC value to a tracked credit family.

    Resolution order (most permissive first):
    1. Exact match against the strict dictionary (preserves historical behaviour).
    2. Substring match (after accent/case/space normalization) so that real-world
       variants like "Credit Consolide" (singular), "Restructure", "CREDIT CONSOLIDE",
       "Consolidation Credit" etc. are still recognized as restructured/consolidated.

    The substring priority is "consolidated" first, then "restructured" so that a
    combined label like "Credit Consolide Restructure" resolves to consolidated.
    """
    normalized = _normalize_family_label(value)
    if not normalized:
        return None
    exact = TRACKED_RESTRUCTURED_CATEGORIES.get(normalized)
    if exact is not None:
        return exact
    if "consolid" in normalized:
        return CONSOLIDATED_FAMILY
    if "restructur" in normalized or "restruct" in normalized or "restruc" in normalized:
        return RESTRUCTURED_FAMILY
    return None


def _resolve_columns(frame: pd.DataFrame, aliases: dict[str, tuple[str, ...]]) -> dict[str, str | None]:
    normalized_lookup: dict[str, str] = {}
    for column in frame.columns:
        key = _normalize_header(column)
        if key and key not in normalized_lookup:
            normalized_lookup[key] = str(column)

    resolved: dict[str, str | None] = {}
    for canonical, candidates in aliases.items():
        match = None
        for alias in candidates:
            match = normalized_lookup.get(_normalize_header(alias))
            if match:
                break
        resolved[canonical] = match
    return resolved


def _read_excel(content: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(BytesIO(content), engine="openpyxl")
    except Exception:
        try:
            return pd.read_excel(BytesIO(content), engine="calamine")
        except Exception:
            return pd.read_excel(BytesIO(content))


def _optional_text(value) -> str | None:
    if pd.isna(value):
        return None
    text_value = str(value).strip()
    return text_value or None


def _optional_int(value) -> int | None:
    if pd.isna(value):
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _optional_decimal(value) -> Decimal | None:
    if pd.isna(value):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.001"))
    except Exception:
        return None


def _optional_date(value) -> date | None:
    if pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _bool_like(value) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, bool):
        return value
    text_value = str(value).strip().lower()
    return text_value in {"1", "true", "t", "yes", "oui"}


def _bucket_for_count(count: int | None) -> str:
    safe_count = int(count or 0)
    if safe_count <= 0:
        return "0"
    if safe_count <= 2:
        return "1-2"
    if safe_count == 3:
        return "3"
    return "4+"


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = (year * 12 + (month - 1)) + offset
    shifted_year = absolute // 12
    shifted_month = absolute % 12 + 1
    return shifted_year, shifted_month


def _month_range_backwards(anchor: tuple[int, int], count: int) -> list[tuple[int, int]]:
    year, month = anchor
    return [_shift_month(year, month, -offset) for offset in range(count)]


def _month_key(value: date | None) -> tuple[int, int] | None:
    if value is None:
        return None
    return value.year, value.month


def _format_month_key(month_key: tuple[int, int] | None) -> str | None:
    if month_key is None:
        return None
    return f"{month_key[0]:04d}-{month_key[1]:02d}"


def _coerce_float(value, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    if isinstance(value, str):
        normalized = value.strip().replace("\u00a0", "").replace(" ", "")
        if "," in normalized and "." not in normalized:
            normalized = normalized.replace(",", ".")
        value = normalized
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_schedule_bool(value) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y", "oui"}


def _is_paid_installment(principal_due, principal_paid) -> bool:
    due = _coerce_float(principal_due, default=0.0)
    paid = _coerce_float(principal_paid, default=0.0)
    return due > 0 and abs(paid - due) < PAID_TOLERANCE


def calculate_paid_last_four_calendar_months(
    schedule_rows: pd.DataFrame,
    shift_date: date | None,
    reference_date: date,
    tolerance: Decimal | float = PAID_TOLERANCE,
) -> dict[str, object]:
    target_months = _month_range_backwards(_shift_month(reference_date.year, reference_date.month, -1), 4)
    diagnostic: dict[str, object] = {
        "reference_date": reference_date.isoformat() if reference_date else None,
        "shift_date": shift_date.isoformat() if shift_date else None,
        "target_months": target_months,
        "target_months_formatted": [_format_month_key(month_key) for month_key in target_months],
        "rows_after_delay": [],
        "rows_in_target_months": [],
        "found_months": [],
        "found_months_formatted": [],
        "all_paid": False,
        "reason": "",
        "status": "N/A",
    }
    if shift_date is None:
        diagnostic["reason"] = "Date de décalage manquante."
        return {
            "status": "N/A",
            "target_months": target_months,
            "found_months": [],
            "all_paid": False,
            "diagnostic": diagnostic,
        }

    due_dates = pd.to_datetime(schedule_rows.get("due_date"), errors="coerce").dt.date
    filtered = schedule_rows[due_dates.apply(lambda value: value is not None and value > shift_date)].copy()
    filtered["due_date"] = pd.to_datetime(filtered["due_date"], errors="coerce").dt.date
    filtered = filtered.sort_values(["due_date", "installment_no"], ascending=[False, False], kind="stable").reset_index(drop=True)

    rows_after_delay = []
    for _, row in filtered.iterrows():
        due_date = _optional_date(row.get("due_date"))
        principal_due = _coerce_float(row.get("principal_due"), default=0.0)
        principal_paid = _coerce_float(row.get("principal_paid"), default=0.0)
        difference = abs(principal_paid - principal_due)
        paid = principal_due > 0 and difference < float(tolerance)
        rows_after_delay.append(
            {
                "installment_no": _optional_int(row.get("installment_no")),
                "due_date": due_date.isoformat() if due_date else None,
                "month": _format_month_key(_month_key(due_date)),
                "principal_due": principal_due,
                "principal_paid": principal_paid,
                "difference": difference,
                "paid": paid,
                "schedule_id": _optional_text(row.get("schedule_id")) if "schedule_id" in row else None,
                "is_active": _coerce_schedule_bool(row.get("is_active")) if "is_active" in row else None,
                "all_paid": _coerce_schedule_bool(row.get("all_paid")) if "all_paid" in row else None,
            }
        )
    diagnostic["rows_after_delay"] = rows_after_delay

    in_target_rows = [row for row in rows_after_delay if row["month"] is not None and tuple(map(int, row["month"].split("-"))) in target_months]
    diagnostic["rows_in_target_months"] = in_target_rows
    found_months = sorted(
        {
            tuple(map(int, row["month"].split("-")))
            for row in in_target_rows
            if row.get("month")
        },
        reverse=True,
    )
    diagnostic["found_months"] = found_months
    diagnostic["found_months_formatted"] = [_format_month_key(month_key) for month_key in found_months]

    if not in_target_rows:
        diagnostic["reason"] = "Aucune échéance dans les quatre mois calendaires ciblés après la date de décalage."
        return {
            "status": "N/A",
            "target_months": target_months,
            "found_months": found_months,
            "all_paid": False,
            "diagnostic": diagnostic,
        }

    all_paid = all(bool(row["paid"]) for row in in_target_rows)
    diagnostic["all_paid"] = all_paid
    status = "Oui" if all_paid and len(found_months) == 4 else "Non"
    diagnostic["status"] = status
    if status == "Oui":
        diagnostic["reason"] = "Toutes les échéances des quatre mois calendaires distincts ciblés sont payées."
    else:
        missing_months = [month_key for month_key in target_months if month_key not in found_months]
        unpaid_rows = [row for row in in_target_rows if not row["paid"]]
        reasons: list[str] = []
        if missing_months:
            reasons.append(
                "Mois manquants: " + ", ".join(_format_month_key(month_key) or "-" for month_key in missing_months)
            )
        if unpaid_rows:
            reasons.append(
                "Échéances non payées: "
                + ", ".join(
                    f"{row['installment_no']} ({row['month']})"
                    for row in unpaid_rows
                )
            )
        if not reasons:
            reasons.append("Les quatre mois distincts requis ne sont pas couverts.")
        diagnostic["reason"] = " | ".join(reasons)

    return {
        "status": status,
        "target_months": target_months,
        "found_months": found_months,
        "all_paid": all_paid,
        "diagnostic": diagnostic,
    }


def _deduplicate_schedule_rows(schedule: pd.DataFrame) -> pd.DataFrame:
    if schedule.empty:
        return schedule
    working = schedule.copy()
    working["_active_rank"] = working["is_active"].apply(_coerce_schedule_bool) if "is_active" in working else False
    working["_all_paid_rank"] = working["all_paid"].apply(_coerce_schedule_bool) if "all_paid" in working else False
    working["_paid_rank"] = working.apply(
        lambda row: _is_paid_installment(row.get("principal_due"), row.get("principal_paid")),
        axis=1,
    )
    working["_due_date_rank"] = pd.to_datetime(working["due_date"], errors="coerce") if "due_date" in working else pd.NaT
    working["_value_date_rank"] = pd.to_datetime(working["value_date"], errors="coerce") if "value_date" in working else pd.NaT
    working["_schedule_id_rank"] = pd.to_numeric(working["schedule_id"], errors="coerce") if "schedule_id" in working else float("nan")
    working["_principal_paid_rank"] = pd.to_numeric(working["principal_paid"], errors="coerce").fillna(0.0)
    working = working.sort_values(
        [
            "account_number",
            "installment_no",
            "_active_rank",
            "_all_paid_rank",
            "_paid_rank",
            "_due_date_rank",
            "_value_date_rank",
            "_schedule_id_rank",
            "_principal_paid_rank",
        ],
        ascending=[True, True, False, False, False, False, False, False, False],
        kind="stable",
    )
    working = working.drop_duplicates(subset=["account_number", "installment_no"], keep="first")
    return working.drop(
        columns=[
            "_active_rank",
            "_all_paid_rank",
            "_paid_rank",
            "_due_date_rank",
            "_value_date_rank",
            "_schedule_id_rank",
            "_principal_paid_rank",
        ],
        errors="ignore",
    ).reset_index(drop=True)


def _safe_datetime_to_string(value: datetime | date | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    return value.strftime("%d/%m/%Y %H:%M")


def _normalize_contract_frame(content: bytes) -> pd.DataFrame:
    frame = _read_excel(content)
    frame.columns = [str(column).strip() for column in frame.columns]
    resolved = _resolve_columns(frame, CONTRACT_COLUMN_ALIASES)
    required = ("contract_no",)
    missing = [field for field in required if not resolved.get(field)]
    if missing:
        raise ValueError(f"Colonnes manquantes dans le fichier contrats restructurés: {', '.join(missing)}")

    normalized = pd.DataFrame(
        {
            "source_contract_no": frame[resolved["source_contract_no"]] if resolved["source_contract_no"] else None,
            "contract_no": frame[resolved["contract_no"]],
            "restructure_label": frame[resolved["restructure_label"]] if resolved["restructure_label"] else None,
            "delay_date": frame[resolved["delay_date"]] if resolved["delay_date"] else None,
            "in_mcr": frame[resolved["in_mcr"]] if resolved["in_mcr"] else None,
            "category_desc": frame[resolved["category_desc"]] if resolved["category_desc"] else None,
            "total_due": frame[resolved["total_due"]] if resolved["total_due"] else None,
            "loan_duration": frame[resolved["loan_duration"]] if resolved["loan_duration"] else None,
        }
    )

    normalized["source_contract_no"] = normalized["source_contract_no"].apply(_optional_text)
    normalized["contract_no"] = normalized["contract_no"].apply(_optional_text)
    normalized["normalized_contract_no"] = normalized["contract_no"].apply(_normalize_contract_key)
    normalized["contract_no"] = normalized["normalized_contract_no"]
    normalized["restructure_label"] = normalized["restructure_label"].apply(_optional_text)
    normalized["delay_date"] = normalized["delay_date"].apply(_optional_date)
    normalized["in_mcr"] = normalized["in_mcr"].apply(_optional_text)
    normalized["category_desc"] = normalized["category_desc"].apply(_optional_text)
    normalized["credit_family"] = normalized["category_desc"].apply(_credit_family_from_category)
    normalized["source"] = LIST_IMPORT_SOURCE
    normalized["total_due"] = normalized["total_due"].apply(_optional_decimal)
    normalized["loan_duration"] = normalized["loan_duration"].apply(_optional_int)
    normalized = normalized[normalized["contract_no"].notna() & normalized["normalized_contract_no"].notna()].copy()
    normalized = normalized.drop_duplicates(subset=["normalized_contract_no"], keep="last")
    return normalized.reset_index(drop=True)


def _normalize_schedule_frame(content: bytes) -> pd.DataFrame:
    frame = _read_excel(content)
    frame.columns = [str(column).strip() for column in frame.columns]
    resolved = _resolve_columns(frame, SCHEDULE_COLUMN_ALIASES)
    required = ("account_number", "installment_no")
    missing = [field for field in required if not resolved.get(field)]
    if missing:
        raise ValueError(f"Colonnes manquantes dans le fichier schedule: {', '.join(missing)}")

    data: dict[str, Iterable] = {}
    for field in SCHEDULE_COLUMN_ALIASES:
        source = resolved.get(field)
        data[field] = frame[source] if source else [None] * len(frame.index)

    normalized = pd.DataFrame(data)
    for field in SCHEDULE_TEXT_FIELDS:
        normalized[field] = normalized[field].apply(_optional_text)
    normalized["account_number"] = normalized["account_number"].apply(_normalize_contract_key)
    for field in SCHEDULE_DATE_FIELDS:
        normalized[field] = normalized[field].apply(_optional_date)
    for field in SCHEDULE_DECIMAL_FIELDS:
        normalized[field] = normalized[field].apply(_optional_decimal)
    normalized["installment_no"] = normalized["installment_no"].apply(_optional_int)
    normalized["delay_days"] = normalized["delay_days"].apply(_optional_int)
    normalized["is_active"] = normalized["is_active"].apply(_bool_like)
    normalized["all_paid"] = normalized["all_paid"].apply(_bool_like)
    normalized = normalized[
        normalized["account_number"].notna() & normalized["installment_no"].notna()
    ].copy()
    normalized = normalized.drop_duplicates(subset=["account_number", "installment_no"], keep="last")
    return normalized.reset_index(drop=True)


def _coerce_schedule_field(field: str, value):
    if field == "account_number":
        return _normalize_contract_key(value)
    if field in SCHEDULE_TEXT_FIELDS:
        return _optional_text(value)
    if field in SCHEDULE_DATE_FIELDS:
        return _optional_date(value)
    if field in SCHEDULE_DECIMAL_FIELDS:
        return _optional_decimal(value)
    if field == "installment_no":
        return _optional_int(value)
    if field == "delay_days":
        return _optional_int(value)
    if field in {"is_active", "all_paid"}:
        return _bool_like(value)
    return value


def _stream_is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, str):
        return not value.strip()
    return False


def _stream_optional_text(value) -> str | None:
    if _stream_is_blank(value):
        return None
    text_value = str(value).strip()
    return text_value or None


def _stream_optional_int(value) -> int | None:
    if _stream_is_blank(value):
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _stream_optional_decimal(value) -> Decimal | None:
    if _stream_is_blank(value):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.001"))
    except Exception:
        return None


def _stream_optional_date(value) -> date | None:
    if _stream_is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _stream_bool_like(value) -> bool:
    if _stream_is_blank(value):
        return False
    if isinstance(value, bool):
        return value
    text_value = str(value).strip().lower()
    return text_value in {"1", "true", "t", "yes", "oui"}


def _schedule_stream_coercer(field: str):
    if field == "account_number":
        return _normalize_contract_key
    if field in SCHEDULE_TEXT_FIELDS:
        return _stream_optional_text
    if field in SCHEDULE_DATE_FIELDS:
        return _stream_optional_date
    if field in SCHEDULE_DECIMAL_FIELDS:
        return _stream_optional_decimal
    if field == "installment_no":
        return _stream_optional_int
    if field == "delay_days":
        return _stream_optional_int
    if field in {"is_active", "all_paid"}:
        return _stream_bool_like
    return lambda value: value


def _compile_schedule_projection(
    header_indexes: dict[str, int | None],
) -> tuple[int | None, int | None, list[tuple[str, int | None, object]]]:
    compiled: list[tuple[str, int | None, object]] = []
    account_source_index = header_indexes.get("account_number")
    installment_source_index = header_indexes.get("installment_no")
    for field in SCHEDULE_COLUMNS:
        compiled.append((field, header_indexes.get(field), _schedule_stream_coercer(field)))
    return account_source_index, installment_source_index, compiled


def _extract_schedule_identity(
    row_values: tuple[object, ...] | list[object],
    *,
    account_source_index: int | None,
    installment_source_index: int | None,
) -> tuple[str | None, int | None]:
    raw_account = (
        row_values[account_source_index]
        if account_source_index is not None and account_source_index < len(row_values)
        else None
    )
    raw_installment = (
        row_values[installment_source_index]
        if installment_source_index is not None and installment_source_index < len(row_values)
        else None
    )
    return _normalize_contract_key(raw_account), _stream_optional_int(raw_installment)


def _build_schedule_row_from_compiled(
    row_values: tuple[object, ...] | list[object],
    compiled_fields: list[tuple[str, int | None, object]],
    *,
    account_number: str | None,
    installment_no: int | None,
) -> list[object]:
    payload: list[object] = []
    for field, source_index, coercer in compiled_fields:
        if field == "account_number":
            payload.append(account_number)
            continue
        if field == "installment_no":
            payload.append(installment_no)
            continue
        raw_value = (
            row_values[source_index]
            if source_index is not None and source_index < len(row_values)
            else None
        )
        payload.append(coercer(raw_value))
    return payload


def _count_csv_data_rows(source_path: str | os.PathLike[str]) -> int:
    with open(source_path, "r", encoding="utf-8-sig", newline="") as source_handle:
        sample = source_handle.read(4096)
        source_handle.seek(0)
        dialect = _sniff_csv_dialect(sample)
        reader = csv.reader(source_handle, dialect)
        next(reader, None)
        return sum(1 for _ in reader)


def _build_progress_snapshot(
    *,
    processed_rows: int,
    total_rows: int,
    accepted_rows: int,
    ignored_rows: int,
    started_at: float,
    memory_peak_mb: float,
) -> dict[str, float | int | None]:
    elapsed_seconds = max(perf_counter() - started_at, 0.000001)
    rows_per_second = processed_rows / elapsed_seconds if processed_rows > 0 else 0.0
    eta_seconds: float | None = None
    if total_rows > 0 and rows_per_second > 0 and processed_rows < total_rows:
        eta_seconds = max((total_rows - processed_rows) / rows_per_second, 0.0)
    progress_ratio = 0.0 if total_rows <= 0 else min(processed_rows / max(total_rows, 1), 1.0)
    progress_percent = int(round(IMPORT_PHASE_WEIGHTS["filtering"] * progress_ratio))
    return {
        "processed_rows": processed_rows,
        "total_rows": total_rows,
        "accepted_rows": accepted_rows,
        "ignored_rows": ignored_rows,
        "elapsed_seconds": elapsed_seconds,
        "rows_per_second": rows_per_second,
        "eta_seconds": eta_seconds,
        "progress_percent": progress_percent,
        "memory_peak_mb": memory_peak_mb,
    }


def _csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _format_seconds(value: float) -> str:
    return f"{max(0.0, float(value or 0.0)):.2f}s"


def _format_megabytes(value: float) -> str:
    return f"{max(0.0, float(value or 0.0)):.2f} Mo"


def _format_import_phase_details(metrics: dict[str, object]) -> str:
    return " | ".join(
        [
            f"lignes_source={metrics.get('source_rows', 0)}",
            f"lignes_utiles={metrics.get('accepted_rows', 0)}",
            f"lignes_ignorees={metrics.get('ignored_rows', 0)}",
            f"lignes_identiques={metrics.get('unchanged_rows', 0)}",
            f"ouverture={_format_seconds(metrics.get('open_seconds', 0.0))}",
            f"feuille={_format_seconds(metrics.get('sheet_seconds', 0.0))}",
            f"lecture={_format_seconds(metrics.get('read_seconds', 0.0))}",
            f"normalisation={_format_seconds(metrics.get('normalize_seconds', 0.0))}",
            f"filtrage={_format_seconds(metrics.get('filter_seconds', 0.0))}",
            f"ecriture_csv={_format_seconds(metrics.get('write_seconds', 0.0))}",
            f"copy={_format_seconds(metrics.get('copy_seconds', 0.0))}",
            f"index={_format_seconds(metrics.get('index_seconds', 0.0))}",
            f"upsert={_format_seconds(metrics.get('upsert_seconds', 0.0))}",
            f"recalcul={_format_seconds(metrics.get('recalculate_seconds', 0.0))}",
            f"total={_format_seconds(metrics.get('total_seconds', 0.0))}",
            f"vitesse={float(metrics.get('rows_per_second', 0.0) or 0.0):.2f} l/s",
            f"eta={_format_seconds(metrics.get('eta_seconds', 0.0)) if metrics.get('eta_seconds') is not None else '-'}",
            f"memoire_pic={_format_megabytes(metrics.get('memory_peak_mb', 0.0))}",
        ]
    )


def _log_import_phase_metrics(prefix: str, metrics: dict[str, object]) -> None:
    logger.info("%s :: %s", prefix, _format_import_phase_details(metrics))


def _sniff_csv_dialect(sample: str):
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except Exception:
        return csv.excel


def _load_restructured_contract_keys(db: Session) -> set[str]:
    keys = db.scalars(
        select(RestructuredContract.normalized_contract_no).where(
            RestructuredContract.normalized_contract_no.is_not(None)
        )
    ).all()
    return {key for key in keys if key}


def _latest_current_import_batch(db: Session) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch)
        .where(ImportBatch.batch_type == ImportBatchType.CURRENT_STATE)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )


def _tracked_mcr_contracts_for_batch(
    db: Session,
    import_batch: ImportBatch | None,
) -> dict[str, LoanRaw]:
    if import_batch is None:
        return {}
    tracked_contracts: dict[str, LoanRaw] = {}
    loans = db.scalars(
        select(LoanRaw)
        .where(LoanRaw.import_batch_id == import_batch.id)
        .order_by(LoanRaw.id.desc())
    ).all()
    for loan in loans:
        normalized_contract = _normalize_contract_key(loan.contract_no)
        if not normalized_contract or _tracked_mcr_credit_family(loan.category_desc) is None:
            continue
        tracked_contracts.setdefault(normalized_contract, loan)
    return tracked_contracts


def _existing_restructured_contract_key(row: RestructuredContract) -> str | None:
    return row.normalized_contract_no or _normalize_contract_key(row.contract_no)


def _existing_pending_contract_key(row: PendingRestructuredContract) -> str | None:
    return row.normalized_contract_no or _normalize_contract_key(row.contract_no)


def _build_sync_deletion_preview(
    *,
    contract_no: str,
    credit_family: str | None,
    source: str | None,
    updated_at: datetime | None,
    scope: str,
) -> RestructuredSyncDeletionRead:
    return RestructuredSyncDeletionRead(
        contract_no=contract_no,
        type_credit=_credit_type_label(credit_family),
        source=source,
        updated_at=updated_at,
        reason="Absent de la nouvelle liste et absent du MCR actif",
        scope=scope,
    )


def _build_restructured_sync_plan(
    db: Session,
    *,
    frame: pd.DataFrame,
    file_name: str,
) -> dict[str, object]:
    imported_rows = _replace_nan_with_none(frame.to_dict(orient="records"))
    imported_map = {
        row["normalized_contract_no"]: row
        for row in imported_rows
        if row.get("normalized_contract_no")
    }
    imported_keys = set(imported_map.keys())
    active_batch = _latest_current_import_batch(db)
    tracked_mcr_contracts = _tracked_mcr_contracts_for_batch(db, active_batch)
    tracked_keys = set(tracked_mcr_contracts.keys())
    allowed_keys = imported_keys | tracked_keys

    official_rows = db.scalars(select(RestructuredContract)).all()
    official_by_key = {
        key: row
        for row in official_rows
        if (key := _existing_restructured_contract_key(row)) is not None
    }
    pending_rows = db.scalars(select(PendingRestructuredContract)).all()
    pending_by_key = {
        key: row
        for row in pending_rows
        if (key := _existing_pending_contract_key(row)) is not None
    }

    official_deletions: list[RestructuredSyncDeletionRead] = []
    official_delete_ids: list[int] = []
    official_delete_contract_nos: list[str] = []
    for key, row in official_by_key.items():
        if key in allowed_keys:
            continue
        official_delete_ids.append(row.id)
        official_delete_contract_nos.append(row.contract_no)
        official_deletions.append(
            _build_sync_deletion_preview(
                contract_no=row.contract_no,
                credit_family=row.credit_family,
                source=row.source,
                updated_at=row.updated_at,
                scope="official",
            )
        )

    pending_deletions: list[RestructuredSyncDeletionRead] = []
    pending_delete_ids: list[int] = []
    for key, row in pending_by_key.items():
        if key in allowed_keys:
            continue
        pending_delete_ids.append(row.id)
        pending_deletions.append(
            _build_sync_deletion_preview(
                contract_no=row.contract_no,
                credit_family=row.credit_family,
                source=f"PENDING_{str(row.status or '').upper()}",
                updated_at=row.detected_at,
                scope="pending",
            )
        )

    add_count = sum(1 for key in imported_keys if key not in official_by_key)
    update_count = len(imported_keys) - add_count
    kept_count = sum(1 for key in official_by_key if key in allowed_keys)

    return {
        "file_name": file_name,
        "rows_seen": len(frame.index),
        "imported_rows": imported_rows,
        "imported_keys": imported_keys,
        "tracked_mcr_keys": tracked_keys,
        "active_mcr_batch": active_batch,
        "existing_contracts_count": len(official_by_key),
        "imported_list_count": len(imported_keys),
        "detected_in_mcr_count": len(tracked_keys),
        "kept_count": kept_count,
        "add_count": add_count,
        "update_count": update_count,
        "delete_count": len(official_delete_ids),
        "pending_cleanup_count": len(pending_delete_ids),
        "deletions": official_deletions + pending_deletions,
        "official_delete_ids": official_delete_ids,
        "official_delete_contract_nos": official_delete_contract_nos,
        "pending_delete_ids": pending_delete_ids,
    }


def preview_restructured_contract_sync(
    db: Session,
    content: bytes,
    file_name: str,
) -> RestructuredSyncPreviewRead:
    frame = _normalize_contract_frame(content)
    plan = _build_restructured_sync_plan(db, frame=frame, file_name=file_name)
    return RestructuredSyncPreviewRead(
        file_name=file_name,
        rows_seen=int(plan["rows_seen"]),
        existing_contracts_count=int(plan["existing_contracts_count"]),
        imported_list_count=int(plan["imported_list_count"]),
        detected_in_mcr_count=int(plan["detected_in_mcr_count"]),
        kept_count=int(plan["kept_count"]),
        add_count=int(plan["add_count"]),
        update_count=int(plan["update_count"]),
        delete_count=int(plan["delete_count"]),
        pending_cleanup_count=int(plan["pending_cleanup_count"]),
        deletions=list(plan["deletions"]),
        message=(
            "Previsualisation de synchronisation terminee. "
            f"{int(plan['delete_count'])} contrat(s) officiel(s) et "
            f"{int(plan['pending_cleanup_count'])} contrat(s) en attente seront nettoyes apres confirmation."
        ),
    )


def _pending_missing_fields(
    *,
    shift_date: date | None,
    total_due: Decimal | None,
    loan_duration: int | None,
) -> list[str]:
    missing: list[str] = []
    if shift_date is None:
        missing.append(PENDING_FIELD_LABELS["shift_date"])
    if total_due is None:
        missing.append(PENDING_FIELD_LABELS["total_due"])
    if loan_duration is None:
        missing.append(PENDING_FIELD_LABELS["loan_duration"])
    return missing


def _pending_status_from_missing_fields(missing_fields: list[str]) -> str:
    return PENDING_STATUS_READY if not missing_fields else PENDING_STATUS_TO_COMPLETE


def _credit_type_label(family: str | None) -> str:
    return "Consolide" if family == CONSOLIDATED_FAMILY else "Restructure"


def _pending_contract_to_read(row: PendingRestructuredContract) -> PendingRestructuredContractRead:
    return PendingRestructuredContractRead(
        id=row.id,
        contract_no=row.contract_no,
        type_credit=_credit_type_label(row.credit_family),
        category_desc=row.category_desc,
        client_name=row.client_name,
        client_first_name=row.client_first_name,
        agency_name=row.agency_name,
        agent_name=row.agent_name,
        disbursement_date=row.disbursement_date,
        disbursement_amount=row.disbursement_amount,
        shift_date=row.shift_date,
        total_due=row.total_due,
        loan_duration=row.loan_duration,
        missing_fields=list(row.missing_fields or []),
        status=row.status,
        detected_at=row.detected_at,
        detected_from_import=row.detected_from_import,
    )


def _pending_status_message(status: str) -> str:
    return "Pret a enregistrer" if status == PENDING_STATUS_READY else "A completer"


def _authorized_import_roles() -> list[UserRole]:
    return [UserRole.SUPER_ADMIN]


def _resolve_schedule_header_indexes(header_row: list[object]) -> dict[str, int | None]:
    normalized_lookup: dict[str, int] = {}
    for index, column in enumerate(header_row):
        key = _normalize_header(column)
        if key and key not in normalized_lookup:
            normalized_lookup[key] = index
    resolved: dict[str, int | None] = {}
    for canonical, aliases in SCHEDULE_COLUMN_ALIASES.items():
        match_index = None
        for alias in aliases:
            match_index = normalized_lookup.get(_normalize_header(alias))
            if match_index is not None:
                break
        resolved[canonical] = match_index
    required = ("account_number", "installment_no")
    missing = [field for field in required if resolved.get(field) is None]
    if missing:
        raise ValueError(
            f"Colonnes manquantes dans le fichier schedule: {', '.join(missing)}"
        )
    return resolved


def _build_schedule_row_from_values(
    row_values: tuple[object, ...] | list[object],
    header_indexes: dict[str, int | None],
) -> list[object] | None:
    payload: list[object] = []
    for field in SCHEDULE_COLUMNS:
        source_index = header_indexes.get(field)
        raw_value = (
            row_values[source_index]
            if source_index is not None and source_index < len(row_values)
            else None
        )
        payload.append(_coerce_schedule_field(field, raw_value))
    account_number = payload[SCHEDULE_COLUMNS.index("account_number")]
    installment_no = payload[SCHEDULE_COLUMNS.index("installment_no")]
    if not account_number or installment_no is None:
        return None
    return payload


def _stream_schedule_xlsx_to_csv(
    source_path: str | os.PathLike[str],
    csv_path: str | os.PathLike[str],
    *,
    useful_contracts: set[str] | None = None,
    progress_callback=None,
    max_rows: int | None = None,
) -> tuple[int, dict[str, float | int]]:
    metrics: dict[str, float | int] = {
        "source_total_rows": 0,
        "total_rows": 0,
        "source_rows": 0,
        "accepted_rows": 0,
        "ignored_rows": 0,
        "open_seconds": 0.0,
        "sheet_seconds": 0.0,
        "read_seconds": 0.0,
        "normalize_seconds": 0.0,
        "filter_seconds": 0.0,
        "write_seconds": 0.0,
    }
    open_started = perf_counter()
    workbook = load_workbook(filename=source_path, read_only=True, data_only=True)
    metrics["open_seconds"] = perf_counter() - open_started
    try:
        sheet_started = perf_counter()
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header_started = perf_counter()
        header = next(rows, None)
        metrics["sheet_seconds"] = perf_counter() - sheet_started
        metrics["read_seconds"] = float(metrics["read_seconds"]) + (perf_counter() - header_started)
        if header is None:
            raise ValueError("Le fichier schedule est vide.")
        header_indexes = _resolve_schedule_header_indexes(list(header))
        account_source_index, installment_source_index, compiled_fields = _compile_schedule_projection(
            header_indexes
        )
        total_rows = max(int(sheet.max_row or 1) - 1, 0)
        metrics["source_total_rows"] = total_rows
        if max_rows is not None:
            total_rows = min(total_rows, max_rows)
        metrics["total_rows"] = total_rows
        written_rows = 0
        processed_rows = 0
        started_at = perf_counter()
        last_progress_at = started_at
        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            while True:
                read_started = perf_counter()
                row = next(rows, None)
                metrics["read_seconds"] = float(metrics["read_seconds"]) + (
                    perf_counter() - read_started
                )
                if row is None:
                    break
                processed_rows += 1
                if max_rows is not None and processed_rows > max_rows:
                    break
                metrics["source_rows"] = processed_rows
                identity_started = perf_counter()
                account_number, installment_no = _extract_schedule_identity(
                    row,
                    account_source_index=account_source_index,
                    installment_source_index=installment_source_index,
                )
                metrics["normalize_seconds"] = float(metrics["normalize_seconds"]) + (
                    perf_counter() - identity_started
                )
                if not account_number or installment_no is None:
                    metrics["ignored_rows"] = int(metrics["ignored_rows"]) + 1
                    continue
                filter_started = perf_counter()
                if useful_contracts is not None and account_number not in useful_contracts:
                    metrics["filter_seconds"] = float(metrics["filter_seconds"]) + (
                        perf_counter() - filter_started
                    )
                    metrics["ignored_rows"] = int(metrics["ignored_rows"]) + 1
                    continue
                metrics["filter_seconds"] = float(metrics["filter_seconds"]) + (
                    perf_counter() - filter_started
                )
                normalize_started = perf_counter()
                payload = _build_schedule_row_from_compiled(
                    row,
                    compiled_fields,
                    account_number=account_number,
                    installment_no=installment_no,
                )
                metrics["normalize_seconds"] = float(metrics["normalize_seconds"]) + (
                    perf_counter() - normalize_started
                )
                write_started = perf_counter()
                writer.writerow([processed_rows, *(_csv_value(value) for value in payload)])
                metrics["write_seconds"] = float(metrics["write_seconds"]) + (
                    perf_counter() - write_started
                )
                written_rows += 1
                metrics["accepted_rows"] = written_rows
                current_time = perf_counter()
                should_publish = (
                    processed_rows % IMPORT_PROGRESS_ROW_INTERVAL == 0
                    or (current_time - last_progress_at) >= IMPORT_PROGRESS_TIME_INTERVAL_SECONDS
                )
                if progress_callback and should_publish:
                    progress_callback(
                        **_build_progress_snapshot(
                            processed_rows=processed_rows,
                            total_rows=total_rows,
                            accepted_rows=written_rows,
                            ignored_rows=int(metrics["ignored_rows"]),
                            started_at=started_at,
                            memory_peak_mb=0.0,
                        )
                    )
                    last_progress_at = current_time
        if progress_callback:
            progress_callback(
                **_build_progress_snapshot(
                    processed_rows=processed_rows,
                    total_rows=total_rows,
                    accepted_rows=written_rows,
                    ignored_rows=int(metrics["ignored_rows"]),
                    started_at=started_at,
                    memory_peak_mb=0.0,
                )
            )
        return written_rows, metrics
    finally:
        workbook.close()


def _stream_schedule_csv_to_csv(
    source_path: str | os.PathLike[str],
    csv_path: str | os.PathLike[str],
    *,
    useful_contracts: set[str] | None = None,
    progress_callback=None,
    max_rows: int | None = None,
) -> tuple[int, dict[str, float | int]]:
    metrics: dict[str, float | int] = {
        "source_total_rows": 0,
        "total_rows": 0,
        "source_rows": 0,
        "accepted_rows": 0,
        "ignored_rows": 0,
        "open_seconds": 0.0,
        "sheet_seconds": 0.0,
        "read_seconds": 0.0,
        "normalize_seconds": 0.0,
        "filter_seconds": 0.0,
        "write_seconds": 0.0,
    }
    open_started = perf_counter()
    total_rows = _count_csv_data_rows(source_path)
    metrics["source_total_rows"] = total_rows
    metrics["open_seconds"] = perf_counter() - open_started
    if max_rows is not None:
        total_rows = min(total_rows, max_rows)
    metrics["total_rows"] = total_rows
    with open(source_path, "r", encoding="utf-8-sig", newline="") as source_handle:
        sample = source_handle.read(4096)
        source_handle.seek(0)
        dialect = _sniff_csv_dialect(sample)
        reader = csv.reader(source_handle, dialect)
        header_started = perf_counter()
        header = next(reader, None)
        metrics["read_seconds"] = float(metrics["read_seconds"]) + (perf_counter() - header_started)
        if header is None:
            raise ValueError("Le fichier schedule est vide.")
        header_indexes = _resolve_schedule_header_indexes(list(header))
        account_source_index, installment_source_index, compiled_fields = _compile_schedule_projection(
            header_indexes
        )
        started_at = perf_counter()
        last_progress_at = started_at
        with open(csv_path, "w", newline="", encoding="utf-8") as output_handle:
            writer = csv.writer(output_handle, lineterminator="\n")
            for processed_rows, row in enumerate(reader, start=1):
                if max_rows is not None and processed_rows > max_rows:
                    break
                metrics["source_rows"] = processed_rows
                read_started = perf_counter()
                row_values = list(row)
                metrics["read_seconds"] = float(metrics["read_seconds"]) + (
                    perf_counter() - read_started
                )
                identity_started = perf_counter()
                account_number, installment_no = _extract_schedule_identity(
                    row_values,
                    account_source_index=account_source_index,
                    installment_source_index=installment_source_index,
                )
                metrics["normalize_seconds"] = float(metrics["normalize_seconds"]) + (
                    perf_counter() - identity_started
                )
                if not account_number or installment_no is None:
                    metrics["ignored_rows"] = int(metrics["ignored_rows"]) + 1
                    continue
                filter_started = perf_counter()
                if useful_contracts is not None and account_number not in useful_contracts:
                    metrics["filter_seconds"] = float(metrics["filter_seconds"]) + (
                        perf_counter() - filter_started
                    )
                    metrics["ignored_rows"] = int(metrics["ignored_rows"]) + 1
                    continue
                metrics["filter_seconds"] = float(metrics["filter_seconds"]) + (
                    perf_counter() - filter_started
                )
                normalize_started = perf_counter()
                payload = _build_schedule_row_from_compiled(
                    row_values,
                    compiled_fields,
                    account_number=account_number,
                    installment_no=installment_no,
                )
                metrics["normalize_seconds"] = float(metrics["normalize_seconds"]) + (
                    perf_counter() - normalize_started
                )
                write_started = perf_counter()
                writer.writerow([processed_rows, *(_csv_value(value) for value in payload)])
                metrics["write_seconds"] = float(metrics["write_seconds"]) + (
                    perf_counter() - write_started
                )
                metrics["accepted_rows"] = int(metrics["accepted_rows"]) + 1
                current_time = perf_counter()
                should_publish = (
                    processed_rows % IMPORT_PROGRESS_ROW_INTERVAL == 0
                    or (current_time - last_progress_at) >= IMPORT_PROGRESS_TIME_INTERVAL_SECONDS
                )
                if progress_callback and should_publish:
                    progress_callback(
                        **_build_progress_snapshot(
                            processed_rows=processed_rows,
                            total_rows=total_rows,
                            accepted_rows=int(metrics["accepted_rows"]),
                            ignored_rows=int(metrics["ignored_rows"]),
                            started_at=started_at,
                            memory_peak_mb=0.0,
                        )
                    )
                    last_progress_at = current_time
        if progress_callback:
            progress_callback(
                **_build_progress_snapshot(
                    processed_rows=int(metrics["source_rows"]),
                    total_rows=total_rows,
                    accepted_rows=int(metrics["accepted_rows"]),
                    ignored_rows=int(metrics["ignored_rows"]),
                    started_at=started_at,
                    memory_peak_mb=0.0,
                )
            )
    return int(metrics["accepted_rows"]), metrics


def _materialize_schedule_from_non_stream_source(
    source_path: str | os.PathLike[str],
    csv_path: str | os.PathLike[str],
    *,
    useful_contracts: set[str] | None = None,
    progress_callback=None,
    max_rows: int | None = None,
) -> tuple[int, dict[str, float | int]]:
    pipeline_started = perf_counter()
    read_started = perf_counter()
    content = Path(source_path).read_bytes()
    read_elapsed = perf_counter() - read_started
    normalize_started = perf_counter()
    frame = _normalize_schedule_frame(content)
    normalize_elapsed = perf_counter() - normalize_started
    source_rows = len(frame.index)
    filter_started = perf_counter()
    if useful_contracts is not None:
        frame = frame[frame["account_number"].isin(useful_contracts)].copy()
    if max_rows is not None:
        frame = frame.head(max_rows).copy()
    filter_elapsed = perf_counter() - filter_started
    write_started = perf_counter()
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        for order_index, row in enumerate(
            frame[SCHEDULE_COLUMNS].itertuples(index=False, name=None), start=1
        ):
            writer.writerow([order_index, *(_csv_value(value) for value in row)])
    write_elapsed = perf_counter() - write_started
    row_count = len(frame.index)
    if progress_callback:
        progress_callback(
            **_build_progress_snapshot(
                processed_rows=row_count,
                total_rows=row_count,
                accepted_rows=row_count,
                ignored_rows=max(0, source_rows - row_count),
                started_at=pipeline_started,
                memory_peak_mb=0.0,
            )
        )
    return row_count, {
        "source_total_rows": source_rows,
        "total_rows": row_count,
        "source_rows": source_rows,
        "accepted_rows": row_count,
        "ignored_rows": max(0, source_rows - row_count),
        "open_seconds": 0.0,
        "sheet_seconds": 0.0,
        "read_seconds": read_elapsed,
        "normalize_seconds": normalize_elapsed,
        "filter_seconds": filter_elapsed,
        "write_seconds": write_elapsed,
    }


def _replace_nan_with_none(records: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for record in records:
        payload: dict = {}
        for key, value in record.items():
            if isinstance(value, float) and math.isnan(value):
                payload[key] = None
            elif pd.isna(value):
                payload[key] = None
            else:
                payload[key] = value
        cleaned.append(payload)
    return cleaned


def _upsert_contracts(db: Session, frame: pd.DataFrame) -> tuple[int, int]:
    payloads = _replace_nan_with_none(frame.to_dict(orient="records"))
    if not payloads:
        return 0, 0

    existing = set(
        db.scalars(
            select(RestructuredContract.contract_no).where(
                RestructuredContract.contract_no.in_([row["contract_no"] for row in payloads])
            )
        ).all()
    )
    inserted = sum(1 for row in payloads if row["contract_no"] not in existing)
    updated = len(payloads) - inserted
    dialect = db.bind.dialect.name if db.bind is not None else ""
    insert_builder = pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None

    if insert_builder is None:
        for payload in payloads:
            db.merge(RestructuredContract(**payload))
        db.flush()
        return inserted, updated

    stmt = insert_builder(RestructuredContract).values(payloads)
    upsert = stmt.on_conflict_do_update(
        index_elements=[RestructuredContract.contract_no],
        set_={
            "source_contract_no": stmt.excluded.source_contract_no,
            "normalized_contract_no": stmt.excluded.normalized_contract_no,
            "credit_family": stmt.excluded.credit_family,
            "restructure_label": stmt.excluded.restructure_label,
            "delay_date": stmt.excluded.delay_date,
            "in_mcr": stmt.excluded.in_mcr,
            "category_desc": stmt.excluded.category_desc,
            "total_due": stmt.excluded.total_due,
            "loan_duration": stmt.excluded.loan_duration,
            "source": stmt.excluded.source,
            "updated_at": func.now(),
        },
    )
    db.execute(upsert)
    db.flush()
    return inserted, updated


def remove_pending_restructured_contracts_matching_official_list(
    db: Session,
    normalized_contract_numbers: Iterable[str] | None,
) -> int:
    scoped_contracts = _normalize_contract_number_list(normalized_contract_numbers)
    if not scoped_contracts:
        return 0
    deleted_count = (
        db.execute(
            delete(PendingRestructuredContract).where(
                PendingRestructuredContract.normalized_contract_no.in_(scoped_contracts)
            )
        ).rowcount
        or 0
    )
    db.flush()
    return int(deleted_count)


def _delete_pending_restructured_contracts_by_ids(
    db: Session,
    pending_ids: Iterable[int] | None,
) -> int:
    scoped_ids = [int(raw_id) for raw_id in (pending_ids or []) if raw_id is not None]
    if not scoped_ids:
        return 0
    deleted_count = (
        db.execute(delete(PendingRestructuredContract).where(PendingRestructuredContract.id.in_(scoped_ids))).rowcount
        or 0
    )
    db.flush()
    return int(deleted_count)


def _delete_restructured_contract_relations(
    db: Session,
    contract_numbers: Iterable[str] | None,
) -> dict[str, int]:
    scoped_contracts = _normalize_contract_number_list(contract_numbers)
    if not scoped_contracts:
        return {
            "contracts": 0,
            "analysis_results": 0,
            "gap_results": 0,
            "schedule_rows": 0,
        }

    analysis_deleted = (
        db.execute(
            delete(RestructuredAnalysisResult).where(
                RestructuredAnalysisResult.contract_no.in_(scoped_contracts)
            )
        ).rowcount
        or 0
    )
    gap_deleted = (
        db.execute(
            delete(RestructuredGapResult).where(
                RestructuredGapResult.contract_no.in_(scoped_contracts)
            )
        ).rowcount
        or 0
    )
    schedule_deleted = (
        db.execute(
            delete(RestructuredScheduleRow).where(
                RestructuredScheduleRow.account_number.in_(scoped_contracts)
            )
        ).rowcount
        or 0
    )
    contract_deleted = (
        db.execute(
            delete(RestructuredContract).where(
                RestructuredContract.contract_no.in_(scoped_contracts)
            )
        ).rowcount
        or 0
    )
    db.flush()
    return {
        "contracts": int(contract_deleted),
        "analysis_results": int(analysis_deleted),
        "gap_results": int(gap_deleted),
        "schedule_rows": int(schedule_deleted),
    }


def _build_pending_contract_payload_from_loan(
    loan: LoanRaw,
    *,
    import_batch_id: int | None,
    existing: PendingRestructuredContract | None = None,
) -> dict[str, object]:
    family = _tracked_mcr_credit_family(loan.category_desc)
    normalized_contract = _normalize_contract_key(loan.contract_no)
    shift_date = existing.shift_date if existing is not None else None
    loan_duration = existing.loan_duration if existing is not None else None
    total_due = loan.total_due if loan.total_due is not None else (existing.total_due if existing is not None else None)
    missing_fields = _pending_missing_fields(
        shift_date=shift_date,
        total_due=total_due,
        loan_duration=loan_duration,
    )
    return {
        "contract_no": _optional_text(loan.contract_no) or normalized_contract,
        "normalized_contract_no": normalized_contract,
        "credit_family": family,
        "category_desc": _optional_text(loan.category_desc),
        "client_name": _optional_text(loan.client_name),
        "client_first_name": _optional_text(loan.client_first_name),
        "agency_name": _optional_text(loan.agency_name),
        "agent_name": _optional_text(loan.agent_name),
        "disbursement_date": loan.disbursement_date,
        "disbursement_amount": loan.disbursement_amount,
        "shift_date": shift_date,
        "total_due": total_due,
        "loan_duration": loan_duration,
        "missing_fields": missing_fields,
        "status": _pending_status_from_missing_fields(missing_fields),
        "detected_at": datetime.utcnow(),
        "detected_from_import": import_batch_id,
        "completed_by_user_id": None,
        "completed_at": None,
    }


def _sync_pending_restructured_contracts_from_mcr_batch(
    db: Session,
    import_batch: ImportBatch,
    *,
    emit_log: bool = True,
) -> dict[str, int]:
    if import_batch is None:
        return {
            "restructured_detected": 0,
            "consolidated_detected": 0,
            "already_present": 0,
            "new_detected": 0,
            "pending_to_complete": 0,
            "validated": 0,
            "errors": 0,
        }

    tracked_loans = db.scalars(
        select(LoanRaw)
        .where(LoanRaw.import_batch_id == import_batch.id)
        .order_by(LoanRaw.id.desc())
    ).all()
    official_keys = _load_restructured_contract_keys(db)
    existing_pending = {
        row.normalized_contract_no: row
        for row in db.scalars(select(PendingRestructuredContract)).all()
        if row.normalized_contract_no
    }

    detected_contracts: dict[str, LoanRaw] = {}
    family_counts = {RESTRUCTURED_FAMILY: 0, CONSOLIDATED_FAMILY: 0}
    already_present = 0
    new_detected = 0
    errors = 0

    for loan in tracked_loans:
        normalized_contract = _normalize_contract_key(loan.contract_no)
        family = _tracked_mcr_credit_family(loan.category_desc)
        if not normalized_contract or family is None:
            continue
        family_counts[family] += 1
        if normalized_contract in detected_contracts:
            continue
        detected_contracts[normalized_contract] = loan
        if normalized_contract in official_keys:
            already_present += 1
            continue
        payload = _build_pending_contract_payload_from_loan(
            loan,
            import_batch_id=import_batch.id,
            existing=existing_pending.get(normalized_contract),
        )
        try:
            current_row = existing_pending.get(normalized_contract)
            if current_row is None:
                db.add(PendingRestructuredContract(**payload))
                new_detected += 1
            else:
                for field_name, field_value in payload.items():
                    setattr(current_row, field_name, field_value)
            db.flush()
        except Exception:
            errors += 1
            logger.exception(
                "Unable to sync pending restructured contract normalized_contract_no=%s import_batch_id=%s",
                normalized_contract,
                import_batch.id,
            )

    pending_count = db.scalar(select(func.count(PendingRestructuredContract.id))) or 0
    summary = {
        "restructured_detected": int(family_counts[RESTRUCTURED_FAMILY]),
        "consolidated_detected": int(family_counts[CONSOLIDATED_FAMILY]),
        "already_present": int(already_present),
        "new_detected": int(new_detected),
        "pending_to_complete": int(pending_count),
        "validated": 0,
        "errors": int(errors),
    }

    if emit_log:
        started_at = datetime.utcnow()
        finished_at = datetime.utcnow()
        _record_log(
            db,
            import_type="mcr_consistency",
            file_name=import_batch.file_name,
            started_at=started_at,
            finished_at=finished_at,
            row_count=summary["restructured_detected"] + summary["consolidated_detected"],
            status="success" if errors == 0 else "warning",
            message=(
                "Controle MCR/restructures termine. "
                f"{summary['new_detected']} contrat(s) a completer, "
                f"{summary['already_present']} deja present(s)."
            ),
            inserted_count=summary["new_detected"],
            updated_count=max(
                summary["restructured_detected"] + summary["consolidated_detected"]
                - summary["already_present"]
                - summary["new_detected"],
                0,
            ),
            recalculated_contracts=summary["validated"],
            phase="completed",
            progress_percent=100,
            phase_details=(
                f"Restructures detectes: {summary['restructured_detected']} | "
                f"Consolides detectes: {summary['consolidated_detected']} | "
                f"Deja presents: {summary['already_present']} | "
                f"A completer: {summary['pending_to_complete']} | "
                f"Erreurs: {summary['errors']}"
            ),
        )
        db.flush()
    return summary


def sync_pending_restructured_contracts_from_mcr_batch(
    db: Session,
    import_batch: ImportBatch,
) -> dict[str, int]:
    return _sync_pending_restructured_contracts_from_mcr_batch(
        db,
        import_batch,
        emit_log=True,
    )


def resync_pending_restructured_contracts_from_all_mcr(
    db: Session,
) -> dict[str, int]:
    """
    Full-table resync.

    Scans the entire `loans_raw` table for rows whose CATEGORY_DESC maps to a
    tracked credit family and whose normalized contract_no is NOT already in
    `restructured_contracts`. Idempotent: re-running it does not create
    duplicates and updates existing pending rows with the latest MCR values.

    This is the safety net the user can call when the per-batch sync was
    missed (e.g. the import's batch_type became SNAPSHOT, the LoanRaw row has
    a NULL import_batch_id, or the CATEGORY_DESC normalization used a too
    strict dictionary in an older version of the code).
    """
    tracked_loans = db.scalars(
        select(LoanRaw).order_by(LoanRaw.id.desc())
    ).all()
    official_keys = _load_restructured_contract_keys(db)
    existing_pending = {
        row.normalized_contract_no: row
        for row in db.scalars(select(PendingRestructuredContract)).all()
        if row.normalized_contract_no
    }

    detected_contracts: dict[str, LoanRaw] = {}
    family_counts = {RESTRUCTURED_FAMILY: 0, CONSOLIDATED_FAMILY: 0}
    already_present = 0
    updated_existing = 0
    new_detected = 0
    errors = 0
    skipped_invalid = 0
    skipped_already_tracked = 0

    for loan in tracked_loans:
        normalized_contract = _normalize_contract_key(loan.contract_no)
        if not normalized_contract:
            skipped_invalid += 1
            continue
        family = _tracked_mcr_credit_family(loan.category_desc)
        if family is None:
            skipped_invalid += 1
            continue
        family_counts[family] += 1
        if normalized_contract in detected_contracts:
            skipped_already_tracked += 1
            continue
        detected_contracts[normalized_contract] = loan
        if normalized_contract in official_keys:
            already_present += 1
            continue
        payload = _build_pending_contract_payload_from_loan(
            loan,
            import_batch_id=loan.import_batch_id,
            existing=existing_pending.get(normalized_contract),
        )
        try:
            current_row = existing_pending.get(normalized_contract)
            if current_row is None:
                db.add(PendingRestructuredContract(**payload))
                new_detected += 1
            else:
                for field_name, field_value in payload.items():
                    setattr(current_row, field_name, field_value)
                updated_existing += 1
            db.flush()
        except Exception:
            errors += 1
            logger.exception(
                "Unable to resync pending restructured contract normalized_contract_no=%s",
                normalized_contract,
            )

    db.flush()
    pending_count = db.scalar(select(func.count(PendingRestructuredContract.id))) or 0
    summary = {
        "loans_scanned": len(tracked_loans),
        "restructured_detected": int(family_counts[RESTRUCTURED_FAMILY]),
        "consolidated_detected": int(family_counts[CONSOLIDATED_FAMILY]),
        "already_present": int(already_present),
        "new_detected": int(new_detected),
        "updated_existing": int(updated_existing),
        "skipped_invalid": int(skipped_invalid),
        "skipped_duplicates_within_mcr": int(skipped_already_tracked),
        "pending_to_complete": int(pending_count),
        "errors": int(errors),
    }
    return summary


def get_pending_restructured_contracts_diagnostics(db: Session) -> dict[str, int]:
    """
    Counts the rows at each stage of the pipeline so the frontend can show
    the user exactly where the data disappears (if it does).
    """
    total_loans = db.scalar(select(func.count(LoanRaw.id))) or 0
    loans_with_category = db.scalar(
        select(func.count(LoanRaw.id)).where(LoanRaw.category_desc.is_not(None))
    ) or 0
    consolidated_loans = 0
    restructured_loans = 0
    for raw_value in db.scalars(
        select(LoanRaw.category_desc).where(LoanRaw.category_desc.is_not(None)).distinct()
    ).all():
        family = _tracked_mcr_credit_family(raw_value)
        if family == CONSOLIDATED_FAMILY:
            consolidated_loans += 1
        elif family == RESTRUCTURED_FAMILY:
            restructured_loans += 1
    distinct_restructured_loans = db.scalar(
        select(func.count(func.distinct(LoanRaw.contract_no))).where(
            _tracked_mcr_credit_family_filter(LoanRaw.category_desc) == RESTRUCTURED_FAMILY
        )
    ) or 0
    distinct_consolidated_loans = db.scalar(
        select(func.count(func.distinct(LoanRaw.contract_no))).where(
            _tracked_mcr_credit_family_filter(LoanRaw.category_desc) == CONSOLIDATED_FAMILY
        )
    ) or 0
    total_official = db.scalar(select(func.count(RestructuredContract.id))) or 0
    total_pending = db.scalar(select(func.count(PendingRestructuredContract.id))) or 0
    return {
        "loans_total": int(total_loans),
        "loans_with_category_desc": int(loans_with_category),
        "loans_restructured_distinct": int(distinct_restructured_loans),
        "loans_consolidated_distinct": int(distinct_consolidated_loans),
        "loans_restructured_distinct_category_values": int(restructured_loans),
        "loans_consolidated_distinct_category_values": int(consolidated_loans),
        "official_restructured_contracts": int(total_official),
        "pending_restructured_contracts": int(total_pending),
    }


def _tracked_mcr_credit_family_filter(column):
    """SQL-side mirror of `_tracked_mcr_credit_family` for diagnostics."""
    normalized = func.lower(
        func.replace(
            func.replace(
                func.replace(func.coalesce(column, ""), "é", "e"),
                "è", "e",
            ),
            "ê", "e",
        )
    )
    return case(
        (normalized.like("%consolid%"), CONSOLIDATED_FAMILY),
        (
            (normalized.like("%restructur%") | normalized.like("%restruct%") | normalized.like("%restruc%")),
            RESTRUCTURED_FAMILY,
        ),
        else_=None,
    )



def _csv_buffer_from_frame(frame: pd.DataFrame, columns: list[str]) -> StringIO:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in frame[columns].itertuples(index=False, name=None):
        writer.writerow(["" if value is None else value for value in row])
    buffer.seek(0)
    return buffer


def _upsert_schedule_postgres_from_csv(
    db: Session,
    csv_path: str | os.PathLike[str],
) -> dict[str, object]:
    connection = db.connection()
    raw_connection = connection.connection
    inserted = 0
    updated = 0
    unchanged = 0
    deleted = 0
    impacted_contracts: list[str] = []
    copy_seconds = 0.0
    index_seconds = 0.0
    upsert_seconds = 0.0
    stage_columns_sql = """
        source_order BIGINT,
        agency_code TEXT,
        agency_name TEXT,
        agent_name TEXT,
        client_name TEXT,
        client_first_name TEXT,
        account_number TEXT,
        t24_reference_number TEXT,
        culoanpart_reference TEXT,
        customer_id TEXT,
        is_active BOOLEAN,
        issue_date DATE,
        installment_no INTEGER,
        due_date DATE,
        total_installment NUMERIC(18, 3),
        principal_paid NUMERIC(18, 3),
        interest_due NUMERIC(18, 3),
        interest_paid NUMERIC(18, 3),
        principal_due NUMERIC(18, 3),
        outstanding_after_payment NUMERIC(18, 3),
        total_penalty_amt NUMERIC(18, 3),
        penalty_interest_amount NUMERIC(18, 3),
        unpaid_interest NUMERIC(18, 3),
        unpaid_penalty_interest NUMERIC(18, 3),
        all_paid BOOLEAN,
        value_date DATE,
        receipt_no TEXT,
        transaction_id TEXT,
        schedule_id TEXT,
        delay_days INTEGER
    """
    target_columns = ", ".join(SCHEDULE_COLUMNS)
    stage_columns = ", ".join(f"stage.{column}" for column in SCHEDULE_COLUMNS)
    update_columns = ",\n                ".join(
        f"{column} = EXCLUDED.{column}"
        for column in SCHEDULE_COLUMNS
        if column not in {"account_number", "installment_no"}
    )
    difference_predicate_stage_target = " OR ".join(
        f"target.{column} IS DISTINCT FROM stage.{column}"
        for column in SCHEDULE_COLUMNS
        if column not in {"account_number", "installment_no"}
    )
    difference_predicate_target_excluded = " OR ".join(
        f"restructured_schedule_rows.{column} IS DISTINCT FROM EXCLUDED.{column}"
        for column in SCHEDULE_COLUMNS
        if column not in {"account_number", "installment_no"}
    )
    with raw_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS restructured_schedule_stage")
        cursor.execute("DROP TABLE IF EXISTS restructured_schedule_stage_dedup")
        cursor.execute("DROP TABLE IF EXISTS restructured_schedule_impacted_contracts")
        cursor.execute(
            f"""
            CREATE TEMP TABLE restructured_schedule_stage (
                {stage_columns_sql}
            ) ON COMMIT DROP
            """
        )
        copy_started = perf_counter()
        with open(csv_path, "r", encoding="utf-8") as handle:
            with cursor.copy(
                """
                COPY restructured_schedule_stage (
                    source_order,
                    agency_code, agency_name, agent_name, client_name, client_first_name,
                    account_number, t24_reference_number, culoanpart_reference, customer_id,
                    is_active, issue_date, installment_no, due_date, total_installment,
                    principal_paid, interest_due, interest_paid, principal_due,
                    outstanding_after_payment, total_penalty_amt, penalty_interest_amount,
                    unpaid_interest, unpaid_penalty_interest, all_paid, value_date,
                    receipt_no, transaction_id, schedule_id, delay_days
                ) FROM STDIN WITH (FORMAT CSV)
                """
            ) as copy:
                for line in handle:
                    copy.write(line)
        copy_seconds = perf_counter() - copy_started

        index_started = perf_counter()
        cursor.execute(
            """
            CREATE TEMP TABLE restructured_schedule_stage_dedup ON COMMIT DROP AS
            SELECT DISTINCT ON (account_number, installment_no)
                agency_code, agency_name, agent_name, client_name, client_first_name,
                account_number, t24_reference_number, culoanpart_reference, customer_id,
                is_active, issue_date, installment_no, due_date, total_installment,
                principal_paid, interest_due, interest_paid, principal_due,
                outstanding_after_payment, total_penalty_amt, penalty_interest_amount,
                unpaid_interest, unpaid_penalty_interest, all_paid, value_date,
                receipt_no, transaction_id, schedule_id, delay_days
            FROM restructured_schedule_stage
            WHERE account_number IS NOT NULL
              AND installment_no IS NOT NULL
            ORDER BY account_number, installment_no, source_order DESC
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_restructured_schedule_stage_dedup_key
            ON restructured_schedule_stage_dedup (account_number, installment_no)
            """
        )
        index_seconds = perf_counter() - index_started

        upsert_started = perf_counter()
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM restructured_schedule_stage_dedup stage
            LEFT JOIN restructured_schedule_rows target
              ON target.account_number = stage.account_number
             AND target.installment_no = stage.installment_no
            WHERE target.id IS NULL
            """
        )
        inserted = int(cursor.fetchone()[0] or 0)
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM restructured_schedule_stage_dedup stage
            JOIN restructured_schedule_rows target
              ON target.account_number = stage.account_number
             AND target.installment_no = stage.installment_no
            WHERE {difference_predicate_stage_target}
            """
        )
        updated = int(cursor.fetchone()[0] or 0)
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM restructured_schedule_stage_dedup stage
            JOIN restructured_schedule_rows target
              ON target.account_number = stage.account_number
             AND target.installment_no = stage.installment_no
            WHERE NOT ({difference_predicate_stage_target})
            """
        )
        unchanged = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            f"""
            CREATE TEMP TABLE restructured_schedule_impacted_contracts ON COMMIT DROP AS
            SELECT DISTINCT contract_no
            FROM (
                SELECT stage.account_number AS contract_no
                FROM restructured_schedule_stage_dedup stage
                LEFT JOIN restructured_schedule_rows target
                  ON target.account_number = stage.account_number
                 AND target.installment_no = stage.installment_no
                WHERE target.id IS NULL OR {difference_predicate_stage_target}

                UNION

                SELECT target.account_number AS contract_no
                FROM restructured_schedule_rows target
                JOIN restructured_contracts contract
                  ON contract.contract_no = target.account_number
                LEFT JOIN restructured_schedule_stage_dedup stage
                  ON stage.account_number = target.account_number
                 AND stage.installment_no = target.installment_no
                WHERE stage.account_number IS NULL
            ) impacted
            WHERE contract_no IS NOT NULL
            """
        )
        cursor.execute("SELECT contract_no FROM restructured_schedule_impacted_contracts ORDER BY contract_no")
        impacted_contracts = [row[0] for row in cursor.fetchall() if row and row[0]]

        cursor.execute(
            f"""
            INSERT INTO restructured_schedule_rows (
                {target_columns}
            )
            SELECT
                {stage_columns}
            FROM restructured_schedule_stage_dedup stage
            ON CONFLICT (account_number, installment_no) DO UPDATE SET
                {update_columns}
            WHERE {difference_predicate_target_excluded}
            """
        )

        cursor.execute(
            """
            DELETE FROM restructured_schedule_rows target
            WHERE NOT EXISTS (
                SELECT 1
                FROM restructured_schedule_stage_dedup stage
                WHERE stage.account_number = target.account_number
                  AND stage.installment_no = target.installment_no
            )
            """
        )
        deleted = int(cursor.rowcount or 0)
        upsert_seconds = perf_counter() - upsert_started
    db.flush()
    return {
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "deleted": deleted,
        "impacted_contracts": impacted_contracts,
        "copy_seconds": copy_seconds,
        "index_seconds": index_seconds,
        "upsert_seconds": upsert_seconds,
    }


def _upsert_schedule_postgres(db: Session, frame: pd.DataFrame) -> tuple[int, int, int]:
    columns = [
        "agency_code",
        "agency_name",
        "agent_name",
        "client_name",
        "client_first_name",
        "account_number",
        "t24_reference_number",
        "culoanpart_reference",
        "customer_id",
        "is_active",
        "issue_date",
        "installment_no",
        "due_date",
        "total_installment",
        "principal_paid",
        "interest_due",
        "interest_paid",
        "principal_due",
        "outstanding_after_payment",
        "total_penalty_amt",
        "penalty_interest_amount",
        "unpaid_interest",
        "unpaid_penalty_interest",
        "all_paid",
        "value_date",
        "receipt_no",
        "transaction_id",
        "schedule_id",
        "delay_days",
    ]
    prepared = frame.copy()
    for column in columns:
        if column not in prepared.columns:
            prepared[column] = None
    for column in ("issue_date", "due_date", "value_date"):
        prepared[column] = prepared[column].apply(
            lambda value: value.isoformat() if isinstance(value, date) else ""
        )
    for column in columns:
        if column in {"is_active", "all_paid"}:
            prepared[column] = prepared[column].apply(lambda value: "true" if bool(value) else "false")
        elif column not in {"issue_date", "due_date", "value_date"}:
            prepared[column] = prepared[column].apply(lambda value: "" if value is None else value)

    connection = db.connection()
    raw_connection = connection.connection
    inserted = 0
    updated = 0
    deleted = 0

    with raw_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS restructured_schedule_stage")
        cursor.execute(
            """
            CREATE TEMP TABLE restructured_schedule_stage (
                agency_code TEXT,
                agency_name TEXT,
                agent_name TEXT,
                client_name TEXT,
                client_first_name TEXT,
                account_number TEXT,
                t24_reference_number TEXT,
                culoanpart_reference TEXT,
                customer_id TEXT,
                is_active BOOLEAN,
                issue_date DATE,
                installment_no INTEGER,
                due_date DATE,
                total_installment NUMERIC(18, 3),
                principal_paid NUMERIC(18, 3),
                interest_due NUMERIC(18, 3),
                interest_paid NUMERIC(18, 3),
                principal_due NUMERIC(18, 3),
                outstanding_after_payment NUMERIC(18, 3),
                total_penalty_amt NUMERIC(18, 3),
                penalty_interest_amount NUMERIC(18, 3),
                unpaid_interest NUMERIC(18, 3),
                unpaid_penalty_interest NUMERIC(18, 3),
                all_paid BOOLEAN,
                value_date DATE,
                receipt_no TEXT,
                transaction_id TEXT,
                schedule_id TEXT,
                delay_days INTEGER
            ) ON COMMIT DROP
            """
        )
        with cursor.copy(
            """
            COPY restructured_schedule_stage (
                agency_code, agency_name, agent_name, client_name, client_first_name,
                account_number, t24_reference_number, culoanpart_reference, customer_id,
                is_active, issue_date, installment_no, due_date, total_installment,
                principal_paid, interest_due, interest_paid, principal_due,
                outstanding_after_payment, total_penalty_amt, penalty_interest_amount,
                unpaid_interest, unpaid_penalty_interest, all_paid, value_date,
                receipt_no, transaction_id, schedule_id, delay_days
            ) FROM STDIN WITH (FORMAT CSV)
            """
        ) as copy:
            buffer = _csv_buffer_from_frame(prepared, columns)
            for line in buffer:
                copy.write(line)

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM restructured_schedule_stage stage
            LEFT JOIN restructured_schedule_rows target
              ON target.account_number = stage.account_number
             AND target.installment_no = stage.installment_no
            WHERE target.id IS NULL
            """
        )
        inserted = int(cursor.fetchone()[0] or 0)
        updated = int(len(prepared.index)) - inserted

        cursor.execute(
            """
            INSERT INTO restructured_schedule_rows (
                agency_code, agency_name, agent_name, client_name, client_first_name,
                account_number, t24_reference_number, culoanpart_reference, customer_id,
                is_active, issue_date, installment_no, due_date, total_installment,
                principal_paid, interest_due, interest_paid, principal_due,
                outstanding_after_payment, total_penalty_amt, penalty_interest_amount,
                unpaid_interest, unpaid_penalty_interest, all_paid, value_date,
                receipt_no, transaction_id, schedule_id, delay_days
            )
            SELECT
                agency_code, agency_name, agent_name, client_name, client_first_name,
                account_number, t24_reference_number, culoanpart_reference, customer_id,
                is_active, issue_date, installment_no, due_date, total_installment,
                principal_paid, interest_due, interest_paid, principal_due,
                outstanding_after_payment, total_penalty_amt, penalty_interest_amount,
                unpaid_interest, unpaid_penalty_interest, all_paid, value_date,
                receipt_no, transaction_id, schedule_id, delay_days
            FROM restructured_schedule_stage
            ON CONFLICT (account_number, installment_no) DO UPDATE SET
                agency_code = EXCLUDED.agency_code,
                agency_name = EXCLUDED.agency_name,
                agent_name = EXCLUDED.agent_name,
                client_name = EXCLUDED.client_name,
                client_first_name = EXCLUDED.client_first_name,
                t24_reference_number = EXCLUDED.t24_reference_number,
                culoanpart_reference = EXCLUDED.culoanpart_reference,
                customer_id = EXCLUDED.customer_id,
                is_active = EXCLUDED.is_active,
                issue_date = EXCLUDED.issue_date,
                due_date = EXCLUDED.due_date,
                total_installment = EXCLUDED.total_installment,
                principal_paid = EXCLUDED.principal_paid,
                interest_due = EXCLUDED.interest_due,
                interest_paid = EXCLUDED.interest_paid,
                principal_due = EXCLUDED.principal_due,
                outstanding_after_payment = EXCLUDED.outstanding_after_payment,
                total_penalty_amt = EXCLUDED.total_penalty_amt,
                penalty_interest_amount = EXCLUDED.penalty_interest_amount,
                unpaid_interest = EXCLUDED.unpaid_interest,
                unpaid_penalty_interest = EXCLUDED.unpaid_penalty_interest,
                all_paid = EXCLUDED.all_paid,
                value_date = EXCLUDED.value_date,
                receipt_no = EXCLUDED.receipt_no,
                transaction_id = EXCLUDED.transaction_id,
                schedule_id = EXCLUDED.schedule_id,
                delay_days = EXCLUDED.delay_days
            """
        )

        cursor.execute(
            """
            DELETE FROM restructured_schedule_rows target
            WHERE NOT EXISTS (
                SELECT 1
                FROM restructured_schedule_stage stage
                WHERE stage.account_number = target.account_number
                  AND stage.installment_no = target.installment_no
            )
            """
        )
        deleted = int(cursor.rowcount or 0)

    db.flush()
    return inserted, updated, deleted


def _upsert_schedule_fallback(db: Session, frame: pd.DataFrame) -> tuple[int, int, int]:
    payloads = _replace_nan_with_none(frame.to_dict(orient="records"))
    if not payloads:
        return 0, 0, 0

    existing_keys = set(
        db.execute(
            select(
                RestructuredScheduleRow.account_number,
                RestructuredScheduleRow.installment_no,
            )
        ).all()
    )
    incoming_keys = {(row["account_number"], row["installment_no"]) for row in payloads}
    inserted = sum(1 for key in incoming_keys if key not in existing_keys)
    updated = len(incoming_keys) - inserted
    deleted = len(existing_keys - incoming_keys)

    db.execute(delete(RestructuredScheduleRow))
    db.bulk_insert_mappings(RestructuredScheduleRow, payloads)
    db.flush()
    return inserted, updated, deleted


def _upsert_schedule_rows(db: Session, frame: pd.DataFrame) -> tuple[int, int, int]:
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        return _upsert_schedule_postgres(db, frame)
    return _upsert_schedule_fallback(db, frame)


def build_restructured_analysis_frames(
    contracts_df: pd.DataFrame,
    schedule_df: pd.DataFrame,
    reference_date: date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if reference_date is None:
        reference_date = date.today()

    contracts = contracts_df.copy()
    if contracts.empty:
        return pd.DataFrame(), pd.DataFrame()

    contracts["contract_no"] = contracts["contract_no"].apply(_optional_text)
    contracts["delay_date"] = pd.to_datetime(contracts["delay_date"], errors="coerce").dt.date
    contracts["loan_duration"] = contracts["loan_duration"].apply(_optional_int)
    contracts["total_due"] = contracts["total_due"].apply(_optional_decimal)

    schedule = schedule_df.copy()
    if not schedule.empty:
        schedule["account_number"] = schedule["account_number"].apply(_optional_text)
        schedule["installment_no"] = schedule["installment_no"].apply(_optional_int)
        schedule["due_date"] = pd.to_datetime(schedule["due_date"], errors="coerce").dt.date
        for column in ("principal_due", "principal_paid"):
            schedule[column] = schedule[column].apply(lambda value: _coerce_float(value, default=0.0))
        schedule = _deduplicate_schedule_rows(schedule)
        schedule = schedule.sort_values(["account_number", "installment_no", "due_date"]).reset_index(drop=True)
        schedule_groups = dict(tuple(schedule.groupby("account_number")))
    else:
        schedule_groups = {}

    analysis_rows: list[dict] = []
    gap_rows: list[dict] = []

    for _, contract in contracts.iterrows():
        contract_no = contract["contract_no"]
        delay_date = contract.get("delay_date")
        loan_duration = contract.get("loan_duration")
        total_due = contract.get("total_due")

        entry = {
            "contract_no": contract_no,
            "agency_name": None,
            "agent_name": None,
            "delay_date": delay_date,
            "total_due": total_due,
            "loan_duration": loan_duration,
            "schedule_status": None,
            "consecutive_paid_count": 0,
            "max_series_installments": "",
            "max_series_dates": "",
            "paid_installments_after_delay": 0,
            "anomaly_detected": False,
            "anomaly_detail": "",
            "paid_last_four_status": "N/A",
            "last_paid_installment_no": None,
            "last_paid_due_date": None,
            "closure_status": CLOSURE_STATUS_NA,
        }

        sub_full = schedule_groups.get(contract_no)
        if sub_full is None or len(sub_full.index) == 0:
            entry["schedule_status"] = "Contrat introuvable dans fichier 2"
            analysis_rows.append(entry)
            continue

        agency_name = _optional_text(sub_full["agency_name"].iloc[0]) if "agency_name" in sub_full else None
        agent_name = _optional_text(sub_full["agent_name"].iloc[0]) if "agent_name" in sub_full else None
        entry["agency_name"] = agency_name
        entry["agent_name"] = agent_name

        paid_full_mask = sub_full.apply(
            lambda row: _is_paid_installment(row.get("principal_due"), row.get("principal_paid")),
            axis=1,
        )

        closure_reason = "Aucune échéance valide payée en capital"
        last_paid_principal_due = None
        last_paid_principal_paid = None
        if paid_full_mask.any():
            paid_full = sub_full.loc[paid_full_mask].sort_values("installment_no")
            last_paid_row = paid_full.iloc[-1]
            entry["last_paid_installment_no"] = _optional_int(last_paid_row["installment_no"])
            entry["last_paid_due_date"] = _optional_date(last_paid_row["due_date"])
            last_paid_principal_due = (
                float(last_paid_row["principal_due"])
                if last_paid_row["principal_due"] is not None
                else None
            )
            last_paid_principal_paid = (
                float(last_paid_row["principal_paid"])
                if last_paid_row["principal_paid"] is not None
                else None
            )
            if loan_duration is not None:
                if int(entry["last_paid_installment_no"] or 0) == int(loan_duration):
                    entry["closure_status"] = CLOSURE_STATUS_ASSUMED_CLOSED
                    closure_reason = "Derniù¨re échéance payée en capital égale ù  LOAN_DURATION"
                else:
                    entry["closure_status"] = CLOSURE_STATUS_IN_PROGRESS
                    closure_reason = "Derniù¨re échéance payée en capital différente de LOAN_DURATION"
            else:
                entry["closure_status"] = CLOSURE_STATUS_NA
                closure_reason = "LOAN_DURATION manquant"
        else:
            entry["last_paid_installment_no"] = None
            entry["closure_status"] = CLOSURE_STATUS_NA
            closure_reason = "Aucune échéance ne respecte principal_paid == principal_due > 0"

        if _normalize_contract_key(contract_no) == _normalize_contract_key(TARGET_CLOSURE_DEBUG_CONTRACT):
            valid_installments = [
                _optional_int(value)
                for value in sub_full["installment_no"].tolist()
                if _optional_int(value) is not None
            ]
            logger.info(
                "Restructured closure debug | contract=%s | normalized=%s | loan_duration=%s | total_schedule_rows=%s | min_installment=%s | max_installment=%s | last_paid_installment=%s | last_paid_due_date=%s | last_paid_principal_due=%s | last_paid_principal_paid=%s | closure_status=%s | reason=%s",
                contract_no,
                _normalize_contract_key(contract_no),
                loan_duration,
                len(sub_full.index),
                min(valid_installments) if valid_installments else None,
                max(valid_installments) if valid_installments else None,
                entry["last_paid_installment_no"],
                entry["last_paid_due_date"],
                last_paid_principal_due,
                last_paid_principal_paid,
                entry["closure_status"],
                closure_reason,
            )

        if len(sub_full.index) >= 2:
            gap_candidates: list[tuple[date, date, int, int, int]] = []
            previous_due = None
            previous_no = None
            for _, item in sub_full.iterrows():
                current_due = _optional_date(item["due_date"])
                current_no = _optional_int(item["installment_no"])
                if previous_due is not None and current_due is not None and previous_no is not None and current_no is not None:
                    days_gap = (current_due - previous_due).days
                    if days_gap > ANALYSIS_GAP_THRESHOLD_DAYS:
                        gap_candidates.append((previous_due, current_due, previous_no, current_no, days_gap))
                previous_due = current_due
                previous_no = current_no
            if gap_candidates:
                last_gap = gap_candidates[-1]
                gap_rows.append(
                    {
                        "contract_no": contract_no,
                        "agency_name": agency_name,
                        "agent_name": agent_name,
                        "due_date_1": last_gap[0],
                        "due_date_2": last_gap[1],
                        "installment_no_1": last_gap[2],
                        "installment_no_2": last_gap[3],
                        "gap_days": last_gap[4],
                        "total_gap_count": len(gap_candidates),
                    }
                )

        if pd.isna(delay_date) or delay_date is None:
            entry["schedule_status"] = "Date de décalage manquante"
            analysis_rows.append(entry)
            continue

        sub = sub_full[sub_full["due_date"].apply(lambda value: value is not None and value > delay_date)].copy()
        sub = sub.sort_values("installment_no").reset_index(drop=True)
        paid_last_four = calculate_paid_last_four_calendar_months(
            sub_full,
            delay_date,
            reference_date,
            tolerance=PAID_TOLERANCE,
        )
        target_months = paid_last_four["target_months"]
        month_diagnostics = paid_last_four["diagnostic"]["rows_in_target_months"]
        entry["paid_last_four_status"] = str(paid_last_four["status"])

        if _normalize_contract_key(contract_no) == _normalize_contract_key(TARGET_PAID_LAST_FOUR_DEBUG_CONTRACT):
            diagnostic = paid_last_four["diagnostic"]
            logger.info(
                "Restructured paid-last-four debug | contract=%s | normalized=%s | reference_date=%s | delay_date=%s | target_months=%s | rows_after_delay=%s | rows_in_target_months=%s | found_months=%s | all_paid=%s | status=%s | reason=%s",
                contract_no,
                _normalize_contract_key(contract_no),
                reference_date.isoformat(),
                delay_date.isoformat() if delay_date else None,
                [_format_month_key(month_key) for month_key in target_months],
                diagnostic["rows_after_delay"],
                diagnostic["rows_in_target_months"],
                diagnostic["found_months_formatted"],
                diagnostic["all_paid"],
                entry["paid_last_four_status"],
                diagnostic["reason"],
            )

        if len(sub.index) == 0:
            entry["schedule_status"] = "Aucune échéance après décalage"
            analysis_rows.append(entry)
            continue

        paid = [
            _is_paid_installment(principal_due, principal_paid)
            for principal_due, principal_paid in zip(sub["principal_due"].tolist(), sub["principal_paid"].tolist())
        ]
        installment_numbers = [_optional_int(value) or 0 for value in sub["installment_no"].tolist()]
        due_dates = [_optional_date(value) for value in sub["due_date"].tolist()]
        entry["paid_installments_after_delay"] = int(sum(1 for item in paid if item))

        if entry["paid_installments_after_delay"] == 0:
            entry["schedule_status"] = "OK - aucune échéance payée après décalage"
            analysis_rows.append(entry)
            continue

        entry["schedule_status"] = "OK"
        runs: list[list[int]] = []
        current_run: list[int] = []
        for index, is_paid in enumerate(paid):
            if is_paid:
                if current_run and installment_numbers[index] == installment_numbers[current_run[-1]] + 1:
                    current_run.append(index)
                else:
                    if current_run:
                        runs.append(current_run)
                    current_run = [index]
            elif current_run:
                runs.append(current_run)
                current_run = []
        if current_run:
            runs.append(current_run)

        max_run = max(runs, key=len)
        entry["consecutive_paid_count"] = len(max_run)
        entry["max_series_installments"] = ", ".join(str(installment_numbers[idx]) for idx in max_run)
        entry["max_series_dates"] = ", ".join(
            due_dates[idx].strftime("%d/%m/%Y") for idx in max_run if due_dates[idx] is not None
        )

        if len(runs) > 1:
            entry["anomaly_detected"] = True
            entry["anomaly_detail"] = "échéances payées non contiguù«s (avec saut) : " + " puis ".join(
                "[" + ",".join(str(installment_numbers[idx]) for idx in run) + "]"
                for run in runs
            )

        analysis_rows.append(entry)

    analysis_df = pd.DataFrame(analysis_rows)
    gaps_df = pd.DataFrame(gap_rows)
    return analysis_df, gaps_df


def _record_log(
    db: Session,
    *,
    import_type: str,
    file_name: str | None,
    started_at: datetime,
    finished_at: datetime,
    row_count: int,
    status: str,
    message: str,
    inserted_count: int | None = None,
    updated_count: int | None = None,
    deleted_count: int | None = None,
    recalculated_contracts: int | None = None,
    progress_percent: int | None = None,
    phase: str | None = None,
    source_rows_seen: int | None = None,
    ignored_rows_count: int | None = None,
    rows_per_second: float | Decimal | None = None,
    eta_seconds: float | Decimal | None = None,
    memory_peak_mb: float | Decimal | None = None,
    last_activity_at: datetime | None = None,
    phase_details: str | None = None,
) -> RestructuredImportLog:
    duration = Decimal(str(round((finished_at - started_at).total_seconds(), 2)))
    log = RestructuredImportLog(
        import_type=import_type,
        file_name=file_name,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        row_count=row_count,
        inserted_count=inserted_count,
        updated_count=updated_count,
        deleted_count=deleted_count,
        recalculated_contracts=recalculated_contracts,
        progress_percent=progress_percent,
        phase=phase,
        source_rows_seen=source_rows_seen,
        ignored_rows_count=ignored_rows_count,
        rows_per_second=Decimal(str(round(float(rows_per_second), 2))) if rows_per_second is not None else None,
        eta_seconds=Decimal(str(round(float(eta_seconds), 2))) if eta_seconds is not None else None,
        memory_peak_mb=Decimal(str(round(float(memory_peak_mb), 2))) if memory_peak_mb is not None else None,
        last_activity_at=last_activity_at or finished_at,
        phase_details=phase_details,
        status=status,
        message=message,
    )
    db.add(log)
    db.flush()
    return log


def _update_import_log(
    db: Session,
    log_id: int,
    *,
    status: str | None = None,
    phase: str | None = None,
    progress_percent: int | None = None,
    message: str | None = None,
    row_count: int | None = None,
    inserted_count: int | None = None,
    updated_count: int | None = None,
    deleted_count: int | None = None,
    recalculated_contracts: int | None = None,
    source_rows_seen: int | None = None,
    ignored_rows_count: int | None = None,
    rows_per_second: float | Decimal | None = None,
    eta_seconds: float | Decimal | None = None,
    memory_peak_mb: float | Decimal | None = None,
    last_activity_at: datetime | None = None,
    phase_details: str | None = None,
    finished_at: datetime | None = None,
) -> RestructuredImportLog | None:
    log = db.get(RestructuredImportLog, log_id)
    if log is None:
        return None
    if status is not None:
        log.status = status
    if phase is not None:
        log.phase = phase
    if progress_percent is not None:
        log.progress_percent = int(max(0, min(100, progress_percent)))
    if message is not None:
        log.message = message
    if row_count is not None:
        log.row_count = row_count
    if inserted_count is not None:
        log.inserted_count = inserted_count
    if updated_count is not None:
        log.updated_count = updated_count
    if deleted_count is not None:
        log.deleted_count = deleted_count
    if recalculated_contracts is not None:
        log.recalculated_contracts = recalculated_contracts
    if source_rows_seen is not None:
        log.source_rows_seen = source_rows_seen
    if ignored_rows_count is not None:
        log.ignored_rows_count = ignored_rows_count
    if rows_per_second is not None:
        log.rows_per_second = Decimal(str(round(float(rows_per_second), 2)))
    if eta_seconds is not None:
        log.eta_seconds = Decimal(str(round(float(eta_seconds), 2)))
    if memory_peak_mb is not None:
        log.memory_peak_mb = Decimal(str(round(float(memory_peak_mb), 2)))
    if last_activity_at is not None:
        log.last_activity_at = last_activity_at
    if phase_details is not None:
        log.phase_details = phase_details
    if finished_at is not None:
        log.finished_at = finished_at
        started_at = log.started_at or finished_at
        log.duration_seconds = Decimal(
            str(round((finished_at - started_at).total_seconds(), 2))
        )
        log.last_activity_at = finished_at
    db.flush()
    return log


def _create_pending_import_log(
    db: Session,
    *,
    import_type: str,
    file_name: str | None,
    message: str,
) -> RestructuredImportLog:
    log = RestructuredImportLog(
        import_type=import_type,
        file_name=file_name,
        started_at=datetime.utcnow(),
        last_activity_at=datetime.utcnow(),
        status="queued",
        progress_percent=IMPORT_PHASE_WEIGHTS["queued"],
        phase="queued",
        message=message,
    )
    db.add(log)
    db.flush()
    return log


def recalculate_restructured_results(db: Session) -> int:
    contracts_df = pd.read_sql(
        select(
            RestructuredContract.contract_no,
            RestructuredContract.delay_date,
            RestructuredContract.total_due,
            RestructuredContract.loan_duration,
        ),
        db.connection(),
    )
    schedule_df = pd.read_sql(
        select(
            RestructuredScheduleRow.agency_name,
            RestructuredScheduleRow.agent_name,
            RestructuredScheduleRow.account_number,
            RestructuredScheduleRow.installment_no,
            RestructuredScheduleRow.due_date,
            RestructuredScheduleRow.principal_due,
            RestructuredScheduleRow.principal_paid,
        )
        .join(
            RestructuredContract,
            RestructuredContract.contract_no == RestructuredScheduleRow.account_number,
        ),
        db.connection(),
    )

    analysis_df, gaps_df = build_restructured_analysis_frames(contracts_df, schedule_df)
    calculated_at = datetime.utcnow()

    db.execute(delete(RestructuredGapResult))
    db.execute(delete(RestructuredAnalysisResult))

    analysis_payloads = _replace_nan_with_none(analysis_df.to_dict(orient="records")) if not analysis_df.empty else []
    for payload in analysis_payloads:
        payload["last_calculated_at"] = calculated_at
    gap_payloads = _replace_nan_with_none(gaps_df.to_dict(orient="records")) if not gaps_df.empty else []
    for payload in gap_payloads:
        payload["last_calculated_at"] = calculated_at

    if analysis_payloads:
        db.bulk_insert_mappings(RestructuredAnalysisResult, analysis_payloads)
    if gap_payloads:
        db.bulk_insert_mappings(RestructuredGapResult, gap_payloads)
    db.flush()

    _record_log(
        db,
        import_type="analysis",
        file_name=None,
        started_at=calculated_at,
        finished_at=calculated_at,
        row_count=len(analysis_payloads),
        status="success",
        message=f"Recalcul restructuré exécuté sur {len(analysis_payloads)} contrat(s).",
    )
    return len(analysis_payloads)


def _normalize_contract_number_list(contract_numbers: Iterable[str] | None) -> list[str]:
    if not contract_numbers:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_value in contract_numbers:
        normalized = _normalize_contract_key(raw_value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _load_restructured_analysis_sources(
    db: Session,
    *,
    contract_numbers: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    scoped_contracts = _normalize_contract_number_list(contract_numbers)
    contract_query = select(
        RestructuredContract.contract_no,
        RestructuredContract.delay_date,
        RestructuredContract.total_due,
        RestructuredContract.loan_duration,
    )
    if scoped_contracts:
        contract_query = contract_query.where(RestructuredContract.contract_no.in_(scoped_contracts))

    schedule_query = (
        select(
            RestructuredScheduleRow.agency_name,
            RestructuredScheduleRow.agent_name,
            RestructuredScheduleRow.account_number,
            RestructuredScheduleRow.installment_no,
            RestructuredScheduleRow.due_date,
            RestructuredScheduleRow.principal_due,
            RestructuredScheduleRow.principal_paid,
        )
        .join(
            RestructuredContract,
            RestructuredContract.contract_no == RestructuredScheduleRow.account_number,
        )
    )
    if scoped_contracts:
        schedule_query = schedule_query.where(RestructuredScheduleRow.account_number.in_(scoped_contracts))

    contracts_df = pd.read_sql(contract_query, db.connection())
    schedule_df = pd.read_sql(schedule_query, db.connection())
    return contracts_df, schedule_df


def _persist_restructured_analysis_results(
    db: Session,
    *,
    analysis_df: pd.DataFrame,
    gaps_df: pd.DataFrame,
    contract_numbers: Iterable[str] | None,
    calculated_at: datetime,
) -> int:
    scoped_contracts = _normalize_contract_number_list(contract_numbers)
    if scoped_contracts:
        db.execute(delete(RestructuredGapResult).where(RestructuredGapResult.contract_no.in_(scoped_contracts)))
        db.execute(
            delete(RestructuredAnalysisResult).where(
                RestructuredAnalysisResult.contract_no.in_(scoped_contracts)
            )
        )
    else:
        db.execute(delete(RestructuredGapResult))
        db.execute(delete(RestructuredAnalysisResult))

    analysis_payloads = (
        _replace_nan_with_none(analysis_df.to_dict(orient="records")) if not analysis_df.empty else []
    )
    for payload in analysis_payloads:
        payload["last_calculated_at"] = calculated_at
    gap_payloads = _replace_nan_with_none(gaps_df.to_dict(orient="records")) if not gaps_df.empty else []
    for payload in gap_payloads:
        payload["last_calculated_at"] = calculated_at

    if analysis_payloads:
        db.bulk_insert_mappings(RestructuredAnalysisResult, analysis_payloads)
    if gap_payloads:
        db.bulk_insert_mappings(RestructuredGapResult, gap_payloads)
    db.flush()
    return len(analysis_payloads)


def _recalculate_restructured_results_internal(
    db: Session,
    *,
    contract_numbers: Iterable[str] | None = None,
    log_message_suffix: str = "",
) -> int:
    started_at = datetime.utcnow()
    bind = db.get_bind()
    current_schema = None
    if getattr(bind.dialect, "name", None) == "postgresql":
        current_schema = db.execute(select(func.current_schema())).scalar_one_or_none()
    logger.info(
        "Restructured recalculation started | backend=%s | host=%s | port=%s | database=%s | schema=%s | scoped_contracts=%s",
        getattr(bind.dialect, "name", "unknown"),
        getattr(bind.url, "host", None),
        getattr(bind.url, "port", None),
        getattr(bind.url, "database", None),
        current_schema,
        len(_normalize_contract_number_list(contract_numbers)) if contract_numbers is not None else "ALL",
    )
    contracts_df, schedule_df = _load_restructured_analysis_sources(
        db,
        contract_numbers=contract_numbers,
    )
    analysis_df, gaps_df = build_restructured_analysis_frames(contracts_df, schedule_df)
    calculated_at = datetime.utcnow()
    contract_count = _persist_restructured_analysis_results(
        db,
        analysis_df=analysis_df,
        gaps_df=gaps_df,
        contract_numbers=contract_numbers,
        calculated_at=calculated_at,
    )

    _record_log(
        db,
        import_type="analysis",
        file_name=None,
        started_at=started_at,
        finished_at=calculated_at,
        row_count=contract_count,
        status="success",
        message=f"Recalcul restructuré exécuté sur {contract_count} contrat(s){log_message_suffix}.",
    )
    closure_counts = (
        analysis_df["closure_status"].fillna(CLOSURE_STATUS_NA).value_counts().to_dict()
        if not analysis_df.empty and "closure_status" in analysis_df.columns
        else {}
    )
    logger.info(
        "Restructured recalculation completed | contracts_read=%s | schedule_rows=%s | persisted=%s | supposed_closed=%s | in_progress=%s | na=%s",
        len(contracts_df.index),
        len(schedule_df.index),
        contract_count,
        int(closure_counts.get(CLOSURE_STATUS_ASSUMED_CLOSED, 0)),
        int(closure_counts.get(CLOSURE_STATUS_IN_PROGRESS, 0)),
        int(closure_counts.get(CLOSURE_STATUS_NA, 0)),
    )
    return contract_count


def recalculate_restructured_results(db: Session) -> int:
    return _recalculate_restructured_results_internal(db)


def recalculate_restructured_results_for_contracts(
    db: Session,
    contract_numbers: Iterable[str] | None,
) -> int:
    scoped_contracts = _normalize_contract_number_list(contract_numbers)
    if not scoped_contracts:
        return 0
    return _recalculate_restructured_results_internal(
        db,
        contract_numbers=scoped_contracts,
        log_message_suffix=" (recalcul incrémental)",
    )


def import_restructured_contracts(db: Session, content: bytes, file_name: str) -> RestructuredImportResult:
    started_at = datetime.utcnow()
    try:
        frame = _normalize_contract_frame(content)
        sync_plan = _build_restructured_sync_plan(db, frame=frame, file_name=file_name)
        inserted, updated = _upsert_contracts(db, frame)

        removed_pending_from_officialization = remove_pending_restructured_contracts_matching_official_list(
            db,
            sync_plan["imported_keys"],
        )
        if sync_plan["active_mcr_batch"] is not None:
            _sync_pending_restructured_contracts_from_mcr_batch(
                db,
                sync_plan["active_mcr_batch"],
                emit_log=False,
            )
        removed_pending_obsolete = _delete_pending_restructured_contracts_by_ids(
            db,
            sync_plan["pending_delete_ids"],
        )
        deletion_stats = _delete_restructured_contract_relations(
            db,
            sync_plan["official_delete_contract_nos"],
        )
        deleted_contracts = int(deletion_stats["contracts"])
        pending_cleanup_count = int(removed_pending_from_officialization + removed_pending_obsolete)
        recalculated = recalculate_restructured_results(db)
        finished_at = datetime.utcnow()
        deleted_contract_labels = [
            item.contract_no
            for item in sync_plan["deletions"]
            if item.scope == "official"
        ]
        log = _record_log(
            db,
            import_type="contracts",
            file_name=file_name,
            started_at=started_at,
            finished_at=finished_at,
            row_count=len(frame.index),
            status="success",
            message=(
                "Import des contrats restructures/consolides termine. "
                f"{deleted_contracts} contrat(s) obsolete(s) supprime(s) et "
                f"{pending_cleanup_count} contrat(s) en attente nettoye(s)."
            ),
            inserted_count=inserted,
            updated_count=updated,
            deleted_count=deleted_contracts,
            recalculated_contracts=recalculated,
            phase="completed",
            progress_percent=100,
            phase_details=(
                f"Base existante: {int(sync_plan['existing_contracts_count'])} | "
                f"Liste importee: {int(sync_plan['imported_list_count'])} | "
                f"MCR actif detecte: {int(sync_plan['detected_in_mcr_count'])} | "
                f"Conserves: {int(sync_plan['kept_count'])} | "
                f"Ajoutes: {inserted} | Mis a jour: {updated} | "
                f"Supprimes: {deleted_contracts} | "
                f"Nettoyage pending: {pending_cleanup_count}"
                + (
                    f" | Contrats supprimes: {', '.join(deleted_contract_labels)}"
                    if deleted_contract_labels
                    else ""
                )
            ),
        )
        db.commit()
        return RestructuredImportResult(
            rows_seen=len(frame.index),
            inserted=inserted,
            updated=updated,
            deleted=deleted_contracts,
            kept_count=int(sync_plan["kept_count"]),
            pending_cleanup_count=pending_cleanup_count,
            recalculated_contracts=recalculated,
            started_at=started_at,
            finished_at=finished_at,
            import_log_id=log.id,
            message=(
                "Import des contrats restructures/consolides termine. "
                f"{deleted_contracts} contrat(s) obsolete(s) supprime(s) et "
                f"{pending_cleanup_count} contrat(s) en attente nettoye(s)."
            ),
        )
    except Exception as exc:
        db.rollback()
        finished_at = datetime.utcnow()
        log = _record_log(
            db,
            import_type="contracts",
            file_name=file_name,
            started_at=started_at,
            finished_at=finished_at,
            row_count=0,
            status="failed",
            message=str(exc),
        )
        db.commit()
        raise ValueError(f"Import contrats restructurés impossible: {exc}") from exc


def list_pending_restructured_contracts(
    db: Session,
    *,
    q: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[PendingRestructuredContractRead]:
    query = select(PendingRestructuredContract)
    if q:
        term = f"%{q.strip()}%"
        query = query.where(
            PendingRestructuredContract.contract_no.ilike(term)
            | func.coalesce(PendingRestructuredContract.category_desc, "").ilike(term)
            | func.coalesce(PendingRestructuredContract.client_name, "").ilike(term)
            | func.coalesce(PendingRestructuredContract.client_first_name, "").ilike(term)
            | func.coalesce(PendingRestructuredContract.agency_name, "").ilike(term)
            | func.coalesce(PendingRestructuredContract.agent_name, "").ilike(term)
        )
    if status in {PENDING_STATUS_READY, PENDING_STATUS_TO_COMPLETE}:
        query = query.where(PendingRestructuredContract.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(
            case((PendingRestructuredContract.status == PENDING_STATUS_READY, 0), else_=1),
            PendingRestructuredContract.detected_at.desc().nullslast(),
            PendingRestructuredContract.contract_no.asc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(
        items=[_pending_contract_to_read(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


def _get_pending_restructured_contract(db: Session, pending_id: int) -> PendingRestructuredContract:
    row = db.get(PendingRestructuredContract, pending_id)
    if row is None:
        raise ValueError("Contrat a completer introuvable")
    return row


def update_pending_restructured_contract(
    db: Session,
    pending_id: int,
    payload: PendingRestructuredContractUpdate,
) -> PendingRestructuredContractRead:
    row = _get_pending_restructured_contract(db, pending_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "total_due" in update_data and update_data["total_due"] is not None and update_data["total_due"] < 0:
        raise ValueError("Total Due doit etre superieur ou egal a 0")
    if "loan_duration" in update_data and update_data["loan_duration"] is not None and int(update_data["loan_duration"]) <= 0:
        raise ValueError("LOAN_DURATION doit etre un entier strictement positif")
    for field_name, field_value in update_data.items():
        setattr(row, field_name, field_value)
    missing_fields = _pending_missing_fields(
        shift_date=row.shift_date,
        total_due=row.total_due,
        loan_duration=row.loan_duration,
    )
    row.missing_fields = missing_fields
    row.status = _pending_status_from_missing_fields(missing_fields)
    db.flush()
    return _pending_contract_to_read(row)


def _validate_pending_contract_fields(row: PendingRestructuredContract) -> None:
    if row.shift_date is None:
        raise ValueError("Date de decalage obligatoire")
    if row.total_due is None:
        raise ValueError("Total Due obligatoire")
    if row.total_due < 0:
        raise ValueError("Total Due doit etre superieur ou egal a 0")
    if row.loan_duration is None:
        raise ValueError("LOAN_DURATION obligatoire")
    if int(row.loan_duration) <= 0:
        raise ValueError("LOAN_DURATION doit etre un entier strictement positif")


def _persist_validated_pending_contract(
    db: Session,
    row: PendingRestructuredContract,
    *,
    actor: User,
) -> str:
    _validate_pending_contract_fields(row)
    normalized_contract = row.normalized_contract_no or _normalize_contract_key(row.contract_no)
    if not normalized_contract:
        raise ValueError("Numero de contrat invalide")
    existing = db.scalar(
        select(RestructuredContract).where(
            RestructuredContract.normalized_contract_no == normalized_contract
        )
    )
    now = datetime.utcnow()
    if existing is None:
        db.add(
            RestructuredContract(
                source_contract_no=row.contract_no,
                contract_no=normalized_contract,
                normalized_contract_no=normalized_contract,
                credit_family=row.credit_family,
                delay_date=row.shift_date,
                category_desc=row.category_desc,
                total_due=row.total_due,
                loan_duration=row.loan_duration,
                source=MANUAL_COMPLETION_SOURCE,
                completed_by_user_id=actor.id,
                completed_at=now,
            )
        )
    else:
        existing.source_contract_no = row.contract_no
        existing.contract_no = normalized_contract
        existing.normalized_contract_no = normalized_contract
        existing.credit_family = row.credit_family
        existing.delay_date = row.shift_date
        existing.category_desc = row.category_desc
        existing.total_due = row.total_due
        existing.loan_duration = row.loan_duration
        existing.source = MANUAL_COMPLETION_SOURCE
        existing.completed_by_user_id = actor.id
        existing.completed_at = now
    db.delete(row)
    db.flush()
    return normalized_contract


def validate_pending_restructured_contract(
    db: Session,
    pending_id: int,
    *,
    actor: User,
) -> PendingRestructuredContractSaveResult:
    row = _get_pending_restructured_contract(db, pending_id)
    normalized_contract = _persist_validated_pending_contract(db, row, actor=actor)
    recalculated = recalculate_restructured_results_for_contracts(db, [normalized_contract])
    db.flush()
    return PendingRestructuredContractSaveResult(
        message=(
            f"Contrat {normalized_contract} enregistre dans la liste officielle. "
            f"{recalculated} contrat(s) recalcule(s)."
        ),
        saved_count=1,
    )


def validate_all_ready_pending_contracts(
    db: Session,
    *,
    actor: User,
) -> PendingRestructuredContractSaveResult:
    rows = db.scalars(
        select(PendingRestructuredContract).where(
            PendingRestructuredContract.status == PENDING_STATUS_READY
        )
    ).all()
    if not rows:
        return PendingRestructuredContractSaveResult(
            message="Aucun contrat pret a enregistrer.",
            saved_count=0,
        )
    saved_contracts: list[str] = []
    for row in rows:
        saved_contracts.append(_persist_validated_pending_contract(db, row, actor=actor))
    recalculated = recalculate_restructured_results_for_contracts(db, saved_contracts)
    db.flush()
    return PendingRestructuredContractSaveResult(
        message=(
            f"{len(saved_contracts)} contrat(s) enregistre(s). "
            f"{recalculated} contrat(s) recalcule(s)."
        ),
        saved_count=len(saved_contracts),
    )


def import_restructured_schedule(db: Session, content: bytes, file_name: str) -> RestructuredImportResult:
    started_at = datetime.utcnow()
    timer_start = perf_counter()
    try:
        frame = _normalize_schedule_frame(content)
        inserted, updated, deleted = _upsert_schedule_rows(db, frame)
        recalculated = recalculate_restructured_results(db)
        finished_at = datetime.utcnow()
        elapsed = perf_counter() - timer_start
        log = _record_log(
            db,
            import_type="schedule",
            file_name=file_name,
            started_at=started_at,
            finished_at=finished_at,
            row_count=len(frame.index),
            status="success",
            message=(
                f"Import schedule terminé en {elapsed:.2f}s "
                f"(insérés={inserted}, mis ù  jour={updated}, supprimés={deleted})."
            ),
        )
        db.commit()
        return RestructuredImportResult(
            rows_seen=len(frame.index),
            inserted=inserted,
            updated=updated,
            deleted=deleted,
            recalculated_contracts=recalculated,
            started_at=started_at,
            finished_at=finished_at,
            import_log_id=log.id,
            message="Import schedule terminé avec recalcul automatique.",
        )
    except Exception as exc:
        db.rollback()
        finished_at = datetime.utcnow()
        log = _record_log(
            db,
            import_type="schedule",
            file_name=file_name,
            started_at=started_at,
            finished_at=finished_at,
            row_count=0,
            status="failed",
            message=str(exc),
        )
        db.commit()
        raise ValueError(f"Import schedule impossible: {exc}") from exc


def list_restructured_import_logs(
    db: Session,
    *,
    import_type: str | None = None,
    limit: int = 20,
) -> list[RestructuredImportLog]:
    query = select(RestructuredImportLog)
    if import_type:
        query = query.where(RestructuredImportLog.import_type == import_type)
    return db.scalars(
        query.order_by(
            RestructuredImportLog.started_at.desc(),
            RestructuredImportLog.id.desc(),
        ).limit(limit)
    ).all()


def get_restructured_import_log(db: Session, log_id: int) -> RestructuredImportLog | None:
    return db.get(RestructuredImportLog, log_id)


def _run_restructured_schedule_import_job(
    *,
    log_id: int,
    upload_path: str,
    file_name: str,
) -> None:
    csv_path: str | None = None
    total_started = perf_counter()
    tracemalloc.start()
    heartbeat_lock = threading.Lock()
    stall_event = threading.Event()
    heartbeat_state: dict[str, object] = {
        "phase": "queued",
        "processed_rows": 0,
        "accepted_rows": 0,
        "ignored_rows": 0,
        "rows_per_second": 0.0,
        "eta_seconds": None,
        "memory_peak_mb": 0.0,
        "last_touch_monotonic": perf_counter(),
        "last_activity_at": datetime.utcnow(),
        "done": False,
    }

    def touch_heartbeat(**patch) -> None:
        with heartbeat_lock:
            heartbeat_state.update(patch)
            heartbeat_state["last_touch_monotonic"] = perf_counter()
            heartbeat_state["last_activity_at"] = datetime.utcnow()

    def current_heartbeat() -> dict[str, object]:
        with heartbeat_lock:
            return dict(heartbeat_state)

    def ensure_not_stalled() -> None:
        if stall_event.is_set():
            raise RuntimeError(
                "Import SCHEDULE interrompu: aucune progression detectee pendant plus de "
                f"{int(IMPORT_STALL_TIMEOUT_SECONDS)} secondes."
            )

    def monitor_stall() -> None:
        while not stall_event.wait(IMPORT_HEARTBEAT_INTERVAL_SECONDS):
            snapshot = current_heartbeat()
            if snapshot.get("done"):
                return
            idle_seconds = perf_counter() - float(snapshot.get("last_touch_monotonic") or 0.0)
            if idle_seconds < IMPORT_STALL_TIMEOUT_SECONDS:
                continue
            with SessionLocal() as monitor_db:
                _update_import_log(
                    monitor_db,
                    log_id,
                    status="stalled",
                    phase=str(snapshot.get("phase") or "running"),
                    progress_percent=None,
                    row_count=int(snapshot.get("accepted_rows") or 0),
                    source_rows_seen=int(snapshot.get("processed_rows") or 0),
                    ignored_rows_count=int(snapshot.get("ignored_rows") or 0),
                    rows_per_second=float(snapshot.get("rows_per_second") or 0.0),
                    eta_seconds=None,
                    memory_peak_mb=float(snapshot.get("memory_peak_mb") or 0.0),
                    last_activity_at=snapshot.get("last_activity_at"),
                    finished_at=datetime.utcnow(),
                    phase_details=(
                        f"Blocage detecte apres {int(idle_seconds)}s sans progression | "
                        f"phase={snapshot.get('phase') or '-'} | "
                        f"lues={int(snapshot.get('processed_rows') or 0)} | "
                        f"utiles={int(snapshot.get('accepted_rows') or 0)} | "
                        f"ignorees={int(snapshot.get('ignored_rows') or 0)}"
                    ),
                    message=(
                        "Import SCHEDULE marque comme bloque. "
                        "Relancer l'import apres diagnostic."
                    ),
                )
                monitor_db.commit()
            stall_event.set()
            return

    watchdog = threading.Thread(
        target=monitor_stall,
        daemon=True,
        name=f"restructured-schedule-watchdog-{log_id}",
    )
    watchdog.start()
    try:
        with SessionLocal() as db:
            useful_contracts = _load_restructured_contract_keys(db)
            if not useful_contracts:
                raise ValueError(
                    "Aucun contrat restructure ou consolide n'est disponible. Importer d'abord la liste fixe."
                )

            metrics: dict[str, float | int] = {
                "source_rows": 0,
                "accepted_rows": 0,
                "ignored_rows": 0,
                "unchanged_rows": 0,
                "open_seconds": 0.0,
                "sheet_seconds": 0.0,
                "read_seconds": 0.0,
                "normalize_seconds": 0.0,
                "filter_seconds": 0.0,
                "write_seconds": 0.0,
                "copy_seconds": 0.0,
                "index_seconds": 0.0,
                "upsert_seconds": 0.0,
                "recalculate_seconds": 0.0,
                "total_seconds": 0.0,
                "rows_per_second": 0.0,
                "eta_seconds": None,
                "memory_peak_mb": 0.0,
            }

            def update_peak_memory() -> None:
                _current, peak = tracemalloc.get_traced_memory()
                metrics["memory_peak_mb"] = max(
                    float(metrics["memory_peak_mb"]),
                    peak / (1024 * 1024),
                )

            def publish_progress(
                *,
                processed_rows: int,
                total_rows: int,
                accepted_rows: int,
                ignored_rows: int,
                elapsed_seconds: float,
                rows_per_second: float,
                eta_seconds: float | None,
                progress_percent: int,
                memory_peak_mb: float,
            ) -> None:
                update_peak_memory()
                metrics["source_rows"] = processed_rows
                metrics["accepted_rows"] = accepted_rows
                metrics["ignored_rows"] = ignored_rows
                metrics["rows_per_second"] = rows_per_second
                metrics["eta_seconds"] = eta_seconds
                phase_details = (
                    f"{processed_rows}/{total_rows or processed_rows} lignes lues | "
                    f"{accepted_rows} utiles | {ignored_rows} ignorees | "
                    f"{rows_per_second:.2f} l/s | "
                    f"temps ecoule={elapsed_seconds:.1f}s"
                )
                if eta_seconds is not None:
                    phase_details += f" | reste={eta_seconds:.1f}s"
                touch_heartbeat(
                    phase="filtering",
                    processed_rows=processed_rows,
                    accepted_rows=accepted_rows,
                    ignored_rows=ignored_rows,
                    rows_per_second=rows_per_second,
                    eta_seconds=eta_seconds,
                    memory_peak_mb=float(metrics["memory_peak_mb"]),
                )
                _update_import_log(
                    db,
                    log_id,
                    status="running",
                    phase="filtering",
                    progress_percent=progress_percent,
                    row_count=accepted_rows,
                    source_rows_seen=processed_rows,
                    ignored_rows_count=ignored_rows,
                    rows_per_second=rows_per_second,
                    eta_seconds=eta_seconds,
                    memory_peak_mb=float(metrics["memory_peak_mb"]),
                    last_activity_at=datetime.utcnow(),
                    phase_details=phase_details,
                    message="Lecture du fichier SCHEDULE et filtrage des contrats utiles...",
                )
                db.commit()
                ensure_not_stalled()

            touch_heartbeat(phase="reading")
            _update_import_log(
                db,
                log_id,
                status="running",
                phase="reading",
                progress_percent=IMPORT_PHASE_WEIGHTS["reading"],
                source_rows_seen=0,
                ignored_rows_count=0,
                rows_per_second=0.0,
                eta_seconds=None,
                memory_peak_mb=0.0,
                last_activity_at=datetime.utcnow(),
                message=(
                    "Lecture du fichier SCHEDULE en cours... "
                    f"{len(useful_contracts)} contrat(s) utiles identifies."
                ),
            )
            db.commit()

            suffix = Path(file_name or upload_path).suffix.lower()
            csv_fd, csv_path = tempfile.mkstemp(prefix="restructured_schedule_stage_", suffix=".csv")
            os.close(csv_fd)

            if suffix == ".xlsx":
                row_count, stream_metrics = _stream_schedule_xlsx_to_csv(
                    upload_path,
                    csv_path,
                    useful_contracts=useful_contracts,
                    progress_callback=publish_progress,
                )
            elif suffix == ".csv":
                row_count, stream_metrics = _stream_schedule_csv_to_csv(
                    upload_path,
                    csv_path,
                    useful_contracts=useful_contracts,
                    progress_callback=publish_progress,
                )
            else:
                row_count, stream_metrics = _materialize_schedule_from_non_stream_source(
                    upload_path,
                    csv_path,
                    useful_contracts=useful_contracts,
                    progress_callback=publish_progress,
                )
            metrics.update(stream_metrics)
            update_peak_memory()
            ensure_not_stalled()
            touch_heartbeat(
                phase="staging",
                processed_rows=int(metrics["source_rows"]),
                accepted_rows=int(metrics["accepted_rows"]),
                ignored_rows=int(metrics["ignored_rows"]),
                rows_per_second=float(metrics.get("rows_per_second") or 0.0),
                eta_seconds=metrics.get("eta_seconds"),
                memory_peak_mb=float(metrics["memory_peak_mb"]),
            )
            _update_import_log(
                db,
                log_id,
                status="running",
                phase="staging",
                progress_percent=IMPORT_PHASE_WEIGHTS["staging"],
                row_count=row_count,
                source_rows_seen=int(metrics["source_rows"]),
                ignored_rows_count=int(metrics["ignored_rows"]),
                rows_per_second=float(metrics.get("rows_per_second") or 0.0),
                eta_seconds=metrics.get("eta_seconds"),
                memory_peak_mb=float(metrics["memory_peak_mb"]),
                last_activity_at=datetime.utcnow(),
                phase_details=(
                    f"{metrics['source_rows']} lignes source | "
                    f"{metrics['accepted_rows']} lignes utiles retenues"
                ),
                message="Chargement des lignes utiles en staging PostgreSQL...",
            )
            db.commit()

            impacted_contracts: list[str] = []
            inserted = 0
            updated = 0
            deleted = 0
            if db.bind and db.bind.dialect.name == "postgresql":
                touch_heartbeat(phase="upsert")
                upsert_metrics = _upsert_schedule_postgres_from_csv(db, csv_path)
                inserted = int(upsert_metrics["inserted"])
                updated = int(upsert_metrics["updated"])
                deleted = int(upsert_metrics["deleted"])
                impacted_contracts = list(upsert_metrics["impacted_contracts"])
                metrics["unchanged_rows"] = int(upsert_metrics["unchanged"])
                metrics["copy_seconds"] = float(upsert_metrics["copy_seconds"])
                metrics["index_seconds"] = float(upsert_metrics["index_seconds"])
                metrics["upsert_seconds"] = float(upsert_metrics["upsert_seconds"])
            else:
                content = Path(upload_path).read_bytes()
                frame = _normalize_schedule_frame(content)
                frame = frame[frame["account_number"].isin(useful_contracts)].copy()
                inserted, updated, deleted = _upsert_schedule_rows(db, frame)
                impacted_contracts = sorted(useful_contracts)
            update_peak_memory()
            ensure_not_stalled()

            touch_heartbeat(
                phase="recalculate",
                processed_rows=int(metrics["source_rows"]),
                accepted_rows=int(metrics["accepted_rows"]),
                ignored_rows=int(metrics["ignored_rows"]),
                rows_per_second=float(metrics.get("rows_per_second") or 0.0),
                eta_seconds=None,
                memory_peak_mb=float(metrics["memory_peak_mb"]),
            )
            _update_import_log(
                db,
                log_id,
                status="running",
                phase="recalculate",
                progress_percent=IMPORT_PHASE_WEIGHTS["upsert"],
                inserted_count=inserted,
                updated_count=updated,
                deleted_count=deleted,
                row_count=int(metrics["accepted_rows"]),
                source_rows_seen=int(metrics["source_rows"]),
                ignored_rows_count=int(metrics["ignored_rows"]),
                rows_per_second=float(metrics.get("rows_per_second") or 0.0),
                eta_seconds=None,
                memory_peak_mb=float(metrics["memory_peak_mb"]),
                last_activity_at=datetime.utcnow(),
                phase_details=(
                    f"copy={_format_seconds(metrics['copy_seconds'])} | "
                    f"index={_format_seconds(metrics['index_seconds'])} | "
                    f"upsert={_format_seconds(metrics['upsert_seconds'])} | "
                    f"identiques={metrics['unchanged_rows']}"
                ),
                message="Recalcul incrémental des contrats impactés...",
            )
            db.commit()

            recalc_started = perf_counter()
            recalculated = recalculate_restructured_results_for_contracts(db, impacted_contracts)
            metrics["recalculate_seconds"] = perf_counter() - recalc_started
            finished_at = datetime.utcnow()
            metrics["total_seconds"] = perf_counter() - total_started
            update_peak_memory()
            metrics["eta_seconds"] = 0.0
            phase_details = _format_import_phase_details(metrics)
            _log_import_phase_metrics("restructured_schedule_import", metrics)
            touch_heartbeat(
                done=True,
                phase="completed",
                processed_rows=int(metrics["source_rows"]),
                accepted_rows=int(metrics["accepted_rows"]),
                ignored_rows=int(metrics["ignored_rows"]),
                rows_per_second=float(metrics.get("rows_per_second") or 0.0),
                eta_seconds=0.0,
                memory_peak_mb=float(metrics["memory_peak_mb"]),
            )
            _update_import_log(
                db,
                log_id,
                status="success",
                phase="completed",
                progress_percent=100,
                row_count=int(metrics["accepted_rows"]),
                recalculated_contracts=recalculated,
                source_rows_seen=int(metrics["source_rows"]),
                ignored_rows_count=int(metrics["ignored_rows"]),
                rows_per_second=float(metrics.get("rows_per_second") or 0.0),
                eta_seconds=0.0,
                memory_peak_mb=float(metrics["memory_peak_mb"]),
                finished_at=finished_at,
                last_activity_at=finished_at,
                phase_details=phase_details,
                message=(
                    f"Import SCHEDULE termine: {int(metrics['source_rows'])} ligne(s) lues, "
                    f"{int(metrics['accepted_rows'])} utile(s), {inserted} ajoutee(s), "
                    f"{updated} mise(s) a jour, {deleted} supprimee(s), "
                    f"{int(metrics['unchanged_rows'])} identique(s), "
                    f"{recalculated} contrat(s) recalcules."
                ),
            )
            db.commit()
    except Exception as exc:
        logger.exception("Restructured schedule import job failed", exc_info=exc)
        touch_heartbeat(done=True, phase="failed")
        with SessionLocal() as db:
            _update_import_log(
                db,
                log_id,
                status="failed",
                phase="failed",
                finished_at=datetime.utcnow(),
                progress_percent=100,
                message=f"Echec import SCHEDULE: {exc}",
                phase_details=str(exc),
                last_activity_at=datetime.utcnow(),
            )
            db.commit()
    finally:
        touch_heartbeat(done=True)
        stall_event.set()
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        if csv_path and os.path.exists(csv_path):
            os.unlink(csv_path)
        if upload_path and os.path.exists(upload_path):
            os.unlink(upload_path)


def diagnose_restructured_schedule_import(
    db: Session,
    *,
    source_path: str | os.PathLike[str],
    sample_rows: int = IMPORT_DIAGNOSTIC_SAMPLE_ROWS,
    useful_contracts: set[str] | None = None,
) -> dict[str, object]:
    useful_contracts = useful_contracts or _load_restructured_contract_keys(db)
    if not useful_contracts:
        raise ValueError(
            "Aucun contrat restructure ou consolide n'est disponible. Importer d'abord la liste fixe."
        )

    suffix = Path(source_path).suffix.lower()
    csv_fd, csv_path = tempfile.mkstemp(prefix="restructured_schedule_diag_", suffix=".csv")
    os.close(csv_fd)
    started = perf_counter()
    try:
        if suffix == ".xlsx":
            row_count, metrics = _stream_schedule_xlsx_to_csv(
                source_path,
                csv_path,
                useful_contracts=useful_contracts,
                max_rows=sample_rows,
            )
        elif suffix == ".csv":
            row_count, metrics = _stream_schedule_csv_to_csv(
                source_path,
                csv_path,
                useful_contracts=useful_contracts,
                max_rows=sample_rows,
            )
        else:
            row_count, metrics = _materialize_schedule_from_non_stream_source(
                source_path,
                csv_path,
                useful_contracts=useful_contracts,
                max_rows=sample_rows,
            )
        total_seconds = perf_counter() - started
        rows_per_second = (
            float(metrics.get("source_rows", 0)) / total_seconds if total_seconds > 0 else 0.0
        )
        estimated_total_seconds = None
        total_rows = int(
            metrics.get("source_total_rows")
            or metrics.get("total_rows")
            or metrics.get("source_rows")
            or 0
        )
        if total_rows > 0 and rows_per_second > 0:
            estimated_total_seconds = total_rows / rows_per_second
        return {
            "file_name": Path(source_path).name,
            "sample_rows": sample_rows,
            "useful_contracts": len(useful_contracts),
            "rows_retained": row_count,
            "rows_scanned": int(metrics.get("source_rows") or 0),
            "rows_ignored": int(metrics.get("ignored_rows") or 0),
            "rows_per_second": round(rows_per_second, 2),
            "estimated_total_seconds": round(estimated_total_seconds, 2) if estimated_total_seconds is not None else None,
            "metrics": metrics,
            "phase_details": _format_import_phase_details(
                {
                    **metrics,
                    "rows_per_second": rows_per_second,
                    "eta_seconds": estimated_total_seconds,
                    "total_seconds": total_seconds,
                }
            ),
        }
    finally:
        if os.path.exists(csv_path):
            os.unlink(csv_path)


def start_restructured_schedule_import_job(
    db: Session,
    *,
    content: bytes,
    file_name: str,
) -> RestructuredImportLog:
    log = _create_pending_import_log(
        db,
        import_type="schedule",
        file_name=file_name,
        message="Import SCHEDULE en attente de traitement.",
    )
    upload_suffix = Path(file_name or "schedule.xlsx").suffix or ".xlsx"
    fd, upload_path = tempfile.mkstemp(prefix="restructured_schedule_upload_", suffix=upload_suffix)
    os.close(fd)
    with open(upload_path, "wb") as handle:
        handle.write(content)
    # Commit the queued log before starting the worker thread so fast failures
    # can update the row instead of leaving the job stuck in "queued".
    db.commit()
    db.refresh(log)
    thread = threading.Thread(
        target=_run_restructured_schedule_import_job,
        kwargs={
            "log_id": log.id,
            "upload_path": upload_path,
            "file_name": file_name,
        },
        daemon=True,
        name=f"restructured-schedule-import-{log.id}",
    )
    thread.start()
    return log


def _role_scoped_filters(
    db: Session,
    user: User,
    model,
    agency_id: str | None,
    agent_id: int | None,
) -> list[object]:
    filters: list[object] = []
    scope = get_user_data_scope(user)

    def agency_name_by_id(raw_id: int | None) -> str | None:
        if raw_id is None:
            return None
        return db.scalar(select(Agency.name).where(Agency.id == raw_id))

    def agent_name_by_id(raw_id: int | None) -> str | None:
        if raw_id is None:
            return None
        return db.scalar(select(Agent.name).where(Agent.id == raw_id))

    if scope.role == UserRole.AGENCY_MANAGER and scope.agency_id is not None:
        agency_name = agency_name_by_id(scope.agency_id)
        if not agency_name:
            return [false()]
        filters.append(model.agency_name == agency_name)
    elif scope.role == UserRole.PORTFOLIO_MANAGER and scope.agent_id is not None:
        scoped_agent_name = agent_name_by_id(scope.agent_id)
        if not scoped_agent_name:
            return [false()]
        filters.append(model.agent_name == scoped_agent_name)

    selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
    if selected_agency_ids and scope.role != UserRole.PORTFOLIO_MANAGER:
        selected_agency_names = [agency_name_by_id(selected_id) for selected_id in selected_agency_ids]
        if any(not name for name in selected_agency_names):
            return [false()]
        if len(selected_agency_names) == 1:
            filters.append(model.agency_name == selected_agency_names[0])
        else:
            filters.append(model.agency_name.in_(selected_agency_names))

    if agent_id:
        selected_agent_name = agent_name_by_id(agent_id)
        if not selected_agent_name:
            return [false()]
        if scope.role == UserRole.PORTFOLIO_MANAGER and scope.agent_id is not None:
            scoped_agent_name = agent_name_by_id(scope.agent_id)
            if scoped_agent_name != selected_agent_name:
                return [false()]
        filters.append(model.agent_name == selected_agent_name)

    return filters


def get_restructured_kpis(
    db: Session,
    user: User,
    agency_id: int | None = None,
    agent_id: int | None = None,
) -> RestructuredKpiRead:
    filters = _role_scoped_filters(db, user, RestructuredAnalysisResult, agency_id, agent_id)
    gap_filters = _role_scoped_filters(db, user, RestructuredGapResult, agency_id, agent_id)

    row = db.execute(
        select(
            func.count(RestructuredAnalysisResult.id),
            func.coalesce(
                func.sum(
                    case((RestructuredAnalysisResult.closure_status == CLOSURE_STATUS_ASSUMED_CLOSED, 1), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((RestructuredAnalysisResult.closure_status == "En cours", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((RestructuredAnalysisResult.anomaly_detected.is_(True), 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((RestructuredAnalysisResult.paid_last_four_status == "Oui", 1), else_=0)),
                0,
            ),
            func.coalesce(func.sum(RestructuredAnalysisResult.total_due), 0),
            func.max(RestructuredAnalysisResult.last_calculated_at),
        ).where(*filters)
    ).one()
    gaps_count = db.scalar(select(func.count(RestructuredGapResult.id)).where(*gap_filters)) or 0
    last_schedule_import_at = db.scalar(
        select(func.max(RestructuredImportLog.finished_at)).where(
            RestructuredImportLog.import_type == "schedule",
            RestructuredImportLog.status == "success",
        )
    )
    return RestructuredKpiRead(
        total_contracts=int(row[0] or 0),
        supposed_closed=int(row[1] or 0),
        in_progress=int(row[2] or 0),
        anomalies_count=int(row[3] or 0),
        gaps_count=int(gaps_count or 0),
        paid_last_four_yes=int(row[4] or 0),
        total_due=Decimal(str(row[5] or 0)),
        last_recalculated_at=row[6],
        last_schedule_import_at=last_schedule_import_at,
    )

def _slice_chart(
    values: list[tuple[str, int]],
    colors: dict[str, str] | None = None,
) -> RestructuredChartRead:
    return RestructuredChartRead(
        items=[
            RestructuredChartSliceRead(label=label, value=int(value or 0), color=(colors or {}).get(label))
            for label, value in values
        ]
    )


def get_restructured_consecutive_chart(
    db: Session,
    user: User,
    agency_id: int | None = None,
    agent_id: int | None = None,
) -> RestructuredChartRead:
    filters = _role_scoped_filters(db, user, RestructuredAnalysisResult, agency_id, agent_id)
    rows = db.execute(
        select(
            RestructuredAnalysisResult.consecutive_paid_count,
            func.count(RestructuredAnalysisResult.id),
        )
        .where(*filters)
        .group_by(RestructuredAnalysisResult.consecutive_paid_count)
    ).all()
    bucket_values = {"0": 0, "1-2": 0, "3": 0, "4+": 0}
    for count_value, row_count in rows:
        bucket_values[_bucket_for_count(count_value)] += int(row_count or 0)
    return _slice_chart(
        [(label, bucket_values[label]) for label in ("0", "1-2", "3", "4+")],
        {label: meta["color"] for label, meta in CONSECUTIVE_BUCKETS.items()},
    )


def get_restructured_closure_chart(db: Session, user: User, agency_id: int | None = None, agent_id: int | None = None) -> RestructuredChartRead:
    filters = _role_scoped_filters(db, user, RestructuredAnalysisResult, agency_id, agent_id)
    rows = db.execute(
        select(RestructuredAnalysisResult.closure_status, func.count(RestructuredAnalysisResult.id))
        .where(*filters)
        .group_by(RestructuredAnalysisResult.closure_status)
    ).all()
    values = {CLOSURE_STATUS_ASSUMED_CLOSED: 0, "En cours": 0, "N/A": 0}
    for label, count_value in rows:
        values[label or "N/A"] = int(count_value or 0)
    return _slice_chart(list(values.items()), STATUS_COLORS)


def get_restructured_paid_last_four_chart(
    db: Session,
    user: User,
    agency_id: int | None = None,
    agent_id: int | None = None,
) -> RestructuredChartRead:
    filters = _role_scoped_filters(db, user, RestructuredAnalysisResult, agency_id, agent_id)
    rows = db.execute(
        select(RestructuredAnalysisResult.paid_last_four_status, func.count(RestructuredAnalysisResult.id))
        .where(*filters)
        .group_by(RestructuredAnalysisResult.paid_last_four_status)
    ).all()
    values = {CLOSURE_STATUS_ASSUMED_CLOSED: 0, "En cours": 0, "N/A": 0}
    for label, count_value in rows:
        values[label or "N/A"] = int(count_value or 0)
    return _slice_chart(list(values.items()), STATUS_COLORS)


def get_restructured_delay_chart(
    db: Session,
    user: User,
    agency_id: int | None = None,
    agent_id: int | None = None,
) -> RestructuredTrendChartRead:
    filters = _role_scoped_filters(db, user, RestructuredAnalysisResult, agency_id, agent_id)
    rows = db.execute(
        select(
            func.extract("year", RestructuredAnalysisResult.delay_date).label("year"),
            func.extract("month", RestructuredAnalysisResult.delay_date).label("month"),
            func.count(RestructuredAnalysisResult.id),
        )
        .where(*filters, RestructuredAnalysisResult.delay_date.is_not(None))
        .group_by("year", "month")
        .order_by("year", "month")
    ).all()
    return RestructuredTrendChartRead(
        items=[
            RestructuredTrendPointRead(
                label=f"{int(month):02d}/{int(year)}",
                value=int(count_value or 0),
            )
            for year, month, count_value in rows
        ]
    )


def _contracts_base_query(
    db: Session,
    user: User,
    agency_id: int | None,
    agent_id: int | None,
    q: str | None = None,
    closure_status: str | None = None,
    consecutive_bucket: str | None = None,
    anomaly: str | None = None,
    paid_last_four: str | None = None,
):
    query = select(RestructuredAnalysisResult).where(
        *_role_scoped_filters(db, user, RestructuredAnalysisResult, agency_id, agent_id)
    )
    if q:
        term = f"%{q.strip()}%"
        query = query.where(
            RestructuredAnalysisResult.contract_no.ilike(term)
            | func.coalesce(RestructuredAnalysisResult.agency_name, "").ilike(term)
            | func.coalesce(RestructuredAnalysisResult.agent_name, "").ilike(term)
            | func.coalesce(RestructuredAnalysisResult.anomaly_detail, "").ilike(term)
        )
    if closure_status:
        query = query.where(RestructuredAnalysisResult.closure_status == closure_status)
    if anomaly in {"Oui", "Non"}:
        query = query.where(RestructuredAnalysisResult.anomaly_detected.is_(anomaly == "Oui"))
    if paid_last_four in {"Oui", "Non", "N/A"}:
        query = query.where(RestructuredAnalysisResult.paid_last_four_status == paid_last_four)
    if consecutive_bucket:
        meta = CONSECUTIVE_BUCKETS.get(consecutive_bucket)
        if meta:
            query = query.where(
                RestructuredAnalysisResult.consecutive_paid_count >= meta["min"],
                RestructuredAnalysisResult.consecutive_paid_count <= meta["max"],
            )
    return query


def list_restructured_contracts(
    db: Session,
    user: User,
    *,
    agency_id: int | None = None,
    agent_id: int | None = None,
    q: str | None = None,
    closure_status: str | None = None,
    consecutive_bucket: str | None = None,
    anomaly: str | None = None,
    paid_last_four: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[RestructuredContractRead]:
    base_query = _contracts_base_query(
        db,
        user,
        agency_id,
        agent_id,
        q=q,
        closure_status=closure_status,
        consecutive_bucket=consecutive_bucket,
        anomaly=anomaly,
        paid_last_four=paid_last_four,
    )
    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    rows = db.scalars(
        base_query.order_by(
            RestructuredAnalysisResult.delay_date.desc().nullslast(),
            RestructuredAnalysisResult.contract_no.asc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        RestructuredContractRead(
            contract_no=row.contract_no,
            agency_name=row.agency_name,
            agent_name=row.agent_name,
            delay_date=row.delay_date,
            total_due=row.total_due,
            loan_duration=row.loan_duration,
            schedule_status=row.schedule_status,
            consecutive_paid_count=row.consecutive_paid_count,
            consecutive_bucket=_bucket_for_count(row.consecutive_paid_count),
            max_series_installments=row.max_series_installments,
            max_series_dates=row.max_series_dates,
            paid_installments_after_delay=row.paid_installments_after_delay,
            anomaly_detected=row.anomaly_detected,
            anomaly_detail=row.anomaly_detail,
            paid_last_four_status=row.paid_last_four_status,
            last_paid_installment_no=row.last_paid_installment_no,
            last_paid_due_date=row.last_paid_due_date,
            closure_status=row.closure_status,
        )
        for row in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


def list_restructured_gaps(
    db: Session,
    user: User,
    *,
    agency_id: int | None = None,
    agent_id: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[RestructuredGapRead]:
    query = select(RestructuredGapResult).where(
        *_role_scoped_filters(db, user, RestructuredGapResult, agency_id, agent_id)
    )
    if q:
        term = f"%{q.strip()}%"
        query = query.where(
            RestructuredGapResult.contract_no.ilike(term)
            | func.coalesce(RestructuredGapResult.agency_name, "").ilike(term)
            | func.coalesce(RestructuredGapResult.agent_name, "").ilike(term)
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(
            RestructuredGapResult.gap_days.desc().nullslast(),
            RestructuredGapResult.contract_no.asc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        RestructuredGapRead(
            contract_no=row.contract_no,
            agency_name=row.agency_name,
            agent_name=row.agent_name,
            due_date_1=row.due_date_1,
            due_date_2=row.due_date_2,
            installment_no_1=row.installment_no_1,
            installment_no_2=row.installment_no_2,
            gap_days=row.gap_days,
            total_gap_count=row.total_gap_count,
        )
        for row in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


def _fit_column_widths(sheet) -> None:
    for column_index in range(1, sheet.max_column + 1):
        max_length = 0
        column_letter = get_column_letter(column_index)
        for row_index in range(1, sheet.max_row + 1):
            value = sheet.cell(row=row_index, column=column_index).value
            max_length = max(max_length, len("" if value is None else str(value)))
        sheet.column_dimensions[column_letter].width = min(36, max(12, max_length + 2))


def build_restructured_contracts_export(
    db: Session,
    user: User,
    *,
    agency_id: int | None = None,
    agent_id: int | None = None,
    q: str | None = None,
    closure_status: str | None = None,
    consecutive_bucket: str | None = None,
    anomaly: str | None = None,
    paid_last_four: str | None = None,
) -> BytesIO:
    query = _contracts_base_query(
        db,
        user,
        agency_id,
        agent_id,
        q=q,
        closure_status=closure_status,
        consecutive_bucket=consecutive_bucket,
        anomaly=anomaly,
        paid_last_four=paid_last_four,
    )
    rows = db.scalars(
        query.order_by(
            RestructuredAnalysisResult.delay_date.desc().nullslast(),
            RestructuredAnalysisResult.contract_no.asc(),
        )
    ).all()
    items = [
        RestructuredContractRead(
            contract_no=row.contract_no,
            agency_name=row.agency_name,
            agent_name=row.agent_name,
            delay_date=row.delay_date,
            total_due=row.total_due,
            loan_duration=row.loan_duration,
            schedule_status=row.schedule_status,
            consecutive_paid_count=row.consecutive_paid_count,
            consecutive_bucket=_bucket_for_count(row.consecutive_paid_count),
            max_series_installments=row.max_series_installments,
            max_series_dates=row.max_series_dates,
            paid_installments_after_delay=row.paid_installments_after_delay,
            anomaly_detected=row.anomaly_detected,
            anomaly_detail=row.anomaly_detail,
            paid_last_four_status=row.paid_last_four_status,
            last_paid_installment_no=row.last_paid_installment_no,
            last_paid_due_date=row.last_paid_due_date,
            closure_status=row.closure_status,
        )
        for row in rows
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Crédits restructurés"

    headers = [
        "NÂ° contrat",
        "Agence",
        "GP",
        "Date de décalage",
        "Total_Due",
        "LOAN_DURATION",
        "Statut",
        "Nb échéances consécutives payées",
        "NÂ° échéances payées (série max)",
        "Dates échéances payées (série max)",
        "Anomalie détectée",
        "Détail anomalie",
        "Payé les 4 derniù¨res échéances",
        "Derniù¨re échéance payée (NÂ°)",
        "Date derniù¨re échéance payée",
        "Statut clù´ture",
    ]

    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    sheet["A1"] = "Suivi des crédits restructurés et consolidés"
    sheet["A1"].fill = TITLE_FILL
    sheet["A1"].font = TITLE_FONT
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
    sheet["A2"] = f"Export généré le {_safe_datetime_to_string(datetime.utcnow())}"
    sheet["A2"].font = Font(size=10, color="334155")

    for column_index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=4, column=column_index, value=header)
        cell.fill = HEADER_BG
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER

    for row_index, item in enumerate(items, start=5):
        values = [
            item.contract_no,
            item.agency_name or "-",
            item.agent_name or "-",
            item.delay_date,
            float(item.total_due or 0),
            item.loan_duration,
            item.schedule_status or "-",
            item.consecutive_paid_count,
            item.max_series_installments or "-",
            item.max_series_dates or "-",
            "Oui" if item.anomaly_detected else "Non",
            item.anomaly_detail or "-",
            item.paid_last_four_status,
            item.last_paid_installment_no,
            item.last_paid_due_date,
            item.closure_status,
        ]
        for column_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=column_index, value=value)
            cell.border = THIN_BORDER
            if row_index % 2 == 0:
                cell.fill = ALT_ROW_FILL
            if column_index in {5}:
                cell.number_format = "#,##0.000"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif column_index in {4, 15}:
                cell.number_format = "DD/MM/YYYY"
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    sheet.freeze_panes = "A5"
    _fit_column_widths(sheet)
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer

