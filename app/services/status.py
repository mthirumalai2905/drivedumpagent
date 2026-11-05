"""Live integration checks. Results describe state, never secrets."""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import IntegrationError
from app.schemas import IntegrationReport, IntegrationsResponse


async def build_integration_report(app_state) -> IntegrationsResponse:
    cached = getattr(app_state, "health_cache", None)
    now = time.monotonic()
    if cached and now - cached[0] < 20:
        return cached[1]
    report = IntegrationsResponse(
        application="ok",
        database=_database(app_state),
        gmail=await _gmail(app_state),
        google_drive=await _drive(app_state),
        deepseek=await _deepseek(app_state),
        last_poll_at=app_state.runner.last_poll_at,
        last_success_at=app_state.runner.last_success_at,
        last_error=app_state.runner.last_error,
        poll_running=app_state.runner.running,
    )
    if report.database.state != "operational":
        report.application = "degraded"
    app_state.health_cache = (now, report)
    return report


def _database(app_state) -> IntegrationReport:
    session: Session = app_state.session_factory()
    try:
        session.execute(text("SELECT 1"))
        return IntegrationReport(state="operational", detail="Database accepted a query")
    except Exception:
        return IntegrationReport(state="error", detail="Database query failed")
    finally:
        session.close()


async def _gmail(app_state) -> IntegrationReport:
    settings = app_state.settings
    if not settings.google_oauth_configured or app_state.gmail is None:
        return IntegrationReport(state="not_configured", detail="Gmail credentials are not set")
    try:
        email = await app_state.gmail.get_profile_email()
    except IntegrationError as exc:
        return IntegrationReport(state="error", detail=str(exc)[:300])
    expected = settings.google_gmail_user.lower()
    if expected and email.lower() != expected:
        return IntegrationReport(
            state="connected",
            detail="Authenticated, but the account does not match GOOGLE_GMAIL_USER",
        )
    return IntegrationReport(state="operational", detail="Gmail mailbox is reachable")


async def _drive(app_state) -> IntegrationReport:
    settings = app_state.settings
    if not settings.google_oauth_configured or app_state.drive is None:
        return IntegrationReport(state="not_configured", detail="Google Drive credentials are not set")
    if not settings.google_drive_folder_id:
        return IntegrationReport(
            state="configured",
            detail="Create a destination folder in the dashboard and set GOOGLE_DRIVE_FOLDER_ID",
        )
    try:
        folder = await app_state.drive.get_folder(settings.google_drive_folder_id)
    except IntegrationError as exc:
        message = str(exc)
        if exc.status_code in {401, 400}:
            return IntegrationReport(state="error", detail=message[:300])
        return IntegrationReport(state="connected", detail=message[:300])
    name = str(folder.get("name") or "folder")
    return IntegrationReport(state="operational", detail=f"Destination folder is reachable ({name})")


async def _deepseek(app_state) -> IntegrationReport:
    settings = app_state.settings
    if not settings.deepseek_api_key and not settings.deepseek_model:
        return IntegrationReport(state="not_configured", detail="DeepSeek is optional and not configured")
    if not settings.deepseek_configured or app_state.deepseek is None:
        return IntegrationReport(
            state="configured",
            detail="Set both DEEPSEEK_API_KEY and DEEPSEEK_MODEL to enable DeepSeek",
        )
    try:
        models = await app_state.deepseek.list_models()
    except IntegrationError as exc:
        return IntegrationReport(state="error", detail=str(exc)[:300])
    if settings.deepseek_model not in models:
        return IntegrationReport(
            state="connected",
            detail="DeepSeek responded, but DEEPSEEK_MODEL is not in the model list",
        )
    app_state.deepseek.model_verified = True
    return IntegrationReport(state="operational", detail="Configured DeepSeek model is available")
