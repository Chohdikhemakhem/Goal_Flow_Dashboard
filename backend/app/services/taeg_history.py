from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AcmRateVersionAudit,
    AcmRateVersion,
    AcmRateVersionDetail,
    ActivitySector,
    Agency,
    Agent,
    CategorySectorMapping,
    ImportBatch,
    TaegDailySnapshot,
    User,
    LoanRaw,
)
from app.services.agent_identity import normalized_agent_name_expression
from app.services.selection import normalize_agency_ids
from app.services.data_scope import get_user_data_scope, region_scope_condition

FRENCH_MONTH_NAMES = {
    1: "Janvier",
    2: "Fevrier",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Aout",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Decembre",
}

STATUS_CONFORME = "conforme"
STATUS_NON_CONFORME = "non_conforme"
STATUS_NON_COUVERT = "non_couvert"


def _month_bounds(snapshot_date: date) -> tuple[date, date]:
    return (
        date(snapshot_date.year, snapshot_date.month, 1),
        date(snapshot_date.year, snapshot_date.month, monthrange(snapshot_date.year, snapshot_date.month)[1]),
    )


def _period_parts(period: str) -> tuple[int, int]:
    year = int(period[:4])
    month = int(period[5:7])
    return year, month


def _agent_join_condition():
    return (
        (normalized_agent_name_expression(Agent.name) == normalized_agent_name_expression(LoanRaw.agent_name))
        & (Agent.agency_id == Agency.id)
    )


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _format_acm_block_range(start_date: date | None, end_date: date | None) -> str:
    if start_date is None:
        return "Bloc ACM inconnu"
    end_label = end_date.strftime("%d/%m/%Y") if isinstance(end_date, date) else "Jusqu'a modification"
    return f"{start_date.strftime('%d/%m/%Y')} -> {end_label}"


def _segment_key(version_id: int | None, range_start: date, range_end: date) -> str:
    version_fragment = f"v{version_id}" if version_id is not None else "vnone"
    return f"{version_fragment}:{range_start.isoformat()}:{range_end.isoformat()}"


def _matching_acm_versions_query(target_date: date):
    return (
        select(AcmRateVersion)
        .where(AcmRateVersion.effective_start_date <= target_date)
        .where(
            or_(
                AcmRateVersion.effective_end_date.is_(None),
                AcmRateVersion.effective_end_date >= target_date,
            )
        )
        .order_by(
            AcmRateVersion.effective_start_date.desc(),
            AcmRateVersion.created_at.desc(),
            AcmRateVersion.id.desc(),
        )
    )


def get_applicable_acm_block(db: Session, disbursement_date: date) -> AcmRateVersion | None:
    matches = db.scalars(_matching_acm_versions_query(disbursement_date)).all()
    if not matches:
        return None
    if len(matches) > 1:
        block_labels = ", ".join(
            _format_acm_block_range(item.effective_start_date, item.effective_end_date)
            for item in matches[:3]
        )
        if len(matches) > 3:
            block_labels = f"{block_labels}, ..."
        raise ValueError(
            "Configuration ACM incoherente : plusieurs blocs couvrent la date "
            f"{disbursement_date.strftime('%d/%m/%Y')} ({block_labels})."
        )
    return matches[0]


def _selected_period_ranges(periods: list[dict]) -> list[tuple[date, date, str]]:
    ranges: list[tuple[date, date, str]] = []
    for period in periods:
        snapshot_date = period.get("snapshot_date")
        if not isinstance(snapshot_date, date):
            continue
        month_start, month_end = _month_bounds(snapshot_date)
        ranges.append((month_start, month_end, str(period.get("label") or snapshot_date.strftime("%m/%Y"))))
    return ranges


def _selected_period_overlap_filter(periods: list[dict]):
    ranges = _selected_period_ranges(periods)
    if not ranges:
        return None
    return or_(*[
        and_(
            AcmRateVersion.effective_start_date <= range_end,
            or_(
                AcmRateVersion.effective_end_date.is_(None),
                AcmRateVersion.effective_end_date >= range_start,
            ),
        )
        for range_start, range_end, _label in ranges
    ])


def validate_acm_blocks_for_periods(db: Session, periods: list[dict]) -> None:
    overlap_filter = _selected_period_overlap_filter(periods)
    if overlap_filter is None:
        return

    ranges = _selected_period_ranges(periods)
    versions = db.scalars(
        select(AcmRateVersion)
        .where(overlap_filter)
        .order_by(
            AcmRateVersion.effective_start_date.asc(),
            AcmRateVersion.created_at.asc(),
            AcmRateVersion.id.asc(),
        )
    ).all()

    for index, version in enumerate(versions):
        current_end = version.effective_end_date
        for other in versions[index + 1:]:
            if current_end is not None and other.effective_start_date > current_end:
                break
            overlap_start = max(version.effective_start_date, other.effective_start_date)
            overlap_end_candidates = [candidate for candidate in (current_end, other.effective_end_date) if candidate is not None]
            overlap_end = min(overlap_end_candidates) if overlap_end_candidates else None
            for range_start, range_end, range_label in ranges:
                effective_overlap_start = max(overlap_start, range_start)
                effective_overlap_end = min(overlap_end or range_end, range_end)
                if effective_overlap_start <= effective_overlap_end:
                    raise ValueError(
                        "Configuration ACM incoherente : plusieurs blocs couvrent la sous-periode "
                        f"{effective_overlap_start.strftime('%d/%m/%Y')} -> {effective_overlap_end.strftime('%d/%m/%Y')} "
                        f"pour {range_label}."
                    )


def _applied_acm_scalar(column, *, date_expr=None, sector_id_expr=None):
    target_date_expr = LoanRaw.disbursement_date if date_expr is None else date_expr
    target_sector_expr = ActivitySector.id if sector_id_expr is None else sector_id_expr
    return (
        select(column)
        .select_from(AcmRateVersionDetail)
        .join(AcmRateVersion, AcmRateVersion.id == AcmRateVersionDetail.version_id)
        .where(AcmRateVersionDetail.activity_sector_id == target_sector_expr)
        .where(AcmRateVersion.effective_start_date <= target_date_expr)
        .where(
            or_(
                AcmRateVersion.effective_end_date.is_(None),
                AcmRateVersion.effective_end_date >= target_date_expr,
            )
        )
        .order_by(
            AcmRateVersion.effective_start_date.desc(),
            AcmRateVersion.created_at.desc(),
            AcmRateVersion.id.desc(),
        )
        .limit(1)
        .correlate(LoanRaw, ActivitySector)
        .scalar_subquery()
    )


def build_applied_acm_subqueries(*, date_expr=None, sector_id_expr=None) -> dict[str, object]:
    return {
        "version_id": _applied_acm_scalar(AcmRateVersion.id, date_expr=date_expr, sector_id_expr=sector_id_expr),
        "version_start_date": _applied_acm_scalar(
            AcmRateVersion.effective_start_date,
            date_expr=date_expr,
            sector_id_expr=sector_id_expr,
        ),
        "version_end_date": _applied_acm_scalar(
            AcmRateVersion.effective_end_date,
            date_expr=date_expr,
            sector_id_expr=sector_id_expr,
        ),
        "acm_rate": _applied_acm_scalar(
            AcmRateVersionDetail.acm_rate,
            date_expr=date_expr,
            sector_id_expr=sector_id_expr,
        ),
    }


def list_acm_rate_periods(db: Session) -> list[dict]:
    versions = db.scalars(
        select(AcmRateVersion).order_by(
            AcmRateVersion.effective_start_date.asc(),
            AcmRateVersion.created_at.asc(),
            AcmRateVersion.id.asc(),
        )
    ).all()
    return [
        {
            "id": version.id,
            "effective_start_date": version.effective_start_date,
            "effective_end_date": version.effective_end_date,
            "is_open_ended": bool(version.is_open_ended or version.effective_end_date is None),
            "status": version.status,
            "comment": version.comment,
            "created_at": version.created_at,
        }
        for version in versions
    ]


def build_acm_coverage_segments_for_periods(db: Session, periods: list[dict]) -> tuple[list[dict], str | None]:
    validate_acm_blocks_for_periods(db, periods)
    versions = list_acm_rate_periods(db)
    if not periods:
        return [], "Aucune periode TAEG disponible."

    raw_segments: list[dict] = []
    uncovered_periods: list[str] = []
    for period in periods:
        snapshot_date = period.get("snapshot_date")
        if not isinstance(snapshot_date, date):
            continue
        month_start, month_end = _month_bounds(snapshot_date)
        cursor = month_start
        while cursor <= month_end:
            active_version = next(
                (
                    version
                    for version in versions
                    if version["effective_start_date"] <= cursor
                    and (
                        version["effective_end_date"] is None
                        or version["effective_end_date"] >= cursor
                    )
                ),
                None,
            )
            if active_version is not None:
                version_end = active_version["effective_end_date"] or month_end
                segment_end = min(month_end, version_end)
                raw_segments.append(
                    {
                        "period_key": period.get("key"),
                        "period_label": period.get("label"),
                        "range_start": cursor,
                        "range_end": segment_end,
                        "covered": True,
                        "version_id": active_version["id"],
                        "block_label": f"Bloc ACM du {active_version['effective_start_date'].strftime('%d/%m/%Y')}",
                        "block_start_date": active_version["effective_start_date"],
                        "block_end_date": active_version["effective_end_date"],
                    }
                )
                cursor = segment_end + timedelta(days=1)
                continue

            next_start = min(
                (
                    version["effective_start_date"]
                    for version in versions
                    if version["effective_start_date"] > cursor
                ),
                default=None,
            )
            uncovered_end = month_end
            if next_start is not None and next_start <= month_end:
                uncovered_end = min(month_end, next_start - timedelta(days=1))
            raw_segments.append(
                {
                    "period_key": period.get("key"),
                    "period_label": period.get("label"),
                    "range_start": cursor,
                    "range_end": uncovered_end,
                    "covered": False,
                    "version_id": None,
                    "block_label": None,
                    "block_start_date": None,
                    "block_end_date": None,
                }
            )
            uncovered_periods.append(period.get("label") or snapshot_date.strftime("%m/%Y"))
            cursor = uncovered_end + timedelta(days=1)

    segments: list[dict] = []
    for segment in sorted(raw_segments, key=lambda item: (item["range_start"], item["range_end"], item.get("version_id") or -1)):
        if segments:
            previous = segments[-1]
            same_block = (
                previous.get("covered") == segment.get("covered")
                and previous.get("version_id") == segment.get("version_id")
                and previous.get("block_label") == segment.get("block_label")
                and previous.get("block_start_date") == segment.get("block_start_date")
                and previous.get("block_end_date") == segment.get("block_end_date")
            )
            contiguous = previous["range_end"] + timedelta(days=1) == segment["range_start"]
            if same_block and contiguous:
                previous["range_end"] = segment["range_end"]
                previous["segment_key"] = _segment_key(
                    previous.get("version_id"),
                    previous["range_start"],
                    previous["range_end"],
                )
                continue
        merged = dict(segment)
        merged["segment_key"] = _segment_key(
            merged.get("version_id"),
            merged["range_start"],
            merged["range_end"],
        )
        merged["credits_count"] = 0
        merged["sectors_count"] = 0
        merged["coverage_status"] = "partial" if not merged.get("covered", True) else "complete"
        segments.append(merged)

    message = None
    if any(not segment["covered"] for segment in segments):
        impacted = " ; ".join(dict.fromkeys(uncovered_periods))
        message = (
            "Certaines dates de la periode selectionnee ne sont couvertes par aucun bloc ACM. "
            f"Periodes impactees : {impacted}."
        )
    return segments, message


def _current_sector_rows(db: Session):
    return db.execute(
        select(
            ActivitySector.id.label("sector_id"),
            ActivitySector.name.label("sector_name"),
            ActivitySector.acm_rate.label("acm_rate"),
        ).order_by(ActivitySector.name.asc())
    ).mappings().all()


def _normalize_acm_rate_details(rate_details: list[dict] | None) -> dict[int, Decimal]:
    normalized: dict[int, Decimal] = {}
    for detail in rate_details or []:
        raw_sector_id = detail.get("sector_id")
        if raw_sector_id in (None, ""):
            raise ValueError("Chaque secteur du bloc ACM doit etre identifie.")
        try:
            sector_id = int(raw_sector_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Secteur ACM invalide: {raw_sector_id}") from exc
        if sector_id in normalized:
            raise ValueError("Un secteur ne peut apparaitre qu'une seule fois dans un bloc ACM.")
        acm_rate = _to_decimal(detail.get("acm_rate"))
        if acm_rate < 0:
            raise ValueError("Les taux ACM doivent etre superieurs ou egaux a 0.")
        normalized[sector_id] = acm_rate
    return normalized


def _resolve_block_sector_rows(
    db: Session,
    *,
    rate_details: list[dict] | None,
) -> list[dict]:
    sector_rows = _current_sector_rows(db)
    if not sector_rows:
        raise ValueError("Aucun secteur d'activite n'est configure. Creez d'abord les secteurs ACM.")

    normalized_rates = _normalize_acm_rate_details(rate_details)
    if not normalized_rates:
        return sector_rows

    available_ids = {int(row["sector_id"]) for row in sector_rows if row["sector_id"] is not None}
    missing_sectors = [row["sector_name"] for row in sector_rows if int(row["sector_id"]) not in normalized_rates]
    unknown_sectors = sorted(str(sector_id) for sector_id in normalized_rates if sector_id not in available_ids)

    if missing_sectors:
        raise ValueError(
            "Tous les secteurs actifs doivent etre renseignes dans le bloc ACM. Secteurs manquants: "
            + ", ".join(missing_sectors)
        )
    if unknown_sectors:
        raise ValueError(
            "Le bloc ACM contient des secteurs inconnus: " + ", ".join(unknown_sectors)
        )

    normalized_rows: list[dict] = []
    for row in sector_rows:
        sector_id = int(row["sector_id"])
        normalized_rows.append(
            {
                **row,
                "acm_rate": normalized_rates[sector_id],
            }
        )
    return normalized_rows


def _serialize_acm_version_state(
    *,
    version_id: int,
    effective_start_date: date,
    effective_end_date: date | None,
    is_open_ended: bool,
    status: str,
    comment: str | None,
    detail_rows: list[dict],
) -> dict:
    return {
        "id": version_id,
        "effective_start_date": effective_start_date.isoformat(),
        "effective_end_date": effective_end_date.isoformat() if isinstance(effective_end_date, date) else None,
        "is_open_ended": bool(is_open_ended or effective_end_date is None),
        "status": status,
        "comment": comment,
        "details": [
            {
                "sector_id": detail.get("sector_id"),
                "sector_name": detail.get("sector_name"),
                "acm_rate": str(detail.get("acm_rate") or Decimal("0")),
            }
            for detail in detail_rows
        ],
    }


def _version_details_rows(db: Session, version_id: int) -> list[dict]:
    return list(
        db.execute(
            select(
                AcmRateVersionDetail.id,
                AcmRateVersionDetail.activity_sector_id.label("sector_id"),
                AcmRateVersionDetail.sector_name,
                AcmRateVersionDetail.acm_rate,
            )
            .where(AcmRateVersionDetail.version_id == version_id)
            .order_by(AcmRateVersionDetail.sector_name.asc())
        ).mappings().all()
    )


def _list_import_batches_affected_by_ranges(
    db: Session,
    ranges: list[tuple[date, date | None]],
) -> list[ImportBatch]:
    normalized_ranges = [(start, end) for start, end in ranges if isinstance(start, date)]
    if not normalized_ranges:
        return []
    batches = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.snapshot_date.is_not(None))
        .order_by(ImportBatch.snapshot_date.asc(), ImportBatch.id.asc())
    ).all()
    impacted: list[ImportBatch] = []
    for batch in batches:
        snapshot_date = batch.snapshot_date
        if not isinstance(snapshot_date, date):
            continue
        month_start, month_end = _month_bounds(snapshot_date)
        if any(start <= month_end and (end is None or end >= month_start) for start, end in normalized_ranges):
            impacted.append(batch)
    return impacted


def _list_batches_affected_by_version_change(
    db: Session,
    *,
    previous_start_date: date,
    previous_end_date: date | None,
    new_start_date: date,
    new_end_date: date | None,
) -> list[ImportBatch]:
    impacted = _list_import_batches_affected_by_ranges(
        db,
        [
            (previous_start_date, previous_end_date),
            (new_start_date, new_end_date),
        ],
    )
    deduplicated: dict[int, ImportBatch] = {}
    for batch in impacted:
        deduplicated[int(batch.id)] = batch
    return list(deduplicated.values())


def _sync_sector_rates_from_active_version(db: Session) -> None:
    active_version = db.scalar(
        select(AcmRateVersion)
        .where(AcmRateVersion.status == "actif")
        .order_by(AcmRateVersion.effective_start_date.desc(), AcmRateVersion.created_at.desc(), AcmRateVersion.id.desc())
        .limit(1)
    )
    active_rate_map: dict[int, Decimal] = {}
    if active_version:
        for detail in _version_details_rows(db, active_version.id):
            sector_id = detail.get("sector_id")
            if sector_id is not None:
                active_rate_map[int(sector_id)] = _to_decimal(detail.get("acm_rate"))
    for sector in db.scalars(select(ActivitySector)).all():
        sector.acm_rate = active_rate_map.get(int(sector.id), Decimal("0"))


def _validate_version_chain(version_rows: list[dict]) -> None:
    if not version_rows:
        return
    ordered = sorted(
        version_rows,
        key=lambda item: (item["effective_start_date"], item.get("id") or 0),
    )
    for index, current in enumerate(ordered):
        start_date = current["effective_start_date"]
        end_date = current["effective_end_date"]
        if end_date is not None and end_date < start_date:
            raise ValueError("La date de fin ACM doit etre superieure ou egale a la date de debut.")
        if end_date is None and index < len(ordered) - 1:
            raise ValueError("Le mode 'Jusqu'a modification' est reserve au dernier bloc ACM.")
        if index == len(ordered) - 1:
            continue
        next_start = ordered[index + 1]["effective_start_date"]
        if end_date is None:
            raise ValueError("Le dernier bloc ACM ne peut pas chevaucher un bloc suivant.")
        if next_start <= end_date:
            raise ValueError("La periode choisie chevauche une version ACM existante.")
        if end_date + timedelta(days=1) < next_start:
            raise ValueError("La periode modifiee cree un intervalle non couvert entre deux blocs ACM.")


def _audit_entries_payload(db: Session, version_id: int) -> list[dict]:
    entries = db.scalars(
        select(AcmRateVersionAudit)
        .where(AcmRateVersionAudit.version_id == version_id)
        .order_by(AcmRateVersionAudit.modified_at.desc(), AcmRateVersionAudit.id.desc())
    ).all()
    user_ids = [entry.modified_by_user_id for entry in entries if entry.modified_by_user_id is not None]
    user_map = {
        user.id: user.full_name
        for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    return [
        {
            "id": entry.id,
            "modified_by_user_id": entry.modified_by_user_id,
            "modified_by_name": user_map.get(entry.modified_by_user_id),
            "modified_at": entry.modified_at,
            "comment": entry.comment,
            "previous_start_date": entry.previous_start_date,
            "previous_end_date": entry.previous_end_date,
            "previous_is_open_ended": entry.previous_is_open_ended,
            "new_start_date": entry.new_start_date,
            "new_end_date": entry.new_end_date,
            "new_is_open_ended": entry.new_is_open_ended,
            "previous_values_json": entry.previous_values_json or {},
            "new_values_json": entry.new_values_json or {},
        }
        for entry in entries
    ]

    available_ids = {int(row["sector_id"]) for row in sector_rows if row["sector_id"] is not None}
    missing_sectors = [row["sector_name"] for row in sector_rows if int(row["sector_id"]) not in normalized_rates]
    unknown_sectors = sorted(str(sector_id) for sector_id in normalized_rates if sector_id not in available_ids)

    if missing_sectors:
        raise ValueError(
            "Tous les secteurs actifs doivent etre renseignes dans le bloc ACM. Secteurs manquants: "
            + ", ".join(missing_sectors)
        )
    if unknown_sectors:
        raise ValueError(
            "Le bloc ACM contient des secteurs inconnus: " + ", ".join(unknown_sectors)
        )

    normalized_rows: list[dict] = []
    for row in sector_rows:
        sector_id = int(row["sector_id"])
        normalized_rows.append(
            {
                **row,
                "acm_rate": normalized_rates[sector_id],
            }
        )
    return normalized_rows


def create_acm_rate_version(
    db: Session,
    *,
    created_by_user_id: int | None,
    effective_start_date: date,
    effective_end_date: date | None = None,
    is_open_ended: bool = False,
    comment: str | None = None,
    details: list[dict] | None = None,
    created_at: datetime | None = None,
) -> AcmRateVersion:
    if is_open_ended and effective_end_date is not None:
        raise ValueError("Un bloc ACM 'Jusqu'a modification' ne doit pas definir de date de fin.")
    if not is_open_ended and effective_end_date is None:
        raise ValueError("La date de fin ACM est obligatoire, sauf en mode 'Jusqu'a modification'.")
    if effective_end_date is not None and effective_end_date < effective_start_date:
        raise ValueError("La date de fin ACM doit etre superieure ou egale a la date de debut.")

    duplicate = db.scalar(
        select(AcmRateVersion).where(AcmRateVersion.effective_start_date == effective_start_date)
    )
    if duplicate:
        raise ValueError("Une version ACM existe deja pour cette date de debut.")

    sector_rows = _resolve_block_sector_rows(db, rate_details=details)

    previous_version = db.scalar(
        select(AcmRateVersion)
        .where(AcmRateVersion.effective_start_date < effective_start_date)
        .order_by(AcmRateVersion.effective_start_date.desc(), AcmRateVersion.id.desc())
        .limit(1)
    )
    if previous_version and previous_version.effective_end_date is not None and previous_version.effective_end_date >= effective_start_date:
        raise ValueError("La periode choisie chevauche une version ACM existante.")
    if previous_version and previous_version.effective_end_date is not None and previous_version.effective_end_date + timedelta(days=1) < effective_start_date:
        raise ValueError("La nouvelle periode ACM cree un intervalle non couvert apres le bloc precedent.")
    if previous_version and previous_version.effective_end_date is None:
        previous_version.effective_end_date = effective_start_date - timedelta(days=1)
        previous_version.is_open_ended = False
        previous_version.status = "historique"

    next_version = db.scalar(
        select(AcmRateVersion)
        .where(AcmRateVersion.effective_start_date > effective_start_date)
        .order_by(AcmRateVersion.effective_start_date.asc(), AcmRateVersion.id.asc())
        .limit(1)
    )
    resolved_end_date = None if is_open_ended else effective_end_date
    if next_version:
        next_start = next_version.effective_start_date
        if resolved_end_date is None:
            resolved_end_date = next_start - timedelta(days=1)
        elif resolved_end_date >= next_start:
            raise ValueError("La periode choisie chevauche une version ACM plus recente.")
        elif resolved_end_date + timedelta(days=1) < next_start:
            raise ValueError("La nouvelle periode ACM cree un intervalle non couvert avant le bloc suivant.")

    if resolved_end_date is not None and resolved_end_date < effective_start_date:
        raise ValueError("La periode ACM doit couvrir au moins un jour complet.")

    version = AcmRateVersion(
        created_by_user_id=created_by_user_id,
        effective_start_date=effective_start_date,
        effective_end_date=resolved_end_date,
        is_open_ended=resolved_end_date is None,
        status="historique",
        comment=(comment or "").strip() or None,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(version)
    db.flush()

    for row in sector_rows:
        db.add(
            AcmRateVersionDetail(
                version_id=version.id,
                activity_sector_id=row["sector_id"],
                sector_name=row["sector_name"],
                acm_rate=row["acm_rate"] or Decimal("0"),
            )
        )
    db.flush()
    _refresh_acm_version_statuses(db)
    _sync_sector_rates_from_active_version(db)
    return version


def update_acm_rate_version(
    db: Session,
    *,
    version_id: int,
    modified_by_user_id: int | None,
    effective_start_date: date,
    effective_end_date: date | None = None,
    is_open_ended: bool = False,
    comment: str | None = None,
    modification_comment: str,
    confirm_impact: bool = False,
    details: list[dict] | None = None,
) -> tuple[AcmRateVersion, list[int]]:
    version = db.get(AcmRateVersion, version_id)
    if not version:
        raise ValueError("Version ACM introuvable.")
    if is_open_ended and effective_end_date is not None:
        raise ValueError("Un bloc ACM 'Jusqu'a modification' ne doit pas definir de date de fin.")
    if not is_open_ended and effective_end_date is None:
        raise ValueError("La date de fin ACM est obligatoire, sauf en mode 'Jusqu'a modification'.")
    if effective_end_date is not None and effective_end_date < effective_start_date:
        raise ValueError("La date de fin ACM doit etre superieure ou egale a la date de debut.")

    sector_rows = _resolve_block_sector_rows(db, rate_details=details)
    previous_details = _version_details_rows(db, version.id)
    previous_state = _serialize_acm_version_state(
        version_id=version.id,
        effective_start_date=version.effective_start_date,
        effective_end_date=version.effective_end_date,
        is_open_ended=bool(version.is_open_ended or version.effective_end_date is None),
        status=version.status,
        comment=version.comment,
        detail_rows=previous_details,
    )

    other_versions = db.scalars(
        select(AcmRateVersion)
        .where(AcmRateVersion.id != version.id)
        .order_by(AcmRateVersion.effective_start_date.asc(), AcmRateVersion.created_at.asc(), AcmRateVersion.id.asc())
    ).all()
    planned_versions = [
        {
            "id": item.id,
            "effective_start_date": item.effective_start_date,
            "effective_end_date": item.effective_end_date,
        }
        for item in other_versions
    ]
    planned_versions.append(
        {
            "id": version.id,
            "effective_start_date": effective_start_date,
            "effective_end_date": None if is_open_ended else effective_end_date,
        }
    )
    _validate_version_chain(planned_versions)

    impacted_batches = _list_batches_affected_by_version_change(
        db,
        previous_start_date=version.effective_start_date,
        previous_end_date=version.effective_end_date,
        new_start_date=effective_start_date,
        new_end_date=None if is_open_ended else effective_end_date,
    )
    if impacted_batches and not confirm_impact:
        raise ValueError("Cette modification peut changer les resultats TAEG des periodes couvertes par ce bloc.")

    version.effective_start_date = effective_start_date
    version.effective_end_date = None if is_open_ended else effective_end_date
    version.is_open_ended = bool(is_open_ended)
    version.comment = (comment or "").strip() or None

    existing_details = db.scalars(
        select(AcmRateVersionDetail).where(AcmRateVersionDetail.version_id == version.id)
    ).all()
    for detail in existing_details:
        db.delete(detail)
    db.flush()

    for row in sector_rows:
        db.add(
            AcmRateVersionDetail(
                version_id=version.id,
                activity_sector_id=row["sector_id"],
                sector_name=row["sector_name"],
                acm_rate=row["acm_rate"] or Decimal("0"),
            )
        )
    db.flush()

    _refresh_acm_version_statuses(db)
    _sync_sector_rates_from_active_version(db)

    new_state = _serialize_acm_version_state(
        version_id=version.id,
        effective_start_date=version.effective_start_date,
        effective_end_date=version.effective_end_date,
        is_open_ended=bool(version.is_open_ended or version.effective_end_date is None),
        status=version.status,
        comment=version.comment,
        detail_rows=_version_details_rows(db, version.id),
    )
    db.add(
        AcmRateVersionAudit(
            version_id=version.id,
            modified_by_user_id=modified_by_user_id,
            comment=modification_comment.strip(),
            previous_start_date=previous_state["effective_start_date"] and date.fromisoformat(previous_state["effective_start_date"]),
            previous_end_date=date.fromisoformat(previous_state["effective_end_date"]) if previous_state["effective_end_date"] else None,
            previous_is_open_ended=bool(previous_state["is_open_ended"]),
            new_start_date=version.effective_start_date,
            new_end_date=version.effective_end_date,
            new_is_open_ended=bool(version.is_open_ended or version.effective_end_date is None),
            previous_values_json=previous_state,
            new_values_json=new_state,
        )
    )
    db.flush()

    recalculated_batch_ids: list[int] = []
    for batch in impacted_batches:
        create_taeg_daily_snapshot_for_batch(db, int(batch.id))
        recalculated_batch_ids.append(int(batch.id))
    db.flush()
    return version, recalculated_batch_ids


def resolve_acm_rate_version(db: Session, effective_date: date) -> AcmRateVersion | None:
    return get_applicable_acm_block(db, effective_date)


def _refresh_acm_version_statuses(db: Session) -> None:
    today = date.today()
    versions = db.scalars(
        select(AcmRateVersion).order_by(
            AcmRateVersion.effective_start_date.asc(),
            AcmRateVersion.created_at.asc(),
            AcmRateVersion.id.asc(),
        )
    ).all()
    active_version_id = None
    for version in versions:
        version.is_open_ended = version.effective_end_date is None
        if version.effective_start_date <= today and (version.effective_end_date is None or version.effective_end_date >= today):
            active_version_id = version.id
    for version in versions:
        version.status = "actif" if version.id == active_version_id else "historique"


def resolve_acm_rate_map(db: Session, effective_date: date) -> dict[int, dict]:
    version = resolve_acm_rate_version(db, effective_date)
    if version:
        details = db.execute(
            select(
                AcmRateVersionDetail.activity_sector_id.label("sector_id"),
                AcmRateVersionDetail.sector_name.label("sector_name"),
                AcmRateVersionDetail.acm_rate.label("acm_rate"),
            )
            .where(AcmRateVersionDetail.version_id == version.id)
            .order_by(AcmRateVersionDetail.sector_name.asc())
        ).mappings().all()
        return {
            int(detail["sector_id"]): {
                "sector_name": detail["sector_name"],
                "acm_rate": detail["acm_rate"] or Decimal("0"),
                "version_id": version.id,
                "version_created_at": version.created_at,
            }
            for detail in details
            if detail["sector_id"] is not None
        }

    return {
        int(row["sector_id"]): {
            "sector_name": row["sector_name"],
            "acm_rate": row["acm_rate"] or Decimal("0"),
            "version_id": None,
            "version_created_at": None,
        }
        for row in _current_sector_rows(db)
        if row["sector_id"] is not None
    }


def resolve_acm_rate_maps_for_periods(db: Session, periods: list[dict]) -> dict[int, dict[int, dict]]:
    resolved: dict[int, dict[int, dict]] = {}
    for period in periods:
        batch_id = period.get("batch_id")
        snapshot_date = period.get("snapshot_date")
        if batch_id is None or not isinstance(snapshot_date, date):
            continue
        resolved[int(batch_id)] = resolve_acm_rate_map(db, snapshot_date)
    return resolved


def list_acm_rate_versions(db: Session) -> list[dict]:
    versions = db.scalars(
        select(AcmRateVersion)
        .order_by(AcmRateVersion.effective_start_date.desc(), AcmRateVersion.created_at.desc(), AcmRateVersion.id.desc())
    ).all()
    user_map = {
        user.id: user.full_name
        for user in db.scalars(select(User).where(User.id.in_([item.created_by_user_id for item in versions if item.created_by_user_id is not None]))).all()
    } if versions else {}
    counts = {
        version_id: count
        for version_id, count in db.execute(
            select(
                AcmRateVersionDetail.version_id,
                func.count(AcmRateVersionDetail.id),
            )
            .group_by(AcmRateVersionDetail.version_id)
        ).all()
    }
    return [
        {
            "id": version.id,
            "effective_start_date": version.effective_start_date,
            "effective_end_date": version.effective_end_date,
            "is_open_ended": bool(version.is_open_ended or version.effective_end_date is None),
            "status": version.status,
            "comment": version.comment,
            "created_at": version.created_at,
            "created_by_user_id": version.created_by_user_id,
            "created_by_name": user_map.get(version.created_by_user_id),
            "sector_count": counts.get(version.id, 0),
        }
        for version in versions
    ]


def get_acm_rate_version_payload(db: Session, version_id: int) -> dict | None:
    version = db.get(AcmRateVersion, version_id)
    if not version:
        return None
    actor = db.get(User, version.created_by_user_id) if version.created_by_user_id else None
    details = _version_details_rows(db, version.id)
    affected_snapshot_count = len(
        _list_import_batches_affected_by_ranges(
            db,
            [(version.effective_start_date, version.effective_end_date)],
        )
    )
    return {
        "id": version.id,
        "effective_start_date": version.effective_start_date,
        "effective_end_date": version.effective_end_date,
        "is_open_ended": bool(version.is_open_ended or version.effective_end_date is None),
        "status": version.status,
        "comment": version.comment,
        "created_at": version.created_at,
        "created_by_user_id": version.created_by_user_id,
        "created_by_name": actor.full_name if actor else None,
        "sector_count": len(details),
        "details": list(details),
        "affected_snapshot_count": affected_snapshot_count,
        "may_affect_existing_results": affected_snapshot_count > 0,
        "audit_entries": _audit_entries_payload(db, version.id),
    }


def create_taeg_daily_snapshot_for_batch(db: Session, import_batch_id: int) -> int:
    batch = db.get(ImportBatch, import_batch_id)
    if not batch:
        return 0
    validate_acm_blocks_for_periods(
        db,
        [
            {
                "key": f"historical:{batch.id}" if batch.period else "current",
                "label": batch.period or "Etat actuel",
                "snapshot_date": batch.snapshot_date,
                "batch_id": batch.id,
            }
        ],
    )
    snapshot_date = batch.snapshot_date
    month_start, month_end = _month_bounds(snapshot_date)
    applied_acm = build_applied_acm_subqueries()
    applied_acm_rate_expr = applied_acm["acm_rate"]
    disbursement_amount_expr = func.coalesce(LoanRaw.disbursement_amount, Decimal("0"))
    taeg_amount_expr = func.coalesce(LoanRaw.teg_rate, Decimal("0")) * disbursement_amount_expr
    covered_amount_expr = func.coalesce(
        func.sum(
            case(
                (applied_acm_rate_expr.is_not(None), disbursement_amount_expr),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    weighted_acm_numerator_expr = func.coalesce(
        func.sum(
            case(
                (applied_acm_rate_expr.is_not(None), applied_acm_rate_expr * disbursement_amount_expr),
                else_=Decimal("0"),
            )
        ),
        Decimal("0"),
    )
    non_compliant_count_expr = func.sum(
        case(
            (
                and_(
                    applied_acm_rate_expr.is_not(None),
                    func.coalesce(LoanRaw.teg_rate, Decimal("0")) > applied_acm_rate_expr,
                ),
                1,
            ),
            else_=0,
        )
    )
    uncovered_count_expr = func.sum(
        case(
            (applied_acm_rate_expr.is_(None), 1),
            else_=0,
        )
    )

    rows = db.execute(
        select(
            Agency.id.label("agency_id"),
            Agent.id.label("agent_id"),
            ActivitySector.id.label("sector_id"),
            ActivitySector.name.label("sector_name"),
            func.count(LoanRaw.id).label("credits_count"),
            func.coalesce(func.sum(LoanRaw.disbursement_amount), Decimal("0")).label("disbursement_amount"),
            func.coalesce(
                func.sum(taeg_amount_expr),
                Decimal("0"),
            ).label("taeg_calculated"),
            covered_amount_expr.label("covered_disbursement_amount"),
            weighted_acm_numerator_expr.label("acm_weighted_numerator"),
            func.coalesce(non_compliant_count_expr, 0).label("non_compliant_credits_count"),
            func.coalesce(uncovered_count_expr, 0).label("uncovered_credits_count"),
        )
        .select_from(LoanRaw)
        .join(Agency, Agency.name == LoanRaw.agency_name)
        .join(Agent, _agent_join_condition())
        .join(CategorySectorMapping, CategorySectorMapping.category_desc == LoanRaw.category_desc)
        .join(ActivitySector, ActivitySector.id == CategorySectorMapping.activity_sector_id)
        .where(
            LoanRaw.import_batch_id == import_batch_id,
            LoanRaw.disbursement_date >= month_start,
            LoanRaw.disbursement_date <= month_end,
        )
        .group_by(Agency.id, Agent.id, ActivitySector.id, ActivitySector.name)
        .order_by(ActivitySector.name.asc(), Agency.id.asc(), Agent.id.asc())
    ).mappings().all()

    db.execute(delete(TaegDailySnapshot).where(TaegDailySnapshot.snapshot_date == snapshot_date))
    db.flush()

    inserted = 0
    for row in rows:
        disbursement_amount = _to_decimal(row["disbursement_amount"])
        taeg_calculated = _to_decimal(row["taeg_calculated"])
        taeg_weighted_rate = taeg_calculated / disbursement_amount if disbursement_amount else Decimal("0")
        covered_disbursement_amount = _to_decimal(row.get("covered_disbursement_amount"))
        acm_weighted_numerator = _to_decimal(row.get("acm_weighted_numerator"))
        acm_rate = (
            acm_weighted_numerator / covered_disbursement_amount
            if covered_disbursement_amount
            else Decimal("0")
        )
        non_compliant_count = int(row.get("non_compliant_credits_count") or 0)
        uncovered_count = int(row.get("uncovered_credits_count") or 0)
        status = (
            STATUS_NON_COUVERT
            if covered_disbursement_amount == 0 and uncovered_count > 0
            else STATUS_CONFORME
            if taeg_weighted_rate <= acm_rate
            else STATUS_NON_CONFORME
        )
        db.add(
            TaegDailySnapshot(
                import_batch_id=import_batch_id,
                snapshot_date=snapshot_date,
                imported_at=batch.imported_at,
                period_month=snapshot_date.month,
                period_year=snapshot_date.year,
                agency_id=row["agency_id"],
                agent_id=row["agent_id"],
                sector_id=row["sector_id"],
                sector_name=row["sector_name"],
                credits_count=int(row["credits_count"] or 0),
                disbursement_amount=disbursement_amount,
                taeg_calculated=taeg_calculated,
                taeg_weighted_rate=taeg_weighted_rate,
                acm_rate=acm_rate,
                status=status,
            )
        )
        inserted += 1
    db.flush()
    return inserted


def delete_taeg_daily_snapshots_for_period(db: Session, period: str) -> int:
    year, month = _period_parts(period)
    start_date, end_date = _month_bounds(date(year, month, 1))
    deleted = db.execute(
        delete(TaegDailySnapshot).where(
            TaegDailySnapshot.snapshot_date >= start_date,
            TaegDailySnapshot.snapshot_date <= end_date,
        )
    ).rowcount or 0
    db.flush()
    return deleted


def list_taeg_monthly_history_periods(db: Session) -> list[dict]:
    rows = db.execute(
        select(
            TaegDailySnapshot.period_year,
            TaegDailySnapshot.period_month,
            func.count(func.distinct(TaegDailySnapshot.snapshot_date)).label("days_count"),
        )
        .group_by(TaegDailySnapshot.period_year, TaegDailySnapshot.period_month)
        .order_by(TaegDailySnapshot.period_year.desc(), TaegDailySnapshot.period_month.desc())
    ).mappings().all()
    return [
        {
            "key": f"{int(row['period_year']):04d}-{int(row['period_month']):02d}",
            "label": f"{FRENCH_MONTH_NAMES.get(int(row['period_month']), row['period_month'])} {row['period_year']}",
            "year": int(row["period_year"]),
            "month": int(row["period_month"]),
            "days_count": int(row["days_count"] or 0),
        }
        for row in rows
    ]


def get_taeg_monthly_history(
    db: Session,
    *,
    period: str,
    agency_id: str | None,
    agent_id: int | None,
    user: User | None = None,
) -> dict:
    year, month = _period_parts(period)
    filters = [
        TaegDailySnapshot.period_year == year,
        TaegDailySnapshot.period_month == month,
    ]
    selected_agency_ids = normalize_agency_ids(agency_id=agency_id)
    if selected_agency_ids:
        filters.append(TaegDailySnapshot.agency_id.in_(selected_agency_ids))
    if agent_id is not None:
        filters.append(TaegDailySnapshot.agent_id == agent_id)
    if user is not None:
        regional_condition = region_scope_condition(Agency.name, get_user_data_scope(user).region)
        if regional_condition is not None:
            filters.append(regional_condition)

    rows = db.execute(
        select(
            TaegDailySnapshot.snapshot_date,
            TaegDailySnapshot.sector_id,
            TaegDailySnapshot.sector_name,
            func.sum(TaegDailySnapshot.credits_count).label("credits_count"),
            func.coalesce(func.sum(TaegDailySnapshot.disbursement_amount), Decimal("0")).label("disbursement_amount"),
            func.coalesce(func.sum(TaegDailySnapshot.taeg_calculated), Decimal("0")).label("taeg_calculated"),
            func.coalesce(
                func.sum(TaegDailySnapshot.acm_rate * TaegDailySnapshot.disbursement_amount),
                Decimal("0"),
            ).label("acm_weighted_numerator"),
            func.sum(case((TaegDailySnapshot.status == STATUS_NON_COUVERT, 1), else_=0)).label("non_couvert_count"),
        )
        .select_from(TaegDailySnapshot)
        .join(Agency, Agency.id == TaegDailySnapshot.agency_id)
        .where(*filters)
        .group_by(
            TaegDailySnapshot.snapshot_date,
            TaegDailySnapshot.sector_id,
            TaegDailySnapshot.sector_name,
        )
        .order_by(TaegDailySnapshot.snapshot_date.asc(), TaegDailySnapshot.sector_name.asc())
    ).mappings().all()

    points = []
    sectors: dict[str, dict] = {}
    for row in rows:
        disbursement_amount = _to_decimal(row["disbursement_amount"])
        taeg_calculated = _to_decimal(row["taeg_calculated"])
        taeg_weighted_rate = taeg_calculated / disbursement_amount if disbursement_amount else Decimal("0")
        acm_weighted_numerator = _to_decimal(row["acm_weighted_numerator"])
        acm_rate = acm_weighted_numerator / disbursement_amount if disbursement_amount else Decimal("0")
        status = (
            STATUS_NON_COUVERT
            if int(row.get("non_couvert_count") or 0) > 0 and acm_weighted_numerator == Decimal("0")
            else STATUS_CONFORME
            if taeg_weighted_rate <= acm_rate
            else STATUS_NON_CONFORME
        )
        sector_name = row["sector_name"]
        sectors[sector_name] = {"sector_id": row["sector_id"], "sector_name": sector_name}
        points.append(
            {
                "snapshot_date": row["snapshot_date"],
                "day_label": f"{row['snapshot_date'].day:02d}",
                "sector_id": row["sector_id"],
                "sector_name": sector_name,
                "credits_count": int(row["credits_count"] or 0),
                "disbursement_amount": disbursement_amount,
                "taeg_calculated": taeg_calculated,
                "taeg_weighted_rate": taeg_weighted_rate,
                "acm_rate": acm_rate,
                "status": status,
            }
        )

    return {
        "period": {
            "key": period,
            "label": f"{FRENCH_MONTH_NAMES.get(month, month)} {year}",
            "year": year,
            "month": month,
        },
        "days_count": len({row["snapshot_date"] for row in rows}),
        "sectors": list(sectors.values()),
        "points": points,
    }
