from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_opaque_token,
    generate_placeholder_password,
    hash_opaque_token,
    hash_password,
    validate_password_policy,
)
from app.models.entities import PasswordSetupToken, RefreshToken, User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def password_is_expired(user: User) -> bool:
    if user.password_changed_at is None:
        return True
    settings = get_settings()
    return _as_utc(user.password_changed_at) <= utcnow() - timedelta(days=settings.password_expiry_days)


def enforce_password_expiration(user: User) -> bool:
    if password_is_expired(user) and not user.must_change_password:
        user.must_change_password = True
        return True
    return False


def _cookie_kwargs(max_age: int) -> dict:
    settings = get_settings()
    return {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite.capitalize(),
        "max_age": max_age,
        "path": "/",
    }


def attach_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.access_cookie_name,
        access_token,
        **_cookie_kwargs(settings.access_token_expire_minutes * 60),
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        **_cookie_kwargs(settings.refresh_token_expire_days * 24 * 60 * 60),
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.access_cookie_name, path="/")
    response.delete_cookie(settings.refresh_cookie_name, path="/")


def issue_session_tokens(
    db: Session,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str, int]:
    token_claims = {"role": user.role.value, "svn": int(user.session_nonce or 0)}
    access_token, _access_payload = create_access_token(str(user.id), token_claims)
    refresh_token, refresh_payload = create_refresh_token(str(user.id), token_claims)
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_opaque_token(refresh_token),
        jti=refresh_payload["jti"],
        expires_at=datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(refresh_record)
    db.flush()
    settings = get_settings()
    return access_token, refresh_token, settings.access_token_expire_minutes * 60


def revoke_refresh_token(db: Session, raw_refresh_token: str | None) -> User | None:
    if not raw_refresh_token:
        return None
    token_hash = hash_opaque_token(raw_refresh_token)
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if not record or record.revoked_at is not None:
        return None
    record.revoked_at = utcnow()
    db.flush()
    return db.get(User, record.user_id)


def revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    records = db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all()
    revoked_at = utcnow()
    for record in records:
        record.revoked_at = revoked_at
    db.flush()


def rotate_refresh_token(
    db: Session,
    raw_refresh_token: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str, str, int]:
    token_hash = hash_opaque_token(raw_refresh_token)
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at.replace(tzinfo=timezone.utc) <= utcnow()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_refresh_token", "message": "Refresh token is invalid or expired"},
        )

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "inactive_user", "message": "User is inactive or missing"},
        )
    enforce_password_expiration(user)

    access_token, refresh_token, expires_in_seconds = issue_session_tokens(
        db,
        user,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    replacement = db.scalar(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.token_hash == hash_opaque_token(refresh_token),
        )
    )
    record.revoked_at = utcnow()
    record.replaced_by_id = replacement.id if replacement else None
    db.flush()
    return user, access_token, refresh_token, expires_in_seconds


def register_failed_login(user: User | None) -> None:
    if user is None:
        return
    settings = get_settings()
    user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= settings.login_max_attempts:
        user.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)


def reset_login_failures(user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None


def ensure_login_allowed(user: User) -> None:
    if user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > utcnow():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "account_locked",
                "message": "Too many failed login attempts. Please try again later.",
            },
        )


def create_password_setup_token(
    db: Session,
    user: User,
    *,
    issued_by_user_id: int | None = None,
    is_reset: bool = False,
    expires_in_hours: int = 24,
) -> tuple[str, PasswordSetupToken]:
    raw_token = generate_opaque_token(32)
    record = PasswordSetupToken(
        user_id=user.id,
        token_hash=hash_opaque_token(raw_token),
        expires_at=utcnow() + timedelta(hours=expires_in_hours),
        issued_by_user_id=issued_by_user_id,
        is_reset=is_reset,
    )
    db.add(record)
    db.flush()
    return raw_token, record


def consume_password_setup_token(db: Session, raw_token: str, password: str) -> User:
    validate_password_policy(password)
    record = db.scalar(
        select(PasswordSetupToken).where(PasswordSetupToken.token_hash == hash_opaque_token(raw_token))
    )
    if (
        record is None
        or record.used_at is not None
        or record.expires_at.replace(tzinfo=timezone.utc) <= utcnow()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_setup_token", "message": "Activation or reset token is invalid or expired"},
        )

    user = db.get(User, record.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "user_not_found", "message": "User linked to token was not found"},
        )

    user.hashed_password = hash_password(password)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    user.temporary_password = None
    user.session_nonce = int(user.session_nonce or 0) + 1
    user.is_active = True
    user.failed_login_attempts = 0
    user.locked_until = None
    record.used_at = utcnow()
    db.flush()
    return user


def make_unusable_password_hash() -> str:
    return hash_password(generate_placeholder_password())
