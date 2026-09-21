from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "tmp_import_fk_pending.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "ImportFkPendingTestsSecretKey!2026"
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BONUS_MODULE_ACTIVE"] = "false"
os.environ["BOOTSTRAP_SUPERADMIN_EMAIL"] = ""
os.environ["BOOTSTRAP_SUPERADMIN_PASSWORD"] = ""

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import event, select, text

from app.core.config import get_settings

get_settings.cache_clear()

from app.main import app
from app.core.security import hash_password
from app.db.base import Base
from app.db.migrations import add_missing_columns
from app.db.session import SessionLocal, engine
from app.models.entities import (
    Agency,
    Agent,
    ImportBatch,
    LoanRaw,
    PendingRestructuredContract,
    User,
)
from app.models.enums import ImportBatchType, UserRole


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """SQLite needs PRAGMA foreign_keys=ON to actually enforce FKs; without it
    the test would silently pass even if a delete is technically invalid.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _build_current_state_import_bytes(
    *,
    contract_no: str = "FK-CURRENT-001",
    snapshot: date = date(2026, 7, 31),
    agency_name: str = "Agence FK",
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "CONTRACT_NO",
            "CLIENT_NO",
            "BRANCH",
            "DAO_NAME",
            "DISBURSEMENT_AMOUNT",
            "PRINCIPAL_OUTSTANDING",
            "TOTAL_PRINCIPAL_DUE_AMT",
            "TOTAL_CUR_NO_OF_DAYS_OVERDUE",
            "TOTAL_DUE_AMT",
            "DISBURSEMENT_DATE",
            "DateEOD",
            "CATEGORY_DESC",
        ]
    )
    sheet.append(
        [
            contract_no,
            "CLI-FK-001",
            agency_name,
            "Agent FK",
            1500,
            1000,
            100,
            0,
            100,
            date(2026, 7, 15),
            snapshot,
            "Micro",
        ]
    )
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class ImportHistoricalForeignKeyTestCase(unittest.TestCase):
    super_admin_email = "fk.superadmin@microcred.com.tn"
    super_admin_password = "FkSuperAdmin!2026"

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        add_missing_columns(engine)
        self.client = TestClient(app)
        self._seed()

    def tearDown(self) -> None:
        self.client.close()

    def _seed(self) -> None:
        with SessionLocal() as db:
            db.add(
                User(
                    email=self.super_admin_email,
                    full_name="FK Test Super Admin",
                    hashed_password=hash_password(self.super_admin_password),
                    role=UserRole.SUPER_ADMIN,
                    password_changed_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

    def _login(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.super_admin_email, "password": self.super_admin_password},
        )
        self.assertEqual(response.status_code, 200, response.text)

    # ----------------------------------------------------------------------
    # 1. Reproduction scenario: SNAPSHOT batch pointed to by a
    #    pending_restructured_contract must be deletable without raising a
    #    ForeignKeyViolation. The detected_from_import column is nullable, so
    #    the delete path must clear it (SET NULL) instead of failing.
    # ----------------------------------------------------------------------
    def test_delete_snapshot_batches_with_pending_restructured_contracts(self) -> None:
        # Seed a SNAPSHOT batch with a loan row and a pending_restructured_contract
        # pointing to it (the production scenario).
        with SessionLocal() as db:
            agency = Agency(name="Agence FK")
            db.add(agency)
            db.flush()
            agent = Agent(name="Agent FK", agency_id=agency.id)
            db.add(agent)
            db.flush()
            snapshot_batch = ImportBatch(
                batch_type=ImportBatchType.SNAPSHOT,
                period=None,
                snapshot_date=date(2026, 6, 15),
                file_name="snapshot.xlsx",
            )
            db.add(snapshot_batch)
            db.flush()
            db.add(
                LoanRaw(
                    contract_no="FK-SNAP-001",
                    client_id="CLI-FK-001",
                    client_name="Client A",
                    client_first_name="Prenom",
                    agency_name=agency.name,
                    agent_name=agent.name,
                    disbursement_amount=Decimal("1500"),
                    principal_outstanding=Decimal("1000"),
                    principal_due=Decimal("100"),
                    total_scheduled_amount=Decimal("100"),
                    days_overdue=0,
                    total_due=Decimal("100"),
                    disbursement_date=date(2026, 1, 1),
                    snapshot_date=date(2026, 6, 15),
                    import_batch_id=snapshot_batch.id,
                )
            )
            pending = PendingRestructuredContract(
                contract_no="FK-SNAP-001",
                normalized_contract_no="FK-SNAP-001",
                credit_family="restructured",
                client_name="Client A",
                client_first_name="Prenom",
                agency_name=agency.name,
                agent_name=agent.name,
                disbursement_date=date(2026, 1, 1),
                disbursement_amount=Decimal("1000"),
                total_due=Decimal("100"),
                loan_duration=12,
                missing_fields=[],
                status="pending",
                detected_from_import=snapshot_batch.id,
            )
            db.add(pending)
            db.commit()
            snapshot_batch_id = snapshot_batch.id
            pending_id = pending.id

        self._login()
        # Now delete the snapshot batch via the super admin endpoint.
        delete_response = self.client.post(
            "/api/v1/imports/snapshots/delete",
            json={"batch_ids": [snapshot_batch_id]},
        )
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertEqual(delete_response.json()["deleted_batch_ids"], [snapshot_batch_id])

        # The ImportBatch must be gone, the pending row must survive but its
        # detected_from_import must be cleared (SET NULL), preserving the
        # user's pending work.
        with SessionLocal() as db:
            self.assertIsNone(db.get(ImportBatch, snapshot_batch_id))
            surviving = db.get(PendingRestructuredContract, pending_id)
            self.assertIsNotNone(surviving)
            self.assertIsNone(surviving.detected_from_import)

    # ----------------------------------------------------------------------
    # 2. /imports/historical must succeed when a previous period contains
    #    snapshot batches referenced by pending_restructured_contracts.
    # ----------------------------------------------------------------------
    def test_historical_import_succeeds_when_period_has_pending_fk(self) -> None:
        self._login()
        # Seed two SNAPSHOT batches in the same period (June 2026).
        with SessionLocal() as db:
            agency = Agency(name="Agence Histo")
            db.add(agency)
            db.flush()
            agent = Agent(name="Agent Histo", agency_id=agency.id)
            db.add(agent)
            db.flush()

            snapshot_batches: list[int] = []
            for day in (5, 20):
                batch = ImportBatch(
                    batch_type=ImportBatchType.SNAPSHOT,
                    period=None,
                    snapshot_date=date(2026, 6, day),
                    file_name=f"snap_{day}.xlsx",
                )
                db.add(batch)
                db.flush()
                snapshot_batches.append(batch.id)

                # A loan row for the snapshot to have a payload.
                db.add(
                    LoanRaw(
                        contract_no=f"CT-{day:03d}",
                        client_id=f"CLI-{day:03d}",
                        client_name="Client",
                        client_first_name="Prenom",
                        agency_name=agency.name,
                        agent_name=agent.name,
                        disbursement_amount=Decimal("1500"),
                        principal_outstanding=Decimal("1000"),
                        principal_due=Decimal("100"),
                        total_scheduled_amount=Decimal("100"),
                        days_overdue=0,
                        total_due=Decimal("100"),
                        disbursement_date=date(2026, 1, 1),
                        snapshot_date=date(2026, 6, day),
                        import_batch_id=batch.id,
                    )
                )

                # A pending_restructured_contract linked to this snapshot,
                # exactly the scenario from the production bug.
                db.add(
                    PendingRestructuredContract(
                        contract_no=f"CT-{day:03d}",
                        normalized_contract_no=f"CT-{day:03d}",
                        credit_family="restructured",
                        client_name="Client",
                        client_first_name="Prenom",
                        agency_name=agency.name,
                        agent_name=agent.name,
                        disbursement_date=date(2026, 1, 1),
                        disbursement_amount=Decimal("1000"),
                        total_due=Decimal("100"),
                        loan_duration=12,
                        missing_fields=[],
                        status="pending",
                        detected_from_import=batch.id,
                    )
                )
            db.commit()
            snapshot_ids = list(snapshot_batches)

        # Now trigger the historical import for the same period with
        # replace_existing=True. This used to raise ForeignKeyViolation.
        content = _build_current_state_import_bytes(
            contract_no="FK-HISTO-NEW",
            snapshot=date(2026, 6, 30),
        )
        response = self.client.post(
            "/api/v1/imports/historical",
            data={"period": "2026-06", "replace_existing": "true"},
            files={"file": ("historical.xlsx", content,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("import_batch", payload)

        # Old SNAPSHOT batches must be gone; their pending rows must survive
        # with detected_from_import=NULL. The new HISTORICAL batch is created.
        with SessionLocal() as db:
            # No SNAPSHOT batch should remain for the period (or globally).
            remaining_snapshots = db.scalars(
                select(ImportBatch).where(ImportBatch.batch_type == ImportBatchType.SNAPSHOT)
            ).all()
            self.assertEqual(
                remaining_snapshots,
                [],
                "All SNAPSHOT batches for the period must be deleted",
            )
            # The two originally seeded batches must be gone (their ids may be
            # reused by the new HISTORICAL insert, but their row objects do
            # not exist anymore because the autoflush deleted them).
            for batch_id in snapshot_ids:
                still_existing = db.scalar(
                    select(ImportBatch).where(
                        ImportBatch.id == batch_id,
                        ImportBatch.batch_type == ImportBatchType.SNAPSHOT,
                    )
                )
                self.assertIsNone(still_existing)
            # The new historical batch is created.
            new_historical = db.scalar(
                select(ImportBatch).where(
                    ImportBatch.batch_type == ImportBatchType.HISTORICAL_MONTH,
                    ImportBatch.period == "2026-06",
                )
            )
            self.assertIsNotNone(new_historical)
            # No pending row remains pointing to a missing import_batches.id.
            orphans = db.execute(
                text(
                    "SELECT p.id FROM pending_restructured_contracts p "
                    "LEFT JOIN import_batches i ON i.id = p.detected_from_import "
                    "WHERE p.detected_from_import IS NOT NULL AND i.id IS NULL"
                )
            ).all()
            self.assertEqual(orphans, [])
            # The two pending rows must still exist with detected_from_import=NULL.
            surviving = db.scalars(
                select(PendingRestructuredContract).order_by(PendingRestructuredContract.id)
            ).all()
            self.assertEqual(len(surviving), 2)
            for row in surviving:
                self.assertIsNone(row.detected_from_import)

    # ----------------------------------------------------------------------
    # 3. _delete_snapshots_for_period must be safe to call on a period that
    #    has NO batches (no FK error, no exception).
    # ----------------------------------------------------------------------
    def test_delete_snapshots_for_period_is_safe_when_empty(self) -> None:
        from app.services.imports import _delete_snapshots_for_period

        with SessionLocal() as db:
            deleted_batches, deleted_rows = _delete_snapshots_for_period(db, "2099-12")
            self.assertEqual(deleted_batches, 0)
            self.assertEqual(deleted_rows, 0)

    # ----------------------------------------------------------------------
    # 4. _delete_batch_payload must clear detected_from_import on dependent
    #    pending rows (same hook as the snapshot delete path).
    # ----------------------------------------------------------------------
    def test_delete_batch_payload_detaches_pending_restructured_contracts(self) -> None:
        from app.services.imports import _delete_batch_payload

        with SessionLocal() as db:
            agency = Agency(name="Agence Payload")
            db.add(agency)
            db.flush()
            agent = Agent(name="Agent Payload", agency_id=agency.id)
            db.add(agent)
            db.flush()
            batch = ImportBatch(
                batch_type=ImportBatchType.HISTORICAL_MONTH,
                period="2026-04",
                snapshot_date=date(2026, 4, 30),
                file_name="payload.xlsx",
            )
            db.add(batch)
            db.flush()
            pending = PendingRestructuredContract(
                contract_no="CT-PAYLOAD",
                normalized_contract_no="CT-PAYLOAD",
                credit_family="restructured",
                client_name="Client",
                client_first_name="Prenom",
                agency_name=agency.name,
                agent_name=agent.name,
                disbursement_date=date(2026, 1, 1),
                disbursement_amount=Decimal("1000"),
                total_due=Decimal("100"),
                loan_duration=12,
                missing_fields=[],
                status="pending",
                detected_from_import=batch.id,
            )
            db.add(pending)
            db.commit()
            batch_id = batch.id
            pending_id = pending.id

        with SessionLocal() as db:
            batch = db.get(ImportBatch, batch_id)
            _delete_batch_payload(db, batch)
            db.commit()

        with SessionLocal() as db:
            self.assertIsNone(db.get(ImportBatch, batch_id))
            surviving = db.get(PendingRestructuredContract, pending_id)
            self.assertIsNotNone(surviving)
            self.assertIsNone(surviving.detected_from_import)

    # ----------------------------------------------------------------------
    # 5. delete_snapshot_batches must clean up ALL dependencies (loans_raw,
    #    taeg_daily_snapshots, pending_restructured_contracts) in a single
    #    transaction, leaving no orphan rows.
    # ----------------------------------------------------------------------
    def test_delete_snapshot_batches_no_orphans(self) -> None:
        self._login()
        # Seed a SNAPSHOT batch with a TAEG daily snapshot and a pending
        # restructured contract pointing to it.
        with SessionLocal() as db:
            agency = Agency(name="Agence Orphan")
            db.add(agency)
            db.flush()
            agent = Agent(name="Agent Orphan", agency_id=agency.id)
            db.add(agent)
            db.flush()
            batch = ImportBatch(
                batch_type=ImportBatchType.SNAPSHOT,
                period=None,
                snapshot_date=date(2026, 3, 10),
                file_name="orphan.xlsx",
            )
            db.add(batch)
            db.flush()
            db.add(
                LoanRaw(
                    contract_no="ORPHAN-001",
                    client_id="CLI-ORPHAN",
                    client_name="Client",
                    client_first_name="Prenom",
                    agency_name=agency.name,
                    agent_name=agent.name,
                    disbursement_amount=Decimal("1000"),
                    principal_outstanding=Decimal("800"),
                    principal_due=Decimal("100"),
                    total_scheduled_amount=Decimal("100"),
                    days_overdue=0,
                    total_due=Decimal("100"),
                    disbursement_date=date(2026, 1, 1),
                    snapshot_date=date(2026, 3, 10),
                    import_batch_id=batch.id,
                )
            )
            from app.models.entities import TaegDailySnapshot
            db.add(
                TaegDailySnapshot(
                    import_batch_id=batch.id,
                    snapshot_date=date(2026, 3, 10),
                    period_month=3,
                    period_year=2026,
                    agency_id=agency.id,
                    agent_id=agent.id,
                    sector_name="Production",
                    credits_count=1,
                    disbursement_amount=Decimal("1000"),
                    taeg_calculated=Decimal("0"),
                    taeg_weighted_rate=Decimal("0"),
                    acm_rate=Decimal("0"),
                    status="conforme",
                )
            )
            db.add(
                PendingRestructuredContract(
                    contract_no="ORPHAN-001",
                    normalized_contract_no="ORPHAN-001",
                    credit_family="restructured",
                    client_name="Client",
                    client_first_name="Prenom",
                    agency_name=agency.name,
                    agent_name=agent.name,
                    disbursement_date=date(2026, 1, 1),
                    disbursement_amount=Decimal("1000"),
                    total_due=Decimal("100"),
                    loan_duration=12,
                    missing_fields=[],
                    status="pending",
                    detected_from_import=batch.id,
                )
            )
            db.commit()
            batch_id = batch.id
            pending_id = db.scalar(
                select(PendingRestructuredContract).where(
                    PendingRestructuredContract.contract_no == "ORPHAN-001"
                )
            ).id

        response = self.client.post(
            "/api/v1/imports/snapshots/delete",
            json={"batch_ids": [batch_id]},
        )
        self.assertEqual(response.status_code, 200, response.text)

        with SessionLocal() as db:
            self.assertIsNone(db.get(ImportBatch, batch_id))
            self.assertEqual(
                db.scalar(
                    select(LoanRaw).where(LoanRaw.import_batch_id == batch_id)
                ),
                None,
            )
            surviving = db.get(PendingRestructuredContract, pending_id)
            self.assertIsNotNone(surviving)
            self.assertIsNone(surviving.detected_from_import)


if __name__ == "__main__":
    unittest.main()