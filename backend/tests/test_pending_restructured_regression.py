"""
Regression tests for the "Contrats a completer" table returning 0 rows when
the backend diagnostic counts > 0.

ROOT CAUSE (found):
  Node.js' URLSearchParams serializes `undefined` as the literal STRING "undefined".
  The frontend passed `{ q: pendingSearch || undefined }` so when pendingSearch is "",
  q became undefined → URLSearchParams produced q=undefined → the backend matched
  nothing with ilike('%undefined%') → 0 rows.

  Node.js: new URLSearchParams({ b: undefined }).toString() === "b=undefined"

FIX:
  Backend: treat q="" / q="undefined" / q="null" as None (no filter).
  Frontend: cleanParams() strips undefined / null / empty-string values.
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

TEST_DB_PATH = BACKEND_DIR / "tmp_pending_regression.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "RegressionNeedsAVeryStrongSecret!2026"
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
from app.models.entities import ImportBatch, LoanRaw, RestructuredContract, User
from app.models.enums import ImportBatchType, UserRole
from app.services.restructured import (
    resync_pending_restructured_contracts_from_all_mcr,
    get_pending_restructured_contracts_diagnostics,
)


class PendingRegressionTestCase(unittest.TestCase):
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

    def _seed_mcr_with_800(self) -> None:
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
                cat = "Credits Restructurés" if i <= 600 else "Credits Consolidés"
                db.add(LoanRaw(
                    contract_no=f"R-{i:06d}", client_name=f"C{i}",
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
                    contract_no=f"R-{i:06d}", normalized_contract_no=f"R-{i:06d}",
                    credit_family="restructured",
                ))
            db.commit()
        with SessionLocal() as db:
            resync_pending_restructured_contracts_from_all_mcr(db)
            db.commit()

    def test_regression_q_undefined_string_does_not_filter_to_zero(self) -> None:
        """Reproduces the exact frontend bug: q=undefined&status=undefined in URL."""
        self._seed_mcr_with_800()
        self.client.post("/api/v1/auth/login", json={"email": "sa@x.tn", "password": "Pass!12345"})

        # The literal URL the frontend was sending (q=undefined as a real string)
        r = self.client.get("/api/v1/imports/restructured-pending?limit=10&offset=0&q=undefined&status=undefined")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["total"], 700, body)
        self.assertEqual(len(body["items"]), 10, body)

    def test_regression_empty_q_string_does_not_422(self) -> None:
        """Empty string q must not cause 422 and must not filter to zero."""
        self._seed_mcr_with_800()
        self.client.post("/api/v1/auth/login", json={"email": "sa@x.tn", "password": "Pass!12345"})

        r = self.client.get("/api/v1/imports/restructured-pending?limit=10&offset=0&q=")
        self.assertEqual(r.status_code, 200, r.text)  # was 422 before fix
        body = r.json()
        self.assertEqual(body["total"], 700, body)

    def test_regression_no_params_returns_all_pending(self) -> None:
        """No q, no status → all pending rows returned."""
        self._seed_mcr_with_800()
        self.client.post("/api/v1/auth/login", json={"email": "sa@x.tn", "password": "Pass!12345"})

        r = self.client.get("/api/v1/imports/restructured-pending?limit=10&offset=0")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["total"], 700, body)
        self.assertEqual(len(body["items"]), 10, body)

    def test_regression_status_empty_string_does_not_filter_to_zero(self) -> None:
        """Empty string status must not cause filtering or 422."""
        self._seed_mcr_with_800()
        self.client.post("/api/v1/auth/login", json={"email": "sa@x.tn", "password": "Pass!12345"})

        r = self.client.get("/api/v1/imports/restructured-pending?limit=10&offset=0&status=")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["total"], 700, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
