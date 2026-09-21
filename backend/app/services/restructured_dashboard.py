from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from time import perf_counter

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import String, and_, case, cast, delete, false, func, literal, or_, select, update
from sqlalchemy.orm import Session

from app.api.v1.metrics import (
    _data_scope_for_period,
    _effective_date_bounds,
    _loan_filters,
    _parse_snapshot_batch_ids,
    _scoped_snapshot_batches,
    calculate_potentially_radiable_threshold,
)
from app.models.entities import Agency, Agent, ImportBatch, LoanRaw, RestructuredAnalysisResult, RestructuredContract, RestructuredImportLog, User
from app.models.enums import ImportBatchType, UserRole
from app.schemas.common import Page
from app.schemas.domain import MetricsChartPoint, MetricsChartRead
from app.schemas.restructured import (
    RestructuredChartRead,
    RestructuredChartSliceRead,
    RestructuredContractDetailRead,
    RestructuredDashboardKpiRead,
    RestructuredMissingMcrContractDeleteResult,
    RestructuredMissingMcrContractRead,
)
from app.services.agent_identity import normalized_agent_name_expression
from app.services.data_scope import get_user_data_scope
from app.services.selection import normalize_agency_ids
from app.services.committee_access import normalize_committee_historical_request
from app.services.restructured import (
    CLOSURE_STATUS_ASSUMED_CLOSED,
    CONSOLIDATED_FAMILY,
    RESTRUCTURED_FAMILY,
)

logger = logging.getLogger(__name__)

HEADER_BG = PatternFill("solid", fgColor="1E3A8A")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FILL = PatternFill("solid", fgColor="0B1220")
TITLE_FONT = Font(color="FFFFFF", bold=True, size=14)
ALT_ROW_FILL = PatternFill("solid", fgColor="F8FAFC")
SUCCESS_FILL = PatternFill("solid", fgColor="DCFCE7")
SUCCESS_FONT = Font(color="166534", bold=True)
WARNING_FILL = PatternFill("solid", fgColor="FEF3C7")
WARNING_FONT = Font(color="92400E", bold=True)
DANGER_FILL = PatternFill("solid", fgColor="FEE2E2")
DANGER_FONT = Font(color="991B1B", bold=True)
NEUTRAL_FILL = PatternFill("solid", fgColor="E5E7EB")
NEUTRAL_FONT = Font(color="374151", bold=True)
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

def _agent_join_condition():
    return (
        (normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name))
        & (Agent.agency_id == Agency.id)
    )


def _family_filter_label(family: str) -> str:
    return CONSOLIDATED_FAMILY if family == CONSOLIDATED_FAMILY else RESTRUCTURED_FAMILY


def _family_param_value(family: str | None) -> str:
    if str(family or "").lower() == "all":
        return "all"
    if str(family or "").lower() == "consolidated":
        return "consolidated"
    return "restructured"


def _family_display_label(family: str) -> str:
    return "Credit consolide" if family == CONSOLIDATED_FAMILY else "Credit restructure"


def _loan_contract_key_expr(db: Session):
    raw = func.upper(func.replace(func.trim(cast(LoanRaw.contract_no, String)), " ", ""))
    if db.bind and db.bind.dialect.name == "postgresql":
        return func.regexp_replace(raw, r"\.0+$", "")
    return case(
        (raw.like("%.0"), func.substr(raw, 1, func.length(raw) - 2)),
        else_=raw,
    )


def _safe_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _bucket_for_count(count: int | None) -> str:
    safe_count = int(count or 0)
    if safe_count <= 0:
        return "0"
    if safe_count <= 2:
        return "1-2"
    if safe_count == 3:
        return "3"
    return "4+"


def _cohort_label(days_overdue: int | None) -> str | None:
    value = int(days_overdue or 0)
    if value <= 0:
        return None
    if value <= 30:
        return "Cohorte 1-30"
    if value <= 60:
        return "Cohorte 31-60"
    if value <= 90:
        return "Cohorte 61-90"
    if value <= 120:
        return "Cohorte 91-120"
    if value < 365:
        return "PAR120"
    return "PAR120"


def _par_label(days_overdue: int | None) -> str | None:
    value = int(days_overdue or 0)
    if value <= 0:
        return None
    if value > 120 and value < 365:
        return "PAR120"
    if value > 30 and value < 365:
        return "PAR30"
    return "PAR0"


def _log_kpi_inconsistencies(
    *,
    family: str,
    effective_snapshot_date: date | None,
    effective_import_batch_id: int | None,
    **kpis: tuple[Decimal, int, int],
) -> None:
    """Alerte si une carte a un montant > 0 sans dossier/client associe."""
    for label, (amount, dossier_count, client_count) in kpis.items():
        if amount > 0 and (dossier_count <= 0 or client_count <= 0):
            logger.warning(
                "KPI_INCONSISTENCY family=%s snapshot_date=%s import_batch_id=%s "
                "kpi=%s amount=%s dossier_count=%s client_count=%s",
                family,
                effective_snapshot_date,
                effective_import_batch_id,
                label,
                amount,
                dossier_count,
                client_count,
            )


def _summary_from_totals(*, family: str, supposed_closed: int, paid_last_four_yes: int, last_recalculated_at, last_schedule_import_at, credits_count: int, disbursement_count: int, disbursements_count: int, disbursement_volume: Decimal, nb_clients: int, outstanding: Decimal, healthy_outstanding: Decimal, healthy_count: int = 0, healthy_client_count: int = 0, par_0: Decimal, par_0_count: int = 0, par_0_client_count: int = 0, par_1_30: Decimal, par_1_30_count: int = 0, par_1_30_client_count: int = 0, par_1_15: Decimal = Decimal("0"), par_1_15_count: int = 0, par_1_15_client_count: int = 0, par_16_30: Decimal = Decimal("0"), par_16_30_count: int = 0, par_16_30_client_count: int = 0, par_31_60: Decimal, par_31_60_count: int = 0, par_31_60_client_count: int = 0, par_61_90: Decimal, par_61_90_count: int = 0, par_61_90_client_count: int = 0, par_91_120: Decimal, par_91_120_count: int = 0, par_91_120_client_count: int = 0, par_120: Decimal, par_120_count: int = 0, par_120_client_count: int = 0, par_30: Decimal, par_30_count: int = 0, par_30_client_count: int = 0, potentially_radiable_volume: Decimal = Decimal("0"), potentially_radiable_rate: Decimal = Decimal("0"), requested_date_to: date | None = None, effective_snapshot_date: date | None = None, effective_import_batch_id: int | None = None, potential_radiable_reference_date: date | None = None, potential_radiable_threshold: int | None = None, potential_radiable_client_count: int = 0, potential_radiable_loan_count: int = 0) -> RestructuredDashboardKpiRead:
    return RestructuredDashboardKpiRead(
        family=family,
        supposed_closed=supposed_closed,
        paid_last_four_yes=paid_last_four_yes,
        last_recalculated_at=last_recalculated_at,
        last_schedule_import_at=last_schedule_import_at,
         credits_count=credits_count,
         disbursement_count=disbursement_count,
         disbursements_count=disbursements_count,
         disbursement_volume=disbursement_volume,
         nb_clients=nb_clients,
         outstanding=outstanding,
         healthy_outstanding=healthy_outstanding,
         healthy_count=healthy_count,
         healthy_client_count=healthy_client_count,
         par_0=par_0,
         par_0_count=par_0_count,
         par_0_client_count=par_0_client_count,
         par_1_30=par_1_30,
         par_1_30_count=par_1_30_count,
         par_1_30_client_count=par_1_30_client_count,
         par_1_15=par_1_15,
         par_1_15_count=par_1_15_count,
         par_1_15_client_count=par_1_15_client_count,
         par_16_30=par_16_30,
         par_16_30_count=par_16_30_count,
         par_16_30_client_count=par_16_30_client_count,
         par_31_60=par_31_60,
         par_31_60_count=par_31_60_count,
         par_31_60_client_count=par_31_60_client_count,
         par_61_90=par_61_90,
         par_61_90_count=par_61_90_count,
         par_61_90_client_count=par_61_90_client_count,
         par_91_120=par_91_120,
         par_91_120_count=par_91_120_count,
         par_91_120_client_count=par_91_120_client_count,
         par_120=par_120,
         par_120_count=par_120_count,
         par_120_client_count=par_120_client_count,
         par_30=par_30,
         par_30_count=par_30_count,
         par_30_client_count=par_30_client_count,
        potentially_radiable_volume=potentially_radiable_volume,
        potentially_radiable_rate=potentially_radiable_rate,
        requested_date_to=requested_date_to,
        effective_snapshot_date=effective_snapshot_date,
        effective_import_batch_id=effective_import_batch_id,
        potential_radiable_reference_date=potential_radiable_reference_date,
        potential_radiable_threshold=potential_radiable_threshold,
        potential_radiable_client_count=potential_radiable_client_count,
        potential_radiable_loan_count=potential_radiable_loan_count,
    )


def _resolved_scope_filter(
    db: Session,
    user: User,
    *,
    agency_id: int | None,
    agent_id: int | None,
    date_from: date | None,
    date_to: date | None,
    snapshot_batch_ids: str | None,
):
    if snapshot_batch_ids:
        normalize_committee_historical_request(
            db,
            user,
            date_from,
            date_to,
            snapshot_batch_ids=snapshot_batch_ids,
        )
    snapshot_ids = _parse_snapshot_batch_ids(snapshot_batch_ids)
    if snapshot_ids:
        batches = _scoped_snapshot_batches(
            db=db,
            user=user,
            agency_id=agency_id,
            agent_id=agent_id,
            snapshot_batch_ids=snapshot_ids,
        )
        allowed_ids = [batch.id for batch in batches]
        if not allowed_ids:
            return None, None, None, None
        effective_snapshot_date = max((batch.snapshot_date for batch in batches if batch.snapshot_date), default=None)
        effective_batch = max(
            (batch for batch in batches if batch.snapshot_date),
            key=lambda batch: (batch.snapshot_date, batch.imported_at, batch.id),
            default=None,
        )
        return LoanRaw.import_batch_id.in_(allowed_ids), batches, effective_snapshot_date, effective_batch.id if effective_batch else None
    effective_snapshot_date, scope_filter, selected_batch = _data_scope_for_period(db, date_from, date_to, user=user)
    if scope_filter is None:
        return None, None, effective_snapshot_date, selected_batch.id if selected_batch else None
    return scope_filter, ([selected_batch] if selected_batch is not None else []), effective_snapshot_date, selected_batch.id if selected_batch else None


def _latest_loans_subquery(
    db: Session,
    user: User,
    *,
    agency_id: int | None,
    agent_id: int | None,
    date_from: date | None,
    date_to: date | None,
    snapshot_batch_ids: str | None,
    include_snapshot_date: bool = False,
):
    scope_filter, batches, effective_snapshot_date, effective_import_batch_id = _resolved_scope_filter(
        db,
        user,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
    )
    if scope_filter is None:
        return (None, effective_snapshot_date, effective_import_batch_id) if include_snapshot_date else None

    effective_date_from, effective_date_to = _effective_date_bounds(date_from, date_to)
    filters = _loan_filters(
        db=db,
        user=user,
        scope_filter=scope_filter,
        agency_id=agency_id,
        agent_id=agent_id,
    )
    if effective_date_from:
        filters.append(LoanRaw.disbursement_date >= effective_date_from)
    if effective_date_to:
        filters.append(LoanRaw.disbursement_date <= effective_date_to)

    contract_key = _loan_contract_key_expr(db).label("contract_key")
    encours = (
        func.coalesce(LoanRaw.principal_outstanding, 0)
        + func.coalesce(LoanRaw.principal_due, 0)
    ).label("encours")
    rn = func.row_number().over(
        partition_by=contract_key,
        order_by=[
            LoanRaw.snapshot_date.desc(),
            LoanRaw.import_batch_id.desc().nullslast(),
            LoanRaw.id.desc(),
        ],
    ).label("rn")
    base = (
        select(
            contract_key,
            LoanRaw.contract_no.label("raw_contract_no"),
            LoanRaw.client_name,
            LoanRaw.client_first_name,
            LoanRaw.client_id,
            LoanRaw.agency_name,
            LoanRaw.agent_name,
            LoanRaw.category_desc,
            LoanRaw.disbursement_amount,
            LoanRaw.principal_outstanding,
            LoanRaw.principal_due,
            LoanRaw.total_scheduled_amount,
            encours,
            LoanRaw.days_overdue,
            LoanRaw.total_due,
            LoanRaw.disbursement_date,
            LoanRaw.snapshot_date.label("dateeod"),
            rn,
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .where(*filters)
        .subquery()
    )
    result = (
        select(*[base.c[column] for column in base.c.keys()])
        .where(base.c.rn == 1)
        .subquery()
    )
    return (result, effective_snapshot_date, effective_import_batch_id) if include_snapshot_date else result


def _base_contract_rows_subquery(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None,
    agent_id: int | None,
    date_from: date | None,
    date_to: date | None,
    snapshot_batch_ids: str | None,
    include_snapshot_date: bool = False,
):
    family_value = _family_filter_label(family)
    latest_loans_result = _latest_loans_subquery(
        db,
        user,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        include_snapshot_date=include_snapshot_date,
    )
    effective_snapshot_date = None
    effective_import_batch_id = None
    if include_snapshot_date:
        latest_loans, effective_snapshot_date, effective_import_batch_id = latest_loans_result
    else:
        latest_loans = latest_loans_result
    if latest_loans is None:
        return (None, effective_snapshot_date, effective_import_batch_id) if include_snapshot_date else None

    scope = get_user_data_scope(user)
    require_mcr_match = bool(
        agency_id
        or agent_id
        or scope.role in {UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD}
    )
    healthy_outstanding = case(
        (func.coalesce(latest_loans.c.days_overdue, 0) == 0, func.coalesce(latest_loans.c.encours, 0)),
        else_=literal(0),
    ).label("healthy_outstanding")

    base = (
        select(
            RestructuredContract.contract_no,
            RestructuredContract.credit_family,
            RestructuredContract.delay_date,
            RestructuredContract.total_due.label("contract_total_due"),
            RestructuredContract.loan_duration,
            latest_loans.c.client_name,
            latest_loans.c.client_first_name,
            latest_loans.c.client_id,
            latest_loans.c.agency_name,
            latest_loans.c.agent_name,
            latest_loans.c.category_desc,
            latest_loans.c.disbursement_amount,
            latest_loans.c.principal_outstanding,
            latest_loans.c.principal_due,
            latest_loans.c.total_scheduled_amount,
            latest_loans.c.encours,
            healthy_outstanding,
            latest_loans.c.days_overdue,
            latest_loans.c.total_due.label("mcr_total_due"),
            latest_loans.c.disbursement_date,
            latest_loans.c.dateeod,
            RestructuredAnalysisResult.schedule_status,
            RestructuredAnalysisResult.consecutive_paid_count,
            RestructuredAnalysisResult.max_series_installments,
            RestructuredAnalysisResult.max_series_dates,
            RestructuredAnalysisResult.paid_installments_after_delay,
            RestructuredAnalysisResult.anomaly_detected,
            RestructuredAnalysisResult.anomaly_detail,
            RestructuredAnalysisResult.paid_last_four_status,
            RestructuredAnalysisResult.last_paid_installment_no,
            RestructuredAnalysisResult.last_paid_due_date,
            RestructuredAnalysisResult.closure_status,
            RestructuredAnalysisResult.last_calculated_at,
        )
        .select_from(RestructuredContract)
        .outerjoin(
            latest_loans,
            latest_loans.c.contract_key == RestructuredContract.normalized_contract_no,
        )
        .outerjoin(
            RestructuredAnalysisResult,
            RestructuredAnalysisResult.contract_no == RestructuredContract.contract_no,
        )
        .where(RestructuredContract.credit_family == family_value)
    )
    if require_mcr_match:
        base = base.where(latest_loans.c.contract_key.is_not(None))
    result = base.subquery()
    return (result, effective_snapshot_date, effective_import_batch_id) if include_snapshot_date else result


def get_restructured_dashboard_kpis(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
) -> RestructuredDashboardKpiRead:
    base, effective_snapshot_date, effective_import_batch_id = _base_contract_rows_subquery(
        db,
        user,
        family=family,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        include_snapshot_date=True,
    )
    if base is None:
        return _summary_from_totals(
            family=family,
            supposed_closed=0,
            paid_last_four_yes=0,
            last_recalculated_at=None,
            last_schedule_import_at=None,
            credits_count=0,
            disbursement_count=0,
            disbursements_count=0,
            disbursement_volume=Decimal("0"),
            nb_clients=0,
            outstanding=Decimal("0"),
            healthy_outstanding=Decimal("0"),
            healthy_count=0,
            healthy_client_count=0,
            par_0=Decimal("0"),
            par_0_count=0,
            par_0_client_count=0,
            par_1_15=Decimal("0"),
            par_1_15_count=0,
            par_1_15_client_count=0,
            par_16_30=Decimal("0"),
            par_16_30_count=0,
            par_16_30_client_count=0,
            par_1_30=Decimal("0"),
            par_1_30_count=0,
            par_1_30_client_count=0,
            par_31_60=Decimal("0"),
            par_31_60_count=0,
            par_31_60_client_count=0,
            par_61_90=Decimal("0"),
            par_61_90_count=0,
            par_61_90_client_count=0,
            par_91_120=Decimal("0"),
            par_91_120_count=0,
            par_91_120_client_count=0,
            par_120=Decimal("0"),
            par_120_count=0,
            par_120_client_count=0,
            par_30=Decimal("0"),
            par_30_count=0,
            par_30_client_count=0,
            potentially_radiable_volume=Decimal("0"),
            potentially_radiable_rate=Decimal("0"),
        )

    reference_date = effective_snapshot_date
    threshold = calculate_potentially_radiable_threshold(reference_date)
    client_radiable_ids = (
        select(base.c.client_id)
        .where(
            base.c.client_id.is_not(None),
            base.c.days_overdue.is_not(None),
            base.c.days_overdue >= threshold,
        )
        .group_by(base.c.client_id)
        .subquery()
    )
    client_radiable_condition = base.c.client_id.in_(select(client_radiable_ids.c.client_id))

    # SELECT uses explicit labels so the mapping is decoupled from positional indices.
    # The dataset is the same `base` subquery (RestructuredContract LEFT JOIN latest loans MCR).
    # For each KPI (amount, contract count, distinct client count) the WHERE-condition
    # (days_overdue range) is applied via the same CASE expression so that amount /
    # dossier_count / client_count always describe the *same* set of contracts.
    row = db.execute(
        select(
            func.coalesce(func.sum(case((base.c.closure_status == CLOSURE_STATUS_ASSUMED_CLOSED, 1), else_=0)), 0).label("supposed_closed"),
            func.coalesce(func.sum(case((base.c.paid_last_four_status == "Oui", 1), else_=0)), 0).label("paid_last_four_yes"),
            func.max(base.c.last_calculated_at).label("last_recalculated_at"),
            func.coalesce(func.sum(case((base.c.encours.is_not(None), 1), else_=0)), 0).label("credits_count"),
            func.coalesce(func.sum(case((base.c.disbursement_amount.is_not(None), 1), else_=0)), 0).label("disbursement_count"),
            func.count(func.distinct(case((base.c.client_id.is_not(None), base.c.client_id), else_=None))).label("nb_clients"),
            func.coalesce(func.sum(func.coalesce(base.c.disbursement_amount, 0)), 0).label("disbursement_volume"),
            func.coalesce(func.sum(func.coalesce(base.c.encours, 0)), 0).label("outstanding"),
            func.coalesce(func.sum(func.coalesce(base.c.healthy_outstanding, 0)), 0).label("healthy_outstanding"),
            func.count(func.distinct(case((func.coalesce(base.c.days_overdue, 0) == 0, base.c.contract_no), else_=None))).label("healthy_count"),
            func.count(func.distinct(case((func.coalesce(base.c.days_overdue, 0) == 0, base.c.client_id), else_=None))).label("healthy_client_count"),
            func.coalesce(func.sum(case((func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_0"),
            func.count(func.distinct(case((func.coalesce(base.c.days_overdue, 0) > 0, base.c.contract_no), else_=None))).label("par_0_count"),
            func.count(func.distinct(case((func.coalesce(base.c.days_overdue, 0) > 0, base.c.client_id), else_=None))).label("par_0_client_count"),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.days_overdue, 0) <= 30), func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_1_30"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.days_overdue, 0) <= 30), base.c.contract_no), else_=None))).label("par_1_30_count"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.days_overdue, 0) <= 30), base.c.client_id), else_=None))).label("par_1_30_client_count"),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.days_overdue, 0) <= 15), func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_1_15"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.days_overdue, 0) <= 15), base.c.contract_no), else_=None))).label("par_1_15_count"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.days_overdue, 0) <= 15), base.c.client_id), else_=None))).label("par_1_15_client_count"),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) >= 16, func.coalesce(base.c.days_overdue, 0) <= 30), func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_16_30"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) >= 16, func.coalesce(base.c.days_overdue, 0) <= 30), base.c.contract_no), else_=None))).label("par_16_30_count"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) >= 16, func.coalesce(base.c.days_overdue, 0) <= 30), base.c.client_id), else_=None))).label("par_16_30_client_count"),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 30, func.coalesce(base.c.days_overdue, 0) <= 60), func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_31_60"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 30, func.coalesce(base.c.days_overdue, 0) <= 60), base.c.contract_no), else_=None))).label("par_31_60_count"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 30, func.coalesce(base.c.days_overdue, 0) <= 60), base.c.client_id), else_=None))).label("par_31_60_client_count"),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 60, func.coalesce(base.c.days_overdue, 0) <= 90), func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_61_90"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 60, func.coalesce(base.c.days_overdue, 0) <= 90), base.c.contract_no), else_=None))).label("par_61_90_count"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 60, func.coalesce(base.c.days_overdue, 0) <= 90), base.c.client_id), else_=None))).label("par_61_90_client_count"),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 90, func.coalesce(base.c.days_overdue, 0) <= 120), func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_91_120"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 90, func.coalesce(base.c.days_overdue, 0) <= 120), base.c.contract_no), else_=None))).label("par_91_120_count"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 90, func.coalesce(base.c.days_overdue, 0) <= 120), base.c.client_id), else_=None))).label("par_91_120_client_count"),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 120, func.coalesce(base.c.days_overdue, 0) < 365), func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_120"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 120, func.coalesce(base.c.days_overdue, 0) < 365), base.c.contract_no), else_=None))).label("par_120_count"),
            func.count(func.distinct(case((and_(func.coalesce(base.c.days_overdue, 0) > 120, func.coalesce(base.c.days_overdue, 0) < 365), base.c.client_id), else_=None))).label("par_120_client_count"),
            func.coalesce(func.sum(case((func.coalesce(base.c.days_overdue, 0) > 30, func.coalesce(base.c.encours, 0)), else_=0)), 0).label("par_30"),
            func.count(func.distinct(case((func.coalesce(base.c.days_overdue, 0) > 30, base.c.contract_no), else_=None))).label("par_30_count"),
            func.count(func.distinct(case((func.coalesce(base.c.days_overdue, 0) > 30, base.c.client_id), else_=None))).label("par_30_client_count"),
            func.coalesce(func.sum(case((client_radiable_condition, func.coalesce(base.c.encours, 0)), else_=0)), 0).label("potentially_radiable_volume"),
            func.count(func.distinct(case((client_radiable_condition, base.c.client_id), else_=None))).label("potentially_radiable_client_count"),
            func.count(case((client_radiable_condition, base.c.contract_no), else_=None)).label("potentially_radiable_loan_count"),
        )
        .select_from(base)
    ).mappings().one()
    last_schedule_import_at = db.scalar(
        select(func.max(RestructuredImportLog.finished_at)).where(
            RestructuredImportLog.import_type == "schedule",
            RestructuredImportLog.status == "success",
        )
    )
    # All KPI values are read by column name (see SELECT labels) to avoid fragile
    # positional access. `row` is a Mapping produced by `.mappings().one()`.
    total_outstanding = _safe_decimal(row["outstanding"])
    healthy_outstanding = _safe_decimal(row["healthy_outstanding"])
    healthy_count = int(row["healthy_count"] or 0)
    healthy_client_count = int(row["healthy_client_count"] or 0)
    par_0 = _safe_decimal(row["par_0"])
    par_0_count = int(row["par_0_count"] or 0)
    par_0_client_count = int(row["par_0_client_count"] or 0)
    par_1_30 = _safe_decimal(row["par_1_30"])
    par_1_30_count = int(row["par_1_30_count"] or 0)
    par_1_30_client_count = int(row["par_1_30_client_count"] or 0)
    par_1_15 = _safe_decimal(row["par_1_15"])
    par_1_15_count = int(row["par_1_15_count"] or 0)
    par_1_15_client_count = int(row["par_1_15_client_count"] or 0)
    par_16_30 = _safe_decimal(row["par_16_30"])
    par_16_30_count = int(row["par_16_30_count"] or 0)
    par_16_30_client_count = int(row["par_16_30_client_count"] or 0)
    par_31_60 = _safe_decimal(row["par_31_60"])
    par_31_60_count = int(row["par_31_60_count"] or 0)
    par_31_60_client_count = int(row["par_31_60_client_count"] or 0)
    par_61_90 = _safe_decimal(row["par_61_90"])
    par_61_90_count = int(row["par_61_90_count"] or 0)
    par_61_90_client_count = int(row["par_61_90_client_count"] or 0)
    par_91_120 = _safe_decimal(row["par_91_120"])
    par_91_120_count = int(row["par_91_120_count"] or 0)
    par_91_120_client_count = int(row["par_91_120_client_count"] or 0)
    par_120 = _safe_decimal(row["par_120"])
    par_120_count = int(row["par_120_count"] or 0)
    par_120_client_count = int(row["par_120_client_count"] or 0)
    par_30 = _safe_decimal(row["par_30"])
    par_30_count = int(row["par_30_count"] or 0)
    par_30_client_count = int(row["par_30_client_count"] or 0)
    potentially_radiable_volume = _safe_decimal(row["potentially_radiable_volume"])
    potentially_radiable_client_count = int(row["potentially_radiable_client_count"] or 0)
    potentially_radiable_loan_count = int(row["potentially_radiable_loan_count"] or 0)
    potentially_radiable_rate = Decimal("0") if not total_outstanding else (potentially_radiable_volume / total_outstanding).quantize(Decimal("0.0001"))
    _log_kpi_inconsistencies(
        family=family,
        effective_snapshot_date=effective_snapshot_date,
        effective_import_batch_id=effective_import_batch_id,
        par_0=(par_0, par_0_count, par_0_client_count),
        par_1_30=(par_1_30, par_1_30_count, par_1_30_client_count),
        par_1_15=(par_1_15, par_1_15_count, par_1_15_client_count),
        par_16_30=(par_16_30, par_16_30_count, par_16_30_client_count),
        par_31_60=(par_31_60, par_31_60_count, par_31_60_client_count),
        par_61_90=(par_61_90, par_61_90_count, par_61_90_client_count),
        par_91_120=(par_91_120, par_91_120_count, par_91_120_client_count),
        par_120=(par_120, par_120_count, par_120_client_count),
        par_30=(par_30, par_30_count, par_30_client_count),
        potentially_radiable=(potentially_radiable_volume, potentially_radiable_loan_count, potentially_radiable_client_count),
    )
    logger.info(
        "POTENTIELLE_RADIABLE_DEBUG restructured requested_end_date=%s effective_snapshot_date=%s "
        "reference_date=%s threshold=%s volume=%s rate=%s",
        date_to,
        effective_snapshot_date,
        reference_date,
        threshold,
        potentially_radiable_volume,
        potentially_radiable_rate,
    )
    return _summary_from_totals(
        family=family,
        supposed_closed=int(row["supposed_closed"] or 0),
        paid_last_four_yes=int(row["paid_last_four_yes"] or 0),
        last_recalculated_at=row["last_recalculated_at"],
        last_schedule_import_at=last_schedule_import_at,
        credits_count=int(row["credits_count"] or 0),
        disbursement_count=int(row["disbursement_count"] or 0),
        disbursements_count=int(row["disbursement_count"] or 0),
        nb_clients=int(row["nb_clients"] or 0),
        disbursement_volume=_safe_decimal(row["disbursement_volume"]),
        outstanding=total_outstanding,
         healthy_outstanding=healthy_outstanding,
         healthy_count=healthy_count,
         healthy_client_count=healthy_client_count,
         par_0=par_0,
         par_0_count=par_0_count,
         par_0_client_count=par_0_client_count,
         par_1_30=par_1_30,
         par_1_30_count=par_1_30_count,
         par_1_30_client_count=par_1_30_client_count,
         par_1_15=par_1_15,
         par_1_15_count=par_1_15_count,
         par_1_15_client_count=par_1_15_client_count,
         par_16_30=par_16_30,
         par_16_30_count=par_16_30_count,
         par_16_30_client_count=par_16_30_client_count,
         par_31_60=par_31_60,
         par_31_60_count=par_31_60_count,
         par_31_60_client_count=par_31_60_client_count,
         par_61_90=par_61_90,
         par_61_90_count=par_61_90_count,
         par_61_90_client_count=par_61_90_client_count,
         par_91_120=par_91_120,
         par_91_120_count=par_91_120_count,
         par_91_120_client_count=par_91_120_client_count,
         par_120=par_120,
         par_120_count=par_120_count,
         par_120_client_count=par_120_client_count,
         par_30=par_30,
         par_30_count=par_30_count,
         par_30_client_count=par_30_client_count,
        potentially_radiable_volume=potentially_radiable_volume,
        potentially_radiable_rate=potentially_radiable_rate,
        requested_date_to=date_to,
        effective_snapshot_date=effective_snapshot_date,
        effective_import_batch_id=effective_import_batch_id,
        potential_radiable_reference_date=reference_date,
        potential_radiable_threshold=threshold,
        potential_radiable_client_count=potentially_radiable_client_count,
        potential_radiable_loan_count=potentially_radiable_loan_count,
    )


def get_restructured_quality_chart(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
) -> MetricsChartRead:
    base = _base_contract_rows_subquery(
        db,
        user,
        family=family,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
    )
    if base is None:
        return MetricsChartRead(mode="GLOBAL_BY_AGENCY", points=[])
    rows = db.execute(
        select(
            base.c.agency_name.label("label"),
            func.coalesce(func.sum(func.coalesce(base.c.disbursement_amount, 0)), 0),
            func.coalesce(func.sum(func.coalesce(base.c.encours, 0)), 0),
            func.coalesce(func.sum(func.coalesce(base.c.healthy_outstanding, 0)), 0),
            func.coalesce(func.sum(case((func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.days_overdue, 0) <= 30), func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 0, func.coalesce(base.c.days_overdue, 0) <= 15), func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) >= 16, func.coalesce(base.c.days_overdue, 0) <= 30), func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 30, func.coalesce(base.c.days_overdue, 0) <= 60), func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 60, func.coalesce(base.c.days_overdue, 0) <= 90), func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 90, func.coalesce(base.c.days_overdue, 0) <= 120), func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((and_(func.coalesce(base.c.days_overdue, 0) > 120, func.coalesce(base.c.days_overdue, 0) < 365), func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((func.coalesce(base.c.days_overdue, 0) > 30, func.coalesce(base.c.encours, 0)), else_=0)), 0),
            func.coalesce(func.sum(case((base.c.contract_no.is_not(None), 1), else_=0)), 0),
        )
        .select_from(base)
        .where(base.c.agency_name.is_not(None))
        .group_by(base.c.agency_name)
        .order_by(base.c.agency_name.asc())
    ).all()
    points = [
        MetricsChartPoint(
            label=row[0],
            disbursement_count=int(row[11] or 0),
            disbursement_volume=_safe_decimal(row[1]),
            outstanding=_safe_decimal(row[2]),
            healthy_outstanding=_safe_decimal(row[3]),
            par_0=_safe_decimal(row[4]),
            par_1_30=_safe_decimal(row[5]),
            par_1_15=_safe_decimal(row[6]),
            par_16_30=_safe_decimal(row[7]),
            par_31_60=_safe_decimal(row[8]),
            par_61_90=_safe_decimal(row[9]),
            par_91_120=_safe_decimal(row[10]),
            par_120=_safe_decimal(row[11]),
            par_30=_safe_decimal(row[12]),
        )
        for row in rows
    ]
    return MetricsChartRead(mode="GLOBAL_BY_AGENCY", points=points)


def _slice_chart(values: list[tuple[str, int]], colors: dict[str, str] | None = None) -> RestructuredChartRead:
    return RestructuredChartRead(
        items=[
            RestructuredChartSliceRead(label=label, value=int(value or 0), color=(colors or {}).get(label))
            for label, value in values
        ]
    )


def _client_sort_expression(base):
    return func.lower(
        func.trim(
            func.coalesce(cast(base.c.client_name, String), "")
            + literal(" ")
            + func.coalesce(cast(base.c.client_first_name, String), "")
        )
    )


def _ordered_expression(expression, direction: str, *, nulls_last: bool = True):
    ordered = expression.desc() if direction == "desc" else expression.asc()
    return ordered.nullslast() if nulls_last else ordered


def _apply_restructured_contract_sorting(stmt, base, sort_key: str | None, sort_direction: str | None):
    direction = "desc" if str(sort_direction or "").lower() == "desc" else "asc"
    text_fields = {
        "contract_no": func.lower(func.coalesce(cast(base.c.contract_no, String), "")),
        "type_credit": func.lower(func.coalesce(cast(base.c.credit_family, String), "")),
        "client_name": _client_sort_expression(base),
        "agency_name": func.lower(func.coalesce(cast(base.c.agency_name, String), "")),
        "agent_name": func.lower(func.coalesce(cast(base.c.agent_name, String), "")),
        "cohort_label": func.lower(func.coalesce(cast(base.c.days_overdue, String), "")),
        "par_label": func.lower(func.coalesce(cast(base.c.days_overdue, String), "")),
        "max_series_installments": func.lower(func.coalesce(cast(base.c.max_series_installments, String), "")),
        "max_series_dates": func.lower(func.coalesce(cast(base.c.max_series_dates, String), "")),
        "anomaly_detail": func.lower(func.coalesce(cast(base.c.anomaly_detail, String), "")),
        "paid_last_four_status": func.lower(func.coalesce(cast(base.c.paid_last_four_status, String), "")),
        "closure_status": func.lower(func.coalesce(cast(base.c.closure_status, String), "")),
    }
    numeric_fields = {
        "total_due": func.coalesce(base.c.contract_total_due, base.c.mcr_total_due, 0),
        "total_scheduled_amount": base.c.total_scheduled_amount,
        "loan_duration": base.c.loan_duration,
        "encours": base.c.encours,
        "healthy_outstanding": base.c.healthy_outstanding,
        "days_overdue": base.c.days_overdue,
        "consecutive_paid_count": base.c.consecutive_paid_count,
        "anomaly_detected": cast(base.c.anomaly_detected, String),
        "last_paid_installment_no": base.c.last_paid_installment_no,
    }
    date_fields = {
        "dateeod": base.c.dateeod,
        "delay_date": base.c.delay_date,
        "last_paid_due_date": base.c.last_paid_due_date,
    }

    if sort_key in text_fields:
        order_clauses = [_ordered_expression(text_fields[sort_key], direction, nulls_last=False)]
    elif sort_key in numeric_fields:
        order_clauses = [_ordered_expression(numeric_fields[sort_key], direction)]
    elif sort_key in date_fields:
        order_clauses = [_ordered_expression(date_fields[sort_key], direction)]
    else:
        order_clauses = [base.c.delay_date.desc().nullslast(), base.c.contract_no.asc()]

    if sort_key != "contract_no":
        order_clauses.append(base.c.contract_no.asc())
    return stmt.order_by(*order_clauses)


def _build_restructured_contracts_stmt(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = None,
    closure_status: str | None = None,
    consecutive_bucket: str | None = None,
    anomaly: str | None = None,
    paid_last_four: str | None = None,
):
    base = _base_contract_rows_subquery(
        db,
        user,
        family=family,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
    )
    if base is None:
        return None, None

    stmt = select(base)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            base.c.contract_no.ilike(term)
            | func.coalesce(base.c.client_name, "").ilike(term)
            | func.coalesce(base.c.client_first_name, "").ilike(term)
            | func.coalesce(base.c.agency_name, "").ilike(term)
            | func.coalesce(base.c.agent_name, "").ilike(term)
            | func.coalesce(base.c.anomaly_detail, "").ilike(term)
        )
    if closure_status:
        normalized_closure = CLOSURE_STATUS_ASSUMED_CLOSED if closure_status == "Suppose cloture" else closure_status
        stmt = stmt.where(base.c.closure_status == normalized_closure)
    if anomaly in {"Oui", "Non"}:
        stmt = stmt.where(base.c.anomaly_detected.is_(anomaly == "Oui"))
    if paid_last_four in {"Oui", "Non", "N/A"}:
        stmt = stmt.where(base.c.paid_last_four_status == paid_last_four)
    if consecutive_bucket:
        meta = CONSECUTIVE_BUCKETS.get(consecutive_bucket)
        if meta:
            stmt = stmt.where(
                base.c.consecutive_paid_count >= meta["min"],
                base.c.consecutive_paid_count <= meta["max"],
            )
    return base, stmt


def _map_restructured_contract_row(row, family: str) -> RestructuredContractDetailRead:
    days_overdue = int(row["days_overdue"]) if row["days_overdue"] is not None else None
    return RestructuredContractDetailRead(
        contract_no=row["contract_no"],
        type_credit=_family_display_label(family),
        client_name=row["client_name"],
        client_first_name=row["client_first_name"],
        agency_name=row["agency_name"],
        agent_name=row["agent_name"],
        dateeod=row["dateeod"],
        delay_date=row["delay_date"],
        total_due=_safe_decimal(row["contract_total_due"] or row["mcr_total_due"]),
        total_scheduled_amount=_safe_decimal(row["total_scheduled_amount"]) if row["total_scheduled_amount"] is not None else None,
        loan_duration=row["loan_duration"],
        encours=_safe_decimal(row["encours"]),
        healthy_outstanding=_safe_decimal(row["healthy_outstanding"]),
        days_overdue=days_overdue,
        cohort_label=_cohort_label(days_overdue),
        par_label=_par_label(days_overdue),
        consecutive_paid_count=int(row["consecutive_paid_count"] or 0),
        paid_last_four_status=row["paid_last_four_status"] or "N/A",
        last_paid_installment_no=row["last_paid_installment_no"],
        last_paid_due_date=row["last_paid_due_date"],
        closure_status="Suppose cloture" if row["closure_status"] == CLOSURE_STATUS_ASSUMED_CLOSED else (row["closure_status"] or "N/A"),
        anomaly_detected=bool(row["anomaly_detected"]),
        anomaly_detail=row["anomaly_detail"],
        max_series_installments=row["max_series_installments"],
        max_series_dates=row["max_series_dates"],
    )


def get_restructured_consecutive_chart(db: Session, user: User, *, family: str, agency_id: int | None = None, agent_id: int | None = None, date_from: date | None = None, date_to: date | None = None, snapshot_batch_ids: str | None = None) -> RestructuredChartRead:
    base = _base_contract_rows_subquery(db, user, family=family, agency_id=agency_id, agent_id=agent_id, date_from=date_from, date_to=date_to, snapshot_batch_ids=snapshot_batch_ids)
    if base is None:
        return _slice_chart([("0", 0), ("1-2", 0), ("3", 0), ("4+", 0)], {label: meta["color"] for label, meta in CONSECUTIVE_BUCKETS.items()})
    rows = db.execute(
        select(base.c.consecutive_paid_count, func.count(base.c.contract_no))
        .select_from(base)
        .group_by(base.c.consecutive_paid_count)
    ).all()
    bucket_values = {"0": 0, "1-2": 0, "3": 0, "4+": 0}
    for count_value, row_count in rows:
        bucket_values[_bucket_for_count(count_value)] += int(row_count or 0)
    return _slice_chart([(label, bucket_values[label]) for label in ("0", "1-2", "3", "4+")], {label: meta["color"] for label, meta in CONSECUTIVE_BUCKETS.items()})


def list_restructured_contracts(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = None,
    closure_status: str | None = None,
    consecutive_bucket: str | None = None,
    anomaly: str | None = None,
    paid_last_four: str | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[RestructuredContractDetailRead]:
    base, stmt = _build_restructured_contracts_stmt(
        db,
        user,
        family=family,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        q=q,
        closure_status=closure_status,
        consecutive_bucket=consecutive_bucket,
        anomaly=anomaly,
        paid_last_four=paid_last_four,
    )
    if base is None or stmt is None:
        return Page(items=[], total=0, limit=limit, offset=offset)

    ordered_stmt = _apply_restructured_contract_sorting(stmt, base, sort_key, sort_direction)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        ordered_stmt
        .limit(limit)
        .offset(offset)
    ).mappings().all()
    items = [_map_restructured_contract_row(row, family) for row in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


def _missing_from_mcr_rows_subquery(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None,
    agent_id: int | None,
    date_from: date | None,
    date_to: date | None,
    snapshot_batch_ids: str | None,
):
    family_value = _family_filter_label(family)
    latest_loans = _latest_loans_subquery(
        db,
        user,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
    )
    if latest_loans is None:
        return None

    scope = get_user_data_scope(user)
    require_mcr_match = bool(
        agency_id
        or agent_id
        or scope.role in {UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER, UserRole.REGIONAL_MANAGER_NORD, UserRole.REGIONAL_MANAGER_SUD}
    )
    if require_mcr_match:
        return None

    selected_batches = _scoped_snapshot_batches(
        db=db,
        user=user,
        agency_id=agency_id,
        agent_id=agent_id,
        snapshot_batch_ids=_parse_snapshot_batch_ids(snapshot_batch_ids) if snapshot_batch_ids else None,
    ) if snapshot_batch_ids else []
    detected_at_value = None
    if selected_batches:
        detected_at_value = max((batch.imported_at for batch in selected_batches if batch.imported_at is not None), default=None)
    elif latest_loans is not None:
        active_imported_at = db.scalar(
            select(ImportBatch.imported_at)
            .where(ImportBatch.batch_type == ImportBatchType.CURRENT_STATE)
            .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
            .limit(1)
        )
        detected_at_value = active_imported_at

    base_stmt = (
        select(
            RestructuredContract.contract_no,
            RestructuredContract.credit_family,
            RestructuredContract.category_desc,
            RestructuredContract.delay_date,
            RestructuredContract.total_due,
            RestructuredContract.loan_duration,
            RestructuredContract.source,
            literal(detected_at_value).label("detected_at"),
        )
        .select_from(RestructuredContract)
        .outerjoin(
            latest_loans,
            latest_loans.c.contract_key == RestructuredContract.normalized_contract_no,
        )
    )
    filters = [latest_loans.c.contract_key.is_(None)]
    if family != "all":
        filters.append(RestructuredContract.credit_family == family_value)
    # Soft-excluded contracts (excluded_from_missing_mcr_at IS NOT NULL) must
    # be hidden from the diagnostic "missing from MCR" view. The contracts
    # themselves remain in the official list; only this view is filtered.
    filters.append(RestructuredContract.excluded_from_missing_mcr_at.is_(None))
    return base_stmt.where(*filters).subquery()


def _parse_table_filters(raw_value: str | None) -> dict:
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError("Filtres des contrats absents du MCR invalides.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Filtres des contrats absents du MCR invalides.")
    return payload


def _apply_missing_filter_expression(column_expr, filter_payload: dict | None, filter_type: str):
    if not filter_payload:
        return None
    mode = filter_payload.get("mode")
    selected = [str(item) for item in (filter_payload.get("selected") or [])]
    value = filter_payload.get("value")
    value_to = filter_payload.get("valueTo")

    if filter_type == "text":
        if mode == "in":
            if not selected:
                return None
            return func.lower(func.coalesce(cast(column_expr, String), "")).in_([item.strip().lower() for item in selected])
        if value in (None, ""):
            return None
        expected = str(value).strip().lower()
        expr = func.lower(func.coalesce(cast(column_expr, String), ""))
        if mode == "not_contains":
            return ~expr.like(f"%{expected}%")
        if mode == "starts_with":
            return expr.like(f"{expected}%")
        if mode == "ends_with":
            return expr.like(f"%{expected}")
        if mode == "equals":
            return expr == expected
        if mode == "not_equals":
            return expr != expected
        return expr.like(f"%{expected}%")

    if filter_type == "number":
        if mode == "in":
            if not selected:
                return None
            return cast(column_expr, String).in_(selected)
        if mode == "between":
            clauses = []
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
        if mode == "today":
            return func.date(column_expr) == date.today()
        if mode == "yesterday":
            return func.date(column_expr) == (date.today() - timedelta(days=1))
        if mode == "this_month":
            today = date.today()
            month_start = date(today.year, today.month, 1)
            month_end = date(today.year, today.month + 1, 1) if today.month < 12 else date(today.year + 1, 1, 1)
            return and_(column_expr >= month_start, column_expr < month_end)
        if mode == "previous_month":
            today = date.today()
            if today.month == 1:
                year, month = today.year - 1, 12
            else:
                year, month = today.year, today.month - 1
            month_start = date(year, month, 1)
            month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            return and_(column_expr >= month_start, column_expr < month_end)
        if mode == "year":
            if value in (None, ""):
                return None
            year = int(value)
            return and_(column_expr >= date(year, 1, 1), column_expr < date(year + 1, 1, 1))
        start_date = date.fromisoformat(str(value)) if value not in (None, "") else None
        end_date = date.fromisoformat(str(value_to)) if value_to not in (None, "") else None
        if mode == "before":
            return None if start_date is None else column_expr < start_date
        if mode == "after":
            return None if start_date is None else column_expr > start_date
        clauses = []
        if start_date is not None:
            clauses.append(column_expr >= start_date)
        if end_date is not None:
            clauses.append(column_expr <= end_date)
        return and_(*clauses) if clauses else None
    return None


def list_restructured_contracts_missing_from_mcr(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = None,
    table_filters: dict | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[RestructuredMissingMcrContractRead]:
    base = _missing_from_mcr_rows_subquery(
        db,
        user,
        family=family,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
    )
    if base is None:
        return Page(items=[], total=0, limit=limit, offset=offset)

    stmt = select(base)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            base.c.contract_no.ilike(term)
            | func.coalesce(base.c.category_desc, "").ilike(term)
        )

    filter_specs = {
        "contract_no": ("text", base.c.contract_no),
        "type_credit": ("text", base.c.credit_family),
        "category_desc": ("text", base.c.category_desc),
        "delay_date": ("date", base.c.delay_date),
        "total_due": ("number", base.c.total_due),
        "loan_duration": ("number", base.c.loan_duration),
        "source": ("text", base.c.source),
        "detected_at": ("date", base.c.detected_at),
    }
    for key, payload in (table_filters or {}).items():
        spec = filter_specs.get(key)
        if not spec:
            continue
        expression = _apply_missing_filter_expression(spec[1], payload, spec[0])
        if expression is not None:
            stmt = stmt.where(expression)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    numeric_sort_fields = {
        "total_due": base.c.total_due,
        "loan_duration": base.c.loan_duration,
    }
    order_clauses = []
    if sort_key in numeric_sort_fields:
        direction = "desc" if str(sort_direction or "").lower() == "desc" else "asc"
        ordered = numeric_sort_fields[sort_key].desc() if direction == "desc" else numeric_sort_fields[sort_key].asc()
        order_clauses.append(ordered.nullslast())
    order_clauses.extend([base.c.delay_date.desc().nullslast(), base.c.contract_no.asc()])
    rows = db.execute(
        stmt.order_by(*order_clauses)
        .limit(limit)
        .offset(offset)
    ).mappings().all()

    items = [
        RestructuredMissingMcrContractRead(
            contract_no=row["contract_no"],
            type_credit=_family_display_label(row["credit_family"]),
            category_desc=row["category_desc"],
            delay_date=row["delay_date"],
            total_due=_safe_decimal(row["total_due"]),
            loan_duration=row["loan_duration"],
            source=row["source"],
            detected_at=row["detected_at"],
        )
        for row in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


def delete_contracts_from_missing_mcr(
    db: Session,
    user: User,
    *,
    contract_nos: list[str],
    family: str | None = "all",
) -> RestructuredMissingMcrContractDeleteResult:
    """Physically delete the given restructured contracts from the database.

    The given ``contract_nos`` MUST currently appear in the
    "missing from MCR" view (otherwise they are reported as ``skipped``).

    Safety guarantees:
    - The given ``contract_nos`` MUST currently appear in the
      "missing from MCR" view (otherwise the request is rejected /
      reported as ``skipped``). This prevents a user from arbitrarily
      deleting arbitrary ``restructured_contracts`` rows by guessing ids.
    - Only operators with the IMPORT_OPERATOR_ROLES (super_admin / support)
      are allowed to call this through the API.
    - The deletion is transactional: if any error occurs, the transaction is
      rolled back and no partial deletion remains.
    - No FK or business data is removed — ``restructured_contracts`` has no
      dependent FK references.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in contract_nos or []:
        if not raw:
            continue
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    if not normalized:
        return RestructuredMissingMcrContractDeleteResult()

    base = _missing_from_mcr_rows_subquery(
        db,
        user,
        family=_family_param_value(family),
        agency_id=None,
        agent_id=None,
        date_from=None,
        date_to=None,
        snapshot_batch_ids=None,
    )
    if base is None:
        return RestructuredMissingMcrContractDeleteResult(
            skipped_contract_nos=list(normalized),
        )

    allowed_contract_nos = {
        str(row.contract_no)
        for row in db.execute(
            select(base.c.contract_no).where(base.c.contract_no.in_(normalized))
        ).all()
    }
    skipped = [value for value in normalized if value not in allowed_contract_nos]
    candidates = [value for value in normalized if value in allowed_contract_nos]

    if not candidates:
        return RestructuredMissingMcrContractDeleteResult(
            skipped_contract_nos=skipped,
        )

    db.execute(
        delete(RestructuredContract)
        .where(
            RestructuredContract.contract_no.in_(candidates),
            RestructuredContract.excluded_from_missing_mcr_at.is_(None),
        )
    )
    db.commit()

    logger.info(
        "missing_mcr_delete actor_id=%s actor_role=%s deleted=%s skipped=%s",
        getattr(user, "id", None),
        getattr(user, "role", None),
        len(candidates),
        len(skipped),
    )

    return RestructuredMissingMcrContractDeleteResult(
        deleted_count=len(candidates),
        skipped_count=len(skipped),
        deleted_contract_nos=candidates,
        skipped_contract_nos=skipped,
    )


def _fit_column_widths(sheet) -> None:
    for column_index in range(1, sheet.max_column + 1):
        max_length = 0
        column_letter = get_column_letter(column_index)
        for row_index in range(1, sheet.max_row + 1):
            value = sheet.cell(row=row_index, column=column_index).value
            max_length = max(max_length, len("" if value is None else str(value)))
        sheet.column_dimensions[column_letter].width = min(30, max(12, max_length + 2))


def _format_export_filter_value(value: object, *, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _apply_status_style(cell, value: str | None) -> None:
    normalized = str(value or "").strip().lower()
    if normalized in {"oui", "suppose cloture"}:
        cell.fill = SUCCESS_FILL
        cell.font = SUCCESS_FONT
    elif normalized in {"non"}:
        cell.fill = DANGER_FILL
        cell.font = DANGER_FONT
    elif normalized in {"en cours"}:
        cell.fill = WARNING_FILL
        cell.font = WARNING_FONT
    elif normalized in {"n/a"}:
        cell.fill = NEUTRAL_FILL
        cell.font = NEUTRAL_FONT


def build_restructured_contracts_export(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = None,
    closure_status: str | None = None,
    consecutive_bucket: str | None = None,
    anomaly: str | None = None,
    paid_last_four: str | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
) -> BytesIO:
    started_at = perf_counter()
    base, stmt = _build_restructured_contracts_stmt(
        db,
        user,
        family=family,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        q=q,
        closure_status=closure_status,
        consecutive_bucket=consecutive_bucket,
        anomaly=anomaly,
        paid_last_four=paid_last_four,
    )
    if base is None or stmt is None:
        items = []
        total = 0
    else:
        total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = db.execute(
            _apply_restructured_contract_sorting(stmt, base, sort_key, sort_direction)
        ).mappings().all()
        items = [_map_restructured_contract_row(row, family) for row in rows]

    logger.info(
        "restructured_contracts_export_started role=%s family=%s agency_id=%s agent_id=%s date_from=%s date_to=%s snapshots=%s q=%s closure_status=%s consecutive_bucket=%s anomaly=%s paid_last_four=%s sort_key=%s sort_direction=%s total_after_filter=%s exported_rows=%s",
        getattr(user, "role", None),
        family,
        agency_id,
        agent_id,
        date_from,
        date_to,
        snapshot_batch_ids,
        q,
        closure_status,
        consecutive_bucket,
        anomaly,
        paid_last_four,
        sort_key,
        sort_direction,
        total,
        len(items),
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Detail contrats"
    title = "Detail des contrats consolides" if family == CONSOLIDATED_FAMILY else "Detail des contrats restructures"
    headers = [
        "Numero de contrat",
        "Type de credit",
        "Client",
        "Agence",
        "GP",
        "DateEOD",
        "Date de decalage",
        "Total Due",
        "Echeance",
        "LOAN_DURATION",
        "Encours",
        "Encours sain",
        "Jours de retard",
        "Cohorte",
        "PAR",
        "Nombre d'echeances consecutives payees",
        "Numero de la serie maximale",
        "Dates de la serie maximale",
        "Paye les quatre dernieres echeances",
        "Derniere echeance payee",
        "Date derniere echeance",
        "Statut cloture",
        "Anomalie",
        "Detail anomalie",
    ]
    last_column_letter = get_column_letter(len(headers))
    sheet.merge_cells(f"A1:{last_column_letter}1")
    title_cell = sheet["A1"]
    title_cell.value = title
    title_cell.fill = TITLE_FILL
    title_cell.font = TITLE_FONT
    title_cell.alignment = Alignment(horizontal="center")

    generated_at = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
    selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
    selected_agencies = (
        db.scalars(select(Agency).where(Agency.id.in_(selected_agency_ids)).order_by(Agency.name)).all()
        if selected_agency_ids
        else []
    )
    agent = db.get(Agent, agent_id) if agent_id else None
    agency_name = " + ".join(agency.name for agency in selected_agencies) if selected_agencies else "Toutes les agences"
    agent_name = agent.name if agent else "Tous les agents"
    metadata_rows = [
        ("Genere le", generated_at),
        ("Utilisateur", _format_export_filter_value(getattr(user, "full_name", None) or getattr(user, "email", None), fallback="Utilisateur inconnu")),
        ("Onglet", "Credits consolides" if family == CONSOLIDATED_FAMILY else "Credits restructures"),
        ("Agence", _format_export_filter_value(agency_name, fallback="Toutes les agences")),
        ("Agent", _format_export_filter_value(agent_name, fallback="Tous les agents")),
        ("Periode", _format_export_filter_value(
            " -> ".join(part for part in [
                date_from.strftime("%d/%m/%Y") if date_from else "",
                date_to.strftime("%d/%m/%Y") if date_to else "",
            ] if part),
            fallback="Toutes les periodes",
        )),
        ("Snapshots", _format_export_filter_value(snapshot_batch_ids, fallback="Etat MCR actif")),
        ("Recherche", _format_export_filter_value(q, fallback="Aucune")),
        ("Statut cloture", _format_export_filter_value(closure_status, fallback="Tous")),
        ("Serie consecutive", _format_export_filter_value(consecutive_bucket, fallback="Toutes")),
        ("Anomalie", _format_export_filter_value(anomaly, fallback="Toutes")),
        ("Paye les 4 dernieres", _format_export_filter_value(paid_last_four, fallback="Tous")),
        ("Tri", _format_export_filter_value(
            " ".join(part for part in [sort_key, str(sort_direction or "").upper()] if part),
            fallback="Par defaut",
        )),
        ("Nombre de lignes exportees", str(len(items))),
    ]
    for row_index, (label, value) in enumerate(metadata_rows, start=2):
        sheet.cell(row=row_index, column=1, value=label).font = Font(bold=True)
        sheet.cell(row=row_index, column=2, value=value)

    start_row = len(metadata_rows) + 4
    for column_index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=start_row, column=column_index, value=header)
        cell.fill = HEADER_BG
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER

    for row_index, item in enumerate(items, start=start_row + 1):
        values = [
            item.contract_no,
            item.type_credit,
            " ".join(part for part in [item.client_name, item.client_first_name] if part),
            item.agency_name,
            item.agent_name,
            item.dateeod.strftime("%d/%m/%Y") if item.dateeod else "",
            item.delay_date.strftime("%d/%m/%Y") if item.delay_date else "",
            float(item.total_due) if item.total_due is not None else "",
            float(item.total_scheduled_amount) if item.total_scheduled_amount is not None else "",
            item.loan_duration,
            float(item.encours) if item.encours is not None else "",
            float(item.healthy_outstanding) if item.healthy_outstanding is not None else "",
            item.days_overdue,
            item.cohort_label,
            item.par_label,
            item.consecutive_paid_count,
            item.max_series_installments or "",
            item.max_series_dates or "",
            item.paid_last_four_status,
            item.last_paid_installment_no,
            item.last_paid_due_date.strftime("%d/%m/%Y") if item.last_paid_due_date else "",
            item.closure_status,
            "Oui" if item.anomaly_detected else "Non",
            item.anomaly_detail or "",
        ]
        for column_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=column_index, value=value)
            cell.border = THIN_BORDER
            cell.alignment = Alignment(vertical="center")
            if row_index % 2 == 0:
                cell.fill = ALT_ROW_FILL
            if column_index in {8, 9, 11, 12} and isinstance(value, (int, float)):
                cell.number_format = "#,##0.00"
            if column_index in {18, 21, 22}:
                _apply_status_style(cell, value)

    sheet.freeze_panes = f"A{start_row + 1}"
    sheet.auto_filter.ref = f"A{start_row}:{last_column_letter}{max(start_row, sheet.max_row)}"
    _fit_column_widths(sheet)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    duration_ms = int((perf_counter() - started_at) * 1000)
    file_size = output.getbuffer().nbytes
    logger.info(
        "restructured_contracts_export_completed role=%s family=%s exported_rows=%s file_size_bytes=%s duration_ms=%s",
        getattr(user, "role", None),
        family,
        len(items),
        file_size,
        duration_ms,
    )
    return output


def build_restructured_missing_from_mcr_export(
    db: Session,
    user: User,
    *,
    family: str,
    agency_id: int | None = None,
    agent_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_batch_ids: str | None = None,
    q: str | None = None,
    table_filters: dict | None = None,
    sort_key: str | None = None,
    sort_direction: str | None = None,
) -> BytesIO:
    page = list_restructured_contracts_missing_from_mcr(
        db,
        user,
        family=family,
        agency_id=agency_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        snapshot_batch_ids=snapshot_batch_ids,
        q=q,
        table_filters=table_filters,
        sort_key=sort_key,
        sort_direction=sort_direction,
        limit=5000,
        offset=0,
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Absents MCR"
    title = (
        "Contrats absents du MCR"
        if family == "all"
        else "Contrats consolides absents du MCR"
        if family == CONSOLIDATED_FAMILY
        else "Contrats restructures absents du MCR"
    )
    sheet.merge_cells("A1:H1")
    title_cell = sheet["A1"]
    title_cell.value = title
    title_cell.fill = TITLE_FILL
    title_cell.font = TITLE_FONT
    title_cell.alignment = Alignment(horizontal="center")

    generated_at = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
    sheet["A2"] = "Genere le"
    sheet["B2"] = generated_at
    sheet["D2"] = "Nombre contrats"
    sheet["E2"] = page.total

    headers = [
        "Numero contrat",
        "Type credit",
        "CATEGORY_DESC",
        "Date decalage",
        "Total Due",
        "LOAN_DURATION",
        "Source",
        "Date detection",
    ]
    start_row = 4
    for column_index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=start_row, column=column_index, value=header)
        cell.fill = HEADER_BG
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER

    for row_index, item in enumerate(page.items, start=start_row + 1):
        values = [
            item.contract_no,
            item.type_credit,
            item.category_desc or "",
            item.delay_date.strftime("%d/%m/%Y") if item.delay_date else "",
            float(item.total_due or 0),
            item.loan_duration,
            item.source or "",
            item.detected_at.strftime("%d/%m/%Y %H:%M") if item.detected_at else "",
        ]
        for column_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=column_index, value=value)
            cell.border = THIN_BORDER
            cell.alignment = Alignment(vertical="center")
            if row_index % 2 == 1:
                cell.fill = ALT_ROW_FILL

    _fit_column_widths(sheet)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output
