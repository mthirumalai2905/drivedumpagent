"""Redact credentials before they reach a log line or an API error."""

from __future__ import annotations

import re

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)((?:postgres(?:ql)?(?:\+\w+)?|mysql|mongodb(?:\+\w+)?)://[^:\s]+:)[^@/\s]+"
    ),
    re.compile(r"ya29\.[0-9A-Za-z_\-]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)(refresh_token[\"']?\s*[:=]\s*[\"']?)[^\"'\s&,}]+"),
    re.compile(r"(?i)(client_secret[\"']?\s*[:=]\s*[\"']?)[^\"'\s&,}]+"),
    re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\"'\s&,}]+"),
    re.compile(r"sk-[A-Za-z0-9]+"),
)


def redact(value: str) -> str:
    text = value
    for pattern in _PATTERNS:
        text = pattern.sub(
            lambda match: (match.group(1) if match.lastindex else "") + "[redacted]",
            text,
        )
    return text
