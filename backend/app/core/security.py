import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def validate_password_policy(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if password.lower() == password or password.upper() == password:
        raise ValueError("Password must include mixed case letters")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must include at least one digit")
    if not any(not char.isalnum() for char in password):
        raise ValueError("Password must include at least one special character")


def _build_token_payload(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires = now + expires_delta
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "exp": expires,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "jti": uuid4().hex,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if extra:
        payload.update(extra)
    return payload


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    payload = _build_token_payload(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        extra=extra,
    )
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm), payload


def create_refresh_token(subject: str, extra: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    payload = _build_token_payload(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
        extra=extra,
    )
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm), payload


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
        if payload.get("type") != expected_type:
            raise ValueError("Invalid authentication token")
        return payload
    except JWTError as exc:
        raise ValueError("Invalid authentication token") from exc


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_opaque_token(length: int = 48) -> str:
    return secrets.token_urlsafe(length)


def generate_placeholder_password() -> str:
    return secrets.token_urlsafe(32)


def generate_temporary_password(length: int = 16) -> str:
    """Generate a policy-compliant temporary password for first login."""
    minimum_length = max(length, 12)
    uppercase = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    lowercase = "abcdefghijkmnopqrstuvwxyz"
    digits = "23456789"
    specials = "!@#$%?_-"
    alphabet = uppercase + lowercase + digits + specials
    chars = [
        secrets.choice(uppercase),
        secrets.choice(lowercase),
        secrets.choice(digits),
        secrets.choice(specials),
    ]
    chars.extend(secrets.choice(alphabet) for _ in range(minimum_length - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
