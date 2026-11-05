"""Configuration status without secret values."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_user
from app.schemas import ConfigFlag, ConfigStatus

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/status", response_model=ConfigStatus)
def config_status(request: Request, _: str = Depends(require_user)) -> ConfigStatus:
    settings = request.app.state.settings
    deepseek = getattr(request.app.state, "deepseek", None)
    verified = None if deepseek is None else deepseek.model_verified
    flags = [
        ConfigFlag(name="APP_SECRET_KEY", configured=bool(settings.app_secret_key)),
        ConfigFlag(name="DASHBOARD_PASSWORD", configured=bool(settings.dashboard_password)),
        ConfigFlag(name="GOOGLE_CLIENT_ID", configured=bool(settings.google_client_id)),
        ConfigFlag(name="GOOGLE_CLIENT_SECRET", configured=bool(settings.google_client_secret)),
        ConfigFlag(name="GOOGLE_REFRESH_TOKEN", configured=bool(settings.google_refresh_token)),
        ConfigFlag(name="GOOGLE_OAUTH_REDIRECT_URI", configured=bool(settings.google_oauth_redirect_uri)),
        ConfigFlag(name="GOOGLE_DRIVE_FOLDER_ID", configured=bool(settings.google_drive_folder_id)),
        ConfigFlag(name="GOOGLE_GMAIL_USER", configured=bool(settings.google_gmail_user)),
        ConfigFlag(name="DEEPSEEK_API_KEY", configured=bool(settings.deepseek_api_key)),
        ConfigFlag(name="DEEPSEEK_MODEL", configured=bool(settings.deepseek_model)),
        ConfigFlag(name="DATABASE_URL", configured=bool(settings.database_url)),
        ConfigFlag(name="TRIGGER_KEYWORD", configured=bool(settings.keywords)),
    ]
    return ConfigStatus(
        app_env=settings.app_env,
        app_name=settings.app_name,
        gmail_user=settings.google_gmail_user,
        trigger_keywords=settings.keywords,
        poll_interval_seconds=settings.poll_interval_seconds,
        poll_enabled=settings.poll_enabled,
        email_lookback_minutes=settings.email_lookback_minutes,
        max_attachment_bytes=settings.max_attachment_bytes,
        database_backend=settings.database_backend,
        deepseek_model=settings.deepseek_model,
        deepseek_model_verified=verified,
        flags=flags,
    )
