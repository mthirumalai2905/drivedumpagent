"""Read a short text excerpt from an attachment. The file is never executed."""

from __future__ import annotations

import io
import re
import zipfile

_LIMIT = 4000
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def read_excerpt(data: bytes, kind: str) -> str:
    try:
        if kind == "pdf":
            return _pdf_text(data)
        if kind == "presentation":
            return _zip_xml_text(data, "ppt/")
        if kind == "sheet":
            if data.startswith(b"PK"):
                return _zip_xml_text(data, "xl/")
            return _plain_text(data)
        if kind == "document":
            if data.startswith(b"PK"):
                return _zip_xml_text(data, "word/")
            return _plain_text(data)
    except Exception:
        return ""
    return ""


def _plain_text(data: bytes) -> str:
    return _SPACE.sub(" ", data[:20_000].decode("utf-8", errors="ignore")).strip()[:_LIMIT]


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    total = 0
    for page in reader.pages[:5]:
        text = page.extract_text() or ""
        parts.append(text)
        total += len(text)
        if total >= _LIMIT:
            break
    return _SPACE.sub(" ", " ".join(parts)).strip()[:_LIMIT]


def _zip_xml_text(data: bytes, prefix: str) -> str:
    chunks: list[str] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist()[:30]:
            if info.is_dir() or info.file_size > 500_000:
                continue
            if not info.filename.startswith(prefix) or not info.filename.endswith(".xml"):
                continue
            raw = archive.read(info)[:200_000]
            text = _TAGS.sub(" ", raw.decode("utf-8", errors="ignore"))
            chunks.append(text)
            total += len(text)
            if total >= _LIMIT:
                break
    return _SPACE.sub(" ", " ".join(chunks)).strip()[:_LIMIT]
