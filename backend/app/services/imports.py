from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal
from io import BytesIO
import logging
import re

import pandas as pd
from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.entities import ImportBatch, LoanRaw, PendingRestructuredContract
from app.models.enums import ImportBatchType
from app.services.agent_identity import normalize_agent_name
from app.schemas.imports import ImportResult, LoanImportRow
from app.services.gp_account_audit import build_gp_mcr_account_audit
from app.services.metrics import recalculate_daily_metrics
from app.services.taeg_history import (
    create_taeg_daily_snapshot_for_batch,
    delete_taeg_daily_snapshots_for_period,
)
from app.services.restructured import sync_pending_restructured_contracts_from_mcr_batch
from app.services.user_accounts import ensure_agent_accounts

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
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
}

OPTIONAL_COLUMNS = {"LOAN_STATUS"}
OPTIONAL_COLUMNS |= {
    "CLIENT_NAME",
    "CLIENT_FIRST_NAME",
    "CLIENT_NCNI",
    "CLIENT_RATING",
    "CATEGORY_DESC",
    "TEG_RATE",
    "MATURITY_DATE",
    "NEXT_SCHEDULE_DATE",
    "TOTAL_SCHEDULED_AMOUNT",
    "TOTAL_INTEREST_DUE_AMT",
}
PERIOD_PATTERN = re.compile(
    r"^(?:(?P<month>\d{1,2})/(?P<year>\d{4})|(?P<year2>\d{4})-(?P<month2>\d{1,2}))$"
)

REQUIRED_CANONICAL = (
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
    "DATEEOD",
)

OPTIONAL_CANONICAL = (
    "LOAN_STATUS",
    "CLIENT_NAME",
    "CLIENT_FIRST_NAME",
    "CLIENT_NCNI",
    "CLIENT_RATING",
    "CATEGORY_DESC",
    "TEG_RATE",
    "MATURITY_DATE",
    "NEXT_SCHEDULE_DATE",
    "TOTAL_SCHEDULED_AMOUNT",
    "TOTAL_INTEREST_DUE_AMT",
)

COLUMN_ALIASES = {
    "CONTRACT_NO": ("CONTRACT_NO", "CONTRACT NO"),
    "CLIENT_NO": ("CLIENT_NO", "CLIENT NO"),
    "BRANCH": ("BRANCH",),
    "DAO_NAME": ("DAO_NAME", "DAO NAME"),
    "DISBURSEMENT_AMOUNT": ("DISBURSEMENT_AMOUNT", "DISBURSEMENT AMOUNT"),
    "PRINCIPAL_OUTSTANDING": ("PRINCIPAL_OUTSTANDING", "PRINCIPAL OUTSTANDING"),
    "TOTAL_PRINCIPAL_DUE_AMT": ("TOTAL_PRINCIPAL_DUE_AMT", "TOTAL PRINCIPAL DUE AMT"),
    "TOTAL_CUR_NO_OF_DAYS_OVERDUE": (
        "TOTAL_CUR_NO_OF_DAYS_OVERDUE",
        "TOTAL CUR NO OF DAYS OVERDUE",
    ),
    "TOTAL_DUE_AMT": ("TOTAL_DUE_AMT", "TOTAL DUE AMT"),
    "DISBURSEMENT_DATE": ("DISBURSEMENT_DATE", "DISBURSEMENT DATE"),
    "DATEEOD": ("DateEOD", "DATEEOD", "DATE EOD"),
    "LOAN_STATUS": ("LOAN_STATUS", "LOAN STATUS"),
    "CLIENT_NAME": ("CLIENT_NAME", "CLIENT NAME"),
    "CLIENT_FIRST_NAME": ("CLIENT_FIRST_NAME", "CLIENT FIRST NAME"),
    "CLIENT_NCNI": ("CLIENT_NCNI", "CLIENT NCNI"),
    "CLIENT_RATING": ("CLIENT_RATING", "CLIENT RATING"),
    "CATEGORY_DESC": ("CATEGORY_DESC", "CATEGORY DESC"),
    "TEG_RATE": ("TEG_RATE", "TEG RATE", "TAEG", "T A E G"),
    "MATURITY_DATE": ("MATURITY_DATE", "MATURITY DATE"),
    "NEXT_SCHEDULE_DATE": ("NEXT_SCHEDULE_DATE", "NEXT SCHEDULE DATE"),
    "TOTAL_SCHEDULED_AMOUNT": ("TOTAL_SCHEDULED_AMOUNT", "TOTAL SCHEDULED AMOUNT"),
    "TOTAL_INTEREST_DUE_AMT": ("TOTAL_INTEREST_DUE_AMT", "TOTAL INTEREST DUE AMT"),
}


class HistoricalPeriodExistsError(ValueError):
    def __init__(self, period: str, existing_batch: ImportBatch):
        super().__init__(f"A historical import already exists for period {period}")
        self.period = period
        self.existing_batch = existing_batch


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _period_parts(period: str) -> tuple[int, int]:
    year = int(period[:4])
    month = int(period[5:7])
    return year, month


def _clean_decimal(value) -> Decimal:
    if pd.isna(value):
        return Decimal("0")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _clean_optional_text(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _excel_serial_to_date(value: int | float) -> date:
    return pd.to_datetime(value, unit="D", origin="1899-12-30").date()


def _clean_disbursement_date(value) -> date:
    if pd.isna(value):
        raise ValueError("Missing DISBURSEMENT_DATE")
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not pd.isna(value):
        as_int = int(value)
        as_text = str(as_int)
        if len(as_text) == 8:
            return pd.to_datetime(as_text, format="%Y%m%d").date()
        if 20_000 <= as_int <= 90_000:
            return _excel_serial_to_date(as_int)
        raise ValueError("DISBURSEMENT_DATE must be in YYYYMMDD format")
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() and len(stripped) == 8:
            return pd.to_datetime(stripped, format="%Y%m%d").date()
        raise ValueError("DISBURSEMENT_DATE must be in YYYYMMDD format")
    raise ValueError("Invalid DISBURSEMENT_DATE value")


def _clean_snapshot_date(value) -> date:
    if pd.isna(value):
        raise ValueError("Missing date")
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not pd.isna(value):
        as_text = str(int(value))
        if len(as_text) == 8:
            return pd.to_datetime(as_text, format="%Y%m%d").date()
        as_int = int(value)
        if 20_000 <= as_int <= 90_000:
            return _excel_serial_to_date(as_int)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() and len(stripped) == 8:
            return pd.to_datetime(stripped, format="%Y%m%d").date()
    return pd.to_datetime(value, dayfirst=True).date()


def _clean_optional_date(value) -> date | None:
    if pd.isna(value):
        return None
    return _clean_snapshot_date(value)


def _normalize_column_key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(name).upper())


def _resolve_column_name(
    normalized_lookup: dict[str, str], canonical: str, required: bool
) -> str | None:
    aliases = COLUMN_ALIASES.get(canonical, (canonical,))
    for alias in aliases:
        found = normalized_lookup.get(_normalize_column_key(alias))
        if found:
            return found
    if required:
        raise ValueError(f"Missing required column: {canonical}")
    return None


def normalize_historical_period(raw_period: str) -> str:
    normalized = raw_period.strip()
    match = PERIOD_PATTERN.match(normalized)
    if not match:
        raise ValueError("Period must use MM/YYYY or YYYY-MM format")

    if match.group("month") and match.group("year"):
        month = int(match.group("month"))
        year = int(match.group("year"))
    else:
        month = int(match.group("month2"))
        year = int(match.group("year2"))

    if month < 1 or month > 12:
        raise ValueError("Period month must be between 01 and 12")
    if year < 2000 or year > 2100:
        raise ValueError("Period year must be between 2000 and 2100")
    return f"{year:04d}-{month:02d}"


def parse_excel(content: bytes) -> list[LoanImportRow]:
    try:
        frame = pd.read_excel(
            BytesIO(content),
            engine="openpyxl",
        )
    except Exception:
        try:
            frame = pd.read_excel(BytesIO(content), engine="calamine")
        except Exception:
            frame = pd.read_excel(BytesIO(content))
    frame.columns = [str(column).strip() for column in frame.columns]

    normalized_lookup: dict[str, str] = {}
    for column in frame.columns:
        key = _normalize_column_key(column)
        if key and key not in normalized_lookup:
            normalized_lookup[key] = column

    resolved: dict[str, str | None] = {}
    for canonical in REQUIRED_CANONICAL:
        resolved[canonical] = _resolve_column_name(normalized_lookup, canonical, required=True)
    for canonical in OPTIONAL_CANONICAL:
        resolved[canonical] = _resolve_column_name(
            normalized_lookup, canonical, required=False
        )

    rows: list[LoanImportRow] = []
    for index, raw in frame.iterrows():
        try:
            contract_no = _clean_optional_text(raw[resolved["CONTRACT_NO"]])
            client_no = _clean_optional_text(raw[resolved["CLIENT_NO"]])
            branch = _clean_optional_text(raw[resolved["BRANCH"]])
            dao_name = _clean_optional_text(raw[resolved["DAO_NAME"]])
            if not contract_no or not client_no or not branch or not dao_name:
                raise ValueError(
                    "Missing one of required identifiers (CONTRACT_NO, CLIENT_NO, BRANCH, DAO_NAME)"
                )

            total_scheduled = (
                _clean_decimal(raw[resolved["TOTAL_SCHEDULED_AMOUNT"]])
                if resolved["TOTAL_SCHEDULED_AMOUNT"]
                else _clean_decimal(raw[resolved["TOTAL_PRINCIPAL_DUE_AMT"]])
            )
            row = LoanImportRow(
                contract_no=contract_no,
                client_name=(
                    _clean_optional_text(raw[resolved["CLIENT_NAME"]])
                    if resolved["CLIENT_NAME"]
                    else None
                ),
                client_first_name=(
                    _clean_optional_text(raw[resolved["CLIENT_FIRST_NAME"]])
                    if resolved["CLIENT_FIRST_NAME"]
                    else None
                ),
                client_id=client_no,
                client_ncni=(
                    _clean_optional_text(raw[resolved["CLIENT_NCNI"]])
                    if resolved["CLIENT_NCNI"]
                    else None
                ),
                agency_name=branch,
                agent_name=normalize_agent_name(dao_name),
                client_rating=(
                    _clean_optional_text(raw[resolved["CLIENT_RATING"]])
                    if resolved["CLIENT_RATING"]
                    else None
                ),
                category_desc=(
                    _clean_optional_text(raw[resolved["CATEGORY_DESC"]])
                    if resolved["CATEGORY_DESC"]
                    else None
                ),
                teg_rate=(
                    _clean_decimal(raw[resolved["TEG_RATE"]])
                    if resolved["TEG_RATE"]
                    else Decimal("0")
                ),
                disbursement_amount=_clean_decimal(raw[resolved["DISBURSEMENT_AMOUNT"]]),
                principal_outstanding=_clean_decimal(
                    raw[resolved["PRINCIPAL_OUTSTANDING"]]
                ),
                principal_due=_clean_decimal(raw[resolved["TOTAL_PRINCIPAL_DUE_AMT"]]),
                interest_due_amt=(
                    _clean_decimal(raw[resolved["TOTAL_INTEREST_DUE_AMT"]])
                    if resolved["TOTAL_INTEREST_DUE_AMT"]
                    else Decimal("0")
                ),
                total_scheduled_amount=total_scheduled,
                days_overdue=int(raw[resolved["TOTAL_CUR_NO_OF_DAYS_OVERDUE"]]),
                total_due=_clean_decimal(raw[resolved["TOTAL_DUE_AMT"]]),
                disbursement_date=_clean_disbursement_date(raw[resolved["DISBURSEMENT_DATE"]]),
                maturity_date=(
                    _clean_optional_date(raw[resolved["MATURITY_DATE"]])
                    if resolved["MATURITY_DATE"]
                    else None
                ),
                next_schedule_date=(
                    _clean_optional_date(raw[resolved["NEXT_SCHEDULE_DATE"]])
                    if resolved["NEXT_SCHEDULE_DATE"]
                    else None
                ),
                snapshot_date=_clean_snapshot_date(raw[resolved["DATEEOD"]]),
                status=(
                    str(raw[resolved["LOAN_STATUS"]]).strip()
                    if resolved["LOAN_STATUS"]
                    and not pd.isna(raw[resolved["LOAN_STATUS"]])
                    else "unknown"
                ),
            )
        except Exception as exc:
            raise ValueError(f"Invalid row {index + 2}: {exc}") from exc
        rows.append(row)
    return rows


def list_import_batches(db: Session) -> list[ImportBatch]:
    return db.scalars(select(ImportBatch).order_by(ImportBatch.imported_at.asc())).all()


def _derive_batch_snapshot_date(db: Session, batch_id: int) -> date | None:
    rows = db.execute(
        select(
            LoanRaw.snapshot_date.label("snapshot_date"),
            func.count(LoanRaw.id).label("row_count"),
        )
        .where(LoanRaw.import_batch_id == batch_id)
        .group_by(LoanRaw.snapshot_date)
        .order_by(desc("row_count"), desc("snapshot_date"))
    ).all()

    if not rows:
        return None
    if len(rows) > 1:
        logger.warning(
            "Import batch %s has multiple DateEOD values; using dominant snapshot_date=%s",
            batch_id,
            rows[0][0],
        )
    return rows[0][0]


def backfill_snapshot_batch_dates(db: Session) -> tuple[int, int]:
    batches = db.scalars(
        select(ImportBatch).where(ImportBatch.batch_type == ImportBatchType.SNAPSHOT)
    ).all()
    updated = 0
    skipped = 0

    for batch in batches:
        derived_date = _derive_batch_snapshot_date(db, batch.id)
        if derived_date is None:
            skipped += 1
            logger.warning(
                "Cannot backfill snapshot_date for snapshot batch %s: no LoanRaw rows found",
                batch.id,
            )
            continue
        if batch.snapshot_date != derived_date:
            batch.snapshot_date = derived_date
            updated += 1

    if updated:
        db.commit()
    return updated, skipped


def _archive_existing_current_batches(
    db: Session, incoming_snapshot_date: date
) -> tuple[int, int]:
    current_batches = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.batch_type == ImportBatchType.CURRENT_STATE)
        .order_by(ImportBatch.imported_at.asc(), ImportBatch.id.asc())
    ).all()
    archived = 0
    replaced_same_day = 0
    for batch in current_batches:
        derived_date = _derive_batch_snapshot_date(db, batch.id)
        effective_snapshot_date = derived_date or batch.snapshot_date
        if effective_snapshot_date == incoming_snapshot_date:
            _delete_batch_payload(db, batch)
            replaced_same_day += 1
            continue
        if derived_date is not None:
            batch.snapshot_date = derived_date
        batch.batch_type = ImportBatchType.SNAPSHOT
        batch.period = None
        archived += 1
    return archived, replaced_same_day


def _latest_current_batch(db: Session) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch)
        .where(ImportBatch.batch_type == ImportBatchType.CURRENT_STATE)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )


def _delete_taeg_daily_snapshots_for_batch(db: Session, import_batch_id: int) -> int:
    """Supprime directement les taeg_daily_snapshots qui referencent ce
    batch precis (via import_batch_id), independamment de la logique par
    periode. Necessaire pour lever la contrainte de cle etrangere
    taeg_daily_snapshots_import_batch_id_fkey avant de supprimer le batch.
    """
    result = db.execute(
        text("DELETE FROM taeg_daily_snapshots WHERE import_batch_id = :batch_id"),
        {"batch_id": import_batch_id},
    )
    return result.rowcount or 0


def _detach_pending_restructured_contracts_for_batch(
    db: Session,
    import_batch_id: int,
) -> int:
    """Detache les pending_restructured_contracts lies a un import_batch
    sur le point d'etre supprime.

    La colonne ``detected_from_import`` est nullable et joue un role
    purement informationnel / audit (elle pointe vers le batch qui a
    detecte la ligne lors d'un MCR). Les pending_restructured_contracts
    representent un travail utilisateur en cours (statut pending / ready)
    qui ne doit PAS etre supprime quand un snapshot est remplace.

    On remet donc simplement la valeur a NULL, ce qui leve la contrainte
    ``pending_restructured_contracts_detected_from_import_fkey`` sans
    detruire de donnees metier.
    """
    result = db.execute(
        text(
            "UPDATE pending_restructured_contracts "
            "SET detected_from_import = NULL "
            "WHERE detected_from_import = :batch_id"
        ),
        {"batch_id": import_batch_id},
    )
    return result.rowcount or 0


def _delete_historical_batch_for_date(db: Session, snapshot_date: date) -> tuple[int, int]:
    """Supprime le batch HISTORICAL_MONTH (mois cloture) dont le snapshot_date
    correspond exactement a la date importee.

    Permet a un import "etat actuel" (CURRENT_STATE) de remplacer un
    historique deja existant sur le meme DateEOD, au lieu d'entrer en
    conflit avec lui.
    """
    existing = db.scalar(
        select(ImportBatch).where(
            ImportBatch.batch_type == ImportBatchType.HISTORICAL_MONTH,
            ImportBatch.snapshot_date == snapshot_date,
        )
    )
    if existing is None:
        return 0, 0
    period = existing.period
    # Les taeg_daily_snapshots referencent import_batches.id via une FK :
    # ils doivent etre supprimes AVANT le batch, sinon la suppression du
    # batch echoue avec une violation de contrainte de cle etrangere.
    _delete_taeg_daily_snapshots_for_batch(db, existing.id)
    # Les pending_restructured_contracts referencent egalement
    # import_batches.id via detected_from_import (FK nullable, role
    # informationnel). On detache ces lignes (SET NULL) avant la
    # suppression du batch pour eviter la ForeignKeyViolation, sans
    # perdre le travail utilisateur en cours sur ces contrats.
    _detach_pending_restructured_contracts_for_batch(db, existing.id)
    if period:
        delete_taeg_daily_snapshots_for_period(db, period)
    deleted_rows = (
        db.execute(delete(LoanRaw).where(LoanRaw.import_batch_id == existing.id)).rowcount
        or 0
    )
    db.delete(existing)
    db.flush()
    recalculate_daily_metrics(db, snapshot_date)
    return 1, deleted_rows


def _delete_snapshot_batches_for_date(db: Session, snapshot_date: date) -> tuple[int, int]:
    snapshot_batches = db.scalars(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type == ImportBatchType.SNAPSHOT,
            ImportBatch.snapshot_date == snapshot_date,
        )
        .order_by(ImportBatch.id.asc())
    ).all()
    deleted_rows = 0
    for batch in snapshot_batches:
        _delete_taeg_daily_snapshots_for_batch(db, batch.id)
        _detach_pending_restructured_contracts_for_batch(db, batch.id)
        deleted_rows += (
            db.execute(delete(LoanRaw).where(LoanRaw.import_batch_id == batch.id)).rowcount
            or 0
        )
        db.delete(batch)
    if snapshot_batches:
        db.flush()
        recalculate_daily_metrics(db, snapshot_date)
    return len(snapshot_batches), deleted_rows


def _delete_snapshots_for_period(db: Session, period: str) -> tuple[int, int]:
    year, month = _period_parts(period)
    start_date, end_date = _month_bounds(year=year, month=month)

    snapshot_batches = db.scalars(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type == ImportBatchType.SNAPSHOT,
            ImportBatch.snapshot_date >= start_date,
            ImportBatch.snapshot_date <= end_date,
        )
        .order_by(ImportBatch.snapshot_date.asc(), ImportBatch.id.asc())
    ).all()

    if not snapshot_batches:
        return 0, 0

    logger.info(
        "Deleting snapshot batches for period=%s ids=%s",
        period,
        [batch.id for batch in snapshot_batches],
    )

    deleted_rows = 0
    affected_dates = {batch.snapshot_date for batch in snapshot_batches}
    for batch in snapshot_batches:
        _delete_taeg_daily_snapshots_for_batch(db, batch.id)
        detached = _detach_pending_restructured_contracts_for_batch(db, batch.id)
        if detached:
            logger.info(
                "Detached %s pending_restructured_contracts from batch id=%s",
                detached,
                batch.id,
            )
        deleted_rows += (
            db.execute(delete(LoanRaw).where(LoanRaw.import_batch_id == batch.id)).rowcount
            or 0
        )
        db.delete(batch)

    db.flush()
    for snapshot_date in affected_dates:
        recalculate_daily_metrics(db, snapshot_date)
    return len(snapshot_batches), deleted_rows


def _upsert_snapshot_rows(
    db: Session,
    rows: list[LoanImportRow],
    snapshot_date: date,
    import_batch_id: int,
) -> tuple[int, int, int]:
    existing_contracts = set(
        db.scalars(
            select(LoanRaw.contract_no).where(LoanRaw.snapshot_date == snapshot_date)
        ).all()
    )

    unique_by_contract: dict[str, LoanImportRow] = {}
    for row in rows:
        unique_by_contract[row.contract_no] = row
    normalized_rows = list(unique_by_contract.values())
    duplicates = len(rows) - len(normalized_rows)

    payloads = [row.model_dump() for row in normalized_rows]
    for payload in payloads:
        payload["import_batch_id"] = import_batch_id

    inserted = sum(1 for row in normalized_rows if row.contract_no not in existing_contracts)
    updated = len(normalized_rows) - inserted

    if payloads:
        dialect = db.bind.dialect.name if db.bind is not None else ""
        if dialect == "sqlite":
            batch_size = 70
            insert_builder = sqlite_insert
        elif dialect == "postgresql":
            batch_size = 1000
            insert_builder = pg_insert
        else:
            batch_size = 500
            insert_builder = None

        for start in range(0, len(payloads), batch_size):
            batch = payloads[start : start + batch_size]
            if insert_builder is None:
                db.bulk_save_objects([LoanRaw(**payload) for payload in batch])
                continue

            stmt = insert_builder(LoanRaw).values(batch)
            update_fields = {
                "client_name": stmt.excluded.client_name,
                "client_first_name": stmt.excluded.client_first_name,
                "client_id": stmt.excluded.client_id,
                "client_ncni": stmt.excluded.client_ncni,
                "agency_name": stmt.excluded.agency_name,
                "agent_name": stmt.excluded.agent_name,
                "client_rating": stmt.excluded.client_rating,
                "category_desc": stmt.excluded.category_desc,
                "teg_rate": stmt.excluded.teg_rate,
                "disbursement_amount": stmt.excluded.disbursement_amount,
                "principal_outstanding": stmt.excluded.principal_outstanding,
                "principal_due": stmt.excluded.principal_due,
                "interest_due_amt": stmt.excluded.interest_due_amt,
                "total_scheduled_amount": stmt.excluded.total_scheduled_amount,
                "days_overdue": stmt.excluded.days_overdue,
                "total_due": stmt.excluded.total_due,
                "status": stmt.excluded.status,
                "disbursement_date": stmt.excluded.disbursement_date,
                "maturity_date": stmt.excluded.maturity_date,
                "next_schedule_date": stmt.excluded.next_schedule_date,
                "import_batch_id": stmt.excluded.import_batch_id,
            }
            upsert = stmt.on_conflict_do_update(
                index_elements=[LoanRaw.contract_no, LoanRaw.snapshot_date],
                set_=update_fields,
            )
            db.execute(upsert)
        db.flush()

    return inserted, updated, duplicates


def _delete_batch_payload(db: Session, batch: ImportBatch) -> None:
    snapshot_date = batch.snapshot_date
    # taeg_daily_snapshots reference import_batches.id via une FK : il faut
    # les supprimer avant le batch, quel que soit le type de batch, sinon la
    # suppression echoue avec une violation de contrainte de cle etrangere.
    _delete_taeg_daily_snapshots_for_batch(db, batch.id)
    # pending_restructured_contracts referencent egalement import_batches.id
    # via detected_from_import (FK nullable, role informationnel). On
    # detache ces lignes (SET NULL) avant la suppression du batch pour eviter
    # la ForeignKeyViolation, sans perdre le travail utilisateur en cours.
    _detach_pending_restructured_contracts_for_batch(db, batch.id)
    db.execute(delete(LoanRaw).where(LoanRaw.import_batch_id == batch.id))
    db.delete(batch)
    db.flush()
    recalculate_daily_metrics(db, snapshot_date)


def delete_snapshot_batches(db: Session, batch_ids: list[int]) -> tuple[list[int], int]:
    normalized_ids = list(dict.fromkeys(batch_id for batch_id in batch_ids if batch_id > 0))
    if not normalized_ids:
        raise ValueError("Select at least one snapshot to delete")

    batches = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.id.in_(normalized_ids))
        .order_by(ImportBatch.id.asc())
    ).all()
    batches_by_id = {batch.id: batch for batch in batches}
    missing_ids = [batch_id for batch_id in normalized_ids if batch_id not in batches_by_id]
    if missing_ids:
        raise ValueError(f"Snapshot batches not found: {missing_ids}")

    protected_ids = [
        batch.id for batch in batches if batch.batch_type != ImportBatchType.SNAPSHOT
    ]
    if protected_ids:
        raise ValueError(
            f"Only SNAPSHOT batches can be deleted from the dashboard: {protected_ids}"
        )

    deleted_rows = 0
    affected_dates = sorted({batch.snapshot_date for batch in batches})
    for batch in batches:
        _delete_taeg_daily_snapshots_for_batch(db, batch.id)
        _detach_pending_restructured_contracts_for_batch(db, batch.id)
        result = db.execute(delete(LoanRaw).where(LoanRaw.import_batch_id == batch.id))
        deleted_rows += result.rowcount or 0
        db.delete(batch)
    db.flush()

    for snapshot_date in affected_dates:
        recalculate_daily_metrics(db, snapshot_date)
    db.commit()

    logger.warning(
        "Deleted snapshot batches ids=%s rows=%s affected_dates=%s",
        normalized_ids,
        deleted_rows,
        affected_dates,
    )
    return normalized_ids, deleted_rows


def _run_import(
    db: Session,
    content: bytes,
    file_name: str,
    batch_type: ImportBatchType,
    period: str | None,
    replace_existing: bool = False,
) -> ImportResult:
    rows = parse_excel(content)
    if not rows:
        raise ValueError("Excel file contains no loan rows")

    snapshot_dates = {row.snapshot_date for row in rows}
    if len(snapshot_dates) != 1:
        raise ValueError("A single import file must contain exactly one DateEOD value")
    snapshot_date = next(iter(snapshot_dates))

    if batch_type == ImportBatchType.HISTORICAL_MONTH and not period:
        raise ValueError("Historical import period is required")
    if batch_type == ImportBatchType.CURRENT_STATE:
        period = None

    archived_current_batches = 0
    replaced_current_batches = 0
    deleted_snapshot_batches = 0
    deleted_snapshot_rows = 0
    deleted_taeg_daily_snapshots = 0
    deleted_historical_batches = 0
    deleted_historical_rows = 0

    if batch_type == ImportBatchType.CURRENT_STATE:
        deleted_historical_batches, deleted_historical_rows = _delete_historical_batch_for_date(
            db, snapshot_date
        )
        active_current = _latest_current_batch(db)
        active_current_date = None
        if active_current:
            active_current_date = _derive_batch_snapshot_date(db, active_current.id) or active_current.snapshot_date
        if active_current_date and snapshot_date < active_current_date:
            batch_type = ImportBatchType.SNAPSHOT
            deleted_snapshot_batches, deleted_snapshot_rows = _delete_snapshot_batches_for_date(
                db, snapshot_date
            )
        else:
            deleted_snapshot_batches, deleted_snapshot_rows = _delete_snapshot_batches_for_date(
                db, snapshot_date
            )
            archived_current_batches, replaced_current_batches = _archive_existing_current_batches(
                db, snapshot_date
            )

    if batch_type == ImportBatchType.HISTORICAL_MONTH:
        existing = db.scalar(
            select(ImportBatch).where(
                ImportBatch.batch_type == ImportBatchType.HISTORICAL_MONTH,
                ImportBatch.period == period,
            )
        )
        if existing and not replace_existing:
            raise HistoricalPeriodExistsError(period=period, existing_batch=existing)
        if existing and replace_existing:
            _delete_taeg_daily_snapshots_for_batch(db, existing.id)
            delete_taeg_daily_snapshots_for_period(db, period)
            _delete_batch_payload(db, existing)
        deleted_snapshot_batches, deleted_snapshot_rows = _delete_snapshots_for_period(
            db, period
        )
        deleted_taeg_daily_snapshots = delete_taeg_daily_snapshots_for_period(db, period)

    import_batch = ImportBatch(
        batch_type=batch_type,
        period=period,
        snapshot_date=snapshot_date,
        file_name=file_name,
    )
    db.add(import_batch)
    db.flush()

    inserted, updated, duplicates = _upsert_snapshot_rows(
        db=db,
        rows=rows,
        snapshot_date=snapshot_date,
        import_batch_id=import_batch.id,
    )
    metrics_count = recalculate_daily_metrics(db, snapshot_date)
    taeg_daily_snapshot_rows = 0
    pending_restructured_summary = None
    if batch_type == ImportBatchType.CURRENT_STATE:
        taeg_daily_snapshot_rows = create_taeg_daily_snapshot_for_batch(db, import_batch.id)
        pending_restructured_summary = sync_pending_restructured_contracts_from_mcr_batch(
            db, import_batch
        )
    ensure_agent_accounts(db)
    gp_account_audit = build_gp_mcr_account_audit(db, import_batch=import_batch)
    db.commit()
    db.refresh(import_batch)

    logger.info(
        "Imported loans type=%s period=%s snapshot=%s rows=%s inserted=%s updated=%s duplicates=%s metrics=%s archived_currents=%s replaced_currents_same_day=%s deleted_snapshots=%s deleted_snapshot_rows=%s deleted_historical_batches=%s deleted_historical_rows=%s deleted_taeg_daily_snapshots=%s taeg_daily_snapshot_rows=%s",
        batch_type,
        period,
        snapshot_date,
        len(rows),
        inserted,
        updated,
        duplicates,
        metrics_count,
        archived_current_batches,
        replaced_current_batches,
        deleted_snapshot_batches,
        deleted_snapshot_rows,
        deleted_historical_batches,
        deleted_historical_rows,
        deleted_taeg_daily_snapshots,
        taeg_daily_snapshot_rows,
    )
    if pending_restructured_summary is not None:
        logger.info(
            "Restructured MCR coherence summary batch_id=%s detected_restructured=%s detected_consolidated=%s already_present=%s pending=%s errors=%s",
            import_batch.id,
            pending_restructured_summary["restructured_detected"],
            pending_restructured_summary["consolidated_detected"],
            pending_restructured_summary["already_present"],
            pending_restructured_summary["pending_to_complete"],
            pending_restructured_summary["errors"],
        )
    logger.info(
        "GP account audit after import batch_id=%s action_needed=%s accounts_absent_from_mcr=%s",
        import_batch.id,
        len(gp_account_audit["new_gp_without_accounts"]),
        len(gp_account_audit["existing_accounts_not_in_mcr"]),
    )
    return ImportResult(
        snapshot_date=snapshot_date,
        rows_seen=len(rows),
        inserted=inserted,
        updated=updated,
        duplicates=duplicates,
        metrics_recalculated=metrics_count,
        import_batch=import_batch,
    )


def import_current_state(db: Session, content: bytes, file_name: str) -> ImportResult:
    return _run_import(
        db=db,
        content=content,
        file_name=file_name,
        batch_type=ImportBatchType.CURRENT_STATE,
        period=None,
        replace_existing=True,
    )


def import_historical_month(
    db: Session,
    content: bytes,
    file_name: str,
    period: str,
    replace_existing: bool,
) -> ImportResult:
    normalized_period = normalize_historical_period(period)
    return _run_import(
        db=db,
        content=content,
        file_name=file_name,
        batch_type=ImportBatchType.HISTORICAL_MONTH,
        period=normalized_period,
        replace_existing=replace_existing,
    )


def import_loan_snapshot(db: Session, content: bytes, file_name: str = "legacy-upload.xlsx") -> ImportResult:
    # Backward compatible alias for existing clients.
    return import_current_state(db=db, content=content, file_name=file_name)


def delete_import_batch(
    db: Session,
    batch_id: int,
    allowed_types: set[ImportBatchType] | None = None,
) -> tuple[ImportBatchType, date, int]:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise ValueError("Import introuvable")
    if allowed_types is not None and batch.batch_type not in allowed_types:
        raise ValueError("Ce type d'import ne peut pas etre supprime depuis cette action")

    snapshot_date = batch.snapshot_date
    batch_type = batch.batch_type
    _delete_taeg_daily_snapshots_for_batch(db, batch.id)
    deleted_rows = (
        db.execute(delete(LoanRaw).where(LoanRaw.import_batch_id == batch.id)).rowcount
        or 0
    )
    db.delete(batch)
    db.flush()
    recalculate_daily_metrics(db, snapshot_date)
    db.commit()
    return batch_type, snapshot_date, deleted_rows
