from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.entities import RestructuredAnalysisResult, RestructuredContract, RestructuredScheduleRow
from app.services.restructured import (
    CLOSURE_STATUS_ASSUMED_CLOSED,
    CLOSURE_STATUS_IN_PROGRESS,
    CLOSURE_STATUS_NA,
    TARGET_CLOSURE_DEBUG_CONTRACT,
    recalculate_restructured_results,
)


def dump_counts(db, title: str) -> None:
    rows = db.execute(
        select(RestructuredAnalysisResult.closure_status, func.count(RestructuredAnalysisResult.id))
        .group_by(RestructuredAnalysisResult.closure_status)
        .order_by(RestructuredAnalysisResult.closure_status)
    ).all()
    print(title)
    for label, count_value in rows:
        print(f"  {label!r}: {int(count_value or 0)}")


def main() -> None:
    db = SessionLocal()
    bind = db.get_bind()
    print("DATABASE")
    print(f"  backend={bind.dialect.name}")
    print(f"  host={getattr(bind.url, 'host', None)}")
    print(f"  port={getattr(bind.url, 'port', None)}")
    print(f"  database={getattr(bind.url, 'database', None)}")
    print(f"  schema={db.execute(select(func.current_schema())).scalar_one_or_none()}")
    print()

    dump_counts(db, "BEFORE")
    print()

    recalculated = recalculate_restructured_results(db)
    db.commit()
    print(f"RECALCULATED={recalculated}")
    print()

    dump_counts(db, "AFTER")
    print()

    contract = db.execute(
        select(
            RestructuredContract.contract_no,
            RestructuredContract.loan_duration,
            RestructuredAnalysisResult.closure_status,
            RestructuredAnalysisResult.last_paid_installment_no,
            RestructuredAnalysisResult.last_paid_due_date,
        )
        .join(
            RestructuredAnalysisResult,
            RestructuredAnalysisResult.contract_no == RestructuredContract.contract_no,
        )
        .where(RestructuredContract.contract_no == TARGET_CLOSURE_DEBUG_CONTRACT)
    ).first()
    print("TARGET CONTRACT")
    print(contract)
    print()

    rows = db.execute(
        select(
            RestructuredScheduleRow.installment_no,
            RestructuredScheduleRow.due_date,
            RestructuredScheduleRow.principal_due,
            RestructuredScheduleRow.principal_paid,
        )
        .where(RestructuredScheduleRow.account_number == TARGET_CLOSURE_DEBUG_CONTRACT)
        .order_by(RestructuredScheduleRow.installment_no.asc())
    ).all()
    print("LAST INSTALLMENT VALUES")
    if rows:
        last_row = rows[-1]
        print(
            f"  installment={last_row.installment_no} | due_date={last_row.due_date} | "
            f"principal_due={last_row.principal_due} | principal_paid={last_row.principal_paid}"
        )
    else:
        print("  no schedule rows")
    print()

    counts = {
        CLOSURE_STATUS_ASSUMED_CLOSED: 0,
        CLOSURE_STATUS_IN_PROGRESS: 0,
        CLOSURE_STATUS_NA: 0,
    }
    for label, count_value in db.execute(
        select(RestructuredAnalysisResult.closure_status, func.count(RestructuredAnalysisResult.id))
        .group_by(RestructuredAnalysisResult.closure_status)
    ):
        counts[label or CLOSURE_STATUS_NA] = int(count_value or 0)
    print("SUMMARY")
    print(f"  supposed_closed={counts[CLOSURE_STATUS_ASSUMED_CLOSED]}")
    print(f"  in_progress={counts[CLOSURE_STATUS_IN_PROGRESS]}")
    print(f"  na={counts[CLOSURE_STATUS_NA]}")
    db.close()


if __name__ == "__main__":
    main()
