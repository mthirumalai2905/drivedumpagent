"""OAuth refresh for Gmail and Drive. Tokens are never logged."""

from __future__ import annotations

import asyncio
import time

import httpx

from app.core.errors import GoogleAuthError, IntegrationError
from app.core.redaction import redact

TOKEN_URL = "https://oauth2.googleapis.com/token"


def _error_text(response: httpx.Response) -> tuple[str, str]:
    try:
        payload = response.json()
    except Exception:
        return "", ""
    error = payload.get("error", "")
    if isinstance(error, dict):
        code = str(error.get("status") or "")
        message = str(error.get("message") or "")[:180]
        return code, redact(message)
    description = str(payload.get("error_description") or "")[:180]
    return str(error), redact(description)


def google_error(response: httpx.Response) -> IntegrationError:
    code, message = _error_text(response)
    if code == "unauthorized_client":
        return GoogleAuthError(
            "Google rejected this client id, client secret, and refresh token as a pair. "
            "A refresh token only works with the OAuth client that issued it. "
            "Mint a new refresh token from this application's Connect Google button "
            "and its own redirect URI. Do not reuse an OAuth Playground token.",
            status_code=response.status_code,
            retryable=False,
        )
    if code == "invalid_grant" or response.status_code == 400 and "invalid_grant" in code:
        return GoogleAuthError(
            "Google refresh token was expired or revoked. "
            "Testing-mode OAuth clients expire refresh tokens after 7 days. "
            "Use a Google Workspace Internal consent screen for a durable token, "
            "mint a new refresh token with this application's redirect URI, "
            "and do not reuse an OAuth Playground token.",
            status_code=response.status_code,
            retryable=False,
        )
    retryable = response.status_code == 429 or response.status_code >= 500
    detail = f"Google API returned HTTP {response.status_code}"
    if code or message:
        detail = f"{detail} ({code} {message}).".replace(" .", ".")
    return IntegrationError(detail, status_code=response.status_code, retryable=retryable)


class GoogleAuth:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        http: httpx.AsyncClient,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._http = http
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        self._access_token = None
        self._expires_at = 0.0

    async def get_access_token(self, *, force: bool = False) -> str:
        async with self._lock:
            if (
                not force
                and self._access_token
                and time.time() < self._expires_at - 60
            ):
                return self._access_token
            try:
                response = await self._http.post(
                    TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": self._refresh_token,
                        "grant_type": "refresh_token",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                raise IntegrationError(
                    "Google token endpoint was unreachable",
                    retryable=True,
                ) from exc
            if response.status_code != 200:
                raise google_error(response)
            try:
                payload = response.json()
                token = payload["access_token"]
                expires_in = int(payload.get("expires_in") or 3600)
            except (KeyError, TypeError, ValueError) as exc:
                raise GoogleAuthError(
                    "Google token response did not include an access token",
                    status_code=response.status_code,
                    retryable=False,
                ) from exc
            self._access_token = token
            self._expires_at = time.time() + expires_in
            return token


async def exchange_authorization_code(
    http: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> str:
    try:
        response = await http.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    except httpx.HTTPError as exc:
        raise IntegrationError("Google token endpoint was unreachable", retryable=True) from exc
    if response.status_code != 200:
        raise google_error(response)
    payload = response.json()
    refresh = payload.get("refresh_token")
    if not refresh:
        raise IntegrationError(
            "Google did not return a refresh token. Start the connection again so consent is requested.",
            status_code=200,
            retryable=False,
        )
    return str(refresh)
