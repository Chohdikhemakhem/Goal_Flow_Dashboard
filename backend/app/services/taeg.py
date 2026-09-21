from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
import logging
from typing import Any

from sqlalchemy import String, and_, case, false, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models.entities import (
    ActivitySector,
    Agency,
    Agent,
    CategorySectorMapping,
    ImportBatch,
    LoanRaw,
    User,
)
from app.models.enums import ImportBatchType, UserRole
from app.services.agent_identity import normalized_agent_name_expression
from app.services.taeg_history import (
    STATUS_CONFORME,
    STATUS_NON_CONFORME,
    STATUS_NON_COUVERT,
    build_acm_coverage_segments_for_periods,
    build_applied_acm_subqueries,
    _format_acm_block_range,
    validate_acm_blocks_for_periods,
)
from app.services.selection import normalize_agency_ids
from app.services.data_scope import get_user_data_scope, region_scope_condition

logger = logging.getLogger(__name__)
FRENCH_MONTH_NAMES = {
    1: "Janvier",
    2: "Fevrier",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Aout",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Decembre",
}

TAEG_DETAIL_SORT_COLUMNS = {
    "disbursement_amount": lambda sector_acm_case, taeg_amount_expr: LoanRaw.disbursement_amount,
    "teg_rate": lambda sector_acm_case, taeg_amount_expr: func.coalesce(LoanRaw.teg_rate, Decimal("0")),
    "taeg_calculated": lambda sector_acm_case, taeg_amount_expr: taeg_amount_expr,
    "taeg_weighted_rate": lambda sector_acm_case, taeg_amount_expr: func.coalesce(LoanRaw.teg_rate, Decimal("0")),
    "acm_rate": lambda sector_acm_case, taeg_amount_expr: sector_acm_case,
}


def _agent_join_condition():
    return (
        (normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name))
        & (Agent.agency_id == Agency.id)
    )


def _month_bounds(snapshot_date: date) -> tuple[date, date]:
    return (
        date(snapshot_date.year, snapshot_date.month, 1),
        date(snapshot_date.year, snapshot_date.month, monthrange(snapshot_date.year, snapshot_date.month)[1]),
    )


def _period_label(snapshot_date: date) -> str:
    return f"{snapshot_date.month:02d}/{snapshot_date.year}"


def _latest_current_batch(db: Session) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch)
        .where(ImportBatch.batch_type == ImportBatchType.CURRENT_STATE)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )


def _historical_batches(db: Session) -> list[ImportBatch]:
    return db.scalars(
        select(ImportBatch)
        .where(ImportBatch.batch_type == ImportBatchType.HISTORICAL_MONTH)
        .order_by(ImportBatch.snapshot_date.asc(), ImportBatch.id.asc())
    ).all()


def _serialize_batch(batch: ImportBatch, *, key: str | None = None, label: str | None = None, is_current: bool = False) -> dict:
    return {
        "key": key or f"historical:{batch.id}",
        "label": label or (_period_label(batch.snapshot_date) if not is_current else "Etat actuel"),
        "snapshot_date": batch.snapshot_date,
        "batch_type": batch.batch_type.value,
        "batch_id": batch.id,
        "is_current": is_current,
        "month_number": batch.snapshot_date.month,
        "year": batch.snapshot_date.year,
    }


def list_taeg_periods(db: Session) -> list[dict]:
    items: list[dict] = []
    current_batch = _latest_current_batch(db)
    if current_batch:
        items.append(_serialize_batch(current_batch, key="current", label="Etat actuel", is_current=True))
    items.extend(_serialize_batch(batch) for batch in _historical_batches(db))
    return items


def _parse_period_keys(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    seen: set[str] = set()
    keys: list[str] = []
    for token in raw_value.split(","):
        normalized = token.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        keys.append(normalized)
    return keys


def _semester_months(semester_key: str) -> set[int]:
    if semester_key == "semester:s1":
        return {1, 2, 3, 4, 5, 6}
    if semester_key == "semester:s2":
        return {7, 8, 9, 10, 11, 12}
    raise ValueError("Periode TAEG invalide.")


def _resolve_reference_year(historical_batches: list[ImportBatch], current_batch: ImportBatch | None) -> int | None:
    if historical_batches:
        return max(batch.snapshot_date.year for batch in historical_batches)
    if current_batch:
        return current_batch.snapshot_date.year
    return None


def resolve_taeg_selection(db: Session, key: str | None, period_keys: str | None = None) -> dict:
    normalized_key = (key or "current").strip() or "current"
    historical_batches = _historical_batches(db)
    current_batch = _latest_current_batch(db)

    if normalized_key == "current":
        if not current_batch:
            raise ValueError("Aucun état actuel n'est disponible pour TAEG.")
        current_period = _serialize_batch(current_batch, key="current", label="Etat actuel", is_current=True)
        return {
            "period": current_period,
            "used_periods": [current_period],
            "is_current": True,
        }

    if normalized_key.startswith("historical:"):
        try:
            batch_id = int(normalized_key.split(":", 1)[1])
        except ValueError as exc:
            raise ValueError("Période TAEG invalide.") from exc
        batch = db.get(ImportBatch, batch_id)
        if not batch or batch.batch_type != ImportBatchType.HISTORICAL_MONTH:
            raise ValueError("Période historique TAEG introuvable.")
        historical_period = _serialize_batch(batch)
        return {
            "period": historical_period,
            "used_periods": [historical_period],
            "is_current": False,
        }

    if normalized_key in {"semester:s1", "semester:s2"}:
        reference_year = _resolve_reference_year(historical_batches, current_batch)
        semester_batches = []
        if reference_year is not None:
            target_months = _semester_months(normalized_key)
            semester_batches = [
                batch for batch in historical_batches
                if batch.snapshot_date.year == reference_year and batch.snapshot_date.month in target_months
            ]
        used_periods = [_serialize_batch(batch) for batch in semester_batches]
        period_snapshot = semester_batches[-1].snapshot_date if semester_batches else date(
            reference_year or date.today().year,
            6 if normalized_key == "semester:s1" else 12,
            1,
        )
        return {
            "period": {
                "key": normalized_key,
                "label": "S1" if normalized_key == "semester:s1" else "S2",
                "snapshot_date": period_snapshot,
                "batch_type": "AGGREGATE",
                "batch_id": None,
                "is_current": False,
                "month_number": None,
                "year": reference_year,
            },
            "used_periods": used_periods,
            "is_current": False,
        }

    if normalized_key == "custom":
        selected_keys = _parse_period_keys(period_keys)
        if len(selected_keys) < 2:
            raise ValueError("Veuillez sélectionner au moins deux mois.")
        historical_by_key = {f"historical:{batch.id}": batch for batch in historical_batches}
        selected_batches: list[ImportBatch] = []
        for selected_key in selected_keys:
            batch = historical_by_key.get(selected_key)
            if batch is None:
                raise ValueError(f"Période personnalisée introuvable: {selected_key}")
            selected_batches.append(batch)
        selected_batches.sort(key=lambda item: (item.snapshot_date, item.id))
        used_periods = [_serialize_batch(batch) for batch in selected_batches]
        return {
            "period": {
                "key": "custom",
                "label": "Personnalise",
                "snapshot_date": selected_batches[-1].snapshot_date,
                "batch_type": "AGGREGATE",
                "batch_id": None,
                "is_current": False,
                "month_number": None,
                "year": None,
            },
            "used_periods": used_periods,
            "is_current": False,
        }

    raise ValueError("Période TAEG invalide.")


def _validate_taeg_user(user: User) -> None:
    if user.role not in {
        UserRole.SUPER_ADMIN,
        UserRole.ADMIN,
        UserRole.COMMITTEE_MEMBER,
        UserRole.AGENCY_MANAGER,
        UserRole.PORTFOLIO_MANAGER,
    }:
        raise ValueError("Accès TAEG non autorisé.")


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def format_taeg_period_name(period: dict | None) -> str:
    if not period:
        return "TAEG"
    key = str(period.get("key") or "")
    if key == "current":
        return "Etat actuel"
    if key == "semester:s1":
        return "S1"
    if key == "semester:s2":
        return "S2"
    if key == "custom":
        return "Personnalise"
    snapshot_date = period.get("snapshot_date")
    if isinstance(snapshot_date, date):
        return f"{FRENCH_MONTH_NAMES.get(snapshot_date.month, snapshot_date.month)} {snapshot_date.year}"
    return str(period.get("label") or "TAEG")


def format_taeg_used_months_label(used_periods: list[dict]) -> str:
    if not used_periods:
        return "Aucun mois disponible"
    snapshot_dates = [
        period.get("snapshot_date")
        for period in used_periods
        if isinstance(period.get("snapshot_date"), date)
    ]
    if not snapshot_dates:
        return "Aucun mois disponible"
    years = {snapshot.year for snapshot in snapshot_dates}
    if len(years) == 1:
        return " • ".join(FRENCH_MONTH_NAMES.get(snapshot.month, str(snapshot.month)) for snapshot in snapshot_dates)
    return " • ".join(format_taeg_period_name(period) for period in used_periods)


def summarize_taeg_rows(rows: list[dict]) -> dict[str, Decimal | int]:
    total_sectors = len(rows)
    compliant_sectors = sum(1 for row in rows if row.get("status") == STATUS_CONFORME)
    non_compliant_sectors = sum(1 for row in rows if row.get("status") == STATUS_NON_CONFORME)
    uncovered_sectors = sum(1 for row in rows if row.get("status") == STATUS_NON_COUVERT)
    total_disbursement = sum(_to_decimal(row.get("disbursement_amount")) for row in rows)
    total_credits = sum(int(row.get("credits_count") or 0) for row in rows)
    total_taeg_calculated = sum(_to_decimal(row.get("taeg_calculated")) for row in rows)
    global_weighted_rate = total_taeg_calculated / total_disbursement if total_disbursement else Decimal("0")
    return {
        "total_sectors": total_sectors,
        "compliant_sectors": compliant_sectors,
        "non_compliant_sectors": non_compliant_sectors,
        "uncovered_sectors": uncovered_sectors,
        "total_disbursement": total_disbursement,
        "total_credits": total_credits,
        "global_weighted_rate": global_weighted_rate,
    }


def _sector_summary_status(
    *,
    taeg_weighted_rate: Decimal | None,
    acm_rate: Decimal | None,
) -> str:
    if acm_rate is None:
        return STATUS_NON_COUVERT
    comparable_taeg = _to_decimal(taeg_weighted_rate)
    return STATUS_CONFORME if comparable_taeg <= acm_rate else STATUS_NON_CONFORME


def _decorate_summary_rows(rows: list[dict]) -> list[dict]:
    normalized_rows: list[dict] = []
    for row in rows:
        covered_disbursement_amount = _to_decimal(row.get("covered_disbursement_amount"))
        acm_weighted_numerator = _to_decimal(row.get("acm_weighted_numerator"))
        acm_rate = (
            acm_weighted_numerator / covered_disbursement_amount
            if covered_disbursement_amount
            else None
        )
        non_compliant_count = int(row.get("non_compliant_credits_count") or 0)
        uncovered_count = int(row.get("uncovered_credits_count") or 0)
        compliant_count = int(row.get("compliant_credits_count") or 0)
        taeg_weighted_rate = _to_decimal(row.get("taeg_weighted_rate"))
        status = _sector_summary_status(
            taeg_weighted_rate=taeg_weighted_rate,
            acm_rate=acm_rate,
        )
        normalized_rows.append(
            {
                **row,
                "acm_rate": acm_rate,
                "taeg_weighted_rate": taeg_weighted_rate,
                "status": status,
                "compliant_credits_count": compliant_count,
                "non_compliant_credits_count": non_compliant_count,
                "uncovered_credits_count": uncovered_count,
            }
        )
    return normalized_rows


def _log_sector_status_diagnostics(
    *,
    selection: dict,
    rows: list[dict],
    acm_segments: list[dict],
) -> None:
    period_label = str(selection.get("period", {}).get("label") or selection.get("period", {}).get("key") or "TAEG")
    segment_labels = [
        f"{segment['range_start']} -> {segment['range_end']} | {segment.get('block_label') or 'Aucun bloc ACM'}"
        for segment in acm_segments
    ]
    for row in rows:
        sector_name = str(row.get("sector_name") or "")
        taeg_calculated = _to_decimal(row.get("taeg_calculated"))
        disbursement_amount = _to_decimal(row.get("disbursement_amount"))
        taeg_weighted_rate = _to_decimal(row.get("taeg_weighted_rate"))
        acm_rate = row.get("acm_rate")
        compared_value = taeg_weighted_rate
        expected_status = _sector_summary_status(
            taeg_weighted_rate=taeg_weighted_rate,
            acm_rate=acm_rate,
        )
        logger.info(
            "TAEG sector status diagnostic | period=%s | secteur=%s | blocs_acm=%s | taux_acm=%s | taeg_calcule=%s | montant_decaisse=%s | taeg_pondere=%s | valeur_comparee=%s | statut_obtenu=%s | statut_attendu=%s | cause=%s",
            period_label,
            sector_name,
            " ; ".join(segment_labels) if segment_labels else "Aucun bloc ACM",
            acm_rate,
            taeg_calculated,
            disbursement_amount,
            taeg_weighted_rate,
            compared_value,
            row.get("status"),
            expected_status,
            "TAEG pondéré compare directement au taux ACM affiché"
            if row.get("status") == expected_status
            else "Le statut diffère de la comparaison affichée",
        )
        if sector_name.strip().lower() == "agriculture":
            logger.info(
                "TAEG agriculture diagnostic | blocs_acm=%s | taux_acm=%s | taeg_calcule=%s | montant_decaisse=%s | taeg_pondere=%s | valeur_comparee=%s | statut_obtenu=%s | statut_attendu=%s",
                " ; ".join(segment_labels) if segment_labels else "Aucun bloc ACM",
                acm_rate,
                taeg_calculated,
                disbursement_amount,
                taeg_weighted_rate,
                compared_value,
                row.get("status"),
                expected_status,
            )


def _selection_filters(
    used_periods: list[dict],
    *,
    agency_id: str | None,
    agent_id: int | None,
    sector_id: int | None = None,
    segment: dict | None = None,
    applied_acm_version_expr=None,
    user: User | None = None,
) -> list:
    period_clauses = []
    range_start = segment.get("range_start") if segment else None
    range_end = segment.get("range_end") if segment else None
    for period in used_periods:
        month_start, month_end = _month_bounds(period["snapshot_date"])
        effective_start = max(month_start, range_start) if isinstance(range_start, date) else month_start
        effective_end = min(month_end, range_end) if isinstance(range_end, date) else month_end
        if effective_start > effective_end:
            continue
        period_clauses.append(
            (LoanRaw.import_batch_id == period["batch_id"])
            & (LoanRaw.disbursement_date >= effective_start)
            & (LoanRaw.disbursement_date <= effective_end)
        )

    filters = [or_(*period_clauses)] if period_clauses else [false()]
    if user is not None:
        scope = get_user_data_scope(user)
        regional_condition = region_scope_condition(Agency.name, scope.region)
        if regional_condition is not None:
            filters.append(regional_condition)
    selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
    if selected_agency_ids:
        filters.append(Agency.id.in_(selected_agency_ids))
    if agent_id is not None:
        filters.append(Agent.id == agent_id)
    if sector_id is not None:
        filters.append(ActivitySector.id == sector_id)
    if segment:
        if segment.get("version_id") is not None and applied_acm_version_expr is not None:
            filters.append(applied_acm_version_expr == segment["version_id"])
        elif segment.get("covered") is False and applied_acm_version_expr is not None:
            filters.append(applied_acm_version_expr.is_(None))
    return filters


def _segment_scope_label(segment: dict | None) -> str:
    if not segment:
        return "Toutes les sous-periodes ACM"
    return f"{segment['range_start'].strftime('%d/%m/%Y')} -> {segment['range_end'].strftime('%d/%m/%Y')}"


def _resolve_active_acm_segment(
    segments: list[dict],
    *,
    acm_block_id: int | None,
    period_start: date | None,
    period_end: date | None,
) -> dict | None:
    if not segments:
        return None
    for segment in segments:
        if (
            acm_block_id == segment.get("version_id")
            and period_start == segment.get("range_start")
            and period_end == segment.get("range_end")
        ):
            return segment
    return segments[0]


def _enrich_acm_segments(
    db: Session,
    *,
    used_periods: list[dict],
    segments: list[dict],
    agency_id: int | None,
    agent_id: int | None,
    user: User,
) -> list[dict]:
    if not segments:
        return []
    applied_acm = build_applied_acm_subqueries()
    version_expr = applied_acm["version_id"]
    enriched: list[dict] = []
    for segment in segments:
        filters = _selection_filters(
            used_periods,
            agency_id=agency_id,
            agent_id=agent_id,
            user=user,
            segment=segment,
            applied_acm_version_expr=version_expr,
        )
        stats = db.execute(
            select(
                func.count(LoanRaw.id).label("credits_count"),
                func.count(func.distinct(ActivitySector.id)).label("sectors_count"),
            )
            .select_from(LoanRaw)
            .join(Agency, Agency.name == LoanRaw.agency_name)
            .join(Agent, _agent_join_condition())
            .join(CategorySectorMapping, CategorySectorMapping.category_desc == LoanRaw.category_desc)
            .join(ActivitySector, ActivitySector.id == CategorySectorMapping.activity_sector_id)
            .where(*filters)
        ).mappings().one()
        enriched.append(
            {
                **segment,
                "credits_count": int(stats["credits_count"] or 0),
                "sectors_count": int(stats["sectors_count"] or 0),
                "coverage_status": "partial" if not segment.get("covered", True) else "complete",
            }
        )
    return enriched


def calculate_taeg_for_acm_block(
    db: Session,
    *,
    used_periods: list[dict],
    segment: dict | None,
    agency_id: int | None,
    agent_id: int | None,
    user: User,
) -> list[dict]:
    taeg_amount_expr = _taeg_amount_expr()
    weighted_expr = _weighted_average_expr(taeg_amount_expr)
    applied_acm = build_applied_acm_subqueries()
    sector_acm_case = applied_acm["acm_rate"]
    version_expr = applied_acm["version_id"]
    filters = _selection_filters(
        used_periods,
        agency_id=agency_id,
        agent_id=agent_id,
        user=user,
        segment=segment,
        applied_acm_version_expr=version_expr,
    )
    disbursement_amount_expr = func.coalesce(LoanRaw.disbursement_amount, Decimal("0"))
    covered_amount_expr = func.coalesce(
        func.sum(
            case(
                (sector_acm_case.is_not(None), disbursement_amount_expr),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    weighted_acm_numerator_expr = func.coalesce(
        func.sum(
            case(
                (sector_acm_case.is_not(None), sector_acm_case * disbursement_amount_expr),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    compliant_count_expr = func.sum(
        case(
            (
                and_(
                    sector_acm_case.is_not(None),
                    func.coalesce(LoanRaw.teg_rate, Decimal("0")) <= sector_acm_case,
                ),
                1,
            ),
            else_=0,
        )
    )
    non_compliant_count_expr = func.sum(
        case(
            (
                and_(
                    sector_acm_case.is_not(None),
                    func.coalesce(LoanRaw.teg_rate, Decimal("0")) > sector_acm_case,
                ),
                1,
            ),
            else_=0,
        )
    )
    uncovered_count_expr = func.sum(
        case(
            (sector_acm_case.is_(None), 1),
            else_=0,
        )
    )
    rows = list(
        db.execute(
            select(
                ActivitySector.id.label("sector_id"),
                ActivitySector.name.label("sector_name"),
                func.count(LoanRaw.id).label("credits_count"),
                func.coalesce(func.sum(LoanRaw.disbursement_amount), Decimal("0")).label("disbursement_amount"),
                func.coalesce(func.sum(taeg_amount_expr), Decimal("0")).label("taeg_calculated"),
                weighted_expr.label("taeg_weighted_rate"),
                covered_amount_expr.label("covered_disbursement_amount"),
                weighted_acm_numerator_expr.label("acm_weighted_numerator"),
                func.coalesce(compliant_count_expr, 0).label("compliant_credits_count"),
                func.coalesce(non_compliant_count_expr, 0).label("non_compliant_credits_count"),
                func.coalesce(uncovered_count_expr, 0).label("uncovered_credits_count"),
            )
            .select_from(LoanRaw)
            .join(Agency, Agency.name == LoanRaw.agency_name)
            .join(Agent, _agent_join_condition())
            .join(CategorySectorMapping, CategorySectorMapping.category_desc == LoanRaw.category_desc)
            .join(ActivitySector, ActivitySector.id == CategorySectorMapping.activity_sector_id)
            .where(*filters)
            .group_by(ActivitySector.id, ActivitySector.name)
            .order_by(ActivitySector.name.asc())
        ).mappings()
    )
    return _decorate_summary_rows(rows)


def _taeg_amount_expr():
    return func.coalesce(LoanRaw.teg_rate, Decimal("0")) * func.coalesce(LoanRaw.disbursement_amount, Decimal("0"))


def _parse_date_value(raw_value: Any) -> date | None:
    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, date):
        return raw_value
    return date.fromisoformat(str(raw_value))


def _apply_table_filter_expression(column_expr, filter_payload: dict[str, Any] | None, filter_type: str):
    if not filter_payload:
        return None
    mode = filter_payload.get("mode")
    selected = [str(item) for item in (filter_payload.get("selected") or [])]
    value = filter_payload.get("value")
    value_to = filter_payload.get("valueTo")

    if filter_type in {"enum", "boolean"} or mode == "in":
        if not selected:
            return None
        return func.cast(column_expr, String()).in_(selected)

    if filter_type == "text":
        if not value:
            return None
        normalized = f"%{str(value).strip().lower()}%"
        if mode == "not_contains":
            return ~func.lower(func.coalesce(column_expr, "")).like(normalized)
        if mode == "starts_with":
            return func.lower(func.coalesce(column_expr, "")).like(f"{str(value).strip().lower()}%")
        if mode == "ends_with":
            return func.lower(func.coalesce(column_expr, "")).like(f"%{str(value).strip().lower()}")
        if mode == "equals":
            return func.lower(func.coalesce(column_expr, "")) == str(value).strip().lower()
        if mode == "not_equals":
            return func.lower(func.coalesce(column_expr, "")) != str(value).strip().lower()
        return func.lower(func.coalesce(column_expr, "")).like(normalized)

    if filter_type == "number":
        clauses = []
        if mode == "between":
            if value not in (None, ""):
                clauses.append(column_expr >= Decimal(str(value)))
            if value_to not in (None, ""):
                clauses.append(column_expr <= Decimal(str(value_to)))
            return and_(*clauses) if clauses else None
        if value in (None, ""):
            return None
        numeric_value = Decimal(str(value))
        if mode == "neq":
            return column_expr != numeric_value
        if mode == "gt":
            return column_expr > numeric_value
        if mode == "gte":
            return column_expr >= numeric_value
        if mode == "lt":
            return column_expr < numeric_value
        if mode == "lte":
            return column_expr <= numeric_value
        return column_expr == numeric_value
    if filter_type == "date":
        today = date.today()
        if mode == "today":
            return column_expr == today
        if mode == "yesterday":
            return column_expr == today - timedelta(days=1)
        if mode == "this_month":
            month_start = date(today.year, today.month, 1)
            month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
            return and_(column_expr >= month_start, column_expr <= month_end)
        if mode == "previous_month":
            if today.month == 1:
                target_year, target_month = today.year - 1, 12
            else:
                target_year, target_month = today.year, today.month - 1
            month_start = date(target_year, target_month, 1)
            month_end = date(target_year, target_month, monthrange(target_year, target_month)[1])
            return and_(column_expr >= month_start, column_expr <= month_end)
        if mode == "year":
            if value in (None, ""):
                return None
            year = int(value)
            return and_(column_expr >= date(year, 1, 1), column_expr <= date(year, 12, 31))
        if mode == "before":
            before_date = _parse_date_value(value)
            return None if before_date is None else column_expr < before_date
        if mode == "after":
            after_date = _parse_date_value(value)
            return None if after_date is None else column_expr > after_date
        from_date = _parse_date_value(value)
        to_date = _parse_date_value(value_to)
        clauses = []
        if from_date is not None:
            clauses.append(column_expr >= from_date)
        if to_date is not None:
            clauses.append(column_expr <= to_date)
        return and_(*clauses) if clauses else None
    return None


def _filter_taeg_summary_rows(rows: list[dict], filters: dict[str, Any] | None) -> list[dict]:
    if not filters:
        return rows

    def match_text(raw_value, payload):
        mode = payload.get("mode")
        selected = payload.get("selected") or []
        raw = str(raw_value or "").strip().lower()
        if mode == "in":
            return not selected or raw in [str(item).strip().lower() for item in selected]
        expected = str(payload.get("value") or "").strip().lower()
        if not expected:
            return True
        if mode == "not_contains":
            return expected not in raw
        if mode == "starts_with":
            return raw.startswith(expected)
        if mode == "ends_with":
            return raw.endswith(expected)
        if mode == "equals":
            return raw == expected
        if mode == "not_equals":
            return raw != expected
        return expected in raw

    def match_number(raw_value, payload):
        mode = payload.get("mode")
        selected = payload.get("selected") or []
        numeric_value = _to_decimal(raw_value)
        if mode == "in":
            if not selected:
                return True
            return str(raw_value) in {str(item) for item in selected}
        first = payload.get("value")
        second = payload.get("valueTo")
        if mode == "between":
            if first not in (None, "") and numeric_value < _to_decimal(first):
                return False
            if second not in (None, "") and numeric_value > _to_decimal(second):
                return False
            return first not in (None, "") or second not in (None, "")
        if first in (None, ""):
            return True
        expected = _to_decimal(first)
        if mode == "neq":
            return numeric_value != expected
        if mode == "gt":
            return numeric_value > expected
        if mode == "gte":
            return numeric_value >= expected
        if mode == "lt":
            return numeric_value < expected
        if mode == "lte":
            return numeric_value <= expected
        return numeric_value == expected

    filtered = []
    for row in rows:
        keep = True
        for key, payload in filters.items():
            if not payload:
                continue
            if key == "sector_name":
                keep = match_text(row.get("sector_name"), payload)
            elif key in {"credits_count", "disbursement_amount", "taeg_calculated", "taeg_weighted_rate", "acm_rate"}:
                keep = match_number(row.get(key), payload)
            elif key == "status":
                selected = {str(item).strip().lower() for item in (payload.get("selected") or [])}
                keep = not selected or str(row.get("status") or "").strip().lower() in selected
            if not keep:
                break
        if keep:
            filtered.append(row)
    return filtered


def _sort_taeg_summary_rows(rows: list[dict], sort_key: str | None, sort_direction: str | None) -> list[dict]:
    if sort_key not in {"credits_count", "disbursement_amount", "taeg_calculated", "taeg_weighted_rate", "acm_rate"}:
        return rows
    if sort_direction not in {"asc", "desc"}:
        return rows
    reverse = sort_direction == "desc"
    return sorted(rows, key=lambda item: _to_decimal(item.get(sort_key)), reverse=reverse)


def _weighted_average_expr(value_expr):
    total_disbursement = func.coalesce(func.sum(LoanRaw.disbursement_amount), Decimal("0"))
    return case(
        (total_disbursement == 0, Decimal("0")),
        else_=func.coalesce(func.sum(value_expr), Decimal("0")) / total_disbursement,
    )


def _taeg_base_from():
    return (
        select(
            LoanRaw.id.label("loan_id"),
            LoanRaw.disbursement_amount.label("disbursement_amount"),
            LoanRaw.teg_rate.label("teg_rate"),
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .join(CategorySectorMapping, CategorySectorMapping.category_desc == LoanRaw.category_desc)
        .join(ActivitySector, ActivitySector.id == CategorySectorMapping.activity_sector_id)
    )


def _log_current_period_debug(
    db: Session,
    *,
    selection: dict,
    filters: list,
    rows: list[dict],
) -> None:
    if not selection.get("is_current"):
        return

    period = selection["used_periods"][0]
    month_start, month_end = _month_bounds(period["snapshot_date"])
    batch_filters = [LoanRaw.import_batch_id == period["batch_id"]]
    rows_before_filter = db.scalar(select(func.count(LoanRaw.id)).where(*batch_filters)) or 0
    rows_after_date_filter = db.scalar(
        select(func.count(LoanRaw.id)).where(
            *batch_filters,
            LoanRaw.disbursement_date >= month_start,
            LoanRaw.disbursement_date <= month_end,
        )
    ) or 0

    scoped_query = _taeg_base_from().where(*filters).subquery()
    scoped_rows = db.scalar(select(func.count(scoped_query.c.loan_id)).select_from(scoped_query)) or 0
    scoped_disbursement_sum = db.scalar(
        select(func.coalesce(func.sum(scoped_query.c.disbursement_amount), Decimal("0"))).select_from(scoped_query)
    ) or Decimal("0")
    sample_teg_rate = db.scalar(
        select(LoanRaw.teg_rate)
        .where(
            *batch_filters,
            LoanRaw.disbursement_date >= month_start,
            LoanRaw.disbursement_date <= month_end,
        )
        .order_by(LoanRaw.id.asc())
        .limit(1)
    )
    total_taeg_calculated = sum(Decimal(row["taeg_calculated"] or 0) for row in rows)
    total_disbursement = sum(Decimal(row["disbursement_amount"] or 0) for row in rows)
    total_taeg_weighted = total_taeg_calculated / total_disbursement if total_disbursement else Decimal("0")

    logger.info(
        "TAEG current-state debug | import_batch_id=%s | dateeod=%s | month_start=%s | month_end=%s | rows_before_filter=%s | rows_after_date_filter=%s | rows_after_full_scope=%s | disbursement_sum=%s | sample_teg_rate=%s | taeg_calculated=%s | taeg_weighted=%s",
        period["batch_id"],
        period["snapshot_date"],
        month_start,
        month_end,
        rows_before_filter,
        rows_after_date_filter,
        scoped_rows,
        scoped_disbursement_sum,
        sample_teg_rate,
        total_taeg_calculated,
        total_taeg_weighted,
    )


def taeg_dashboard(
    db: Session,
    *,
    user: User,
    period_key: str | None,
    period_keys: str | None,
    agency_id: int | None,
    agent_id: int | None,
    acm_block_id: int | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict:
    _validate_taeg_user(user)
    selection = resolve_taeg_selection(db, period_key, period_keys)
    used_periods = selection["used_periods"]
    validate_acm_blocks_for_periods(db, used_periods)
    acm_segments, acm_coverage_message = build_acm_coverage_segments_for_periods(db, used_periods)
    acm_segments = _enrich_acm_segments(
        db,
        used_periods=used_periods,
        segments=acm_segments,
        agency_id=agency_id,
        agent_id=agent_id,
        user=user,
    )
    active_segment = _resolve_active_acm_segment(
        acm_segments,
        acm_block_id=acm_block_id,
        period_start=period_start,
        period_end=period_end,
    )
    rows = calculate_taeg_for_acm_block(
        db,
        used_periods=used_periods,
        segment=active_segment,
        agency_id=agency_id,
        agent_id=agent_id,
        user=user,
    )

    active_filters = _selection_filters(
        used_periods,
        agency_id=agency_id,
        agent_id=agent_id,
        user=user,
        segment=active_segment,
    )
    _log_current_period_debug(db, selection=selection, filters=active_filters, rows=rows)
    _log_sector_status_diagnostics(selection=selection, rows=rows, acm_segments=acm_segments)
    return {
        "period": selection["period"],
        "used_periods": used_periods,
        "acm_segments": acm_segments,
        "active_acm_segment": active_segment,
        "acm_coverage_message": acm_coverage_message,
        "rows": rows,
    }


def taeg_credit_details(
    db: Session,
    *,
    user: User,
    period_key: str | None,
    period_keys: str | None,
    agency_id: int | None,
    agent_id: int | None,
    sector_id: int | None,
    acm_block_id: int | None,
    period_start: date | None,
    period_end: date | None,
    column_filters: dict[str, Any] | None,
    sort_key: str | None,
    sort_direction: str | None,
    limit: int,
    offset: int,
) -> tuple[dict, list[dict], int]:
    _validate_taeg_user(user)
    selection = resolve_taeg_selection(db, period_key, period_keys)
    validate_acm_blocks_for_periods(db, selection["used_periods"])
    acm_segments, _acm_coverage_message = build_acm_coverage_segments_for_periods(db, selection["used_periods"])
    acm_segments = _enrich_acm_segments(
        db,
        used_periods=selection["used_periods"],
        segments=acm_segments,
        agency_id=agency_id,
        agent_id=agent_id,
        user=user,
    )
    active_segment = _resolve_active_acm_segment(
        acm_segments,
        acm_block_id=acm_block_id,
        period_start=period_start,
        period_end=period_end,
    )
    applied_acm = build_applied_acm_subqueries()
    acm_block_version_id_expr = applied_acm["version_id"]
    filters = _selection_filters(
        selection["used_periods"],
        agency_id=agency_id,
        agent_id=agent_id,
        sector_id=sector_id,
        segment=active_segment,
        applied_acm_version_expr=acm_block_version_id_expr,
        user=user,
    )
    taeg_amount_expr = _taeg_amount_expr()
    sector_acm_case = applied_acm["acm_rate"]
    acm_block_start_expr = applied_acm["version_start_date"]
    acm_block_end_expr = applied_acm["version_end_date"]
    detail_filters = []
    filter_specs = {
        "contract_no": ("text", LoanRaw.contract_no),
        "sector_name": ("text", ActivitySector.name),
        "disbursement_date": ("date", LoanRaw.disbursement_date),
        "disbursement_amount": ("number", func.coalesce(LoanRaw.disbursement_amount, Decimal("0"))),
        "teg_rate": ("number", func.coalesce(LoanRaw.teg_rate, Decimal("0"))),
        "taeg_calculated": ("number", taeg_amount_expr),
        "taeg_weighted_rate": ("number", func.coalesce(LoanRaw.teg_rate, Decimal("0"))),
        "acm_rate": ("number", sector_acm_case),
        "status": (
            "enum",
            case(
                (
                    sector_acm_case.is_(None),
                    literal(STATUS_NON_COUVERT),
                ),
                (
                    func.coalesce(LoanRaw.teg_rate, Decimal("0")) > sector_acm_case,
                    literal(STATUS_NON_CONFORME),
                ),
                else_=literal(STATUS_CONFORME),
            ),
        ),
    }
    for key, payload in (column_filters or {}).items():
        spec = filter_specs.get(key)
        if not spec:
            continue
        expression = _apply_table_filter_expression(spec[1], payload, spec[0])
        if expression is not None:
            detail_filters.append(expression)
    base_query = (
        select(
            LoanRaw.contract_no.label("contract_no"),
            ActivitySector.id.label("sector_id"),
            ActivitySector.name.label("sector_name"),
            LoanRaw.disbursement_date.label("disbursement_date"),
            LoanRaw.disbursement_amount.label("disbursement_amount"),
            func.coalesce(LoanRaw.teg_rate, Decimal("0")).label("teg_rate"),
            taeg_amount_expr.label("taeg_calculated"),
            func.coalesce(LoanRaw.teg_rate, Decimal("0")).label("taeg_weighted_rate"),
            sector_acm_case.label("acm_rate"),
            acm_block_version_id_expr.label("acm_block_version_id"),
            acm_block_start_expr.label("acm_block_start_date"),
            acm_block_end_expr.label("acm_block_end_date"),
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .join(CategorySectorMapping, CategorySectorMapping.category_desc == LoanRaw.category_desc)
        .join(ActivitySector, ActivitySector.id == CategorySectorMapping.activity_sector_id)
        .where(*filters, *detail_filters)
    )
    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    sort_expr_factory = TAEG_DETAIL_SORT_COLUMNS.get(sort_key or "")
    sort_expr = sort_expr_factory(sector_acm_case, taeg_amount_expr) if sort_expr_factory else None
    ordered_query = base_query.order_by(
        sort_expr.desc() if sort_expr is not None and sort_direction == "desc" else sort_expr.asc() if sort_expr is not None and sort_direction == "asc" else ActivitySector.name.asc(),
        LoanRaw.contract_no.asc(),
    )
    rows = list(
        db.execute(
            ordered_query.limit(limit).offset(offset)
        ).mappings()
    )
    normalized_rows = []
    for row in rows:
        raw_acm_rate = row.get("acm_rate")
        acm_rate = _to_decimal(raw_acm_rate) if raw_acm_rate is not None else None
        teg_rate = _to_decimal(row["teg_rate"])
        acm_block_start_date = row.get("acm_block_start_date")
        acm_block_end_date = row.get("acm_block_end_date")
        if acm_block_start_date:
            block_end_label = acm_block_end_date.strftime("%d/%m/%Y") if isinstance(acm_block_end_date, date) else "Jusqu'a modification"
            acm_block_label = f"{acm_block_start_date.strftime('%d/%m/%Y')} -> {block_end_label}"
        else:
            acm_block_label = None
        status = (
            STATUS_NON_COUVERT
            if acm_rate is None
            else STATUS_NON_CONFORME
            if teg_rate > acm_rate
            else STATUS_CONFORME
        )
        normalized_rows.append(
            {
                **row,
                "acm_rate": acm_rate,
                "acm_block_label": acm_block_label,
                "status": status,
            }
        )
    return selection["period"], normalized_rows, total


def list_category_sector_mappings(db: Session) -> list[dict]:
    distinct_categories = (
        select(
            LoanRaw.category_desc.label("category_desc"),
            func.count(LoanRaw.id).label("occurrence_count"),
        )
        .where(LoanRaw.category_desc.is_not(None), LoanRaw.category_desc != "")
        .group_by(LoanRaw.category_desc)
        .subquery()
    )
    rows = db.execute(
        select(
            CategorySectorMapping.id.label("id"),
            distinct_categories.c.category_desc,
            distinct_categories.c.occurrence_count,
            CategorySectorMapping.activity_sector_id.label("activity_sector_id"),
            ActivitySector.name.label("activity_sector_name"),
            CategorySectorMapping.updated_at.label("updated_at"),
        )
        .select_from(distinct_categories)
        .outerjoin(
            CategorySectorMapping,
            CategorySectorMapping.category_desc == distinct_categories.c.category_desc,
        )
        .outerjoin(ActivitySector, ActivitySector.id == CategorySectorMapping.activity_sector_id)
        .order_by(distinct_categories.c.category_desc.asc())
    ).mappings()
    return list(rows)
