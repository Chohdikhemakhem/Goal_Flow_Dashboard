from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ActivitySector


def parse_csv_ints(raw_value: str | None) -> list[int]:
    if not raw_value:
        return []
    parsed: list[int] = []
    for token in str(raw_value).split(","):
        value = token.strip()
        if not value:
            continue
        try:
            parsed_id = int(value)
        except ValueError:
            continue
        if parsed_id > 0 and parsed_id not in parsed:
            parsed.append(parsed_id)
    if parsed:
        return parsed
    return [0]


def normalize_agency_ids(*, agency_id: str | None = None, agency_ids: str | None = None) -> list[int]:
    parsed_ids = parse_csv_ints(agency_ids)
    if parsed_ids:
        return parsed_ids
    return parse_csv_ints(agency_id)


def normalize_sector_ids(*, sector_ids: str | None = None) -> list[int]:
    return parse_csv_ints(sector_ids)


def sector_filter_condition(db: Session, sector_ids: list[int] | None):
    if not sector_ids:
        return None
    existing_sector_ids = set(
        db.scalars(select(ActivitySector.id).where(ActivitySector.id.in_(sector_ids))).all()
    )
    if len(existing_sector_ids) != len(sector_ids):
        from sqlalchemy import false
        return false()
    from app.models.entities import CategorySectorMapping, LoanRaw
    return LoanRaw.category_desc.in_(
        select(CategorySectorMapping.category_desc).where(
            CategorySectorMapping.activity_sector_id.in_(sector_ids)
        )
    )
