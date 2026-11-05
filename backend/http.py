"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from backend import __version__
from backend.api import agent, attachments, config, drive, emails, health, logs, oauth, stats
from backend.core.config import Settings, get_settings
from backend.core.errors import ConfigurationError
from backend.core.logging import configure_logging, log_event
from backend.core.security import RateLimiter
from backend.dashboard.routes import router as dashboard_router
from backend.database.migrate import run_migrations
from backend.database.models import Base
from backend.database.session import make_engine, make_session_factory
from backend.integrations.deepseek import DeepSeekClient
from backend.integrations.gmail import GmailClient
from backend.integrations.google_auth import GoogleAuth
from backend.integrations.google_drive import DriveClient
from backend.services.email_processor import EmailProcessor
from backend.services.upload_service import UploadService
from backend.workers.gmail_poller import AgentRunner, poll_forever


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response


def _limit(settings: Settings, amount: int, window: int) -> RateLimiter:
    scale = 1000 if settings.app_env == "test" else 1
    return RateLimiter(amount * scale, window)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    configure_logging(settings)
    log_event(logging.INFO, "app_startup", "Back Office starting", status="success")
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory
    if settings.app_env == "test":
        Base.metadata.create_all(engine)
    else:
        try:
            run_migrations(settings.database_url)
        except Exception as exc:
            log_event(
                logging.ERROR,
                "migration_failed",
                "Database migration failed",
                status="failed",
                error_type=type(exc).__name__,
            )
            raise ConfigurationError(
                "Database migration failed. Check DATABASE_URL and database permissions."
            ) from None

    probe = session_factory()
    try:
        probe.execute(text("SELECT 1"))
    except Exception as exc:
        log_event(
            logging.ERROR,
            "database_error",
            "Database connection failed",
            status="failed",
            error_type=type(exc).__name__,
        )
        raise ConfigurationError("Database connection failed.") from None
    finally:
        probe.close()

    http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    app.state.http = http
    overrides = getattr(app.state, "overrides", {}) or {}
    gmail = overrides.get("gmail")
    drive = overrides.get("drive")
    deepseek = overrides.get("deepseek")

    if settings.google_oauth_configured and (gmail is None or drive is None):
        auth = GoogleAuth(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            refresh_token=settings.google_refresh_token,
            http=http,
        )
        if gmail is None:
            gmail = GmailClient(auth, http)
        if drive is None:
            drive = DriveClient(
                auth,
                http,
                supports_shared_drives=settings.google_drive_supports_shared,
            )
    if deepseek is None and settings.deepseek_configured:
        deepseek = DeepSeekClient(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            http=http,
        )
        if await deepseek.verify_model():
            log_event(
                logging.INFO,
                "deepseek_ready",
                "Configured DeepSeek model is available",
                status="success",
            )
        else:
            log_event(
                logging.WARNING,
                "deepseek_failed",
                "DeepSeek model check failed. Attachment upload will continue without AI.",
                status="failed",
            )
    elif settings.deepseek_api_key or settings.deepseek_model:
        log_event(
            logging.WARNING,
            "deepseek_failed",
            "DeepSeek is disabled until both DEEPSEEK_API_KEY and DEEPSEEK_MODEL are set",
            status="skipped",
        )

    uploads = UploadService(drive, settings.google_drive_folder_id) if drive is not None else None
    processor = overrides.get("processor") or EmailProcessor(
        settings=settings,
        session_factory=session_factory,
        gmail=gmail,
        uploads=uploads,
        deepseek=deepseek,
        lock_owner=overrides.get("lock_owner")
        or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}",
    )
    runner = overrides.get("runner") or AgentRunner(processor)
    app.state.gmail = gmail
    app.state.drive = drive
    app.state.deepseek = deepseek
    app.state.runner = runner
    app.state.health_cache = None

    stop = asyncio.Event()
    task = None
    if settings.poll_enabled and settings.app_env != "test":
        task = asyncio.create_task(
            poll_forever(stop, runner, settings.poll_interval_seconds)
        )
    try:
        yield
    finally:
        log_event(logging.INFO, "app_shutdown", "Back Office stopping", status="success")
        stop.set()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await http.aclose()
        engine.dispose()


def create_app(settings: Settings | None = None, overrides: dict | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if settings.app_env == "development" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env == "development" else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.overrides = overrides or {}
    app.state.api_limiter = _limit(settings, 120, 60)
    app.state.login_limiter = _limit(settings, 10, 300)
    app.state.run_limiter = _limit(settings, 6, 60)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: StarletteRequest, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    @app.exception_handler(Exception)
    async def unhandled(_request: StarletteRequest, exc: Exception) -> JSONResponse:
        log_event(
            logging.ERROR,
            "api_error",
            "Unhandled request error",
            status="failed",
            error_type=type(exc).__name__,
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    app.include_router(health.router)
    app.include_router(emails.router)
    app.include_router(attachments.router)
    app.include_router(logs.router)
    app.include_router(stats.router)
    app.include_router(agent.router)
    app.include_router(config.router)
    app.include_router(drive.router)
    app.include_router(oauth.router)
    app.include_router(dashboard_router)
    static_dir = Path(__file__).resolve().parent / "dashboard" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


app = create_app()
