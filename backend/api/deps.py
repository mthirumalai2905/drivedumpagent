"""Shared API dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def require_user(request: Request) -> str:
    settings = request.app.state.settings
    from backend.core.security import session_user

    user = session_user(request, settings.app_secret_key)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    host = request.client.host if request.client else "unknown"
    if not request.app.state.api_limiter.allow(host):
        raise HTTPException(status_code=429, detail="Too many requests")
    return user


def pagination(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 200)), max(0, offset)
