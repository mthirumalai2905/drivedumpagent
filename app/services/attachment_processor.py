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
    if mime not in allowed_mimes:
        return ValidationResult(False, safe_name, "mime type is not allowed")
    return ValidationResult(True, safe_name, None)
