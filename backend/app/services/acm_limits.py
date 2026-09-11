from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AcmLimitConfig


ACM_LIMIT_FIELDS = (
    "par_0_limit",
    "par_30_limit",
    "par_120_limit",
    "cohort_1_30_limit",
    "cohort_31_60_limit",
    "cohort_61_90_limit",
    "cohort_91_120_limit",
)


def _configured_payload(config: AcmLimitConfig | None) -> dict:
    payload = {field: None for field in ACM_LIMIT_FIELDS}
    if config:
        for field in ACM_LIMIT_FIELDS:
            payload[field] = getattr(config, field)
        payload["updated_at"] = config.updated_at
        payload["updated_by_user_id"] = config.updated_by_user_id
    else:
        payload["updated_at"] = None
        payload["updated_by_user_id"] = None
    payload["configured"] = any(payload.get(field) is not None for field in ACM_LIMIT_FIELDS)
    return payload


def get_acm_limits_payload(db: Session) -> dict:
    config = db.scalar(select(AcmLimitConfig).order_by(AcmLimitConfig.id.asc()).limit(1))
    return _configured_payload(config)


def save_acm_limits(db: Session, payload, updated_by_user_id: int | None) -> dict:
    config = db.scalar(select(AcmLimitConfig).order_by(AcmLimitConfig.id.asc()).limit(1))
    if not config:
        config = AcmLimitConfig()
        db.add(config)
        db.flush()

    raw = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    for field in ACM_LIMIT_FIELDS:
        value = raw.get(field)
        setattr(config, field, Decimal(str(value)) if value not in (None, "") else None)
    config.updated_by_user_id = updated_by_user_id
    db.flush()
    db.refresh(config)
    return _configured_payload(config)
