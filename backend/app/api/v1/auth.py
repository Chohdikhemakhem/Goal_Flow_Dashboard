from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import User
from app.schemas.auth import (
    ActivationTokenRead,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    PasswordSetupRequest,
    UserRead,
)
from app.services.auth_security import (
    attach_auth_cookies,
    clear_auth_cookies,
    consume_password_setup_token,
    enforce_password_expiration,
    ensure_login_allowed,
    issue_session_tokens,
    register_failed_login,
    reset_login_failures,
    revoke_all_refresh_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.core.security import hash_password, validate_password_policy, verify_password
from app.services.login_audit import record_successful_login

router = APIRouter(prefix="/auth", tags=["auth"])


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent"), request.client.host if request.client else None


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == payload.email))
    if user:
        ensure_login_allowed(user)
    if not user or not verify_password(payload.password, user.hashed_password):
        register_failed_login(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "bad_credentials", "message": "Invalid email or password"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "inactive_user", "message": "User account is deactivated"},
        )

    enforce_password_expiration(user)
    reset_login_failures(user)
    user_agent, ip_address = _request_meta(request)
    access_token, refresh_token, expires_in_seconds = issue_session_tokens(
        db,
        user,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    record_successful_login(db, user, user_agent=user_agent, ip_address=ip_address)
    attach_auth_cookies(response, access_token, refresh_token)
    db.commit()
    db.refresh(user)
    return LoginResponse(
        user=UserRead.model_validate(user),
        expires_in_seconds=expires_in_seconds,
    )


@router.post("/refresh", response_model=LoginResponse)
def refresh_session(response: Response, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    raw_refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_refresh_token", "message": "Refresh token is missing"},
        )
    user_agent, ip_address = _request_meta(request)
    user, access_token, refresh_token, expires_in_seconds = rotate_refresh_token(
        db,
        raw_refresh_token,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    attach_auth_cookies(response, access_token, refresh_token)
    db.commit()
    return LoginResponse(
        user=UserRead.model_validate(user),
        expires_in_seconds=expires_in_seconds,
    )


@router.post("/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    raw_refresh_token = request.cookies.get(settings.refresh_cookie_name)
    user = revoke_refresh_token(db, raw_refresh_token)
    if user:
        user.session_nonce = int(user.session_nonce or 0) + 1
    clear_auth_cookies(response)
    db.commit()
    return {"message": "Logged out"}


@router.post("/set-password", response_model=UserRead)
def set_password(
    payload: PasswordSetupRequest,
    db: Session = Depends(get_db),
):
    try:
        user = consume_password_setup_token(db, payload.token, payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "weak_password", "message": str(exc)},
        ) from exc
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/change-password", response_model=UserRead)
def change_password(
    payload: PasswordChangeRequest,
    response: Response,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_current_password", "message": "Le mot de passe actuel est incorrect."},
        )
    if verify_password(payload.new_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "password_reuse", "message": "Le nouveau mot de passe doit etre different."},
        )
    try:
        validate_password_policy(payload.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "weak_password", "message": str(exc)},
        ) from exc

    revoke_all_refresh_tokens(db, user.id)
    user.hashed_password = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.must_change_password = False
    user.temporary_password = None
    user.session_nonce = int(user.session_nonce or 0) + 1
    user.failed_login_attempts = 0
    user.locked_until = None
    user_agent, ip_address = _request_meta(request)
    access_token, refresh_token, _expires_in_seconds = issue_session_tokens(
        db,
        user,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    attach_auth_cookies(response, access_token, refresh_token)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user
