from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ImportBatch, User
from app.models.enums import ImportBatchType, UserRole

logger = logging.getLogger(__name__)
_MCR_BATCH_TYPES = (
    ImportBatchType.CURRENT_STATE,
    ImportBatchType.HISTORICAL_MONTH,
    ImportBatchType.SNAPSHOT,
)


def is_committee_member(user: User | None) -> bool:
    return bool(user and user.role == UserRole.COMMITTEE_MEMBER)


def month_bounds(snapshot_date: date) -> tuple[date, date]:
    return (
        date(snapshot_date.year, snapshot_date.month, 1),
        date(snapshot_date.year, snapshot_date.month, monthrange(snapshot_date.year, snapshot_date.month)[1]),
    )


def closed_month_key(snapshot_date: date) -> str:
    return f"{snapshot_date.year:04d}-{snapshot_date.month:02d}"


def _current_month_start(reference_date: date | None = None) -> date:
    today = reference_date or date.today()
    return today.replace(day=1)


def _closed_month_batch_priority(batch: ImportBatch) -> tuple[int, str, int]:
    priority = {
        ImportBatchType.HISTORICAL_MONTH: 0,
        ImportBatchType.CURRENT_STATE: 1,
        ImportBatchType.SNAPSHOT: 2,
    }.get(batch.batch_type, 9)
    return priority, batch.imported_at.isoformat() if batch.imported_at else "", batch.id or 0


def _is_better_closed_month_candidate(candidate: ImportBatch, current: ImportBatch) -> bool:
    candidate_priority, candidate_imported_at, candidate_id = _closed_month_batch_priority(candidate)
    current_priority, current_imported_at, current_id = _closed_month_batch_priority(current)
    if candidate_priority != current_priority:
        return candidate_priority < current_priority
    if candidate_imported_at != current_imported_at:
        return candidate_imported_at > current_imported_at
    return candidate_id > current_id


def latest_closed_month_batch(db: Session) -> ImportBatch | None:
    batches = list_closed_month_batches(db)
    return batches[0] if batches else None


def list_closed_month_batches(db: Session) -> list[ImportBatch]:
    raw_batches = db.scalars(
        select(ImportBatch)
        .where(
            ImportBatch.batch_type.in_(_MCR_BATCH_TYPES),
            ImportBatch.snapshot_date.is_not(None),
        )
        .order_by(ImportBatch.snapshot_date.desc(), ImportBatch.imported_at.desc(), ImportBatch.id.desc())
    ).all()
    current_month = _current_month_start()
    selected_by_month: dict[str, ImportBatch] = {}

    logger.info(
        "Committee closed-month scan started | total_batches=%s | current_month=%s",
        len(raw_batches),
        current_month.isoformat(),
    )

    for batch in raw_batches:
        snapshot_date = batch.snapshot_date
        if snapshot_date is None:
            logger.info(
                "Committee closed-month excluded | batch_id=%s | batch_type=%s | reason=no_snapshot_date",
                batch.id,
                batch.batch_type,
            )
            continue

        normalized_month_start, _month_end = month_bounds(snapshot_date)
        month_key = closed_month_key(snapshot_date)
        imported_for_period = batch.period or month_key
        if batch.period and batch.period != month_key:
            logger.warning(
                "Committee closed-month period mismatch | batch_id=%s | batch_type=%s | snapshot_date=%s | period=%s | normalized_month=%s",
                batch.id,
                batch.batch_type,
                snapshot_date.isoformat(),
                batch.period,
                month_key,
            )

        if normalized_month_start >= current_month:
            logger.info(
                "Committee closed-month excluded | batch_id=%s | batch_type=%s | snapshot_date=%s | normalized_month=%s | imported_for=%s | reason=current_or_future_month",
                batch.id,
                batch.batch_type,
                snapshot_date.isoformat(),
                month_key,
                imported_for_period,
            )
            continue

        existing = selected_by_month.get(month_key)
        if existing is None:
            selected_by_month[month_key] = batch
            logger.info(
                "Committee closed-month included | batch_id=%s | batch_type=%s | snapshot_date=%s | normalized_month=%s | imported_for=%s | duplicate=no",
                batch.id,
                batch.batch_type,
                snapshot_date.isoformat(),
                month_key,
                imported_for_period,
            )
            continue

        if _is_better_closed_month_candidate(batch, existing):
            logger.info(
                "Committee closed-month replaced | month=%s | previous_batch_id=%s | previous_type=%s | new_batch_id=%s | new_type=%s",
                month_key,
                existing.id,
                existing.batch_type,
                batch.id,
                batch.batch_type,
            )
            selected_by_month[month_key] = batch
            continue

        logger.info(
            "Committee closed-month duplicate skipped | month=%s | kept_batch_id=%s | skipped_batch_id=%s",
            month_key,
            existing.id,
            batch.id,
        )

    resolved = [selected_by_month[key] for key in sorted(selected_by_month.keys(), reverse=True)]
    logger.info(
        "Committee closed-month scan completed | detected_months=%s",
        [closed_month_key(batch.snapshot_date) for batch in resolved if batch.snapshot_date is not None],
    )
    return resolved


def closed_month_batch_for_period(db: Session, period_label: str) -> ImportBatch | None:
    for batch in list_closed_month_batches(db):
        if batch.snapshot_date is not None and closed_month_key(batch.snapshot_date) == period_label:
            return batch
    return None


def normalize_committee_historical_request(
    db: Session,
    user: User,
    date_from: date | None,
    date_to: date | None,
    *,
    snapshot_batch_ids: str | None = None,
) -> tuple[date | None, date | None, ImportBatch | None]:
    if not is_committee_member(user):
        return date_from, date_to, None

    if snapshot_batch_ids and str(snapshot_batch_ids).strip():
        raise ValueError("Le profil Membre comité ne peut pas accéder aux snapshots journaliers.")

    if date_from is None and date_to is None:
        batch = latest_closed_month_batch(db)
        if batch is None or batch.snapshot_date is None:
            raise ValueError("Aucun mois clôturé n'est disponible pour le profil Membre comité.")
        month_start, month_end = month_bounds(batch.snapshot_date)
        return month_start, month_end, batch

    if date_from is None or date_to is None:
        raise ValueError("Le profil Membre comité doit sélectionner un mois clôturé complet.")
    if date_from > date_to:
        raise ValueError("La date de début doit être antérieure ou égale à la date de fin.")
    if (date_from.year, date_from.month) != (date_to.year, date_to.month):
        raise ValueError("Le profil Membre comité ne peut consulter qu'un seul mois clôturé à la fois.")

    period_label = f"{date_from.year:04d}-{date_from.month:02d}"
    batch = closed_month_batch_for_period(db, period_label)
    if batch is None or batch.snapshot_date is None:
        raise ValueError("Le mois sélectionné n'est pas clôturé ou aucune donnée historique n'est disponible.")
    month_start, month_end = month_bounds(batch.snapshot_date)
    return month_start, month_end, batch
