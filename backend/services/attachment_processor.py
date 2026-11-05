"""Validate untrusted attachment metadata before anything is uploaded."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    filename: str
    reason: str | None = None


def sanitize_filename(filename: str) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    name = unicodedata.normalize("NFKC", name)
    name = _UNSAFE.sub("_", name).strip(" .")
    if name in {"", ".", ".."}:
        return "attachment"
    if len(name) > 180:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = f"{stem[:160]}.{ext}"
        else:
            name = name[:180]
    return name or "attachment"


def normalize_mime(mime_type: str) -> str:
    return (mime_type or "").split(";", 1)[0].strip().lower()


_GENERIC_MIMES = {
    "",
    "application/octet-stream",
    "application/binary",
    "binary/octet-stream",
    "application/x-download",
}
_MIME_TOKEN = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
KNOWN_FILING_EXTENSIONS = {
    "pdf",
    "ppt",
    "pptx",
    "pps",
    "ppsx",
    "pptm",
    "potx",
    "odp",
    "key",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "csv",
    "xls",
    "xlsx",
    "txt",
    "doc",
    "docx",
    "mp4",
    "m4v",
    "mov",
    "webm",
    "avi",
    "mkv",
    "mpeg",
    "mpg",
    "ogv",
    "3gp",
}
_EXTENSION_MIME = {
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pps": "application/vnd.ms-powerpoint",
    "ppsx": "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
    "pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
    "potx": "application/vnd.openxmlformats-officedocument.presentationml.template",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "key": "application/vnd.apple.keynote",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "avi": "video/x-msvideo",
    "mkv": "video/x-matroska",
    "mpeg": "video/mpeg",
    "mpg": "video/mpeg",
    "ogv": "video/ogg",
    "3gp": "video/3gpp",
}


def _extension(filename: str) -> str:
    safe = sanitize_filename(filename)
    if "." not in safe:
        return ""
    return safe.rsplit(".", 1)[-1].lower()


def content_type_for_upload(filename: str, mime_type: str) -> str:
    mime = normalize_mime(mime_type)
    safe = mime if _MIME_TOKEN.fullmatch(mime) else ""
    if safe and safe not in _GENERIC_MIMES:
        return safe
    return _EXTENSION_MIME.get(_extension(filename)) or safe or "application/octet-stream"


def validate_attachment(
    *,
    filename: str,
    mime_type: str,
    size: int | None,
    allowed_mimes: set[str],
    max_bytes: int,
) -> ValidationResult:
    safe_name = sanitize_filename(filename)
    if safe_name in {".", ".."} or "/" in safe_name or "\\" in safe_name:
        return ValidationResult(False, "attachment", "filename is not allowed")
    mime = normalize_mime(mime_type)
    if size is not None and size > max_bytes:
        return ValidationResult(False, safe_name, "attachment exceeds size limit")
    extension_known = _extension(safe_name) in KNOWN_FILING_EXTENSIONS
    if mime not in allowed_mimes and not (mime in _GENERIC_MIMES and extension_known):
        return ValidationResult(False, safe_name, "mime type is not allowed")
    return ValidationResult(True, safe_name, None)
