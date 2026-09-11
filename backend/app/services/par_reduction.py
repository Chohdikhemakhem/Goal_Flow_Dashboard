from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.entities import Agency, Agent, ImportBatch, LoanRaw, ParReductionTarget, User
from app.models.enums import ImportBatchType, UserRole
from app.services.agent_identity import normalized_agent_name_expression
from app.services.data_scope import get_user_data_scope
from app.services.selection import normalize_agency_ids

PAR_REDUCTION_KEYS = ("par30", "cohort_1_15", "cohort_16_30")


def _latest_snapshot_before_month_start(
    db: Session,
    *,
    month: int,
    year: int,
) -> ImportBatch | None:
    period_start = date(year, month, 1)
    query = select(ImportBatch).where(
        ImportBatch.batch_type.in_((ImportBatchType.HISTORICAL_MONTH, ImportBatchType.SNAPSHOT, ImportBatchType.CURRENT_STATE)),
        ImportBatch.snapshot_date < period_start,
    )
    return db.scalar(
        query.order_by(
            ImportBatch.snapshot_date.desc(),
            ImportBatch.imported_at.desc(),
            ImportBatch.id.desc(),
        ).limit(1)
    )


def _latest_snapshot_in_period(
    db: Session,
    *,
    month: int,
    year: int,
    as_of: date,
) -> ImportBatch | None:
    period_start = date(year, month, 1)
    period_end = date(year, month, monthrange(year, month)[1])
    query = select(ImportBatch).where(
        ImportBatch.batch_type.in_((ImportBatchType.HISTORICAL_MONTH, ImportBatchType.SNAPSHOT, ImportBatchType.CURRENT_STATE)),
        ImportBatch.snapshot_date >= period_start,
        ImportBatch.snapshot_date <= min(period_end, as_of),
    )
    return db.scalar(
        query.order_by(
            ImportBatch.snapshot_date.desc(),
            ImportBatch.imported_at.desc(),
            ImportBatch.id.desc(),
        ).limit(1)
    )


def _volume_query(db: Session, batch_id: int | None, agency_id: str | None, agent_id: int | None):
    empty = {key: Decimal("0") for key in PAR_REDUCTION_KEYS}
    if batch_id is None:
        return empty
    exposure = LoanRaw.principal_outstanding + LoanRaw.principal_due
    filters = [LoanRaw.import_batch_id == batch_id, LoanRaw.disbursement_date.is_not(None)]
    selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
    if selected_agency_ids:
        filters.append(Agency.id.in_(selected_agency_ids))
    if agent_id is not None:
        filters.append(Agent.id == agent_id)
    is_par30 = LoanRaw.days_overdue > 30
    is_1_15 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 15)
    is_16_30 = (LoanRaw.days_overdue >= 16) & (LoanRaw.days_overdue <= 30)
    row = db.execute(
        select(
            func.coalesce(func.sum(case((is_par30, exposure), else_=0)), 0).label("par30"),
            func.coalesce(func.sum(case((is_1_15, exposure), else_=0)), 0).label("cohort_1_15"),
            func.coalesce(func.sum(case((is_16_30, exposure), else_=0)), 0).label("cohort_16_30"),
        ).select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, (normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name)) & (Agent.agency_id == Agency.id))
        .where(*filters)
    ).mappings().one()
    return {key: Decimal(str(row[key] or 0)) for key in PAR_REDUCTION_KEYS}


def _volumes_by_agent(db: Session, batch_id: int | None, agency_id: str | None, agent_id: int | None) -> dict[int, dict[str, Decimal]]:
    if batch_id is None:
        return {}
    exposure = LoanRaw.principal_outstanding + LoanRaw.principal_due
    loan_match = and_(
        LoanRaw.import_batch_id == batch_id,
        LoanRaw.disbursement_date.is_not(None),
        normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name),
        Agency.name == LoanRaw.agency_name,
    )
    filters = []
    selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
    if selected_agency_ids:
        filters.append(Agent.agency_id.in_(selected_agency_ids))
    if agent_id is not None:
        filters.append(Agent.id == agent_id)
    rows = db.execute(
        select(
            Agent.id.label("agent_id"),
            func.coalesce(func.sum(case((LoanRaw.days_overdue > 30, exposure), else_=0)), 0).label("par30"),
            func.coalesce(func.sum(case(((LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 15), exposure), else_=0)), 0).label("cohort_1_15"),
            func.coalesce(func.sum(case(((LoanRaw.days_overdue >= 16) & (LoanRaw.days_overdue <= 30), exposure), else_=0)), 0).label("cohort_16_30"),
        )
        .select_from(Agent)
        .join(Agency, Agency.id == Agent.agency_id)
        .outerjoin(LoanRaw, loan_match)
        .where(*filters)
        .group_by(Agent.id)
    ).mappings().all()
    return {
        row["agent_id"]: {key: Decimal(str(row[key] or 0)) for key in PAR_REDUCTION_KEYS}
        for row in rows
    }


def _comparison_rows(
    db: Session,
    *,
    month: int,
    year: int,
    user: User,
    agency_id: str | None,
    agent_id: int | None,
    initial_batch: ImportBatch | None,
    current_batch: ImportBatch | None,
) -> list[dict]:
    selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
    if not selected_agency_ids and agent_id is None:
        return []
    agent_filters = []
    if selected_agency_ids:
        agent_filters.append(Agent.agency_id.in_(selected_agency_ids))
    if agent_id is not None:
        agent_filters.append(Agent.id == agent_id)
    agents = db.scalars(select(Agent).options(joinedload(Agent.agency)).where(*agent_filters).order_by(Agent.name)).all()
    if not agents:
        return []
    initial_by_agent = _volumes_by_agent(db, initial_batch.id if initial_batch else None, agency_id, agent_id)
    current_by_agent = _volumes_by_agent(db, current_batch.id if current_batch else None, agency_id, agent_id)
    target_rows = db.execute(
        select(ParReductionTarget).where(
            ParReductionTarget.month == month,
            ParReductionTarget.year == year,
            ParReductionTarget.agent_id.in_([agent.id for agent in agents]),
        )
    ).scalars().all()
    targets = {target.agent_id: target for target in target_rows}
    rows = []
    for agent in agents:
        initial = initial_by_agent.get(agent.id, {key: Decimal("0") for key in PAR_REDUCTION_KEYS})
        current = current_by_agent.get(agent.id, {key: Decimal("0") for key in PAR_REDUCTION_KEYS})
        target = targets.get(agent.id)
        target_values = {
            "par30": target.target_par30 if target else None,
            "cohort_1_15": target.target_cohort_1_15 if target else None,
            "cohort_16_30": target.target_cohort_16_30 if target else None,
        }
        metrics = {}
        for key in PAR_REDUCTION_KEYS:
            metrics[key] = {
                "initial": initial[key],
                "current": current[key],
                "target_to_reach": target_values[key],
                "reduction_realized": initial[key] - current[key],
                "reduction_required": initial[key] - target_values[key] if target else None,
                "achievement_rate": (
                    (initial[key] - current[key]) / (initial[key] - target_values[key]) * Decimal("100")
                    if target and initial[key] > target_values[key] else Decimal("0")
                ) if target else None,
            }
        rows.append({
            "row_type": "portfolio_manager",
            "agent_id": agent.id,
            "agent_name": agent.name,
            "agency_id": agent.agency_id,
            "agency_name": agent.agency.name,
            "has_target": target is not None,
            "metrics": metrics,
        })
    return rows


def resolve_reduction_scope(user: User, agency_id: str | None, agent_id: int | None) -> tuple[str | None, int | None]:
    scope = get_user_data_scope(user)
    if user.role == UserRole.AGENCY_MANAGER:
        return (str(scope.agency_id) if scope.agency_id is not None else None), None
    if user.role == UserRole.PORTFOLIO_MANAGER:
        return (str(scope.agency_id) if scope.agency_id is not None else None), scope.agent_id
    return agency_id, agent_id


def reduction_metric(initial: Decimal, current: Decimal, target_to_reach: Decimal) -> dict[str, Decimal | bool | str | None]:
    reduction_required = initial - target_to_reach
    reduction_realized = initial - current
    valid_target = target_to_reach <= initial
    achievement = (
        Decimal("0")
        if not valid_target or reduction_required <= 0
        else (reduction_realized / reduction_required * Decimal("100"))
    )
    return {
        "initial": initial,
        "current": current,
        "target_to_reach": target_to_reach,
        "reduction_required": reduction_required,
        "reduction_realized": reduction_realized,
        "achievement_rate": achievement,
        "valid_target": valid_target,
        "message": None if valid_target else "Objectif invalide : l'objectif a atteindre doit etre inferieur ou egal au PAR initial.",
        "initial_volume": initial,
        "current_volume": current,
        "reduction": reduction_realized,
        "target": target_to_reach,
        "remaining": target_to_reach - current,
    }


def compute_par_reduction(db: Session, *, month: int, year: int, user: User, agency_id: str | None = None, agent_id: int | None = None) -> dict:
    agency_id, agent_id = resolve_reduction_scope(user, agency_id, agent_id)
    today = date.today()
    period_end = date(year, month, monthrange(year, month)[1])
    as_of = min(today, period_end)
    initial_batch = _latest_snapshot_before_month_start(db, month=month, year=year)
    current_batch = _latest_snapshot_in_period(db, month=month, year=year, as_of=as_of)
    initial = _volume_query(db, initial_batch.id if initial_batch else None, agency_id, agent_id)
    current = _volume_query(db, current_batch.id if current_batch else None, agency_id, agent_id)
    target_filters = [ParReductionTarget.month == month, ParReductionTarget.year == year]
    if agent_id is not None:
        target_filters.append(ParReductionTarget.agent_id == agent_id)
    else:
        selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
        if selected_agency_ids:
            target_filters.append(ParReductionTarget.agency_id.in_(selected_agency_ids))
    target = db.execute(
        select(
            func.coalesce(func.sum(ParReductionTarget.target_par30), 0).label("par30"),
            func.coalesce(func.sum(ParReductionTarget.target_cohort_1_15), 0).label("cohort_1_15"),
            func.coalesce(func.sum(ParReductionTarget.target_cohort_16_30), 0).label("cohort_16_30"),
        ).where(*target_filters)
    ).mappings().one()
    target_values = {
        "par30": Decimal(str(target["par30"] or 0)),
        "cohort_1_15": Decimal(str(target["cohort_1_15"] or 0)),
        "cohort_16_30": Decimal(str(target["cohort_16_30"] or 0)),
    }
    metrics = {key: reduction_metric(initial[key], current[key], target_values[key]) for key in PAR_REDUCTION_KEYS}
    if initial_batch is None:
        for metric in metrics.values():
            metric["valid_target"] = True
            metric["message"] = "Snapshot initial indisponible pour cette periode."
            metric["achievement_rate"] = Decimal("0")
    elif current_batch is None:
        for metric in metrics.values():
            metric["message"] = "Snapshot actuel indisponible pour cette periode."
            metric["achievement_rate"] = Decimal("0")
    active_rates = [item["achievement_rate"] for item in metrics.values() if item["target"] > 0]
    result = {
        "period": {"month": month, "year": year},
        "scope": {"type": "AGENT" if agent_id is not None else "AGENCY" if agency_id is not None else "GLOBAL", "agency_id": agency_id, "agent_id": agent_id},
        "metrics": metrics,
        "global_achievement_rate": sum(active_rates, Decimal("0")) / Decimal(str(len(active_rates))) if active_rates else Decimal("0"),
        "has_initial_snapshot": initial_batch is not None,
        "has_current_snapshot": current_batch is not None,
        "initial_snapshot_date": initial_batch.snapshot_date if initial_batch else None,
        "current_snapshot_date": current_batch.snapshot_date if current_batch else None,
        "initial_snapshot_id": initial_batch.id if initial_batch else None,
        "current_snapshot_id": current_batch.id if current_batch else None,
        "target_par30": target_values["par30"],
        "target_cohort_1_15": target_values["cohort_1_15"],
        "target_cohort_16_30": target_values["cohort_16_30"],
        "initial_par30": metrics["par30"]["initial_volume"],
        "current_par30": metrics["par30"]["current_volume"],
        "reduction_par30": metrics["par30"]["reduction"],
        "initial_cohort_1_15": metrics["cohort_1_15"]["initial_volume"],
        "current_cohort_1_15": metrics["cohort_1_15"]["current_volume"],
        "reduction_cohort_1_15": metrics["cohort_1_15"]["reduction"],
        "initial_cohort_16_30": metrics["cohort_16_30"]["initial_volume"],
        "current_cohort_16_30": metrics["cohort_16_30"]["current_volume"],
        "reduction_cohort_16_30": metrics["cohort_16_30"]["reduction"],
    }
    comparison_rows = _comparison_rows(
        db,
        month=month,
        year=year,
        user=user,
        agency_id=agency_id,
        agent_id=agent_id,
        initial_batch=initial_batch,
        current_batch=current_batch,
    )
    if comparison_rows and normalize_agency_ids(agency_id=agency_id) and user.role != UserRole.PORTFOLIO_MANAGER:
        selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
        agency_metrics = {}
        for key in PAR_REDUCTION_KEYS:
            initial_total = sum((row["metrics"][key]["initial"] for row in comparison_rows), Decimal("0"))
            current_total = sum((row["metrics"][key]["current"] for row in comparison_rows), Decimal("0"))
            required_values = [row["metrics"][key]["reduction_required"] for row in comparison_rows if row["metrics"][key]["reduction_required"] is not None]
            required_total = sum(required_values, Decimal("0")) if required_values else None
            realized_total = initial_total - current_total
            agency_metrics[key] = {
                "initial": initial_total,
                "current": current_total,
                "target_to_reach": initial_total - required_total if required_total is not None else None,
                "reduction_realized": realized_total,
                "reduction_required": required_total,
                "achievement_rate": realized_total / required_total * Decimal("100") if required_total and required_total > 0 else None,
            }
        comparison_rows.insert(0, {
            "row_type": "agency",
            "agency_id": selected_agency_ids[0] if len(selected_agency_ids) == 1 else None,
            "agency_name": " + ".join(sorted({row["agency_name"] for row in comparison_rows})),
            "agent_count": len(comparison_rows),
            "has_target": any(row["has_target"] for row in comparison_rows),
            "metrics": agency_metrics,
        })
    result["portfolio_comparison"] = comparison_rows
    return result


def compute_par_reduction_evolution(
    db: Session,
    *,
    month: int,
    year: int,
    user: User,
    agency_id: str | None = None,
    agent_id: int | None = None,
) -> list[dict]:
    agency_id, agent_id = resolve_reduction_scope(user, agency_id, agent_id)
    today = date.today()
    period_start = date(year, month, 1)
    period_end = date(year, month, monthrange(year, month)[1])
    as_of = min(today, period_end)
    initial_batch = _latest_snapshot_before_month_start(db, month=month, year=year)
    initial = _volume_query(db, initial_batch.id if initial_batch else None, agency_id, agent_id)
    target_filters = [ParReductionTarget.month == month, ParReductionTarget.year == year]
    if agent_id is not None:
        target_filters.append(ParReductionTarget.agent_id == agent_id)
    else:
        selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
        if selected_agency_ids:
            target_filters.append(ParReductionTarget.agency_id.in_(selected_agency_ids))
    target_row = db.execute(
        select(
            func.count(ParReductionTarget.id).label("target_count"),
            func.coalesce(func.sum(ParReductionTarget.target_par30), 0).label("target_par30"),
            func.coalesce(func.sum(ParReductionTarget.target_cohort_1_15), 0).label("target_cohort_1_15"),
            func.coalesce(func.sum(ParReductionTarget.target_cohort_16_30), 0).label("target_cohort_16_30"),
        ).where(*target_filters)
    ).mappings().one()
    required = None
    if target_row["target_count"]:
        required = {
            "cohort_1_15": initial["cohort_1_15"] - Decimal(str(target_row["target_cohort_1_15"] or 0)),
            "cohort_16_30": initial["cohort_16_30"] - Decimal(str(target_row["target_cohort_16_30"] or 0)),
            "par30": initial["par30"] - Decimal(str(target_row["target_par30"] or 0)),
        }
    batches = db.scalars(
        select(ImportBatch)
        .where(
            ImportBatch.snapshot_date >= period_start,
            ImportBatch.snapshot_date <= min(period_end, as_of),
            ImportBatch.batch_type.in_((ImportBatchType.HISTORICAL_MONTH, ImportBatchType.SNAPSHOT, ImportBatchType.CURRENT_STATE)),
        )
        .order_by(ImportBatch.snapshot_date.asc(), ImportBatch.imported_at.asc(), ImportBatch.id.asc())
    ).all()
    points = []
    seen_dates: set[date] = set()
    for batch in batches:
        if batch.snapshot_date in seen_dates:
            continue
        seen_dates.add(batch.snapshot_date)
        current = _volume_query(db, batch.id, agency_id, agent_id)
        point = {"snapshot_date": batch.snapshot_date, **{key: initial[key] - current[key] for key in PAR_REDUCTION_KEYS}}
        if required is not None:
            point.update({f"reduction_required_{key}": value for key, value in required.items()})
        points.append(point)
    return points
