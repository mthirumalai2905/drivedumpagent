"""Deterministic keyword matching. This does not call an AI model."""

from __future__ import annotations

import re


def message_matches(subject: str, body: str, keywords: list[str]) -> str | None:
    """Return the first configured keyword found in the subject or body."""
    haystack = f"{subject or ''}\n{body or ''}"
    for keyword in keywords:
        phrase = keyword.strip()
        if not phrase:
            continue
        pattern = re.compile(
            rf"(?<!\w){re.escape(phrase)}(?!\w)",
            re.IGNORECASE,
        )
        if pattern.search(haystack):
            return phrase
    return None
