from collections.abc import Iterable

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.entities import User
from app.models.enums import UserRole
from app.services.auth_security import enforce_password_expiration


def pagination(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> tuple[int, int]:
    return limit, offset


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    settings = get_settings()
    token: str | None = None
    authorization = request.headers.get("Authorization")
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get(settings.access_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_token", "message": "Authentication token is missing"},
        )
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "Invalid authentication token"},
        ) from exc

    user_id = payload.get("sub")
    user = db.get(User, int(user_id)) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "inactive_user", "message": "User is inactive or missing"},
        )
    if int(payload.get("svn", 0)) != int(user.session_nonce or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "revoked_token", "message": "Authentication token is no longer valid"},
        )
    if enforce_password_expiration(user):
        db.commit()
    password_change_allowed_paths = {
        f"{settings.api_v1_prefix}/auth/me",
        f"{settings.api_v1_prefix}/auth/change-password",
        f"{settings.api_v1_prefix}/auth/logout",
    }
    if user.must_change_password and request.url.path not in password_change_allowed_paths:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "password_change_required",
                "message": "Vous devez modifier votre mot de passe avant de continuer.",
            },
        )
    return user


def require_roles(roles: Iterable[UserRole]):
    allowed = set(roles)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "forbidden", "message": "Insufficient permissions"},
            )
        return user

    return dependency


def require_non_support_user(user: User = Depends(get_current_user)) -> User:
    if user.role == UserRole.SUPPORT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "Insufficient permissions"},
        )
    return user
