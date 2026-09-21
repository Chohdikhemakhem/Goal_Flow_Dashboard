from datetime import date

from sqlalchemy import case, delete, distinct, func, select
from sqlalchemy.orm import Session

from app.models.entities import Agency, Agent, DailyMetric, LoanRaw
from app.services.agent_identity import normalized_agent_name_expression
from app.services.lookups import get_or_create_agency, get_or_create_agent


def recalculate_daily_metrics(db: Session, snapshot_date: date) -> int:
    month_start = snapshot_date.replace(day=1)
    pairs = db.execute(
        select(LoanRaw.agency_name, LoanRaw.agent_name)
        .where(LoanRaw.snapshot_date == snapshot_date)
        .distinct()
    ).all()

    for agency_name, agent_name in pairs:
        agency = get_or_create_agency(db, agency_name)
        get_or_create_agent(db, agent_name, agency)
    db.flush()

    db.execute(delete(DailyMetric).where(DailyMetric.date == snapshot_date))

    exposure = LoanRaw.principal_outstanding + LoanRaw.principal_due
    is_out = LoanRaw.disbursement_date <= snapshot_date
    is_disb_month = (LoanRaw.disbursement_date >= month_start) & (
        LoanRaw.disbursement_date <= snapshot_date
    )
    is_healthy = LoanRaw.days_overdue == 0
    is_par_0 = LoanRaw.days_overdue > 0
    is_par_1_30 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 30)
    is_par_1_15 = (LoanRaw.days_overdue > 0) & (LoanRaw.days_overdue <= 15)
    is_par_16_30 = (LoanRaw.days_overdue >= 16) & (LoanRaw.days_overdue <= 30)
    is_par_31_60 = (LoanRaw.days_overdue >= 31) & (LoanRaw.days_overdue <= 60)
    is_par_61_90 = (LoanRaw.days_overdue > 60) & (LoanRaw.days_overdue <= 90)
    is_par_91_120 = (LoanRaw.days_overdue > 90) & (LoanRaw.days_overdue <= 120)
    is_par_120 = (LoanRaw.days_overdue > 120) 
    is_par_30 = LoanRaw.days_overdue > 30

    rows = db.execute(
        select(
            Agency.id.label("agency_id"),
            Agent.id.label("agent_id"),
            func.coalesce(func.sum(case((is_disb_month, 1), else_=0)), 0).label(
                "disbursement_count"
            ),
            func.coalesce(
                func.sum(case((is_disb_month, LoanRaw.disbursement_amount), else_=0)),
                0,
            ).label("disbursement_volume"),
            func.count(distinct(case((is_out, LoanRaw.client_id), else_=None))).label(
                "nb_clients"
            ),
            func.coalesce(func.sum(case((is_out, exposure), else_=0)), 0).label(
                "outstanding"
            ),
            func.coalesce(func.sum(case((is_out & is_healthy, exposure), else_=0)), 0).label(
                "healthy_outstanding"
            ),
            func.coalesce(func.sum(case((is_out & is_par_0, exposure), else_=0)), 0).label(
                "par_0"
            ),
            func.coalesce(
                func.sum(case((is_out & is_par_1_30, exposure), else_=0)), 0
            ).label("par_1_30"),
            func.coalesce(func.sum(case((is_out & is_par_1_15, exposure), else_=0)), 0).label("par_1_15"),
            func.coalesce(func.sum(case((is_out & is_par_16_30, exposure), else_=0)), 0).label("par_16_30"),
            func.coalesce(
                func.sum(case((is_out & is_par_31_60, exposure), else_=0)), 0
            ).label("par_31_60"),
            func.coalesce(
                func.sum(case((is_out & is_par_61_90, exposure), else_=0)), 0
            ).label("par_61_90"),
            func.coalesce(
                func.sum(case((is_out & is_par_91_120, exposure), else_=0)), 0
            ).label("par_91_120"),
            func.coalesce(
                func.sum(case((is_out & is_par_120, exposure), else_=0)), 0
            ).label("par_120"),
            func.coalesce(func.sum(case((is_out & is_par_30, exposure), else_=0)), 0).label(
                "par_30"
            ),
        )
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(
            Agent,
            (normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name))
            & (Agent.agency_id == Agency.id),
        )
        .where(LoanRaw.snapshot_date == snapshot_date)
        .group_by(Agency.id, Agent.id)
    ).mappings()

    count = 0
    for row in rows:
        db.add(DailyMetric(date=snapshot_date, **dict(row)))
        count += 1
    db.flush()
    return count


def recalculate_all_daily_metrics(db: Session) -> int:
    dates = db.scalars(select(LoanRaw.snapshot_date).distinct()).all()
    total = 0
    for snapshot_date in dates:
        total += recalculate_daily_metrics(db, snapshot_date)
    return total
