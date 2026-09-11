from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.migrations import _migrate_par_reduction_targets
from app.models.entities import Agency, Agent, ImportBatch, LoanRaw, ParReductionTarget, User
from app.models.enums import ImportBatchType, UserRole
from app.services.par_reduction import (
    _latest_snapshot_before_month_start,
    _latest_snapshot_in_period,
    reduction_metric,
    resolve_reduction_scope,
)


def test_reduction_and_achievement_keep_positive_decrease():
    result = reduction_metric(Decimal("500000"), Decimal("420000"), Decimal("400000"))
    assert result["reduction_required"] == Decimal("100000")
    assert result["reduction_realized"] == Decimal("80000")
    assert result["achievement_rate"] == Decimal("80")


def test_reduction_keeps_negative_degradation():
    result = reduction_metric(Decimal("500000"), Decimal("530000"), Decimal("400000"))
    assert result["reduction_realized"] == Decimal("-30000")
    assert result["achievement_rate"] == Decimal("-30")


def test_zero_target_has_no_division_by_zero():
    result = reduction_metric(Decimal("500000"), Decimal("420000"), Decimal("500000"))
    assert result["reduction_required"] == Decimal("0")
    assert result["achievement_rate"] == Decimal("0")


def test_target_above_initial_is_invalid_and_has_no_fake_rate():
    result = reduction_metric(Decimal("500000"), Decimal("420000"), Decimal("550000"))
    assert result["valid_target"] is False
    assert result["reduction_required"] == Decimal("-50000")
    assert result["achievement_rate"] == Decimal("0")
    assert result["message"]


def test_agency_manager_scope_cannot_be_narrowed_by_request_agent_id():
    user = User(role=UserRole.AGENCY_MANAGER, agency_id=12, agent_id=45)
    assert resolve_reduction_scope(user, agency_id=99, agent_id=77) == (12, None)


def test_portfolio_manager_scope_is_forced_to_own_agent():
    user = User(role=UserRole.PORTFOLIO_MANAGER, agency_id=12, agent_id=45)
    assert resolve_reduction_scope(user, agency_id=99, agent_id=77) == (12, 45)


def test_initial_snapshot_uses_last_batch_before_month_start():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        session.add_all(
            [
                ImportBatch(batch_type=ImportBatchType.HISTORICAL_MONTH, period="2026-07", snapshot_date=date(2026, 7, 5), file_name="july-1.csv"),
                ImportBatch(batch_type=ImportBatchType.HISTORICAL_MONTH, period="2026-07", snapshot_date=date(2026, 7, 12), file_name="july-2.csv"),
                ImportBatch(batch_type=ImportBatchType.HISTORICAL_MONTH, period="2026-07", snapshot_date=date(2026, 7, 19), file_name="july-3.csv"),
                ImportBatch(batch_type=ImportBatchType.HISTORICAL_MONTH, period="2026-07", snapshot_date=date(2026, 7, 31), file_name="july-4.csv"),
                ImportBatch(batch_type=ImportBatchType.SNAPSHOT, period="2026-08", snapshot_date=date(2026, 8, 5), file_name="aug-1.csv"),
                ImportBatch(batch_type=ImportBatchType.SNAPSHOT, period="2026-08", snapshot_date=date(2026, 8, 12), file_name="aug-2.csv"),
                ImportBatch(batch_type=ImportBatchType.SNAPSHOT, period="2026-08", snapshot_date=date(2026, 8, 19), file_name="aug-3.csv"),
            ]
        )
        session.commit()

        initial_batch = _latest_snapshot_before_month_start(session, year=2026, month=8)
        current_batch = _latest_snapshot_in_period(session, year=2026, month=8, as_of=date(2026, 8, 20))

        assert initial_batch is not None
        assert initial_batch.snapshot_date == date(2026, 7, 31)
        assert current_batch is not None
        assert current_batch.snapshot_date == date(2026, 8, 19)


def test_target_migration_is_idempotent_after_startup():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE par_reduction_targets ADD COLUMN legacy_target_par30_reduction NUMERIC(18, 2)"))
        connection.execute(text("ALTER TABLE par_reduction_targets ADD COLUMN legacy_target_cohort_1_15_reduction NUMERIC(18, 2)"))
        connection.execute(text("ALTER TABLE par_reduction_targets ADD COLUMN legacy_target_cohort_16_30_reduction NUMERIC(18, 2)"))

    with Session(engine) as session:
        agency = Agency(name="Migration Agency")
        session.add(agency)
        session.flush()
        agent = Agent(name="Migration Agent", agency_id=agency.id)
        session.add(agent)
        session.flush()
        batch = ImportBatch(
            batch_type=ImportBatchType.HISTORICAL_MONTH,
            period="2026-07",
            snapshot_date=date(2026, 7, 31),
            file_name="july.csv",
        )
        session.add(batch)
        session.flush()
        session.add(
            LoanRaw(
                import_batch_id=batch.id,
                agency_name=agency.name,
                agent_name=agent.name,
                days_overdue=31,
                principal_outstanding=500000,
                principal_due=0,
            )
        )
        session.flush()
        session.execute(
            text(
                "INSERT INTO par_reduction_targets "
                "(agency_id, agent_id, month, year, target_par30, "
                "target_cohort_1_15, target_cohort_16_30, "
                "legacy_target_par30_reduction, legacy_target_cohort_1_15_reduction, "
                "legacy_target_cohort_16_30_reduction) "
                "VALUES (:agency_id, :agent_id, 8, 2026, 0, 0, 0, 100000, 0, 0)"
            ),
            {"agency_id": agency.id, "agent_id": agent.id},
        )
        session.commit()

    with engine.begin() as connection:
        _migrate_par_reduction_targets(connection)
        first_value = connection.execute(
            text("SELECT target_par30 FROM par_reduction_targets")
        ).scalar_one()
        _migrate_par_reduction_targets(connection)
        second_value = connection.execute(
            text("SELECT target_par30 FROM par_reduction_targets")
        ).scalar_one()

    assert first_value == 400000
    assert second_value == first_value