"""In-memory stand-ins for Google and DeepSeek."""

from __future__ import annotations

import base64

from backend.core.errors import IntegrationError
from backend.integrations.deepseek import AttachmentInsight, EmailInsight

FOLDER_MIME = "application/vnd.google-apps.folder"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def gmail_message(
    message_id: str,
    subject: str,
    body: str,
    attachments: list[tuple[str, str, str, int]] | None = None,
    sender: str = "billing@example.com",
    html: str | None = None,
) -> dict:
    parts: list[dict] = []
    if html and not body:
        parts.append({"mimeType": "text/html", "body": {"data": _b64(html), "size": len(html)}})
    else:
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(body), "size": len(body)}})
    for filename, mime, attachment_id, size in attachments or []:
        parts.append(
            {
                "mimeType": mime,
                "filename": filename,
                "body": {"attachmentId": attachment_id, "size": size},
            }
        )
    return {
        "id": message_id,
        "internalDate": "1762340000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
            ],
            "parts": parts,
        },
    }


class FakeGmail:
    def __init__(
        self,
        messages: dict[str, dict],
        attachments: dict[tuple[str, str], bytes],
        profile: str = "backoffice@synx.tools",
    ) -> None:
        self.messages = messages
        self.attachments = attachments
        self.profile = profile
        self.downloads: list[tuple[str, str]] = []

    async def get_profile_email(self) -> str:
        return self.profile

    async def list_message_ids(self, *, lookback_minutes: int, limit: int) -> list[str]:
        del lookback_minutes
        return list(self.messages)[:limit]

    async def get_message(self, message_id: str) -> dict:
        return self.messages[message_id]

    async def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        self.downloads.append((message_id, attachment_id))
        return self.attachments[(message_id, attachment_id)]


class FakeDrive:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.files: dict[str, str] = {}
        self.uploads: list[dict] = []
        self.folders: dict[str, str] = {}

    async def get_folder(self, folder_id: str) -> dict:
        return {
            "id": folder_id,
            "name": "Back Office",
            "mimeType": FOLDER_MIME,
            "trashed": False,
        }

    async def create_folder(self, name: str) -> dict:
        return {"id": "folder-created", "name": name, "mimeType": FOLDER_MIME}

    async def ensure_child_folder(self, parent_id: str, name: str) -> str:
        key = f"{parent_id}/{name}"
        folder_id = self.folders.get(key)
        if folder_id:
            return folder_id
        folder_id = f"folder-{name}"
        self.folders[key] = folder_id
        return folder_id

    async def find_by_dedupe_key(self, key: str) -> str | None:
        return self.files.get(key)

    async def upload(
        self,
        *,
        name: str,
        mime_type: str,
        data: bytes,
        folder_id: str,
        dedupe_key: str,
    ) -> str:
        if self.fail:
            raise IntegrationError("Google Drive was unavailable", status_code=503, retryable=True)
        file_id = f"drive-{len(self.uploads) + 1}"
        self.files[dedupe_key] = file_id
        self.uploads.append(
            {
                "name": name,
                "mime_type": mime_type,
                "size": len(data),
                "folder_id": folder_id,
            }
        )
        return file_id


class FakeDeepSeek:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.document_calls = 0
        self.model_verified = not fail

    async def inspect_email(
        self,
        *,
        subject: str,
        sender: str,
        body_excerpt: str,
        attachments: list[tuple[str, str, int]],
    ) -> EmailInsight:
        del subject, sender, body_excerpt
        self.calls += 1
        if self.fail:
            raise IntegrationError("DeepSeek was unreachable", status_code=503, retryable=True)
        return EmailInsight(
            summary="Invoice for November",
            attachments=[
                AttachmentInsight(
                    filename=name,
                    description="November invoice",
                    category="invoice",
                    attachment_type="pdf",
                )
                for name, _mime, _size in attachments
            ],
        )

    async def describe_document(
        self,
        *,
        filename: str,
        mime_type: str,
        excerpt: str,
    ) -> AttachmentInsight:
        del excerpt
        self.document_calls += 1
        if self.fail:
            raise IntegrationError("DeepSeek was unreachable", status_code=503, retryable=True)
        return AttachmentInsight(
            filename=filename,
            description="Read from the file contents",
            category="statement",
            attachment_type=mime_type[:80],
        )
