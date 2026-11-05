"""Parse Gmail API message resources into plain data."""

from __future__ import annotations

import base64
import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header

_BODY_LIMIT = 512_000
_TAG = re.compile(r"(?is)<(script|style).*?>.*?</\1>")
_TAGS = re.compile(r"(?s)<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass
class ParsedAttachment:
    filename: str
    mime_type: str
    size: int
    attachment_id: str
    data: bytes | None = None


@dataclass
class ParsedEmail:
    gmail_message_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime
    attachments: list[ParsedAttachment] = field(default_factory=list)


def decode_b64url(data: str) -> bytes:
    if not data:
        return b""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def decode_mime_header(value: str) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for text, encoding in decode_header(value):
        if isinstance(text, bytes):
            parts.append(text.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


def strip_html(value: str) -> str:
    text = _TAG.sub(" ", value)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    return _SPACE.sub(" ", text).strip()


def _header_map(part: dict) -> dict[str, str]:
    headers = {}
    for item in part.get("headers") or []:
        name = str(item.get("name", "")).lower()
        if name:
            headers[name] = str(item.get("value", ""))
    return headers


def _walk(
    part: dict,
    plain: list[str],
    rich: list[str],
    attachments: list[ParsedAttachment],
    index: list[int],
) -> None:
    mime = str(part.get("mimeType") or "application/octet-stream")
    filename = decode_mime_header(str(part.get("filename") or ""))
    body = part.get("body") or {}
    disposition = _header_map(part).get("content-disposition", "")
    is_attachment = bool(filename) or "attachment" in disposition.lower()

    if is_attachment and not mime.startswith("multipart/"):
        raw_id = str(body.get("attachmentId") or "")
        data = decode_b64url(body.get("data")) if body.get("data") and not raw_id else None
        size = int(body.get("size") or (len(data) if data else 0))
        index[0] += 1
        if raw_id:
            attachment_id = raw_id
        elif data:
            attachment_id = "inline-" + hashlib.sha256(data).hexdigest()[:32]
        else:
            name_hash = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]
            attachment_id = f"part-{index[0]}-{size}-{name_hash}"
        attachments.append(
            ParsedAttachment(
                filename=filename or "attachment",
                mime_type=mime,
                size=size,
                attachment_id=attachment_id,
                data=data,
            )
        )
    elif mime == "text/plain" and body.get("data"):
        plain.append(decode_b64url(body["data"]).decode("utf-8", errors="replace"))
    elif mime == "text/html" and body.get("data"):
        rich.append(decode_b64url(body["data"]).decode("utf-8", errors="replace"))

    for child in part.get("parts") or []:
        _walk(child, plain, rich, attachments, index)


def parse_gmail_message(message: dict) -> ParsedEmail:
    payload = message.get("payload") or {}
    headers = _header_map(payload)
    plain: list[str] = []
    rich: list[str] = []
    attachments: list[ParsedAttachment] = []
    _walk(payload, plain, rich, attachments, [0])
    if plain:
        body = "\n".join(plain)
    else:
        body = "\n".join(strip_html(part) for part in rich)
    if len(body) > _BODY_LIMIT:
        body = body[:_BODY_LIMIT]
    internal = str(message.get("internalDate") or "0")
    try:
        received = datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc)
    except (ValueError, OSError):
        received = datetime.now(timezone.utc)
    return ParsedEmail(
        gmail_message_id=str(message.get("id") or ""),
        sender=decode_mime_header(headers.get("from", ""))[:512],
        subject=decode_mime_header(headers.get("subject", ""))[:998],
        body=body,
        received_at=received,
        attachments=attachments,
    )
