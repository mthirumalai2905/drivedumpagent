"""Cross-process lock so only one poller works at a time."""

from __future__ import annotations

import time

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import WorkerLock


def acquire_worker_lock(
    session: Session, *, name: str, owner: str, ttl_seconds: int
) -> bool:
    now = int(time.time())
    expires = now + ttl_seconds
    updated = session.execute(
        update(WorkerLock)
        .where(WorkerLock.name == name)
        .where((WorkerLock.expires_at <= now) | (WorkerLock.owner == owner))
        .values(owner=owner, acquired_at=now, expires_at=expires)
    )
    if updated.rowcount == 1:
        session.commit()
        return True
    session.rollback()
    try:
        session.add(
            WorkerLock(name=name, owner=owner, acquired_at=now, expires_at=expires)
        )
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False


def release_worker_lock(session: Session, *, name: str, owner: str) -> None:
    now = int(time.time())
    session.execute(
        update(WorkerLock)
        .where(WorkerLock.name == name, WorkerLock.owner == owner)
        .values(expires_at=now)
    )
    session.commit()
