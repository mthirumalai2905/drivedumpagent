"""Upload validated bytes to the configured Drive folder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.core.errors import IntegrationError
from app.integrations.google_drive import DriveClient
from app.services.file_classifier import FOLDER_NAMES


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
        key = dedupe_key(message_id, attachment_id)
        existing = await self._drive.find_by_dedupe_key(key)
        if existing:
            return UploadResult(file_id=existing, duplicate=True, folder_name=destination)
        parent_id = await self._child_folder(destination)
        file_id = await self._drive.upload(
            name=filename,
            mime_type=mime_type,
            data=data,
            folder_id=parent_id,
            dedupe_key=key,
        )
        if not file_id:
            raise IntegrationError("Google Drive did not confirm the upload", retryable=True)
        return UploadResult(file_id=file_id, duplicate=False, folder_name=destination)

    async def _child_folder(self, name: str) -> str:
        cached = self._children.get(name)
        if cached:
            return cached
        folder_id = await self._drive.ensure_child_folder(self._folder_id, name)
        self._children[name] = folder_id
        return folder_id
