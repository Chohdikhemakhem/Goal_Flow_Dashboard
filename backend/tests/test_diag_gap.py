"""
Reproduce the user's exact scenario: 718 pending rows but the table returns 0.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "tmp_diag_gap.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "GapTestNeedsAVeryStrongSecret!2026"
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BONUS_MODULE_ACTIVE"] = "false"
os.environ["BOOTSTRAP_SUPERADMIN_EMAIL"] = ""
os.environ["BOOTSTRAP_SUPERADMIN_PASSWORD"] = ""

from app.core.config import get_settings
get_settings.cache_clear()

from app.core.security import hash_password
from app.db.base import Base
from app.db.migrations import add_missing_columns
from app.db.session import SessionLocal, engine
from app.main import app
from app.models.entities import (
    ImportBatch,
    LoanRaw,
    PendingRestructuredContract,
    RestructuredContract,
    User,
)
from app.models.enums import ImportBatchType, UserRole
from app.services.restructured import (
    list_pending_restructured_contracts,
    resync_pending_restructured_contracts_from_all_mcr,
    get_pending_restructured_contracts_diagnostics,
)


class DiagGapTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        add_missing_columns(engine)
        self.client = TestClient(app)
        with SessionLocal() as db:
            u = User(
                email="sa@x.tn", full_name="SA", role=UserRole.SUPER_ADMIN,
                hashed_password=hash_password("Pass!12345"),
                is_active=True, must_change_password=False,
                password_changed_at=datetime.now(timezone.utc),
            )
            db.add(u)
            db.commit()

    def test_reproduce_diagnostic_vs_table_gap(self) -> None:
        """Reproduce: diagnostic shows N pending but table shows 0."""
        # Seed an MCR with 800 loans (mix of restructured + consolidated + normal)
        with SessionLocal() as db:
            batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=date(2026, 7, 31),
                file_name="big_mcr.xlsx",
            )
            db.add(batch)
            db.flush()
            n_restructured = 600
            n_consolidated = 200
            n_normal = 800
            counter = 0
            for i in range(n_restructured):
                counter += 1
                db.add(LoanRaw(
                    contract_no=f"R-{counter:06d}", client_name=f"C{counter}",
                    client_first_name="X", client_id=f"CLI-{counter:04d}",
                    agency_name="Agence Centre", agent_name="GP Centre",
                    category_desc="Credits Restructurés",
                    disbursement_amount=Decimal("1000"),
                    principal_outstanding=Decimal("500"),
                    principal_due=Decimal("100"),
                    total_scheduled_amount=Decimal("100"),
                    days_overdue=0, total_due=Decimal("500"),
                    status="active", disbursement_date=date(2026, 7, 7),
                    snapshot_date=batch.snapshot_date,
                    import_batch_id=batch.id,
                ))
            for i in range(n_consolidated):
                counter += 1
                db.add(LoanRaw(
                    contract_no=f"C-{counter:06d}", client_name=f"C{counter}",
                    client_first_name="X", client_id=f"CLI-{counter:04d}",
                    agency_name="Agence Centre", agent_name="GP Centre",
                    category_desc="Credits Consolidés",
                    disbursement_amount=Decimal("1000"),
                    principal_outstanding=Decimal("500"),
                    principal_due=Decimal("100"),
                    total_scheduled_amount=Decimal("100"),
                    days_overdue=0, total_due=Decimal("500"),
                    status="active", disbursement_date=date(2026, 7, 7),
                    snapshot_date=batch.snapshot_date,
                    import_batch_id=batch.id,
                ))
            for i in range(n_normal):
                counter += 1
                db.add(LoanRaw(
                    contract_no=f"N-{counter:06d}", client_name=f"C{counter}",
                    client_first_name="X", client_id=f"CLI-{counter:04d}",
                    agency_name="Agence Centre", agent_name="GP Centre",
                    category_desc="Crédit Normal",
                    disbursement_amount=Decimal("1000"),
                    principal_outstanding=Decimal("500"),
                    principal_due=Decimal("100"),
                    total_scheduled_amount=Decimal("100"),
                    days_overdue=0, total_due=Decimal("500"),
                    status="active", disbursement_date=date(2026, 7, 7),
                    snapshot_date=batch.snapshot_date,
                    import_batch_id=batch.id,
                ))
            # 100 of the restructured contracts are already in the official list
            for i in range(1, 101):
                db.add(RestructuredContract(
                    contract_no=f"R-{i:06d}", normalized_contract_no=f"R-{i:06d}",
                    credit_family="restructured",
                ))
            db.commit()

        # Step 1: resync to populate pending table
        with SessionLocal() as db:
            summary = resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        print(f"\n=== Resync summary: {summary} ===")
        self.assertEqual(summary["new_detected"], 700, summary)
        self.assertEqual(summary["already_present"], 100, summary)
        self.assertEqual(summary["pending_to_complete"], 700, summary)

        # Step 2: get diagnostics
        with SessionLocal() as db:
            diag = get_pending_restructured_contracts_diagnostics(db)
        print(f"\n=== Diagnostics: {diag} ===")
        self.assertEqual(diag["pending_restructured_contracts"], 700)

        # Step 3: call list endpoint with empty q, empty status, limit=10, offset=0
        with SessionLocal() as db:
            page = list_pending_restructured_contracts(db, q=None, status=None, limit=10, offset=0)
        print(f"\n=== List endpoint: total={page.total}, returned items={len(page.items)} ===")
        for item in page.items:
            print(f"  - {item.contract_no} (status={item.status})")
        self.assertEqual(page.total, 700, f"total should be 700 but got {page.total}")
        self.assertEqual(len(page.items), 10, f"items should be 10 but got {len(page.items)}")

    def test_http_endpoint_with_empty_params(self) -> None:
        """The exact same scenario but called via HTTP to see what the frontend receives."""
        # Seed same data as the previous test
        with SessionLocal() as db:
            batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=date(2026, 7, 31),
                file_name="big_mcr.xlsx",
            )
            db.add(batch)
            db.flush()
            for i in range(1, 801):
                cat = "Credits Restructurés" if i <= 600 else ("Credits Consolidés" if i <= 800 else "Crédit Normal")
                if i <= 800:
                    db.add(LoanRaw(
                        contract_no=f"X-{i:06d}", client_name=f"C{i}",
                        client_first_name="X", client_id=f"CLI-{i:04d}",
                        agency_name="Agence Centre", agent_name="GP Centre",
                        category_desc=cat,
                        disbursement_amount=Decimal("1000"),
                        principal_outstanding=Decimal("500"),
                        principal_due=Decimal("100"),
                        total_scheduled_amount=Decimal("100"),
                        days_overdue=0, total_due=Decimal("500"),
                        status="active", disbursement_date=date(2026, 7, 7),
                        snapshot_date=batch.snapshot_date,
                        import_batch_id=batch.id,
                    ))
            for i in range(1, 101):
                db.add(RestructuredContract(
                    contract_no=f"X-{i:06d}", normalized_contract_no=f"X-{i:06d}",
                    credit_family="restructured",
                ))
            db.commit()
        with SessionLocal() as db:
            resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()

        # Login
        r = self.client.post("/api/v1/auth/login", json={"email": "sa@x.tn", "password": "Pass!12345"})
        self.assertEqual(r.status_code, 200, r.text)

        # Try every combination the frontend might send
        cases = [
            ("/api/v1/imports/restructured-pending?limit=10&offset=0", "no q, no status"),
            ("/api/v1/imports/restructured-pending?limit=10&offset=0&status=", "empty status"),
            ("/api/v1/imports/restructured-pending?limit=10&offset=0&status=pending", "status=pending"),
            ("/api/v1/imports/restructured-pending?limit=10&offset=0&q=", "empty q (this should 422!)"),
            # === THE EXACT URL THE FRONTEND SENDS (with literal "undefined") ===
            ("/api/v1/imports/restructured-pending?limit=10&offset=0&q=undefined&status=undefined", "q=undefined&status=undefined (the real frontend bug)"),
        ]
        for url, desc in cases:
            r = self.client.get(url)
            print(f"\n>>> [{desc}] GET {url}")
            print(f">>> status={r.status_code}")
            if r.status_code == 200:
                body = r.json()
                print(f">>> body keys: {list(body.keys())}, total={body.get('total')}, items={len(body.get('items', []))}")
            else:
                print(f">>> body: {r.text[:200]}")

    def test_diagnostic_says_700_but_table_endpoint_returns_0_with_dirty_data(self) -> None:
        """Real-world scenario: dirty data in pending table causes the list endpoint to fail
        with 500 even though the diagnostic COUNT succeeds. The frontend .catch() then
        returns empty -> user sees 0/0."""
        # Seed MCR + resync
        with SessionLocal() as db:
            batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=date(2026, 7, 31),
                file_name="big_mcr.xlsx",
            )
            db.add(batch)
            db.flush()
            for i in range(1, 101):
                db.add(LoanRaw(
                    contract_no=f"Y-{i:06d}", client_name=f"C{i}",
                    client_first_name="X", client_id=f"CLI-{i:04d}",
                    agency_name="Agence Centre", agent_name="GP Centre",
                    category_desc="Credits Restructurés",
                    disbursement_amount=Decimal("1000"),
                    principal_outstanding=Decimal("500"),
                    principal_due=Decimal("100"),
                    total_scheduled_amount=Decimal("100"),
                    days_overdue=0, total_due=Decimal("500"),
                    status="active", disbursement_date=date(2026, 7, 7),
                    snapshot_date=batch.snapshot_date,
                    import_batch_id=batch.id,
                ))
            db.commit()
        with SessionLocal() as db:
            resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        # Inject dirty data: a pending row with non-string items in missing_fields
        with SessionLocal() as db:
            row = db.query(PendingRestructuredContract).first()
            row.missing_fields = [{"field": "shift_date"}, "total_due"]  # mixed types
            db.commit()
        # Diagnostic count still works
        with SessionLocal() as db:
            diag = get_pending_restructured_contracts_diagnostics(db)
        self.assertEqual(diag["pending_restructured_contracts"], 100)
        # But the HTTP list endpoint will likely 500
        r = self.client.post("/api/v1/auth/login", json={"email": "sa@x.tn", "password": "Pass!12345"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.get("/api/v1/imports/restructured-pending?limit=10&offset=0")
        print(f"\n>>> [dirty data] status={r.status_code}, body={r.text[:300]}")
        # The frontend .catch would swallow this error and show 0/0


if __name__ == "__main__":
    unittest.main(verbosity=2)
