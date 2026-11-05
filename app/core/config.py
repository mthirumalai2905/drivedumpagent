"""Environment configuration. Values are validated, never logged."""

from __future__ import annotations

import os
from functools import lru_cache
from ipaddress import ip_address

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigurationError

DEFAULT_MIME_TYPES = ",".join(
    [
        "application/pdf",
        "text/plain",
        "text/csv",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/zip",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ]
)

GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Back Office"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_secret_key: str = ""

    dashboard_username: str = "admin"
    dashboard_password: str = ""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_oauth_redirect_uri: str = ""
    google_drive_folder_id: str = ""
    google_gmail_user: str = "backoffice@synx.tools"
    google_drive_supports_shared: bool = False

    trigger_keyword: str = "back office,backoffice"
    poll_interval_seconds: int = 60
    poll_enabled: bool = True
    email_lookback_minutes: int = 10
    max_attachment_bytes: int = 26_214_400
    max_attachments_per_email: int = 20
    max_messages_per_cycle: int = 100
    allowed_mime_types: str = DEFAULT_MIME_TYPES

    database_url: str = "sqlite:///./backoffice.db"

    log_level: str = "INFO"
    log_file: str = "logs/backoffice.log"
    log_to_file: bool | None = None

    lock_ttl_seconds: int = Field(default=0)

    @field_validator("app_env")
    @classmethod
    def _env_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "production", "test"}:
            raise ValueError("APP_ENV must be development, production, or test")
        return normalized

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return normalized

    @field_validator("deepseek_base_url", "google_oauth_redirect_uri")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator(
        "app_secret_key",
        "dashboard_username",
        "dashboard_password",
        "deepseek_api_key",
        "deepseek_model",
        "google_client_id",
        "google_client_secret",
        "google_refresh_token",
        "google_drive_folder_id",
        "google_gmail_user",
        "trigger_keyword",
        "database_url",
    )
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _apply_runtime_rules(self) -> "Settings":
        port = os.environ.get("PORT")
        if port:
            try:
                self.app_port = int(port)
            except ValueError as exc:
                raise ValueError("PORT must be an integer") from exc

        if self.log_to_file is None:
            self.log_to_file = self.app_env == "development"

        if self.lock_ttl_seconds <= 0:
            self.lock_ttl_seconds = max(self.poll_interval_seconds * 10, 180)

        self._validate_bounds()
        self._validate_secrets()
        if self.app_env == "production":
            self._validate_production()
        elif self.app_env == "test":
            self._validate_test()
        else:
            self._validate_development()
        return self

    def _validate_bounds(self) -> None:
        if not 15 <= self.poll_interval_seconds <= 3600:
            raise ValueError("POLL_INTERVAL_SECONDS must be between 15 and 3600")
        if not 1 <= self.email_lookback_minutes <= 1440:
            raise ValueError("EMAIL_LOOKBACK_MINUTES must be between 1 and 1440")
        if self.max_attachment_bytes < 1 or self.max_attachment_bytes > 100_000_000:
            raise ValueError("MAX_ATTACHMENT_BYTES must be between 1 and 100000000")
        if not 1 <= self.max_attachments_per_email <= 50:
            raise ValueError("MAX_ATTACHMENTS_PER_EMAIL must be between 1 and 50")
        if not 1 <= self.max_messages_per_cycle <= 500:
            raise ValueError("MAX_MESSAGES_PER_CYCLE must be between 1 and 500")
        if not self.keywords:
            raise ValueError("TRIGGER_KEYWORD must contain at least one keyword")

    def _validate_secrets(self) -> None:
        if len(self.app_secret_key) < 32:
            raise ValueError("APP_SECRET_KEY must be a random string of at least 32 characters")
        minimum_password = 1 if self.app_env == "development" else 12
        if len(self.dashboard_password) < minimum_password:
            raise ValueError("DASHBOARD_PASSWORD must be at least 12 characters in production")
        if not self.dashboard_username:
            raise ValueError("DASHBOARD_USERNAME is required")

    def _validate_development(self) -> None:
        if self.deepseek_base_url and not self.deepseek_base_url.startswith(
            ("https://", "http://127.0.0.1", "http://localhost")
        ):
            raise ValueError("DEEPSEEK_BASE_URL must use https, except for localhost")

    def _validate_test(self) -> None:
        self.poll_enabled = False

    def _validate_production(self) -> None:
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL in production")
        missing = []
        if not self.google_client_id:
            missing.append("GOOGLE_CLIENT_ID")
        if not self.google_client_secret:
            missing.append("GOOGLE_CLIENT_SECRET")
        if not self.google_refresh_token:
            missing.append("GOOGLE_REFRESH_TOKEN")
        if not self.google_drive_folder_id:
            missing.append("GOOGLE_DRIVE_FOLDER_ID")
        if not self.google_gmail_user:
            missing.append("GOOGLE_GMAIL_USER")
        if not self.google_oauth_redirect_uri:
            missing.append("GOOGLE_OAUTH_REDIRECT_URI")
        if missing:
            raise ValueError("Production is missing " + ", ".join(missing))
        if not self.google_oauth_redirect_uri.startswith("https://"):
            raise ValueError("GOOGLE_OAUTH_REDIRECT_URI must use https in production")
        if not self.deepseek_base_url.startswith("https://"):
            raise ValueError("DEEPSEEK_BASE_URL must use https in production")
        if self.app_host not in {"0.0.0.0", "127.0.0.1"}:
            try:
                ip_address(self.app_host)
            except ValueError as exc:
                raise ValueError("APP_HOST must be an IP address") from exc

    @property
    def keywords(self) -> list[str]:
        return [part.strip() for part in self.trigger_keyword.split(",") if part.strip()]

    @property
    def mime_allowlist(self) -> set[str]:
        return {
            part.strip().lower()
            for part in self.allowed_mime_types.split(",")
            if part.strip()
        }

    @property
    def google_oauth_configured(self) -> bool:
        return bool(
            self.google_client_id and self.google_client_secret and self.google_refresh_token
        )

    @property
    def deepseek_configured(self) -> bool:
        return bool(self.deepseek_api_key and self.deepseek_model)

    @property
    def database_backend(self) -> str:
        if self.database_url.startswith("sqlite"):
            return "sqlite"
        if self.database_url.startswith(("postgres://", "postgresql")):
            return "postgresql"
        return "other"

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "production"


def _format_validation_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return "Invalid configuration."
    lines = ["Invalid configuration:"]
    for error in errors():
        loc = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg", "invalid value"))
        lines.append(f"- {loc}: {message}" if loc else f"- {message}")
    return "\n".join(lines)


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            raise ConfigurationError(_format_validation_error(exc)) from None
        raise
