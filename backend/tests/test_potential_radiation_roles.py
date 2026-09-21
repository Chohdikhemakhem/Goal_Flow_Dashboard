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

TEST_DB_PATH = BACKEND_DIR / "tmp_potential_radiation_roles.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "PotentialRadiationRolesTestsSecretKey!2026"
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BONUS_MODULE_ACTIVE"] = "false"
os.environ["BOOTSTRAP_SUPERADMIN_EMAIL"] = ""
os.environ["BOOTSTRAP_SUPERADMIN_PASSWORD"] = ""

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from app.core.config import get_settings

get_settings.cache_clear()

from app.main import app
from app.core.security import hash_password
from app.db.base import Base
from app.db.migrations import add_missing_columns
from app.db.session import SessionLocal, engine
from app.models.entities import Agency, Agent, ImportBatch, LoanRaw, User
from app.models.enums import ImportBatchType, UserRole


EXPECTED_HEADERS = [
    "CONTRACT_NO",
    "CLIENT_NAME",
    "CLIENT_FIRST_NAME",
    "CLIENT_NO",
    "BRANCHE",
    "TOTAL_CUR_NO_OF_DAYS_OVERDUE",
    "TOTAL_DUE_AMT",
    "TOTAL_INTEREST_DUE_AMT",
    "TOTAL_PRINCIPAL_DUE_AMT",
    "GLP",
]


class PotentialRadiationRolesTestCase(unittest.TestCase):
    super_admin_email = "potential.superadmin@microcred.com.tn"
    super_admin_password = "PotentialSuperAdmin!2026"
    admin_email = "potential.admin@microcred.com.tn"
    admin_password = "PotentialAdmin!2026"
    chef_email = "potential.chef@microcred.com.tn"
    chef_password = "PotentialChef!2026"
    gp_email = "potential.gp@microcred.com.tn"
    gp_password = "PotentialGP!2026"

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        add_missing_columns(engine)
        self.client = TestClient(app)
        self._seed()

    def tearDown(self) -> None:
        self.client.close()

    def _seed(self) -> None:
        """Seed two agencies, two GPs, two snapshots, and clients that match the
        'potentially radiable' business rule on the older snapshot only.
        """
        with SessionLocal() as db:
            db.add(
                User(
                    email=self.super_admin_email,
                    full_name="Super Admin Test",
                    hashed_password=hash_password(self.super_admin_password),
                    role=UserRole.SUPER_ADMIN,
                    password_changed_at=datetime.now(timezone.utc),
                )
            )
            db.add(
                User(
                    email=self.admin_email,
                    full_name="Admin Test",
                    hashed_password=hash_password(self.admin_password),
                    role=UserRole.ADMIN,
                    password_changed_at=datetime.now(timezone.utc),
                )
            )

            self.agency_ids: dict[str, int] = {}
            for agency_name in ["Tunis Centre", "Ariana"]:
                agency = Agency(name=agency_name)
                db.add(agency)
                db.flush()
                self.agency_ids[agency_name] = agency.id

            self.agent_ids: dict[str, int] = {}
            for agent_name, agency_name, agency_key in [
                ("Ahmed Ben Ali", "Tunis Centre", "tunis"),
                ("Fatma Ben Salem", "Ariana", "ariana"),
            ]:
                agent = Agent(name=agent_name, agency_id=self.agency_ids[agency_name])
                db.add(agent)
                db.flush()
                self.agent_ids[agency_key] = agent.id

            db.add(
                User(
                    email=self.chef_email,
                    full_name="Chef Agence Tunis",
                    hashed_password=hash_password(self.chef_password),
                    role=UserRole.AGENCY_MANAGER,
                    agency_id=self.agency_ids["Tunis Centre"],
                    password_changed_at=datetime.now(timezone.utc),
                )
            )
            db.add(
                User(
                    email=self.gp_email,
                    full_name="GP Tunis",
                    hashed_password=hash_password(self.gp_password),
                    role=UserRole.PORTFOLIO_MANAGER,
                    agency_id=self.agency_ids["Tunis Centre"],
                    agent_id=self.agent_ids["tunis"],
                    password_changed_at=datetime.now(timezone.utc),
                )
            )

            # Snapshot A (older): 2026-01-15 -> last day of month = 2026-01-31
            # jours_restants = 31 - 15 = 16 -> threshold = 365 - 16 = 349
            # Client CL-RAD Tunis: DPD=400 (>= 349) -> radiable
            # Client CL-MIX Tunis: DPD=400 (>= 349) -> radiable -> all 2 loans must appear
            # Client CL-OK Tunis: DPD=10 -> not radiable
            # Client CL-RAD Ariana: DPD=400 -> radiable but only in Ariana (out of scope for Chef/GP)
            # GLP NULL coverage:
            #   CT-OLD-5 -> principal_outstanding NULL, principal_due=200 -> GLP=200
            #   CT-OLD-6 -> principal_outstanding=750, principal_due NULL -> GLP=750
            #   CT-OLD-7 -> both NULL -> GLP=0
            batch_old = ImportBatch(
                batch_type=ImportBatchType.SNAPSHOT,
                snapshot_date=date(2026, 1, 15),
                file_name="snapshot_old.xlsx",
            )
            db.add(batch_old)
            db.flush()
            self.batch_old_id = batch_old.id

            batch_new = ImportBatch(
                batch_type=ImportBatchType.SNAPSHOT,
                snapshot_date=date(2026, 7, 31),
                file_name="snapshot_new.xlsx",
            )
            db.add(batch_new)
            db.flush()
            self.batch_new_id = batch_new.id

            loans_old = [
                # Tunis - radiable client (will trigger inclusion of all this client's loans)
                ("CT-OLD-1", "CL-RAD", "Client Rad", "Ahmed Ben Ali", "Tunis Centre", 400, Decimal("800"), Decimal("100"), Decimal("50"), Decimal("200")),
                ("CT-OLD-2", "CL-RAD", "Client Rad", "Ahmed Ben Ali", "Tunis Centre", 30, Decimal("800"), Decimal("100"), Decimal("50"), Decimal("200")),
                # Tunis - low DPD, not radiable -> must not appear
                ("CT-OLD-3", "CL-OK", "Client Ok", "Ahmed Ben Ali", "Tunis Centre", 10, Decimal("800"), Decimal("100"), Decimal("50"), Decimal("200")),
                # Ariana - radiable but outside Tunis scope
                ("CT-OLD-4", "CL-ARIA-RAD", "Client Ariana Rad", "Fatma Ben Salem", "Ariana", 400, Decimal("800"), Decimal("100"), Decimal("50"), Decimal("200")),
                # GLP NULL coverage (all belong to CL-RAD -> will be exported)
                # CT-OLD-5: principal_outstanding NULL, principal_due=200 -> GLP=200
                ("CT-OLD-5", "CL-RAD", "Client Rad", "Ahmed Ben Ali", "Tunis Centre", 5, None, Decimal("200"), Decimal("50"), Decimal("250")),
                # CT-OLD-6: principal_outstanding=750, principal_due NULL -> GLP=750
                ("CT-OLD-6", "CL-RAD", "Client Rad", "Ahmed Ben Ali", "Tunis Centre", 5, Decimal("750"), None, Decimal("50"), Decimal("200")),
                # CT-OLD-7: both NULL -> GLP=0
                ("CT-OLD-7", "CL-RAD", "Client Rad", "Ahmed Ben Ali", "Tunis Centre", 5, None, None, Decimal("50"), Decimal("50")),
            ]
            for contract_no, client_id, client_name, agent_name, agency_name, dpd, principal_outstanding, principal_due, interest_due, total_due in loans_old:
                db.add(
                    LoanRaw(
                        contract_no=contract_no,
                        client_id=client_id,
                        client_name=client_name,
                        client_first_name="Prenom",
                        agency_name=agency_name,
                        agent_name=agent_name,
                        teg_rate=Decimal("0"),
                        disbursement_amount=Decimal("1000"),
                        principal_outstanding=principal_outstanding,
                        principal_due=principal_due,
                        interest_due_amt=interest_due,
                        total_scheduled_amount=(principal_due or Decimal("0")) + interest_due,
                        days_overdue=dpd,
                        total_due=total_due,
                        disbursement_date=date(2025, 6, 1),
                        snapshot_date=date(2026, 1, 15),
                        import_batch_id=self.batch_old_id,
                    )
                )

            # Snapshot B (newer): 2026-07-31 -> last day of month = 2026-07-31
            # jours_restants = 0 -> threshold = 365
            # CL-NEW-RAD has DPD=400 (> 365) -> radiable
            loans_new = [
                ("CT-NEW-1", "CL-NEW-RAD", "Client New Rad", "Ahmed Ben Ali", "Tunis Centre", 400, Decimal("100"), Decimal("50"), Decimal("200")),
                # A second client (same GP) with low DPD - must not appear.
                ("CT-NEW-2", "CL-NEW-OK", "Client New Ok", "Ahmed Ben Ali", "Tunis Centre", 5, Decimal("100"), Decimal("50"), Decimal("200")),
            ]
            for contract_no, client_id, client_name, agent_name, agency_name, dpd, principal_due, interest_due, total_due in loans_new:
                db.add(
                    LoanRaw(
                        contract_no=contract_no,
                        client_id=client_id,
                        client_name=client_name,
                        client_first_name="Prenom",
                        agency_name=agency_name,
                        agent_name=agent_name,
                        teg_rate=Decimal("0"),
                        disbursement_amount=Decimal("1000"),
                        principal_outstanding=Decimal("800"),
                        principal_due=principal_due,
                        interest_due_amt=interest_due,
                        total_scheduled_amount=principal_due + interest_due,
                        days_overdue=dpd,
                        total_due=total_due,
                        disbursement_date=date(2025, 9, 1),
                        snapshot_date=date(2026, 7, 31),
                        import_batch_id=self.batch_new_id,
                    )
                )

            db.commit()

    def _login(self, email: str, password: str) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _download_excel(self, params):
        return self.client.get("/api/v1/reports/portfolio.xlsx", params=params)

    def _download_snapshots(self, params):
        return self.client.get("/api/v1/reports/potential-radiation/snapshots", params=params)

    def _sheet_rows(self, content: bytes) -> list[list]:
        workbook = load_workbook(BytesIO(content))
        sheet = workbook.active
        return [[cell.value for cell in row] for row in sheet.iter_rows()]

    def _data_rows(self, content: bytes) -> list[list]:
        rows = self._sheet_rows(content)
        # header at row 5 (index 4), data starts row 6 (index 5)
        header = [value for value in rows[4] if value is not None]
        self.assertEqual(header, EXPECTED_HEADERS)
        return [row for row in rows[5:] if row[0] is not None]

    # ---------------------------------------------------------------
    # Test 1 — SUPER_ADMIN: identical UI flow, multi-agency, snapshot
    # ---------------------------------------------------------------
    def test_super_admin_multi_agency_access(self) -> None:
        self._login(self.super_admin_email, self.super_admin_password)

        # Snapshots endpoint must return both snapshots (super_admin has no agency scope).
        response = self._download_snapshots({})
        self.assertEqual(response.status_code, 200, response.text)
        snapshots = response.json()
        self.assertEqual(len(snapshots), 2)
        self.assertEqual({item["batch_id"] for item in snapshots}, {self.batch_old_id, self.batch_new_id})

        # Multi-agency export: Tunis + Ariana on the OLD snapshot.
        params = {
            "report_type": "potential_radiation",
            "agency_ids": f"{self.agency_ids['Tunis Centre']},{self.agency_ids['Ariana']}",
            "snapshot_batch_id": self.batch_old_id,
        }
        response = self._download_excel(params)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Potentiel_Radiation_2026-01-15.xlsx", response.headers.get("content-disposition", ""))

        data_rows = self._data_rows(response.content)
        # CL-RAD (5 Tunis loans) + CL-ARIA-RAD = 6 rows on the OLD snapshot
        self.assertEqual(len(data_rows), 6)
        contracts = {row[0] for row in data_rows}
        self.assertEqual(
            contracts,
            {"CT-OLD-1", "CT-OLD-2", "CT-OLD-4", "CT-OLD-5", "CT-OLD-6", "CT-OLD-7"},
        )
        # BRANCHE column is correctly populated for both agencies
        branches = {row[4] for row in data_rows}
        self.assertEqual(branches, {"Tunis Centre", "Ariana"})

    def test_super_admin_without_agency_is_rejected(self) -> None:
        """The existing admin-style guard remains in force for SUPER_ADMIN."""
        self._login(self.super_admin_email, self.super_admin_password)
        response = self._download_excel(
            {"report_type": "potential_radiation", "snapshot_batch_id": self.batch_old_id}
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("agency_required", response.text)

    # ---------------------------------------------------------------
    # Test 2 — ADMIN: no regression, behaviour identical to SUPER_ADMIN.
    # ---------------------------------------------------------------
    def test_admin_multi_agency_access(self) -> None:
        self._login(self.admin_email, self.admin_password)

        response = self._download_excel(
            {
                "report_type": "potential_radiation",
                "agency_ids": f"{self.agency_ids['Tunis Centre']},{self.agency_ids['Ariana']}",
                "snapshot_batch_id": self.batch_old_id,
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        self.assertEqual(len(data_rows), 6)
        contracts = {row[0] for row in data_rows}
        self.assertEqual(
            contracts,
            {"CT-OLD-1", "CT-OLD-2", "CT-OLD-4", "CT-OLD-5", "CT-OLD-6", "CT-OLD-7"},
        )
        branches = {row[4] for row in data_rows}
        self.assertEqual(branches, {"Tunis Centre", "Ariana"})

    def test_admin_without_agency_is_rejected(self) -> None:
        self._login(self.admin_email, self.admin_password)
        response = self._download_excel(
            {"report_type": "potential_radiation", "snapshot_batch_id": self.batch_old_id}
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("agency_required", response.text)

    # ---------------------------------------------------------------
    # Test 3 — AGENCY_MANAGER: forced to own agency, ignores other IDs.
    # ---------------------------------------------------------------
    def test_chef_agence_scope_enforced(self) -> None:
        self._login(self.chef_email, self.chef_password)

        # Snapshots must be limited to those accessible within their agency.
        snapshots = self._download_snapshots({}).json()
        self.assertEqual(len(snapshots), 2)

        # Attempt 1: no agency_id provided -> backend must still scope to Tunis only.
        response = self._download_excel(
            {"report_type": "potential_radiation", "snapshot_batch_id": self.batch_old_id}
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        # Only Tunis loans of CL-RAD (5 loans) -> CT-OLD-4 (Ariana) must be absent.
        self.assertEqual(
            {row[0] for row in data_rows},
            {"CT-OLD-1", "CT-OLD-2", "CT-OLD-5", "CT-OLD-6", "CT-OLD-7"},
        )
        self.assertEqual({row[4] for row in data_rows}, {"Tunis Centre"})

        # Attempt 2: frontend tampering with another agency_id -> backend still scopes.
        response = self._download_excel(
            {
                "report_type": "potential_radiation",
                "snapshot_batch_id": self.batch_old_id,
                "agency_id": self.agency_ids["Ariana"],
                "agency_ids": f"{self.agency_ids['Ariana']},{self.agency_ids['Tunis Centre']}",
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        self.assertEqual(
            {row[0] for row in data_rows},
            {"CT-OLD-1", "CT-OLD-2", "CT-OLD-5", "CT-OLD-6", "CT-OLD-7"},
        )
        self.assertEqual({row[4] for row in data_rows}, {"Tunis Centre"})

    # ---------------------------------------------------------------
    # Test 4 — PORTFOLIO_MANAGER: scoped to portfolio identity, no data leakage.
    # ---------------------------------------------------------------
    def test_portfolio_manager_scope_enforced(self) -> None:
        self._login(self.gp_email, self.gp_password)

        # No agency_id needed; scope by portfolio identity.
        response = self._download_excel(
            {"report_type": "potential_radiation", "snapshot_batch_id": self.batch_old_id}
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        # Only Tunis loans of CL-RAD -> the Ariana loan (different agent) must not appear.
        self.assertEqual(
            {row[0] for row in data_rows},
            {"CT-OLD-1", "CT-OLD-2", "CT-OLD-5", "CT-OLD-6", "CT-OLD-7"},
        )
        self.assertEqual({row[4] for row in data_rows}, {"Tunis Centre"})

        # Snapshots endpoint must return both snapshots (GP identity covers both snapshots).
        snapshots = self._download_snapshots({}).json()
        self.assertEqual({item["batch_id"] for item in snapshots}, {self.batch_old_id, self.batch_new_id})

    # ---------------------------------------------------------------
    # Test 5 — Snapshot isolation: report uses ONLY the selected snapshot.
    # ---------------------------------------------------------------
    def test_snapshot_isolation(self) -> None:
        self._login(self.super_admin_email, self.super_admin_password)

        # The new snapshot only has CT-NEW-1 radiable.
        response = self._download_excel(
            {
                "report_type": "potential_radiation",
                "agency_id": self.agency_ids["Tunis Centre"],
                "snapshot_batch_id": self.batch_new_id,
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        self.assertEqual({row[0] for row in data_rows}, {"CT-NEW-1"})
        # No row from the OLD snapshot leaks into the NEW snapshot export.
        self.assertFalse(any(row[0] in {"CT-OLD-1", "CT-OLD-2", "CT-OLD-3", "CT-OLD-4"} for row in data_rows))

    # ---------------------------------------------------------------
    # Test 6 — Client logic: all loans of a radiable client are returned.
    # ---------------------------------------------------------------
    def test_all_loans_of_radiable_client_are_returned(self) -> None:
        self._login(self.super_admin_email, self.super_admin_password)
        response = self._download_excel(
            {
                "report_type": "potential_radiation",
                "agency_id": self.agency_ids["Tunis Centre"],
                "snapshot_batch_id": self.batch_old_id,
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        # CL-RAD has CT-OLD-1 (DPD=400 -> radiable trigger) AND CT-OLD-2 (DPD=30).
        # All other CL-RAD loans (CT-OLD-5/6/7) must also appear (same client).
        # Both contracts must appear, even though only CT-OLD-1 crosses the threshold.
        contracts = {row[0] for row in data_rows}
        self.assertEqual(
            contracts,
            {"CT-OLD-1", "CT-OLD-2", "CT-OLD-5", "CT-OLD-6", "CT-OLD-7"},
        )
        # CL-OK (DPD=10) is NOT radiable -> must not appear at all.
        self.assertNotIn("CT-OLD-3", contracts)

    # ---------------------------------------------------------------
    # Test 7 — Forbidden role: snapshot endpoint is restricted to the four roles.
    # ---------------------------------------------------------------
    def test_snapshot_endpoint_role_guard(self) -> None:
        with SessionLocal() as db:
            db.add(
                User(
                    email="potential.support@microcred.com.tn",
                    full_name="Support Test",
                    hashed_password=hash_password("SupportPwd!2026"),
                    role=UserRole.SUPPORT,
                    password_changed_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        self.client.post(
            "/api/v1/auth/login",
            json={"email": "potential.support@microcred.com.tn", "password": "SupportPwd!2026"},
        )
        response = self._download_snapshots({})
        self.assertEqual(response.status_code, 403, response.text)

    # ---------------------------------------------------------------
    # Test 8 — Branch column: BRANCHE reflects LoanRaw.agency_name value.
    # ---------------------------------------------------------------
    def test_branche_column_uses_loan_agency_name(self) -> None:
        self._login(self.super_admin_email, self.super_admin_password)
        response = self._download_excel(
            {
                "report_type": "potential_radiation",
                "agency_id": self.agency_ids["Tunis Centre"],
                "snapshot_batch_id": self.batch_old_id,
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        # All Tunis rows must carry "Tunis Centre" as the BRANCHE.
        for row in data_rows:
            self.assertEqual(row[4], "Tunis Centre")

    # ---------------------------------------------------------------
    # Test 9 — GLP column: standard case (principal_outstanding + principal_due).
    # ---------------------------------------------------------------
    def test_glp_column_sum_of_outstanding_and_principal_due(self) -> None:
        self._login(self.super_admin_email, self.super_admin_password)
        response = self._download_excel(
            {
                "report_type": "potential_radiation",
                "agency_id": self.agency_ids["Tunis Centre"],
                "snapshot_batch_id": self.batch_old_id,
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        by_contract = {row[0]: row for row in data_rows}
        # CT-OLD-1 / CT-OLD-2 -> 800 + 100 = 900
        self.assertEqual(by_contract["CT-OLD-1"][9], Decimal("900"))
        self.assertEqual(by_contract["CT-OLD-2"][9], Decimal("900"))

    # ---------------------------------------------------------------
    # Test 10 — GLP column: NULL handling (one or both operands NULL).
    # ---------------------------------------------------------------
    def test_glp_column_handles_null_values(self) -> None:
        self._login(self.super_admin_email, self.super_admin_password)
        response = self._download_excel(
            {
                "report_type": "potential_radiation",
                "agency_id": self.agency_ids["Tunis Centre"],
                "snapshot_batch_id": self.batch_old_id,
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data_rows = self._data_rows(response.content)
        by_contract = {row[0]: row for row in data_rows}
        # CT-OLD-5 -> principal_outstanding NULL, principal_due=200 -> GLP=200
        self.assertEqual(by_contract["CT-OLD-5"][9], Decimal("200"))
        # CT-OLD-6 -> principal_outstanding=750, principal_due NULL -> GLP=750
        self.assertEqual(by_contract["CT-OLD-6"][9], Decimal("750"))
        # CT-OLD-7 -> both NULL -> GLP=0
        self.assertEqual(by_contract["CT-OLD-7"][9], Decimal("0"))

    # ---------------------------------------------------------------
    # Test 11 — Column order: GLP must be the last column.
    # ---------------------------------------------------------------
    def test_glp_column_is_last_in_header(self) -> None:
        self._login(self.super_admin_email, self.super_admin_password)
        response = self._download_excel(
            {
                "report_type": "potential_radiation",
                "agency_id": self.agency_ids["Tunis Centre"],
                "snapshot_batch_id": self.batch_old_id,
            }
        )
        rows = self._sheet_rows(response.content)
        header = [value for value in rows[4] if value is not None]
        self.assertEqual(header[-1], "GLP")
        # PRINCIPAL_OUTSTANDING must not be exposed as a column.
        self.assertNotIn("PRINCIPAL_OUTSTANDING", header)


if __name__ == "__main__":
    unittest.main()