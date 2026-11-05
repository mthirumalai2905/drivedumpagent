"""OAuth callback for minting a refresh token with this application's redirect URI."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from backend.core.config import GOOGLE_SCOPES
from backend.core.errors import IntegrationError
from backend.core.security import make_oauth_state, oauth_state_valid, session_user
from backend.integrations.google_auth import exchange_authorization_code

router = APIRouter(prefix="/oauth/google", tags=["oauth"])

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<link rel="stylesheet" href="/static/app.css"></head>
<body class="login-body"><main class="login-card"><h1>{title}</h1>{body}</main></body></html>"""
    return HTMLResponse(html, status_code=status_code)


@router.get("/start")
def start_oauth(request: Request):
    settings = request.app.state.settings
    if not session_user(request, settings.app_secret_key):
        raise HTTPException(status_code=401, detail="Authentication required")
    if not settings.google_client_id or not settings.google_oauth_redirect_uri:
        return _page(
            "Redirect URI required",
            "<p>Set GOOGLE_CLIENT_ID and GOOGLE_OAUTH_REDIRECT_URI. "
            "Register that exact URI on the Google OAuth client. "
            "Do not use the OAuth Playground callback.</p>"
            "<p>Local example: http://127.0.0.1:8000/oauth/google/callback</p>",
            status_code=400,
        )
    state = make_oauth_state(settings.app_secret_key)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    from fastapi.responses import RedirectResponse

    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}", status_code=302)


@router.get("/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    settings = request.app.state.settings
    if not session_user(request, settings.app_secret_key):
        return _page(
            "Sign in required",
            "<p>Sign in to Back Office and start the Google connection again.</p>",
            status_code=401,
        )
    if error:
        return _page(
            "Google authorization was not completed",
            "<p>No refresh token was created.</p>",
            status_code=400,
        )
    if not oauth_state_valid(state, settings.app_secret_key):
        return _page(
            "Authorization state was rejected",
            "<p>Start the connection again from the dashboard.</p>",
            status_code=400,
        )
    if not code or not settings.google_oauth_redirect_uri:
        return _page("Authorization code missing", "<p>Start the connection again.</p>", status_code=400)
    try:
        refresh = await exchange_authorization_code(
            request.app.state.http,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            code=code,
            redirect_uri=settings.google_oauth_redirect_uri,
        )
    except IntegrationError as exc:
        return _page("Google token exchange failed", f"<p>{_escape(str(exc))}</p>", status_code=502)
    return _page(
        "Refresh token created",
        "<p>Copy this token into GOOGLE_REFRESH_TOKEN and restart. "
        "It is shown once and is not stored by the dashboard.</p>"
        f"<pre class=\"secret\">{_escape(refresh)}</pre>"
        "<p>If this token, or an older one, was pasted into a chat or ticket, revoke it in Google Account security settings.</p>",
    )


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
