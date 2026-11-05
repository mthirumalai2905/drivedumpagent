"""Choose a Drive folder from the file itself, not only its name."""

from __future__ import annotations

import io
import zipfile

from backend.services.attachment_processor import normalize_mime, sanitize_filename

FOLDER_NAMES = {
    "pdf": "PDFs",
    "presentation": "Presentations",
    "image": "Images",
    "sheet": "Sheets",
    "document": "Documents",
    "video": "Videos",
    "other": "Other",
}

_MIME_KIND = {
    "application/pdf": "pdf",
    "application/vnd.ms-powerpoint": "presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "presentation",
    "application/vnd.ms-powerpoint.presentation.macroEnabled.12": "presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow": "presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.template": "presentation",
    "application/vnd.oasis.opendocument.presentation": "presentation",
    "application/vnd.apple.keynote": "presentation",
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/webm": "video",
    "video/x-msvideo": "video",
    "video/mpeg": "video",
    "video/3gpp": "video",
    "video/x-matroska": "video",
    "video/ogg": "video",
    "image/png": "image",
    "image/jpeg": "image",
    "image/gif": "image",
    "image/webp": "image",
    "text/csv": "sheet",
    "application/vnd.ms-excel": "sheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "sheet",
    "text/plain": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
}

_EXTENSION_KIND = {
    "pdf": "pdf",
    "ppt": "presentation",
    "pptx": "presentation",
    "pps": "presentation",
    "ppsx": "presentation",
    "pptm": "presentation",
    "potx": "presentation",
    "odp": "presentation",
    "key": "presentation",
    "mp4": "video",
    "m4v": "video",
    "mov": "video",
    "webm": "video",
    "avi": "video",
    "mkv": "video",
    "mpeg": "video",
    "mpg": "video",
    "ogv": "video",
    "3gp": "video",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "webp": "image",
    "csv": "sheet",
    "xls": "sheet",
    "xlsx": "sheet",
    "txt": "document",
    "doc": "document",
    "docx": "document",
}


def folder_for(kind: str) -> str:
    return FOLDER_NAMES.get(kind, FOLDER_NAMES["other"])


def classify_file(filename: str, mime_type: str, data: bytes) -> str:
    """Return the filing kind. Magic bytes win over a misleading filename."""
    sniffed = _sniff(data)
    if sniffed:
        return sniffed
    mime_kind = _MIME_KIND.get(normalize_mime(mime_type))
    if mime_kind:
        return mime_kind
    extension = _extension(filename)
    return _EXTENSION_KIND.get(extension, "other")


def _extension(filename: str) -> str:
    safe = sanitize_filename(filename)
    if "." not in safe:
        return ""
    return safe.rsplit(".", 1)[-1].lower()


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff") or data.startswith(b"GIF8"):
        return "image"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image"
    if data.startswith(b"RIFF") and data[8:12] == b"AVI ":
        return "video"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] not in {b"heic", b"heix", b"heif", b"mif1", b"avif"}:
        return "video"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video"
    if data.startswith(b"PK"):
        return _sniff_office_zip(data)
    return None


def _sniff_office_zip(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [info.filename for info in archive.infolist()[:40]]
    except zipfile.BadZipFile:
        return None
    if any(name.startswith("ppt/") for name in names):
        return "presentation"
    if any(name.startswith("xl/") for name in names):
        return "sheet"
    if any(name.startswith("word/") for name in names):
        return "document"
    return None
