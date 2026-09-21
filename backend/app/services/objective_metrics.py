from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.entities import Agency, Agent, ImportBatch, LoanRaw
from app.models.enums import ImportBatchType
from app.services.agent_identity import normalized_agent_name_expression


def get_objective_period_bounds(month: int, year: int) -> tuple[date, date]:
    start_date = date(year, month, 1)
    end_date = date(year, month, monthrange(year, month)[1])
    return start_date, end_date


def _latest_current_batch(db: Session) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch)
        .where(ImportBatch.batch_type == ImportBatchType.CURRENT_STATE)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )


def _resolve_period_filter(
    db: Session,
    month: int,
    year: int,
    start_date: date,
    end_date: date,
):
    period = f"{year:04d}-{month:02d}"
    historical_batch = db.scalar(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type == ImportBatchType.HISTORICAL_MONTH,
            ImportBatch.period == period,
        )
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )
    if historical_batch is not None:
        return LoanRaw.import_batch_id == historical_batch.id

    current_batch = _latest_current_batch(db)
    if current_batch is not None:
        if current_batch.snapshot_date.year == year and current_batch.snapshot_date.month == month:
            return LoanRaw.import_batch_id == current_batch.id

    has_batch_metadata = (db.scalar(select(func.count(ImportBatch.id))) or 0) > 0
    if has_batch_metadata:
        return None

    legacy_snapshot = db.scalar(
        select(func.max(LoanRaw.snapshot_date)).where(
            LoanRaw.snapshot_date >= start_date,
            LoanRaw.snapshot_date <= end_date,
        )
    )
    if legacy_snapshot is None:
        return None
    return LoanRaw.snapshot_date == legacy_snapshot


def compute_objective_period_realizations(
    db: Session,
    month: int,
    year: int,
    agency_id: int | None = None,
    agent_id: int | None = None,
) -> dict[str, int | float]:
    empty_values: dict[str, int | float] = {
        "disbursement_count": 0,
        "disbursement_volume": 0,
        "nb_clients": 0,
        "outstanding": 0,
        "healthy_outstanding": 0,
        "par_0": 0,
        "par_1_30": 0,
        "par_1_15": 0,
        "par_16_30": 0,
        "par_31_60": 0,
        "par_30": 0,
    }

    start_date, end_date = get_objective_period_bounds(month=month, year=year)
    period_filter = _resolve_period_filter(
        db=db,
        month=month,
        year=year,
        start_date=start_date,
        end_date=end_date,
    )
    if period_filter is None:
        return empty_values

    exposure = LoanRaw.principal_outstanding + LoanRaw.principal_due
    flow_condition = (LoanRaw.disbursement_date >= start_date) & (
        LoanRaw.disbursement_date <= end_date
    )
    stock_condition = LoanRaw.disbursement_date <= end_date
    is_healthy = LoanRaw.days_overdue == 0
    is_par_0 = LoanRaw.days_overdue > 0
    is_par_1_30 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 30)
    is_par_1_15 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 15)
    is_par_16_30 = (LoanRaw.days_overdue >= 16) & (LoanRaw.days_overdue <= 30)
    is_par_31_60 = (LoanRaw.days_overdue >= 31) & (LoanRaw.days_overdue <= 60)
    is_par_30 = LoanRaw.days_overdue > 30

    filters = [period_filter, LoanRaw.disbursement_date.is_not(None)]
    if agency_id is not None:
        filters.append(Agency.id == agency_id)
    if agent_id is not None:
        filters.append(Agent.id == agent_id)

    row = db.execute(
        select(
            func.coalesce(func.sum(case((flow_condition, 1), else_=0)), 0).label(
                "disbursement_count"
            ),
            func.coalesce(
                func.sum(case((flow_condition, LoanRaw.disbursement_amount), else_=0)), 0
            ).label("disbursement_volume"),
            func.count(
                func.distinct(case((flow_condition, LoanRaw.client_id), else_=None))
            ).label("nb_clients"),
            func.coalesce(func.sum(case((stock_condition, exposure), else_=0)), 0).label(
                "outstanding"
            ),
            func.coalesce(
                func.sum(case((stock_condition & is_healthy, exposure), else_=0)), 0
            ).label("healthy_outstanding"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_0, exposure), else_=0)), 0
            ).label("par_0"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_1_30, exposure), else_=0)), 0
            ).label("par_1_30"),
            func.coalesce(func.sum(case((stock_condition & is_par_1_15, exposure), else_=0)), 0).label("par_1_15"),
            func.coalesce(func.sum(case((stock_condition & is_par_16_30, exposure), else_=0)), 0).label("par_16_30"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_31_60, exposure), else_=0)), 0
            ).label("par_31_60"),
            func.coalesce(
                func.sum(case((stock_condition & is_par_30, exposure), else_=0)), 0
            ).label("par_30"),
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(
            Agent,
            (normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name))
            & (Agent.agency_id == Agency.id),
        )
        .where(*filters)
    ).mappings().one()

    return {**empty_values, **dict(row)}
