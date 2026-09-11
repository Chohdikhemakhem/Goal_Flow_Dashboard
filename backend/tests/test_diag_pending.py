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

TEST_DB_PATH = BACKEND_DIR / "tmp_diag_pending.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "DiagNeedsAVeryStrongSecret!2026"
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["BONUS_MODULE_ACTIVE"] = "false"
os.environ["BOOTSTRAP_SUPERADMIN_EMAIL"] = ""
os.environ["BOOTSTRAP_SUPERADMIN_PASSWORD"] = ""

from app.core.config import get_settings
get_settings.cache_clear()

from app.db.base import Base
from app.db.migrations import add_missing_columns
from app.db.session import SessionLocal, engine
from app.models.entities import (
    ImportBatch,
    LoanRaw,
    PendingRestructuredContract,
    RestructuredContract,
)
from app.models.enums import ImportBatchType
from app.services.restructured import (
    list_pending_restructured_contracts,
    sync_pending_restructured_contracts_from_mcr_batch,
    _tracked_mcr_credit_family,
    _normalize_family_label,
)


class PendingDiagTestCase(unittest.TestCase):
    def setUp(self) -> None:
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        add_missing_columns(engine)

    def test_diagnostic_real_mcr_scenario(self) -> None:
        """
        Reproduce the user scenario:
        MCR has 4 loans with mixed categories; 1 of them already in restructured_contracts.
        Expected pending list size = 2.
        """
        print("\n=== DIAG 1: CATEGORY_DESC normalization ===")
        for raw in [
            "Credits Consolidés",
            "Credits Restructurés",
            "Crédit Normal",
            "credits consolides",
            " Credits Consolidés ",
            "Crédits Consolidés",
            "Credits Consolidés".lower(),
        ]:
            norm = _normalize_family_label(raw)
            family = _tracked_mcr_credit_family(raw)
            print(f"  raw={raw!r}  normalized={norm!r}  family={family!r}")

        with SessionLocal() as db:
            batch = ImportBatch(
                batch_type=ImportBatchType.CURRENT_STATE,
                period=None,
                snapshot_date=date(2026, 7, 31),
                file_name="current_mcr.xlsx",
            )
            db.add(batch)
            db.flush()
            loans = [
                ("100001", "Credits Restructurés"),
                ("100002", "Credits Consolidés"),
                ("100003", "Crédit Normal"),
                ("100004", "Credits Restructurés"),
            ]
            for idx, (cno, cat) in enumerate(loans, start=1):
                db.add(LoanRaw(
                    contract_no=cno, client_name=f"Client {idx}",
                    client_first_name="X", client_id=f"CLI-{idx:03d}",
                    agency_name="Agence Centre", agent_name="GP Centre",
                    category_desc=cat,
                    disbursement_amount=Decimal("25000"),
                    principal_outstanding=Decimal("1000"),
                    principal_due=Decimal("100"),
                    total_scheduled_amount=Decimal("100"),
                    days_overdue=0, total_due=Decimal("500"),
                    status="active", disbursement_date=date(2026, 7, 7),
                    snapshot_date=batch.snapshot_date,
                    import_batch_id=batch.id,
                ))
            # 100001 already in restructured_contracts
            db.add(RestructuredContract(
                contract_no="100001", normalized_contract_no="100001",
                credit_family="restructured",
            ))
            db.commit()
            batch_id = batch.id

        # Now run the sync that would normally run on import
        with SessionLocal() as db:
            batch = db.get(ImportBatch, batch_id)
            summary = sync_pending_restructured_contracts_from_mcr_batch(db, batch)
            db.commit()
        print("\n=== DIAG 2: sync summary ===")
        for k, v in summary.items():
            print(f"  {k} = {v}")

        # Inspect pending table
        with SessionLocal() as db:
            rows = db.query(PendingRestructuredContract).all()
            print(f"\n=== DIAG 3: pending table count = {len(rows)} ===")
            for r in rows:
                print(f"  id={r.id} contract_no={r.contract_no} norm={r.normalized_contract_no} category_desc={r.category_desc!r} family={r.credit_family}")

        # Now call the list endpoint service
        with SessionLocal() as db:
            page = list_pending_restructured_contracts(db, q=None, status=None, limit=50, offset=0)
        print(f"\n=== DIAG 4: list endpoint returned total={page.total}, items={[i.contract_no for i in page.items]} ===")

        # Assertions
        self.assertEqual(page.total, 2, f"Expected 2 pending contracts (100002, 100004), got {page.total}")
        returned = sorted(i.contract_no for i in page.items)
        self.assertEqual(returned, ["100002", "100004"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
