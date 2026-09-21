from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "tmp_missing_mcr_delete.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "MissingMcrDeleteTestsSecret!2026"
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BONUS_MODULE_ACTIVE"] = "false"
os.environ["BOOTSTRAP_SUPERADMIN_EMAIL"] = ""
os.environ["BOOTSTRAP_SUPERADMIN_PASSWORD"] = ""

from fastapi.testclient import TestClient
from sqlalchemy import select

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
    RestructuredContract,
    User,
)
from app.models.enums import ImportBatchType, UserRole


class MissingMcrDeleteTestCase(unittest.TestCase):
    super_admin_email = "missing.superadmin@microcred.com.tn"
    super_admin_password = "MissingSuper!2026"
    support_email = "missing.support@microcred.com.tn"
    support_password = "MissingSupport!2026"
    admin_email = "missing.admin@microcred.com.tn"
    admin_password = "MissingAdmin!2026"

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        add_missing_columns(engine)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def _login(self, email: str, password: str) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _seed_users(self) -> None:
        with SessionLocal() as db:
            db.add_all([
                User(
                    email=self.super_admin_email,
                    full_name="SA",
                    hashed_password=hash_password(self.super_admin_password),
                    role=UserRole.SUPER_ADMIN,
                    password_changed_at=datetime.now(timezone.utc),
                ),
                User(
                    email=self.support_email,
                    full_name="SUP",
                    hashed_password=hash_password(self.support_password),
                    role=UserRole.SUPPORT,
                    password_changed_at=datetime.now(timezone.utc),
                ),
                User(
                    email=self.admin_email,
                    full_name="ADM",
                    hashed_password=hash_password(self.admin_password),
                    role=UserRole.ADMIN,
                    password_changed_at=datetime.now(timezone.utc),
                ),
            ])
            db.commit()

    def _seed_scenario(
        self,
        *,
        in_mcr_contracts: tuple[str, ...] = (),
        missing_contracts: tuple[str, ...] = (),
    ) -> None:
        """Seed a deterministic scenario where:
        - ``in_mcr_contracts`` exist in both the official restructured list
          AND the latest MCR (so they are NOT in the missing-from-mcr view).
        - ``missing_contracts`` exist in the official restructured list but
          NOT in the latest MCR (so they ARE in the missing-from-mcr view).
        """
        with SessionLocal() as db:
            agency = Agency(name="Agence Missing")
            db.add(agency)
            db.flush()
            agent = Agent(name="Agent Missing", agency_id=agency.id)
            db.add(agent)
            db.flush()

            # Latest CURRENT_STATE MCR batch.
            current_batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                snapshot_date=date(2026, 7, 31),
                file_name="current.xlsx",
            )
            db.add(current_batch)
            db.flush()

            for contract_no in in_mcr_contracts:
                db.add_all([
                    RestructuredContract(
                        contract_no=contract_no,
                        normalized_contract_no=contract_no,
                        credit_family="restructured",
                        source="list",
                    ),
                    LoanRaw(
                        contract_no=contract_no,
                        client_id=f"CLI-{contract_no}",
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
                        snapshot_date=date(2026, 7, 31),
                        import_batch_id=current_batch.id,
                    ),
                ])

            for contract_no in missing_contracts:
                db.add(
                    RestructuredContract(
                        contract_no=contract_no,
                        normalized_contract_no=contract_no,
                        credit_family="restructured",
                        source="list",
                    )
                )
            db.commit()

    # ------------------------------------------------------------------
    # 1. Auth/role gate: only super_admin / support can delete.
    # ------------------------------------------------------------------
    def test_admin_role_is_forbidden(self) -> None:
        self._seed_users()
        self._seed_scenario(missing_contracts=("M-001",))
        self._login(self.admin_email, self.admin_password)
        response = self.client.request(
            "DELETE",
            "/api/v1/credits-restructures/absents-mcr/contracts",
            json={"contract_nos": ["M-001"]},
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_unauthenticated_is_forbidden(self) -> None:
        self._seed_users()
        self._seed_scenario(missing_contracts=("M-001",))
        response = self.client.request(
            "DELETE",
            "/api/v1/credits-restructures/absents-mcr/contracts",
            json={"contract_nos": ["M-001"]},
        )
        self.assertEqual(response.status_code, 401, response.text)

    def test_empty_selection_is_rejected(self) -> None:
        self._seed_users()
        self._seed_scenario(missing_contracts=("M-001",))
        self._login(self.super_admin_email, self.super_admin_password)
        response = self.client.request(
            "DELETE",
            "/api/v1/credits-restructures/absents-mcr/contracts",
            json={"contract_nos": []},
        )
        # Pydantic enforces the min_length=1 at the request body schema,
        # so FastAPI returns 422 before the endpoint logic runs.
        self.assertIn(response.status_code, (400, 422), response.text)

    # ------------------------------------------------------------------
    # 2. Real delete: missing-from-mcr contracts are physically deleted
    #    from restructured_contracts.
    # ------------------------------------------------------------------
    def test_super_admin_can_delete_missing_mcr_contracts(self) -> None:
        self._seed_users()
        self._seed_scenario(
            in_mcr_contracts=("KEEP-001",),
            missing_contracts=("DEL-001", "DEL-002", "DEL-003"),
        )
        self._login(self.super_admin_email, self.super_admin_password)

        list_before = self.client.get(
            "/api/v1/credits-restructures/absents-mcr",
            params={"family": "restructured", "limit": 50, "offset": 0},
        )
        self.assertEqual(list_before.status_code, 200, list_before.text)
        before_nos = {item["contract_no"] for item in list_before.json()["items"]}
        self.assertEqual(before_nos, {"DEL-001", "DEL-002", "DEL-003"})

        response = self.client.request(
            "DELETE",
            "/api/v1/credits-restructures/absents-mcr/contracts",
            json={"contract_nos": ["DEL-001", "DEL-002"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["deleted_count"], 2)
        self.assertEqual(payload["skipped_count"], 0)
        self.assertEqual(set(payload["deleted_contract_nos"]), {"DEL-001", "DEL-002"})

        # The deleted contracts are physically gone from restructured_contracts.
        with SessionLocal() as db:
            rows = db.scalars(
                select(RestructuredContract)
                .where(RestructuredContract.contract_no.in_(["DEL-001", "DEL-002"]))
                .order_by(RestructuredContract.contract_no)
            ).all()
            self.assertEqual(rows, [])
            # KEEP-001 and DEL-003 are untouched.
            remaining = db.scalars(
                select(RestructuredContract).order_by(RestructuredContract.contract_no)
            ).all()
            self.assertEqual(
                {r.contract_no for r in remaining},
                {"KEEP-001", "DEL-003"},
            )

        # The view no longer exposes the deleted contracts.
        list_after = self.client.get(
            "/api/v1/credits-restructures/absents-mcr",
            params={"family": "restructured", "limit": 50, "offset": 0},
        )
        self.assertEqual(list_after.status_code, 200, list_after.text)
        after_nos = {item["contract_no"] for item in list_after.json()["items"]}
        self.assertEqual(after_nos, {"DEL-003"})

    # ------------------------------------------------------------------
    # 3. The endpoint refuses contract_nos that are NOT in the missing
    #    view (security: a user cannot arbitrarily delete arbitrary
    #    restructured_contracts rows).
    # ------------------------------------------------------------------
    def test_skips_contracts_not_in_missing_view(self) -> None:
        self._seed_users()
        self._seed_scenario(
            in_mcr_contracts=("IN-MCR-001",),
            missing_contracts=("MISS-001",),
        )
        self._login(self.super_admin_email, self.super_admin_password)
        response = self.client.request(
            "DELETE",
            "/api/v1/credits-restructures/absents-mcr/contracts",
            json={"contract_nos": ["MISS-001", "IN-MCR-001", "DOES-NOT-EXIST"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["deleted_count"], 1)
        self.assertEqual(payload["skipped_count"], 2)
        self.assertEqual(payload["deleted_contract_nos"], ["MISS-001"])
        self.assertEqual(set(payload["skipped_contract_nos"]),
                         {"IN-MCR-001", "DOES-NOT-EXIST"})

        # The skipped rows remain untouched.
        with SessionLocal() as db:
            in_mcr = db.scalar(
                select(RestructuredContract).where(
                    RestructuredContract.contract_no == "IN-MCR-001"
                )
            )
            self.assertIsNotNone(in_mcr)

    # ------------------------------------------------------------------
    # 4. Support role can also call the endpoint.
    # ------------------------------------------------------------------
    def test_support_role_can_delete(self) -> None:
        self._seed_users()
        self._seed_scenario(missing_contracts=("SUP-001",))
        self._login(self.support_email, self.support_password)
        response = self.client.request(
            "DELETE",
            "/api/v1/credits-restructures/absents-mcr/contracts",
            json={"contract_nos": ["SUP-001"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted_count"], 1)

    # ------------------------------------------------------------------
    # 5. Idempotence: a second delete on the same contract reports 0 deleted.
    # ------------------------------------------------------------------
    def test_delete_is_idempotent(self) -> None:
        self._seed_users()
        self._seed_scenario(missing_contracts=("IDEM-001",))
        self._login(self.super_admin_email, self.super_admin_password)
        first = self.client.request(
            "DELETE",
            "/api/v1/credits-restructures/absents-mcr/contracts",
            json={"contract_nos": ["IDEM-001"]},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["deleted_count"], 1)

        second = self.client.request(
            "DELETE",
            "/api/v1/credits-restructures/absents-mcr/contracts",
            json={"contract_nos": ["IDEM-001"]},
        )
        self.assertEqual(second.status_code, 200, second.text)
        # The contract was physically deleted, so it is no longer in the
        # missing-from-mcr view — the service refuses to re-delete it.
        self.assertEqual(second.json()["deleted_count"], 0)
        self.assertEqual(second.json()["skipped_contract_nos"], ["IDEM-001"])


if __name__ == "__main__":
    unittest.main()