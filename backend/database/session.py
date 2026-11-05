"""Database engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def make_engine(url: str) -> Engine:
    normalized = normalize_database_url(url)
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if normalized.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs.pop("pool_pre_ping", None)
        if normalized in {"sqlite://", "sqlite:///:memory:"} or ":memory:" in normalized:
            kwargs["poolclass"] = StaticPool
    return create_engine(normalized, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
