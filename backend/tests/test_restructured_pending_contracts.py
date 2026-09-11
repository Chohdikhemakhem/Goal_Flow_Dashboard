from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import func, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "tmp_restructured_pending.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "PendingContractsNeedAVeryStrongSecret!2026"
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
from app.models.entities import (
    ImportBatch,
    LoanRaw,
    PendingRestructuredContract,
    RestructuredAnalysisResult,
    RestructuredContract,
    RestructuredGapResult,
    RestructuredScheduleRow,
    User,
)
from app.models.enums import ImportBatchType, UserRole
from app.services.restructured import (
    CONSOLIDATED_FAMILY,
    LIST_IMPORT_SOURCE,
    MANUAL_COMPLETION_SOURCE,
    PENDING_STATUS_READY,
    PENDING_STATUS_TO_COMPLETE,
    RESTRUCTURED_FAMILY,
    _tracked_mcr_credit_family,
    import_restructured_contracts,
    list_pending_restructured_contracts,
    preview_restructured_contract_sync,
    remove_pending_restructured_contracts_matching_official_list,
    sync_pending_restructured_contracts_from_mcr_batch,
    update_pending_restructured_contract,
    validate_pending_restructured_contract,
)
from app.api.v1.metrics import calculate_potentially_radiable_threshold, metrics_summary
from app.schemas.restructured import PendingRestructuredContractUpdate
from app.services.restructured_dashboard import get_restructured_dashboard_kpis


class RestructuredPendingContractsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        add_missing_columns(engine)

    def _create_super_admin(self) -> int:
        with SessionLocal() as db:
            user = User(
                email="super.admin@microcred.com.tn",
                full_name="Super Admin",
                hashed_password=hash_password("UltraSecureAdmin!2026"),
                role=UserRole.SUPER_ADMIN,
                is_active=True,
                must_change_password=False,
                password_changed_at=datetime.now(timezone.utc),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user.id

    def _seed_current_batch(self, *, contract_no: str, category_desc: str, total_due: Decimal | None = None) -> int:
        return self._seed_current_batch_with_loans([
            {
                "contract_no": contract_no,
                "category_desc": category_desc,
                "total_due": total_due,
            }
        ])

    def _seed_current_batch_with_loans(self, loans: list[dict[str, object]]) -> int:
        with SessionLocal() as db:
            batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=date(2026, 7, 31),
                file_name="current_mcr.xlsx",
            )
            db.add(batch)
            db.flush()
            for index, loan in enumerate(loans, start=1):
                db.add(
                    LoanRaw(
                        contract_no=str(loan.get("contract_no") or ""),
                        client_name=str(loan.get("client_name") or f"Ahmed {index}"),
                        client_first_name=str(loan.get("client_first_name") or "Ali"),
                        client_id=str(loan.get("client_id") or f"CLI-{index:03d}"),
                        agency_name=str(loan.get("agency_name") or "Agence Centre"),
                        agent_name=str(loan.get("agent_name") or "GP Centre"),
                        category_desc=loan.get("category_desc"),
                        disbursement_amount=Decimal(str(loan.get("disbursement_amount") or "25000.000")),
                        principal_outstanding=Decimal(str(loan.get("principal_outstanding") or "1000.000")),
                        principal_due=Decimal(str(loan.get("principal_due") or "100.000")),
                        total_scheduled_amount=Decimal(str(loan.get("total_scheduled_amount") or "100.000")),
                        days_overdue=int(loan.get("days_overdue") or 0),
                        total_due=loan.get("total_due"),
                        status=str(loan.get("status") or "active"),
                        disbursement_date=loan.get("disbursement_date") or date(2026, 7, 7),
                        snapshot_date=batch.snapshot_date,
                        import_batch_id=batch.id,
                    )
                )
            db.commit()
            return batch.id

    def _build_restructured_contract_excel(self, rows: list[dict[str, object]]) -> bytes:
        frame = pd.DataFrame(rows)
        buffer = BytesIO()
        frame.to_excel(buffer, index=False)
        return buffer.getvalue()

    def test_potentially_radiable_threshold_uses_month_end_reference_date(self) -> None:
        self.assertEqual(calculate_potentially_radiable_threshold(date(2026, 8, 15)), 349)
        self.assertEqual(calculate_potentially_radiable_threshold(date(2026, 8, 11)), 345)
        self.assertEqual(calculate_potentially_radiable_threshold(date(2026, 8, 31)), 365)

    def test_metrics_summary_computes_potentially_radiable_volume_and_percentage(self) -> None:
        actor_id = self._create_super_admin()
        with SessionLocal() as db:
            batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=date(2026, 8, 15),
                file_name="current_radiable.xlsx",
            )
            db.add(batch)
            db.flush()
            loan_rows = [
                {
                    "contract_no": "RAD-001",
                    "client_name": "Client 1",
                    "client_first_name": "Alpha",
                    "client_id": "CLI-001",
                    "agency_name": "Agence Centre",
                    "agent_name": "GP Centre",
                    "disbursement_amount": Decimal("5000.00"),
                    "principal_outstanding": Decimal("1000.00"),
                    "principal_due": Decimal("200.00"),
                    "days_overdue": 348,
                    "status": "active",
                    "disbursement_date": date(2026, 5, 1),
                    "snapshot_date": batch.snapshot_date,
                    "import_batch_id": batch.id,
                },
                {
                    "contract_no": "RAD-002",
                    "client_name": "Client 2",
                    "client_first_name": "Beta",
                    "client_id": "CLI-002",
                    "agency_name": "Agence Centre",
                    "agent_name": "GP Centre",
                    "disbursement_amount": Decimal("7000.00"),
                    "principal_outstanding": Decimal("2000.00"),
                    "principal_due": Decimal("0.00"),
                    "days_overdue": 349,
                    "status": "active",
                    "disbursement_date": date(2026, 5, 1),
                    "snapshot_date": batch.snapshot_date,
                    "import_batch_id": batch.id,
                },
                {
                    "contract_no": "RAD-003",
                    "client_name": "Client 3",
                    "client_first_name": "Gamma",
                    "client_id": "CLI-003",
                    "agency_name": "Agence Centre",
                    "agent_name": "GP Centre",
                    "disbursement_amount": Decimal("10000.00"),
                    "principal_outstanding": Decimal("3000.00"),
                    "principal_due": Decimal("0.00"),
                    "days_overdue": 365,
                    "status": "active",
                    "disbursement_date": date(2026, 5, 1),
                    "snapshot_date": batch.snapshot_date,
                    "import_batch_id": batch.id,
                },
            ]
            for loan in loan_rows:
                db.add(LoanRaw(**loan))
            db.commit()
            actor = db.get(User, actor_id)
            summary = metrics_summary(db=db, user=actor)

            self.assertEqual(summary.potentially_radiable_volume, Decimal("5000.00"))
            self.assertEqual(summary.potentially_radiable_rate, Decimal("0.8065"))

    def test_period_summary_uses_exact_end_date_snapshot_when_available(self) -> None:
        actor_id = self._create_super_admin()
        with SessionLocal() as db:
            target_batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=date(2026, 8, 20),
                file_name="snapshot_2026_08_20.xlsx",
            )
            older_batch = ImportBatch(
                batch_type=ImportBatchType.SNAPSHOT,
                period=None,
                snapshot_date=date(2026, 8, 19),
                file_name="snapshot_2026_08_19.xlsx",
            )
            db.add_all([target_batch, older_batch])
            db.flush()
            db.add_all([
                LoanRaw(
                    contract_no="EXACT-001",
                    client_name="Exact Client",
                    client_first_name="E",
                    client_id="CLI-EXACT",
                    agency_name="Agence Centre",
                    agent_name="GP Centre",
                    disbursement_amount=Decimal("10000.00"),
                    principal_outstanding=Decimal("1500.00"),
                    principal_due=Decimal("0.00"),
                    total_scheduled_amount=Decimal("100.00"),
                    days_overdue=0,
                    status="active",
                    disbursement_date=date(2026, 7, 1),
                    snapshot_date=target_batch.snapshot_date,
                    import_batch_id=target_batch.id,
                ),
                LoanRaw(
                    contract_no="OLDER-001",
                    client_name="Older Client",
                    client_first_name="O",
                    client_id="CLI-OLDER",
                    agency_name="Agence Centre",
                    agent_name="GP Centre",
                    disbursement_amount=Decimal("5000.00"),
                    principal_outstanding=Decimal("500.00"),
                    principal_due=Decimal("50.00"),
                    total_scheduled_amount=Decimal("100.00"),
                    days_overdue=10,
                    status="active",
                    disbursement_date=date(2026, 7, 1),
                    snapshot_date=older_batch.snapshot_date,
                    import_batch_id=older_batch.id,
                ),
            ])
            db.commit()
            actor = db.get(User, actor_id)
            summary = metrics_summary(db=db, user=actor, date_from=date(2026, 8, 1), date_to=date(2026, 8, 20))
            self.assertEqual(summary.outstanding, Decimal("1500.00"))
            self.assertEqual(summary.par_1_30, Decimal("0.00"))

    def test_period_summary_uses_latest_prior_snapshot_when_end_date_missing(self) -> None:
        actor_id = self._create_super_admin()
        with SessionLocal() as db:
            exact_batch = ImportBatch(
                batch_type=ImportBatchType.SNAPSHOT,
                period=None,
                snapshot_date=date(2026, 8, 22),
                file_name="snapshot_2026_08_22.xlsx",
            )
            prior_batch = ImportBatch(
                batch_type=ImportBatchType.SNAPSHOT,
                period=None,
                snapshot_date=date(2026, 8, 19),
                file_name="snapshot_2026_08_19.xlsx",
            )
            db.add_all([exact_batch, prior_batch])
            db.flush()
            db.add_all([
                LoanRaw(
                    contract_no="PRIOR-001",
                    client_name="Prior Client",
                    client_first_name="P",
                    client_id="CLI-PRIOR",
                    agency_name="Agence Centre",
                    agent_name="GP Centre",
                    disbursement_amount=Decimal("5000.00"),
                    principal_outstanding=Decimal("2500.00"),
                    principal_due=Decimal("0.00"),
                    total_scheduled_amount=Decimal("100.00"),
                    days_overdue=0,
                    status="active",
                    disbursement_date=date(2026, 7, 1),
                    snapshot_date=prior_batch.snapshot_date,
                    import_batch_id=prior_batch.id,
                ),
                LoanRaw(
                    contract_no="FUTURE-001",
                    client_name="Future Client",
                    client_first_name="F",
                    client_id="CLI-FUTURE",
                    agency_name="Agence Centre",
                    agent_name="GP Centre",
                    disbursement_amount=Decimal("10000.00"),
                    principal_outstanding=Decimal("1000.00"),
                    principal_due=Decimal("0.00"),
                    total_scheduled_amount=Decimal("100.00"),
                    days_overdue=0,
                    status="active",
                    disbursement_date=date(2026, 7, 1),
                    snapshot_date=exact_batch.snapshot_date,
                    import_batch_id=exact_batch.id,
                ),
            ])
            db.commit()
            actor = db.get(User, actor_id)
            summary = metrics_summary(db=db, user=actor, date_from=date(2026, 8, 1), date_to=date(2026, 8, 20))
            self.assertEqual(summary.outstanding, Decimal("2500.00"))
            self.assertNotEqual(summary.outstanding, Decimal("3500.00"))

    def test_tracked_mcr_credit_family_only_accepts_target_categories(self) -> None:
        self.assertEqual(_tracked_mcr_credit_family("Credits Consolidés"), CONSOLIDATED_FAMILY)
        self.assertEqual(_tracked_mcr_credit_family("Credits Restructurés"), RESTRUCTURED_FAMILY)
        self.assertIsNone(_tracked_mcr_credit_family("Micro credit"))

    def test_mcr_contract_absent_from_official_list_is_added_to_pending(self) -> None:
        batch_id = self._seed_current_batch(
            contract_no="1000-00047746.0",
            category_desc="Credits Consolidés",
            total_due=Decimal("1500.000"),
        )
        with SessionLocal() as db:
            batch = db.get(ImportBatch, batch_id)
            summary = sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            db.commit()

            self.assertEqual(summary["consolidated_detected"], 1)
            self.assertEqual(summary["new_detected"], 1)

            pending = db.scalars(select(PendingRestructuredContract)).all()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].normalized_contract_no, "1000-00047746")
            self.assertEqual(pending[0].status, PENDING_STATUS_TO_COMPLETE)
            self.assertIn("Date de decalage", pending[0].missing_fields)
            self.assertIn("LOAN_DURATION", pending[0].missing_fields)

    def test_contract_with_all_required_fields_becomes_ready_after_update(self) -> None:
        actor_id = self._create_super_admin()
        batch_id = self._seed_current_batch(
            contract_no="RST-0001",
            category_desc="Credits Restructurés",
            total_due=Decimal("900.000"),
        )
        with SessionLocal() as db:
            batch = db.get(ImportBatch, batch_id)
            sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            pending = db.scalar(select(PendingRestructuredContract))
            self.assertIsNotNone(pending)

            updated = update_pending_restructured_contract(
                db,
                pending.id,
                PendingRestructuredContractUpdate(
                    shift_date=date(2026, 6, 1),
                    total_due=Decimal("900.000"),
                    loan_duration=12,
                ),
            )
            db.commit()

            self.assertEqual(updated.status, PENDING_STATUS_READY)
            self.assertEqual(updated.missing_fields, [])

            actor = db.get(User, actor_id)
            result = validate_pending_restructured_contract(db, pending.id, actor=actor)
            db.commit()

            self.assertEqual(result.saved_count, 1)
            official = db.scalar(select(RestructuredContract).where(RestructuredContract.contract_no == "RST-0001"))
            self.assertIsNotNone(official)
            self.assertEqual(official.source, MANUAL_COMPLETION_SOURCE)
            self.assertEqual(official.credit_family, RESTRUCTURED_FAMILY)
            self.assertIsNone(db.get(PendingRestructuredContract, pending.id))

    def test_validation_is_refused_when_required_fields_are_missing(self) -> None:
        actor_id = self._create_super_admin()
        batch_id = self._seed_current_batch(
            contract_no="CONS-0001",
            category_desc="Credits Consolidés",
            total_due=Decimal("1200.000"),
        )
        with SessionLocal() as db:
            batch = db.get(ImportBatch, batch_id)
            sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            pending = db.scalar(select(PendingRestructuredContract))
            actor = db.get(User, actor_id)

            with self.assertRaises(ValueError):
                validate_pending_restructured_contract(db, pending.id, actor=actor)

    def test_second_sync_of_same_mcr_does_not_create_duplicates(self) -> None:
        batch_id = self._seed_current_batch(
            contract_no="RST-0002",
            category_desc="Credits Restructurés",
            total_due=Decimal("1000.000"),
        )
        with SessionLocal() as db:
            batch = db.get(ImportBatch, batch_id)
            sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            db.commit()

            total = db.scalar(select(func.count(PendingRestructuredContract.id)))
            self.assertEqual(total, 1)

    def test_official_contract_is_never_added_to_pending_and_dashboard_ignores_pending_only(self) -> None:
        actor_id = self._create_super_admin()
        batch_id = self._seed_current_batch(
            contract_no="RST-0003",
            category_desc="Credits Restructurés",
            total_due=Decimal("1300.000"),
        )
        with SessionLocal() as db:
            db.add(
                RestructuredContract(
                    source_contract_no="RST-0003",
                    contract_no="RST-0003",
                    normalized_contract_no="RST-0003",
                    credit_family=RESTRUCTURED_FAMILY,
                    delay_date=date(2026, 6, 10),
                    category_desc="Credits Restructurés",
                    total_due=Decimal("1300.000"),
                    loan_duration=10,
                    source=LIST_IMPORT_SOURCE,
                )
            )
            db.commit()

            batch = db.get(ImportBatch, batch_id)
            summary = sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            db.commit()

            self.assertEqual(summary["already_present"], 1)
            self.assertEqual(db.scalar(select(func.count(PendingRestructuredContract.id))), 0)

            actor = db.get(User, actor_id)
            kpis = get_restructured_dashboard_kpis(db, actor, family=RESTRUCTURED_FAMILY)
            self.assertEqual(kpis.family, RESTRUCTURED_FAMILY)
            self.assertEqual(kpis.disbursement_count, 0)
            self.assertEqual(kpis.outstanding, Decimal("0"))

    def test_official_import_removes_matching_pending_rows(self) -> None:
        batch_id = self._seed_current_batch(
            contract_no="RST-0004",
            category_desc="Credits Restructurés",
            total_due=Decimal("800.000"),
        )
        with SessionLocal() as db:
            batch = db.get(ImportBatch, batch_id)
            sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            deleted = remove_pending_restructured_contracts_matching_official_list(db, ["RST-0004"])
            db.commit()

            self.assertEqual(deleted, 1)
            page = list_pending_restructured_contracts(db, limit=20, offset=0)
            self.assertEqual(page.total, 0)

    def test_restructured_import_preview_and_sync_keep_only_list_or_active_mcr_contracts(self) -> None:
        payload = self._build_restructured_contract_excel([
            {
                "Numero contrat": "LIST-KEEP",
                "No contrat": "LIST-KEEP",
                "Colonne1": "RST",
                "date de decalage": date(2026, 1, 10),
                "dans MCR": "Oui",
                "CATEGORY_DESC": "Credits Restructures",
                "Total_Due": 1000,
                "LOAN_DURATION": 12,
            },
            {
                "Numero contrat": "NEW-LIST",
                "No contrat": "NEW-LIST",
                "Colonne1": "RST",
                "date de decalage": date(2026, 5, 10),
                "dans MCR": "Non",
                "CATEGORY_DESC": "Credits Restructures",
                "Total_Due": 1100,
                "LOAN_DURATION": 9,
            },
        ])
        with SessionLocal() as db:
            batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=date(2026, 7, 31),
                file_name="current_mcr.xlsx",
            )
            db.add(batch)
            db.flush()
            db.add_all([
                LoanRaw(
                    contract_no="MCR-KEEP",
                    client_name="Ahmed 1",
                    client_first_name="Ali",
                    client_id="CLI-001",
                    agency_name="Agence Centre",
                    agent_name="GP Centre",
                    category_desc="Credits Restructures",
                    disbursement_amount=Decimal("25000.000"),
                    principal_outstanding=Decimal("1000.000"),
                    principal_due=Decimal("100.000"),
                    total_scheduled_amount=Decimal("100.000"),
                    days_overdue=0,
                    total_due=Decimal("900.000"),
                    status="active",
                    disbursement_date=date(2026, 7, 7),
                    snapshot_date=batch.snapshot_date,
                    import_batch_id=batch.id,
                ),
                LoanRaw(
                    contract_no="PEND-KEEP",
                    client_name="Ahmed 2",
                    client_first_name="Ali",
                    client_id="CLI-002",
                    agency_name="Agence Centre",
                    agent_name="GP Centre",
                    category_desc="Credits Consolides",
                    disbursement_amount=Decimal("25000.000"),
                    principal_outstanding=Decimal("1000.000"),
                    principal_due=Decimal("100.000"),
                    total_scheduled_amount=Decimal("100.000"),
                    days_overdue=0,
                    total_due=Decimal("600.000"),
                    status="active",
                    disbursement_date=date(2026, 7, 7),
                    snapshot_date=batch.snapshot_date,
                    import_batch_id=batch.id,
                ),
                LoanRaw(
                    contract_no="OTHER-CATEGORY",
                    client_name="Ahmed 3",
                    client_first_name="Ali",
                    client_id="CLI-003",
                    agency_name="Agence Centre",
                    agent_name="GP Centre",
                    category_desc="Autre produit",
                    disbursement_amount=Decimal("25000.000"),
                    principal_outstanding=Decimal("1000.000"),
                    principal_due=Decimal("100.000"),
                    total_scheduled_amount=Decimal("100.000"),
                    days_overdue=0,
                    total_due=Decimal("300.000"),
                    status="active",
                    disbursement_date=date(2026, 7, 7),
                    snapshot_date=batch.snapshot_date,
                    import_batch_id=batch.id,
                ),
            ])
            db.add_all([
                RestructuredContract(
                    source_contract_no="LIST-KEEP",
                    contract_no="LIST-KEEP",
                    normalized_contract_no="LIST-KEEP",
                    credit_family=RESTRUCTURED_FAMILY,
                    delay_date=date(2026, 1, 10),
                    category_desc="Credits Restructures",
                    total_due=Decimal("1000.000"),
                    loan_duration=12,
                    source=LIST_IMPORT_SOURCE,
                ),
                RestructuredContract(
                    source_contract_no="MCR-KEEP",
                    contract_no="MCR-KEEP",
                    normalized_contract_no="MCR-KEEP",
                    credit_family=RESTRUCTURED_FAMILY,
                    delay_date=date(2026, 2, 10),
                    category_desc="Credits Restructures",
                    total_due=Decimal("900.000"),
                    loan_duration=10,
                    source=MANUAL_COMPLETION_SOURCE,
                ),
                RestructuredContract(
                    source_contract_no="DELETE-ME",
                    contract_no="DELETE-ME",
                    normalized_contract_no="DELETE-ME",
                    credit_family=CONSOLIDATED_FAMILY,
                    delay_date=date(2026, 3, 10),
                    category_desc="Credits Consolides",
                    total_due=Decimal("700.000"),
                    loan_duration=8,
                    source=LIST_IMPORT_SOURCE,
                ),
                RestructuredContract(
                    source_contract_no="OTHER-CATEGORY",
                    contract_no="OTHER-CATEGORY",
                    normalized_contract_no="OTHER-CATEGORY",
                    credit_family=RESTRUCTURED_FAMILY,
                    delay_date=date(2026, 4, 10),
                    category_desc="Autre produit",
                    total_due=Decimal("300.000"),
                    loan_duration=6,
                    source=LIST_IMPORT_SOURCE,
                ),
            ])
            db.add(PendingRestructuredContract(
                contract_no="PEND-DELETE",
                normalized_contract_no="PEND-DELETE",
                credit_family=RESTRUCTURED_FAMILY,
                category_desc="Credits Restructures",
                status=PENDING_STATUS_TO_COMPLETE,
                missing_fields=["Date de decalage"],
            ))
            db.add(PendingRestructuredContract(
                contract_no="PEND-KEEP",
                normalized_contract_no="PEND-KEEP",
                credit_family=CONSOLIDATED_FAMILY,
                category_desc="Credits Consolides",
                status=PENDING_STATUS_TO_COMPLETE,
                missing_fields=["Date de decalage"],
            ))
            db.add(RestructuredAnalysisResult(contract_no="DELETE-ME", closure_status="En cours"))
            db.add(RestructuredGapResult(contract_no="DELETE-ME", total_gap_count=1))
            db.add(RestructuredScheduleRow(account_number="DELETE-ME", installment_no=1))
            db.commit()

            preview = preview_restructured_contract_sync(db, payload, "liste_restructures.xlsx")

            self.assertEqual(preview.existing_contracts_count, 4)
            self.assertEqual(preview.imported_list_count, 2)
            self.assertEqual(preview.detected_in_mcr_count, 2)
            self.assertEqual(preview.kept_count, 2)
            self.assertEqual(preview.add_count, 1)
            self.assertEqual(preview.update_count, 1)
            self.assertEqual(preview.delete_count, 2)
            self.assertEqual(preview.pending_cleanup_count, 1)
            self.assertEqual(
                {item.contract_no for item in preview.deletions},
                {"DELETE-ME", "OTHER-CATEGORY", "PEND-DELETE"},
            )

            result = import_restructured_contracts(db, payload, "liste_restructures.xlsx")

            self.assertEqual(result.inserted, 1)
            self.assertEqual(result.updated, 1)
            self.assertEqual(result.deleted, 2)
            self.assertEqual(result.kept_count, 2)
            self.assertEqual(result.pending_cleanup_count, 1)

            remaining_contracts = {
                row.contract_no
                for row in db.scalars(select(RestructuredContract)).all()
            }
            self.assertEqual(remaining_contracts, {"LIST-KEEP", "MCR-KEEP", "NEW-LIST"})
            remaining_pending = {
                row.contract_no
                for row in db.scalars(select(PendingRestructuredContract)).all()
            }
            self.assertEqual(remaining_pending, {"PEND-KEEP"})
            self.assertIsNone(
                db.scalar(
                    select(RestructuredAnalysisResult).where(
                        RestructuredAnalysisResult.contract_no == "DELETE-ME"
                    )
                )
            )
            self.assertIsNone(
                db.scalar(
                    select(RestructuredGapResult).where(
                        RestructuredGapResult.contract_no == "DELETE-ME"
                    )
                )
            )
            self.assertEqual(
                db.scalar(
                    select(func.count(RestructuredScheduleRow.id)).where(
                        RestructuredScheduleRow.account_number == "DELETE-ME"
                    )
                ),
                0,
            )

    def test_restructured_import_is_idempotent_for_same_list(self) -> None:
        self._seed_current_batch(
            contract_no="MCR-KEEP",
            category_desc="Credits Restructures",
            total_due=Decimal("900.000"),
        )
        payload = self._build_restructured_contract_excel([
            {
                "Numero contrat": "LIST-KEEP",
                "No contrat": "LIST-KEEP",
                "Colonne1": "RST",
                "date de decalage": date(2026, 1, 10),
                "dans MCR": "Oui",
                "CATEGORY_DESC": "Credits Restructures",
                "Total_Due": 1000,
                "LOAN_DURATION": 12,
            }
        ])
        with SessionLocal() as db:
            first = import_restructured_contracts(db, payload, "liste_restructures.xlsx")
            second = import_restructured_contracts(db, payload, "liste_restructures.xlsx")

            self.assertEqual(first.inserted, 1)
            self.assertEqual(second.inserted, 0)
            self.assertEqual(second.updated, 1)
            self.assertEqual(
                db.scalar(
                    select(func.count(RestructuredContract.id)).where(
                        RestructuredContract.contract_no == "LIST-KEEP"
                    )
                ),
                1,
            )

    def test_restructured_import_rolls_back_completely_on_failure(self) -> None:
        with SessionLocal() as db:
            db.add(
                RestructuredContract(
                    source_contract_no="LEGACY-KEEP",
                    contract_no="LEGACY-KEEP",
                    normalized_contract_no="LEGACY-KEEP",
                    credit_family=RESTRUCTURED_FAMILY,
                    delay_date=date(2026, 1, 1),
                    category_desc="Credits Restructures",
                    total_due=Decimal("500.000"),
                    loan_duration=6,
                    source=LIST_IMPORT_SOURCE,
                )
            )
            db.commit()

            payload = self._build_restructured_contract_excel([
                {
                    "Numero contrat": "NEW-LIST",
                    "No contrat": "NEW-LIST",
                    "Colonne1": "RST",
                    "date de decalage": date(2026, 5, 10),
                    "dans MCR": "Non",
                    "CATEGORY_DESC": "Credits Restructures",
                    "Total_Due": 1100,
                    "LOAN_DURATION": 9,
                }
            ])

            with self.assertRaises(ValueError):
                with patch("app.services.restructured.recalculate_restructured_results", side_effect=RuntimeError("boom")):
                    import_restructured_contracts(db, payload, "liste_restructures.xlsx")

            remaining_contracts = {
                row.contract_no
                for row in db.scalars(select(RestructuredContract)).all()
            }
            self.assertEqual(remaining_contracts, {"LEGACY-KEEP"})


if __name__ == "__main__":
    unittest.main()
