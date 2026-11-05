"""Google Drive uploads limited to files this application can access."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from urllib.parse import quote

import httpx

from backend.core.errors import IntegrationError
from backend.integrations.google_auth import GoogleAuth, google_error
from backend.services.retry import retry_async

DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
_FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ]{0,40}$")
_HEX_KEY = re.compile(r"^[0-9a-f]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FOLDER_HINT = (
    "The destination folder is not visible to this application. "
    "drive.file only grants access to files and folders this app created. "
    "Create a folder from the dashboard, copy its id into GOOGLE_DRIVE_FOLDER_ID, and restart."
)


def escape_drive_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def name_in_folder_query(folder_id: str, filename: str) -> str:
    return (
        f"name = '{escape_drive_literal(filename)}' and '{folder_id}' in parents "
        f"and trashed = false and mimeType != '{FOLDER_MIME}'"
    )


def content_hash_query(digest: str) -> str:
    return f"appProperties has {{ key = 'bo_sha256' and value = '{digest}' }} and trashed = false"


class DriveClient:
    def __init__(
        self,
        auth: GoogleAuth,
        http: httpx.AsyncClient,
        *,
        supports_shared_drives: bool = False,
    ) -> None:
        self._auth = auth
        self._http = http
        self._supports_shared = supports_shared_drives

    def _shared_params(self) -> dict[str, str]:
        if not self._supports_shared:
            return {}
        return {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> httpx.Response:
        token = await self._auth.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            return await self._http.request(
                method,
                url,
                params=params,
                json=json_body,
                content=content,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise IntegrationError("Google Drive API was unreachable", retryable=True) from exc

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> dict:
        response = await self._send(
            method,
            url,
            params=params,
            json_body=json_body,
            content=content,
            content_type=content_type,
        )
        if response.status_code == 401:
            self._auth.invalidate()
            response = await self._send(
                method,
                url,
                params=params,
                json_body=json_body,
                content=content,
                content_type=content_type,
            )
        if response.status_code >= 400:
            error = google_error(response)
            if response.status_code in {403, 404} and "/files/" in url:
                raise IntegrationError(
                    f"{error} {FOLDER_HINT}",
                    status_code=response.status_code,
                    retryable=False,
                )
            raise error
        if not response.content:
            return {}
        return response.json()

    async def get_folder(self, folder_id: str) -> dict:
        safe_id = quote(folder_id, safe="")
        params = {"fields": "id,name,mimeType,trashed", **self._shared_params()}
        payload = await retry_async(
            lambda: self._request("GET", f"{DRIVE_API}/files/{safe_id}", params=params)
        )
        if payload.get("mimeType") != FOLDER_MIME or payload.get("trashed"):
            raise IntegrationError(
                "GOOGLE_DRIVE_FOLDER_ID does not point at an active folder. " + FOLDER_HINT,
                retryable=False,
            )
        return payload

    async def create_folder(self, name: str) -> dict:
        body = {"name": name, "mimeType": FOLDER_MIME}
        params = {"fields": "id,name,mimeType", **self._shared_params()}
        return await retry_async(
            lambda: self._request("POST", f"{DRIVE_API}/files", params=params, json_body=body)
        )

    async def ensure_child_folder(self, parent_id: str, name: str) -> str:
        if not _FOLDER_ID.fullmatch(parent_id) or not _FOLDER_NAME.fullmatch(name):
            raise IntegrationError("Drive folder name is invalid", retryable=False)
        query = (
            f"mimeType = '{FOLDER_MIME}' and name = '{name}' "
            f"and '{parent_id}' in parents and trashed = false"
        )
        params = {
            "q": query,
            "spaces": "drive",
            "pageSize": 1,
            "fields": "files(id,name)",
            **self._shared_params(),
        }
        payload = await retry_async(
            lambda: self._request("GET", f"{DRIVE_API}/files", params=params)
        )
        files = payload.get("files") or []
        if files and files[0].get("id"):
            return str(files[0]["id"])
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        created = await retry_async(
            lambda: self._request(
                "POST",
                f"{DRIVE_API}/files",
                params={"fields": "id", **self._shared_params()},
                json_body=body,
            )
        )
        folder_id = created.get("id")
        if not folder_id:
            raise IntegrationError("Google Drive did not create the folder", retryable=True)
        return str(folder_id)

    async def move_file(self, file_id: str, *, add_parent: str, remove_parent: str) -> None:
        if not all(_FOLDER_ID.fullmatch(value) for value in (file_id, add_parent, remove_parent)):
            raise IntegrationError("Drive file id is invalid", retryable=False)
        params = {
            "addParents": add_parent,
            "removeParents": remove_parent,
            "fields": "id,parents",
            **self._shared_params(),
        }
        await retry_async(
            lambda: self._request(
                "PATCH",
                f"{DRIVE_API}/files/{quote(file_id, safe='')}",
                params=params,
            )
        )

    async def _first_file_id(self, query: str) -> str | None:
        params = {
            "q": query,
            "spaces": "drive",
            "pageSize": 1,
            "fields": "files(id)",
            **self._shared_params(),
        }
        payload = await retry_async(
            lambda: self._request("GET", f"{DRIVE_API}/files", params=params)
        )
        files = payload.get("files") or []
        if not files:
            return None
        file_id = files[0].get("id")
        return str(file_id) if file_id else None

    async def find_by_dedupe_key(self, key: str) -> str | None:
        if not key or _HEX_KEY.fullmatch(key) is None:
            return None
        query = f"appProperties has {{ key = 'bo_dedupe' and value = '{key}' }} and trashed = false"
        return await self._first_file_id(query)

    async def find_by_content_hash(self, digest: str) -> str | None:
        if _SHA256.fullmatch(digest) is None:
            return None
        return await self._first_file_id(content_hash_query(digest))

    async def find_by_name(self, folder_id: str, filename: str) -> str | None:
        if _FOLDER_ID.fullmatch(folder_id) is None or not filename:
            return None
        return await self._first_file_id(name_in_folder_query(folder_id, filename))

    async def upload(
        self,
        *,
        name: str,
        mime_type: str,
        data: bytes,
        folder_id: str,
        dedupe_key: str,
        content_sha256: str,
    ) -> str:
        metadata = {
            "name": name,
            "parents": [folder_id],
            "appProperties": {"bo_dedupe": dedupe_key, "bo_sha256": content_sha256},
        }
        boundary = "bo" + secrets.token_hex(12)
        preamble = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        closing = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = preamble + data + closing
        params = {"uploadType": "multipart", "fields": "id", **self._shared_params()}
        last_error: IntegrationError | None = None
        for attempt in range(3):
            if attempt:
                existing = await self.find_by_content_hash(content_sha256)
                if existing is None:
                    existing = await self.find_by_name(folder_id, name)
                if existing:
                    return existing
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
            try:
                payload = await self._request(
                    "POST",
                    UPLOAD_API,
                    params=params,
                    content=body,
                    content_type=f"multipart/related; boundary={boundary}",
                )
            except IntegrationError as exc:
                last_error = exc
                if not exc.retryable or attempt == 2:
                    raise
                continue
            file_id = payload.get("id")
            if not file_id:
                last_error = IntegrationError(
                    "Google Drive upload did not return a file id",
                    retryable=True,
                )
                if attempt == 2:
                    raise last_error
                continue
            return str(file_id)
        if last_error:
            raise last_error
        raise IntegrationError("Google Drive did not confirm the upload", retryable=True)
