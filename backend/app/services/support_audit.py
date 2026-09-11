from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.entities import SupportActionAudit, User
from app.models.enums import UserRole


def request_meta(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    return user_agent, ip_address


def record_support_action(
    db: Session,
    *,
    actor: User,
    action: str,
    result: str,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    target_label: str | None = None,
    details: dict | None = None,
) -> None:
    if actor.role != UserRole.SUPPORT:
        return
    user_agent, ip_address = request_meta(request)
    db.add(
        SupportActionAudit(
            actor_user_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            result=result,
            ip_address=(ip_address or "")[:128] or None,
            user_agent=(user_agent or "")[:512] or None,
            details_json=details or None,
            occurred_at=datetime.now(timezone.utc),
        )
    )
