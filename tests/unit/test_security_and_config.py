import json
import logging

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import JsonFormatter, RedactionFilter, log_event
from app.core.redaction import redact
from app.core.security import oauth_state_valid, read_session, secrets_equal, sign_session, make_oauth_state
from app.database.session import normalize_database_url


def test_redacts_tokens_and_database_passwords():
    text = redact(
        "bearer ya29.accessTOKENVALUE refresh_token=super-secret-refresh "
        "postgresql://app:super-secret-db@localhost/backoffice"
    )
    assert "ya29.accessTOKENVALUE" not in text
    assert "super-secret-refresh" not in text
    assert "super-secret-db" not in text
    assert "postgresql://app:" in text


def test_json_log_shape_omits_secrets():
    logger = logging.getLogger("backoffice")
    logger.setLevel(logging.INFO)
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = Capture()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    try:
        log_event(
            logging.INFO,
            "attachment_uploaded",
            "uploaded ya29.accessTOKENVALUE",
            status="success",
            email_id="gmail-message-id",
            filename="invoice.pdf",
        )
    finally:
        logger.removeHandler(handler)
    payload = json.loads(records[0])
    assert payload["event"] == "attachment_uploaded"
    assert payload["email_id"] == "gmail-message-id"
    assert payload["filename"] == "invoice.pdf"
    assert payload["status"] == "success"
    assert "ya29.accessTOKENVALUE" not in records[0]


def test_session_cookie_round_trip():
    secret = "test-secret-key-32-characters-minimum"
    token = sign_session("admin", secret, now=1_700_000_000)
    assert read_session(token, secret, now=1_700_000_100) == "admin"
    assert read_session(token, "wrong-secret-key-32-characters-minimum", now=1_700_000_100) is None
    assert read_session(token, secret, now=1_700_000_000 + 60 * 60 * 13) is None


def test_password_compare_does_not_use_plain_equality_result_for_mismatch():
    assert secrets_equal("test-password-12", "test-password-12")
    assert not secrets_equal("test-password-12", "test-password-13")


def test_oauth_state_rejects_tampering():
    secret = "test-secret-key-32-characters-minimum"
    state = make_oauth_state(secret)
    assert oauth_state_valid(state, secret)
    assert not oauth_state_valid(state + "x", secret)
    assert not oauth_state_valid("1.nonce.deadbeef", secret)


def test_postgres_url_is_normalized_for_psycopg():
    assert normalize_database_url("postgres://user:pw@host/db").startswith("postgresql+psycopg://")
    assert normalize_database_url("sqlite:///./backoffice.db") == "sqlite:///./backoffice.db"


def test_production_rejects_sqlite_and_missing_google(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "p" * 32)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "q" * 12)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./backoffice.db")
    with pytest.raises(ValidationError):
        Settings()


def test_short_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_SECRET_KEY", "too-short")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "q" * 12)
    with pytest.raises(ValidationError):
        Settings()
