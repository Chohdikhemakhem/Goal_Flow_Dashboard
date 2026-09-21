from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import LoginAudit, User
from app.models.enums import UserRole


def record_successful_login(
    db: Session,
    user: User,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> None:
    db.add(
        LoginAudit(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role,
            ip_address=(ip_address or "")[:128] or None,
            user_agent=(user_agent or "")[:512] or None,
            logged_at=datetime.now(timezone.utc),
        )
    )


def _matches_filters(
    item: LoginAudit,
    *,
    user_id: int | None,
    role: UserRole | None,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    logged_date = item.logged_at.date()
    if user_id and item.user_id != user_id:
        return False
    if role and item.role != role:
        return False
    if date_from and logged_date < date_from:
        return False
    if date_to and logged_date > date_to:
        return False
    return True


def _grouped_rows(rows: list[LoginAudit]) -> list[dict]:
    grouped: dict[tuple, int] = defaultdict(int)
    for item in rows:
        hour_bucket = f"{item.logged_at.hour:02d}:00"
        key = (
            item.user_id,
            item.full_name,
            item.email,
            item.role,
            item.logged_at.date(),
            hour_bucket,
            item.ip_address,
            item.user_agent,
        )
        grouped[key] += 1

    payload = [
        {
            "user_id": key[0],
            "full_name": key[1],
            "email": key[2],
            "role": key[3],
            "login_date": key[4],
            "login_hour": key[5],
            "ip_address": key[6],
            "user_agent": key[7],
            "connection_count": count,
        }
        for key, count in grouped.items()
    ]
    payload.sort(key=lambda row: (row["login_date"], row["login_hour"], row["full_name"]), reverse=True)
    return payload


def build_login_audit_dashboard(
    db: Session,
    *,
    user_id: int | None = None,
    role: UserRole | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    all_rows = db.scalars(select(LoginAudit).order_by(LoginAudit.logged_at.desc())).all()
    filtered = [
        item
        for item in all_rows
        if _matches_filters(
            item,
            user_id=user_id,
            role=role,
            date_from=date_from,
            date_to=date_to,
        )
    ]

    grouped_rows = _grouped_rows(filtered)
    by_user_counter = Counter(f"{item.full_name} ({item.email})" for item in filtered)
    by_day_counter = Counter(item.logged_at.strftime("%d/%m/%Y") for item in filtered)
    by_hour_counter = Counter(f"{item.logged_at.hour:02d}:00" for item in filtered)

    return {
        "total_connections": len(filtered),
        "by_user": [{"label": label, "count": count} for label, count in by_user_counter.most_common()],
        "by_day": [{"label": label, "count": count} for label, count in sorted(by_day_counter.items(), reverse=True)],
        "by_hour": [{"label": label, "count": count} for label, count in sorted(by_hour_counter.items())],
        "rows": grouped_rows,
    }
