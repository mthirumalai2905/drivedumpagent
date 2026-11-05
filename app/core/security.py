"""Dashboard session cookies, password checks, and a small rate limiter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict

from fastapi import Request, Response

COOKIE_NAME = "bo_session"
SESSION_TTL_SECONDS = 12 * 60 * 60


def secrets_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(left.encode("utf-8")).digest(),
        hashlib.sha256(right.encode("utf-8")).digest(),
    )


def sign_session(username: str, secret: str, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else now
    expires = issued + SESSION_TTL_SECONDS
    payload = f"v1|{username}|{expires}"
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}|{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def read_session(token: str, secret: str, now: int | None = None) -> str | None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        version, username, expires_raw, signature = decoded.split("|", 3)
    except (ValueError, UnicodeError):
        return None
    if version != "v1" or not username:
        return None
    payload = f"{version}|{username}|{expires_raw}"
    expected = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        expires = int(expires_raw)
    except ValueError:
        return None
    current = int(time.time()) if now is None else now
    if expires < current:
        return None
    return username


def session_user(request: Request, secret: str) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return read_session(token, secret)


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def make_oauth_state(secret: str, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else now
    nonce = secrets.token_urlsafe(16)
    payload = f"{issued}.{nonce}"
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def oauth_state_valid(state: str, secret: str, *, max_age: int = 600) -> bool:
    parts = state.split(".")
    if len(parts) != 3:
        return False
    issued_raw, nonce, signature = parts
    if not nonce:
        return False
    payload = f"{issued_raw}.{nonce}"
    expected = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    try:
        issued = int(issued_raw)
    except ValueError:
        return False
    return 0 <= int(time.time()) - issued <= max_age


class RateLimiter:
    """In-memory sliding window. Sufficient for a single Back Office process."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        recent = [hit for hit in self._hits[key] if now - hit < self.window_seconds]
        if len(recent) >= self.limit:
            self._hits[key] = recent
            return False
        recent.append(now)
        self._hits[key] = recent
        return True

    def reset(self) -> None:
        self._hits.clear()
