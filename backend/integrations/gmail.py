"""Gmail API client using OAuth access tokens."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from backend.core.errors import IntegrationError
from backend.integrations.google_auth import GoogleAuth, google_error
from backend.services.email_parser import decode_b64url
from backend.services.retry import retry_async

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailClient:
    def __init__(self, auth: GoogleAuth, http: httpx.AsyncClient) -> None:
        self._auth = auth
        self._http = http

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
    ) -> dict:
        async def once(force: bool) -> httpx.Response:
            token = await self._auth.get_access_token(force=force)
            try:
                return await self._http.request(
                    method,
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise IntegrationError("Gmail API was unreachable", retryable=True) from exc

        response = await once(False)
        if response.status_code == 401:
            self._auth.invalidate()
            response = await once(True)
        if response.status_code >= 400:
            raise google_error(response)
        if not response.content:
            return {}
        return response.json()

    async def get_profile_email(self) -> str:
        payload = await retry_async(
            lambda: self._request("GET", f"{GMAIL_BASE}/profile")
        )
        email = str(payload.get("emailAddress") or "")
        if not email:
            raise IntegrationError("Gmail profile did not include an email address", retryable=False)
        return email

    async def list_message_ids(self, *, lookback_minutes: int, limit: int) -> list[str]:
        query = f"newer_than:{int(lookback_minutes)}m -in:chats"
        found: list[str] = []
        page_token: str | None = None
        while len(found) < limit:
            params: dict[str, str | int] = {
                "q": query,
                "maxResults": min(50, limit - len(found)),
            }
            if page_token:
                params["pageToken"] = page_token

            payload = await retry_async(
                lambda params=params: self._request("GET", f"{GMAIL_BASE}/messages", params=params)
            )
            for item in payload.get("messages") or []:
                message_id = item.get("id")
                if message_id:
                    found.append(str(message_id))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return found[:limit]

    async def get_message(self, message_id: str) -> dict:
        safe_id = quote(message_id, safe="")
        return await retry_async(
            lambda: self._request("GET", f"{GMAIL_BASE}/messages/{safe_id}", params={"format": "full"})
        )

    async def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        safe_message = quote(message_id, safe="")
        safe_attachment = quote(attachment_id, safe="")
        payload = await retry_async(
            lambda: self._request(
                "GET",
                f"{GMAIL_BASE}/messages/{safe_message}/attachments/{safe_attachment}",
            )
        )
        data = payload.get("data")
        if not data:
            raise IntegrationError("Gmail attachment response did not include data", retryable=True)
        return decode_b64url(str(data))
