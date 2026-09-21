"""
Tests for the deep fix of the "Contrats à compléter" feature.

Covers:
  T1. CATEGORY_DESC variants (singular, mixed case, accents, spaces, typos)
  T2. Empty MCR / no tracked categories
  T3. All eligible contracts already in restructured_contracts
  T4. Several loans for the same contract in the MCR -> one pending row
  T5. Loan with NULL import_batch_id is still picked up by resync
  T6. Loan with category_desc that was previously unrecognized becomes recognized
  T7. Resync is idempotent (no duplicates, fields refreshed)
  T8. The resync HTTP endpoint requires SUPER_ADMIN/SUPPORT
  T9. The diagnostics HTTP endpoint returns the expected counters
  T10. A loan already in restructured_contracts is NOT added by resync
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

_SENTINEL = object()
TEST_DB_PATH = BACKEND_DIR / "tmp_pending_deep_fix.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "DeepFixNeedsAVeryStrongSecret!2026"
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
    CONSOLIDATED_FAMILY,
    RESTRUCTURED_FAMILY,
    _tracked_mcr_credit_family,
    get_pending_restructured_contracts_diagnostics,
    list_pending_restructured_contracts,
    resync_pending_restructured_contracts_from_all_mcr,
    sync_pending_restructured_contracts_from_mcr_batch,
)


class PendingDeepFixTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        add_missing_columns(engine)
        self.client = TestClient(app)

    def _create_user(self, role: UserRole, email: str, password: str = "Pass!12345") -> int:
        with SessionLocal() as db:
            u = User(
                email=email,
                full_name=email.split("@")[0].title(),
                hashed_password=hash_password(password),
                role=role,
                is_active=True,
                must_change_password=False,
                password_changed_at=datetime.now(timezone.utc),
            )
            db.add(u)
            db.commit()
            db.refresh(u)
            return u.id

    def _login(self, email: str, password: str) -> None:
        response = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)

    def _seed_mcr(self, loans: list[dict[str, object]], *, snapshot_date: date = date(2026, 7, 31), import_batch_id: int | None | object = _SENTINEL) -> int:
        """Seed an ImportBatch + LoanRaw rows. Returns the batch.id.

        `import_batch_id` distinguishes three cases:
        - omitted (default) -> the freshly created batch.id is used
        - explicit value (int or None) -> that value is used (use None to simulate a backfilled LoanRaw)
        """
        if import_batch_id is _SENTINEL:
            effective_batch_id = None  # set below after flush
        else:
            effective_batch_id = import_batch_id
        with SessionLocal() as db:
            batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=snapshot_date,
                file_name="current_mcr.xlsx",
            )
            db.add(batch)
            db.flush()
            if effective_batch_id is None and import_batch_id is _SENTINEL:
                # default case: link the loans to the freshly created batch
                effective_batch_id = batch.id
            for idx, loan in enumerate(loans, start=1):
                db.add(LoanRaw(
                    contract_no=str(loan["contract_no"]),
                    client_name=str(loan.get("client_name") or f"Client {idx}"),
                    client_first_name=str(loan.get("client_first_name") or "X"),
                    client_id=str(loan.get("client_id") or f"CLI-{idx:04d}"),
                    agency_name=str(loan.get("agency_name") or "Agence Centre"),
                    agent_name=str(loan.get("agent_name") or "GP Centre"),
                    category_desc=loan.get("category_desc"),
                    disbursement_amount=Decimal(str(loan.get("disbursement_amount") or "25000")),
                    principal_outstanding=Decimal(str(loan.get("principal_outstanding") or "1000")),
                    principal_due=Decimal(str(loan.get("principal_due") or "100")),
                    total_scheduled_amount=Decimal("100"),
                    days_overdue=int(loan.get("days_overdue") or 0),
                    total_due=loan.get("total_due"),
                    status=str(loan.get("status") or "active"),
                    disbursement_date=loan.get("disbursement_date") or date(2026, 7, 7),
                    snapshot_date=snapshot_date,
                    import_batch_id=effective_batch_id,
                ))
            db.commit()
            return batch.id

    def _seed_official(self, contract_nos: list[str]) -> None:
        with SessionLocal() as db:
            for no in contract_nos:
                db.add(RestructuredContract(
                    contract_no=no,
                    normalized_contract_no=no,
                    credit_family=RESTRUCTURED_FAMILY,
                ))
            db.commit()

    def _pending_contract_nos(self) -> list[str]:
        with SessionLocal() as db:
            page = list_pending_restructured_contracts(db, limit=500, offset=0)
            return sorted(item.contract_no for item in page.items)

    def test_T1_category_desc_variants_are_all_recognized(self) -> None:
        """All realistic variants of the category must map to a tracked family."""
        cases = [
            ("Credits Consolidés", CONSOLIDATED_FAMILY),
            ("Credits Restructurés", RESTRUCTURED_FAMILY),
            ("Credit Consolide", CONSOLIDATED_FAMILY),
            ("Credit Restructure", RESTRUCTURED_FAMILY),
            ("credits consolides", CONSOLIDATED_FAMILY),
            ("CREDIT CONSOLIDE", CONSOLIDATED_FAMILY),
            ("  Credits  Consolidés  ", CONSOLIDATED_FAMILY),
            ("Restructure", RESTRUCTURED_FAMILY),
            ("Consolide", CONSOLIDATED_FAMILY),
            ("Restructuration", RESTRUCTURED_FAMILY),
            ("Credit Consolide Restructure", CONSOLIDATED_FAMILY),  # priority: consolid first
            ("Crédit Normal", None),
            ("", None),
            (None, None),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(_tracked_mcr_credit_family(raw), expected, f"raw={raw!r}")

    def test_T2_no_tracked_category_yields_empty_list(self) -> None:
        """When the MCR contains no eligible category, the list must be empty."""
        batch_id = self._seed_mcr([
            {"contract_no": "X-001", "category_desc": "Crédit Normal"},
            {"contract_no": "X-002", "category_desc": "Crédit Normal"},
        ])
        with SessionLocal() as db:
            batch = db.get(ImportBatch, batch_id)
            sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            db.commit()
        self.assertEqual(self._pending_contract_nos(), [])

    def test_T3_all_eligible_contracts_already_in_official_list(self) -> None:
        """If every tracked contract is already in restructured_contracts, the list is empty."""
        self._seed_official(["100001", "100002"])
        self._seed_mcr([
            {"contract_no": "100001", "category_desc": "Credits Restructurés"},
            {"contract_no": "100002", "category_desc": "Credits Consolidés"},
        ])
        with SessionLocal() as db:
            resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        self.assertEqual(self._pending_contract_nos(), [])

    def test_T4_duplicates_in_mcr_collapse_to_one_pending_row(self) -> None:
        """Several loans for the same contract must produce one pending entry."""
        # In a real import the upsert path dedupes (contract_no, snapshot_date).
        # We simulate that by giving the two rows for C-001 different snapshot_dates
        # (which is the realistic case: a contract appears in two snapshots over time).
        self._seed_mcr([
            {"contract_no": "C-001", "category_desc": "Credits Restructurés", "total_due": Decimal("500")},
        ], snapshot_date=date(2026, 7, 30))
        self._seed_mcr([
            {"contract_no": "C-001", "category_desc": "Credits Restructurés", "total_due": Decimal("999")},
            {"contract_no": "C-002", "category_desc": "Credits Consolidés"},
        ], snapshot_date=date(2026, 7, 31))
        with SessionLocal() as db:
            summary = resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        self.assertEqual(summary["new_detected"], 2)
        self.assertEqual(self._pending_contract_nos(), ["C-001", "C-002"])
        with SessionLocal() as db:
            row = db.query(PendingRestructuredContract).filter_by(contract_no="C-001").first()
            # The most recent snapshot wins (order_by id.desc() => id order; we
            # inserted older first, so the later (999) row is processed last)
            self.assertEqual(row.total_due, Decimal("999"))

    def test_T5_loans_with_null_import_batch_are_picked_up_by_resync(self) -> None:
        """A loan with NULL import_batch_id (e.g. from a backfill) is still recognized by resync."""
        from sqlalchemy import select
        self._seed_mcr([
            {"contract_no": "NULL-1", "category_desc": "Credits Restructurés"},
            {"contract_no": "NULL-2", "category_desc": "Credits Consolidés"},
        ], import_batch_id=None)
        # The per-batch sync sees ZERO loans (no batch_id match) and adds nothing
        with SessionLocal() as db:
            for batch in db.scalars(select(ImportBatch)).all():
                sync_pending_restructured_contracts_from_mcr_batch(db, batch)
                db.commit()
        self.assertEqual(self._pending_contract_nos(), [])
        # ...but the resync scans the whole table
        with SessionLocal() as db:
            summary = resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        self.assertEqual(summary["new_detected"], 2)
        self.assertEqual(self._pending_contract_nos(), ["NULL-1", "NULL-2"])

    def test_T6_singular_category_desc_is_recognized(self) -> None:
        """Singular "Credit Consolide" (the real-world variant) must produce a pending row."""
        self._seed_mcr([
            {"contract_no": "S-1", "category_desc": "Credit Consolide"},
            {"contract_no": "S-2", "category_desc": "Credit Restructure"},
        ])
        with SessionLocal() as db:
            summary = resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        self.assertEqual(summary["new_detected"], 2)
        self.assertEqual(self._pending_contract_nos(), ["S-1", "S-2"])

    def test_T7_resync_is_idempotent_and_updates_existing_rows(self) -> None:
        """Running resync twice must not create duplicates and must refresh fields."""
        self._seed_mcr([
            {"contract_no": "ID-1", "category_desc": "Credit Consolide", "total_due": Decimal("100")},
        ])
        with SessionLocal() as db:
            s1 = resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        self.assertEqual(s1["new_detected"], 1)
        with SessionLocal() as db:
            row = db.query(PendingRestructuredContract).filter_by(contract_no="ID-1").first()
            row.total_due = Decimal("999")  # simulate manual edit
            db.commit()
        with SessionLocal() as db:
            s2 = resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        self.assertEqual(s2["new_detected"], 0)
        self.assertEqual(s2["updated_existing"], 1)
        self.assertEqual(self._pending_contract_nos(), ["ID-1"])
        with SessionLocal() as db:
            row = db.query(PendingRestructuredContract).filter_by(contract_no="ID-1").first()
            self.assertEqual(row.total_due, Decimal("100"))  # resync restored from MCR

    def test_T8_resync_endpoint_requires_super_admin_or_support(self) -> None:
        self._create_user(UserRole.AGENCY_MANAGER, "am@x.tn")
        self._create_user(UserRole.PORTFOLIO_MANAGER, "pm@x.tn")
        self._create_user(UserRole.ADMIN, "ad@x.tn")
        self._create_user(UserRole.COMMITTEE_MEMBER, "cm@x.tn")
        self._create_user(UserRole.SUPER_ADMIN, "sa@x.tn")
        # Unauthenticated
        r = self.client.post("/api/v1/imports/restructured-pending/resync")
        self.assertEqual(r.status_code, 401, r.text)
        # Wrong roles
        for email, pwd in [("am@x.tn", "Pass!12345"), ("pm@x.tn", "Pass!12345"), ("ad@x.tn", "Pass!12345"), ("cm@x.tn", "Pass!12345")]:
            self.client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
            r = self.client.post("/api/v1/imports/restructured-pending/resync")
            self.assertIn(r.status_code, (401, 403), r.text)
            self.client.post("/api/v1/auth/logout")
        # SUPER_ADMIN ok
        self._login("sa@x.tn", "Pass!12345")
        r = self.client.post("/api/v1/imports/restructured-pending/resync")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("pending_to_complete", body)
        self.assertIn("new_detected", body)
        self.assertIn("loans_scanned", body)

    def test_T9_diagnostics_endpoint_returns_counters(self) -> None:
        self._create_user(UserRole.SUPER_ADMIN, "sa@x.tn")
        self._login("sa@x.tn", "Pass!12345")
        self._seed_mcr([
            {"contract_no": "D-1", "category_desc": "Credits Restructurés"},
            {"contract_no": "D-2", "category_desc": "Credits Consolidés"},
            {"contract_no": "D-3", "category_desc": "Crédit Normal"},
        ])
        r = self.client.get("/api/v1/imports/restructured-pending/diagnostics")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["loans_total"], 3)
        self.assertEqual(body["loans_with_category_desc"], 3)
        self.assertGreaterEqual(body["loans_restructured_distinct"], 1)
        self.assertGreaterEqual(body["loans_consolidated_distinct"], 1)
        self.assertEqual(body["pending_restructured_contracts"], 0)
        # After a resync, the pending count should be 2
        r2 = self.client.post("/api/v1/imports/restructured-pending/resync")
        self.assertEqual(r2.status_code, 200, r2.text)
        r3 = self.client.get("/api/v1/imports/restructured-pending/diagnostics")
        self.assertEqual(r3.status_code, 200, r3.text)
        self.assertEqual(r3.json()["pending_restructured_contracts"], 2)

    def test_T10_official_list_contracts_are_never_added_to_pending(self) -> None:
        self._seed_official(["OFF-1"])
        self._seed_mcr([
            {"contract_no": "OFF-1", "category_desc": "Credits Restructurés"},
            {"contract_no": "OFF-2", "category_desc": "Credits Consolidés"},
        ])
        with SessionLocal() as db:
            summary = resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()
        self.assertEqual(summary["new_detected"], 1)
        self.assertEqual(summary["already_present"], 1)
        self.assertEqual(self._pending_contract_nos(), ["OFF-2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
