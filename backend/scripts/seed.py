from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from sqlalchemy import delete, func, select, update

from app.core.security import hash_password
from app.db.base import Base
from app.db.migrations import add_missing_columns
from app.db.session import SessionLocal, engine
from app.models.entities import Agency, Agent, BonusRule, LoanRaw, Target, User
from app.models.enums import UserRole
from app.services.user_accounts import (
    bootstrap_super_admin_from_env,
    ensure_agent_accounts,
    normalize_existing_accounts,
)
from app.services.metrics import recalculate_all_daily_metrics

LEGACY_DEMO_AGENCIES = ("Downtown", "North Branch")


def prune_legacy_demo_agencies(db) -> None:
    agencies = db.scalars(select(Agency).where(Agency.name.in_(LEGACY_DEMO_AGENCIES))).all()
    for agency in agencies:
        loan_count = db.scalar(
            select(func.count(LoanRaw.id)).where(LoanRaw.agency_name == agency.name)
        ) or 0
        if loan_count > 0:
            # Keep agencies that are backed by imported loan data.
            continue

        agent_ids = db.scalars(select(Agent.id).where(Agent.agency_id == agency.id)).all()
        db.execute(delete(Target).where(Target.agency_id == agency.id))

        if agent_ids:
            db.execute(
                update(User)
                .where(User.agent_id.in_(agent_ids))
                .values(agent_id=None, agency_id=None, is_active=False)
            )
            db.execute(delete(Agent).where(Agent.id.in_(agent_ids)))

        db.execute(
            update(User)
            .where(
                User.agency_id == agency.id,
                User.role.notin_([UserRole.SUPER_ADMIN, UserRole.ADMIN]),
            )
            .values(agency_id=None, is_active=False)
        )
        db.execute(delete(Agency).where(Agency.id == agency.id))


def main() -> None:
    Base.metadata.create_all(bind=engine)
    add_missing_columns(engine)
    db = SessionLocal()
    try:
        prune_legacy_demo_agencies(db)
        if not db.scalar(select(BonusRule).where(BonusRule.name == "Default Performance Bonus")):
            db.add(
                BonusRule(
                    name="Default Performance Bonus",
                    formula={
                        "expression": (
                            "250000 * ("
                            "0.35 * min(disbursement_volume / target_disbursement, 1) + "
                            "0.25 * min(outstanding / target_outstanding, 1) + "
                            "0.25 * min(healthy_outstanding / target_healthy_outstanding, 1) + "
                            "0.15 * max(1 - par_30_rate / target_par, 0)"
                            ")"
                        ),
                    },
                )
            )
        db.commit()
        recalculate_all_daily_metrics(db)
        ensure_agent_accounts(db)
        normalize_existing_accounts(db)
        bootstrap_super_admin_from_env(db)
        db.commit()
        print("Seed data ready")
    finally:
        db.close()


if __name__ == "__main__":
    main()
