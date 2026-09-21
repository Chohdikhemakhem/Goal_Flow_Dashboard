from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MicroCred Performance API"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"
    database_url: str = "sqlite:///./microcred.db"
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "metrics-gp-mcr"
    jwt_audience: str = "metrics-gp-mcr-users"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    access_cookie_name: str = "microcred_access"
    refresh_cookie_name: str = "microcred_refresh"
    cookie_secure: bool = False
    cookie_samesite: str = "strict"
    login_max_attempts: int = 6
    login_lockout_minutes: int = 15
    password_expiry_days: int = 40
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"
    bonus_module_active: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.is_production:
            if len(self.jwt_secret_key or "") < 32:
                raise ValueError("JWT_SECRET_KEY must be at least 32 characters in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be enabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
