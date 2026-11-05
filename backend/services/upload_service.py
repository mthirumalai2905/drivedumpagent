"""Upload validated bytes to the configured Drive folder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.core.errors import IntegrationError
from backend.integrations.google_drive import DriveClient
from backend.services.file_classifier import FOLDER_NAMES


@dataclass(frozen=True)
class UploadResult:
    file_id: str
    duplicate: bool
    folder_name: str


_ALLOWED_FOLDERS = frozenset(FOLDER_NAMES.values())


def dedupe_key(message_id: str, attachment_id: str) -> str:
    return hashlib.sha256(f"{message_id}:{attachment_id}".encode("utf-8")).hexdigest()


class UploadService:
    def __init__(self, drive: DriveClient, folder_id: str) -> None:
        self._drive = drive
        self._folder_id = folder_id
        self._children: dict[str, str] = {}
        self._seen_key: dict[str, str] = {}
        self._seen_hash: dict[str, str] = {}
        self._seen_name: dict[tuple[str, str], str] = {}

    def _remember(
        self,
        key: str,
        digest: str,
        file_id: str,
        parent_id: str | None = None,
        filename: str | None = None,
    ) -> None:
        self._seen_key[key] = file_id
        self._seen_hash[digest] = file_id
        if parent_id and filename:
            self._seen_name[(parent_id, filename)] = file_id

    async def upload_bytes(
        self,
        *,
        message_id: str,
        attachment_id: str,
        filename: str,
        mime_type: str,
        data: bytes,
        folder_name: str,
    ) -> UploadResult:
        if not self._folder_id:
            raise IntegrationError(
                "GOOGLE_DRIVE_FOLDER_ID is not configured",
                retryable=False,
            )
        destination = folder_name if folder_name in _ALLOWED_FOLDERS else "Other"
        digest = hashlib.sha256(data).hexdigest()
        key = dedupe_key(message_id, attachment_id)
        cached = self._seen_key.get(key) or self._seen_hash.get(digest)
        if cached:
            return UploadResult(file_id=cached, duplicate=True, folder_name=destination)
        existing = await self._drive.find_by_dedupe_key(key)
        if existing:
            self._remember(key, digest, existing)
            return UploadResult(file_id=existing, duplicate=True, folder_name=destination)
        existing = await self._drive.find_by_content_hash(digest)
        if existing:
            self._remember(key, digest, existing)
            return UploadResult(file_id=existing, duplicate=True, folder_name=destination)
        parent_id = await self._child_folder(destination)
        named = self._seen_name.get((parent_id, filename))
        if named:
            return UploadResult(file_id=named, duplicate=True, folder_name=destination)
        existing = await self._drive.find_by_name(parent_id, filename)
        if existing:
            self._remember(key, digest, existing, parent_id, filename)
            return UploadResult(file_id=existing, duplicate=True, folder_name=destination)
        file_id = await self._drive.upload(
            name=filename,
            mime_type=mime_type,
            data=data,
            folder_id=parent_id,
            dedupe_key=key,
            content_sha256=digest,
        )
        if not file_id:
            raise IntegrationError("Google Drive did not confirm the upload", retryable=True)
        self._remember(key, digest, file_id, parent_id, filename)
        return UploadResult(file_id=file_id, duplicate=False, folder_name=destination)

    async def _child_folder(self, name: str) -> str:
        cached = self._children.get(name)
        if cached:
            return cached
        folder_id = await self._drive.ensure_child_folder(self._folder_id, name)
        self._children[name] = folder_id
        return folder_id
