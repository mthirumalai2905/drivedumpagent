"""Run Alembic migrations using the configured database URL."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.database.session import normalize_database_url


def run_migrations(database_url: str) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url", normalize_database_url(database_url).replace("%", "%%")
    )
    command.upgrade(config, "head")
