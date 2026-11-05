"""Dashboard pages. Monitoring only; credentials are not editable here."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.security import (
    clear_session_cookie,
    secrets_equal,
    session_user,
    set_session_cookie,
    sign_session,
)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


def _logged_in(request: Request) -> bool:
    settings = request.app.state.settings
    return session_user(request, settings.app_secret_key) is not None


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _logged_in(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": request.query_params.get("error") == "1",
            "rate_limited": False,
        },
    )


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    settings = request.app.state.settings
    host = request.client.host if request.client else "unknown"
    if not request.app.state.login_limiter.allow(host):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": True, "rate_limited": True},
            status_code=429,
        )
    username_ok = secrets_equal(username, settings.dashboard_username)
    password_ok = secrets_equal(password, settings.dashboard_password)
    if not (username_ok and password_ok):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": True, "rate_limited": False},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(
        response,
        sign_session(settings.dashboard_username, settings.app_secret_key),
        secure=settings.cookie_secure,
    )
    return response


@router.post("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "app_name": request.app.state.settings.app_name},
    )
