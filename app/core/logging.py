"""Structured JSON logging. Secret-bearing fields are redacted."""

from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.redaction import redact
from app.core.time import utcnow

_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "taskName",
}

_configured = False


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(
                redact(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "message": redact(record.getMessage()),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            output_key = key[4:] if key.startswith("ctx_") else key
            if key in _RESERVED or key.startswith("_") or key == "event":
                continue
            if not key.startswith("ctx_") and output_key in _RESERVED:
                continue
            if isinstance(value, str):
                payload[output_key] = redact(value)
            elif isinstance(value, (int, float, bool)) or value is None:
                payload[output_key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def configure_logging(settings: Any) -> None:
    global _configured
    logger = logging.getLogger("backoffice")
    logger.setLevel(settings.log_level)
    logger.propagate = False
    if _configured and logger.handlers:
        return

    formatter = JsonFormatter()
    redactor = RedactionFilter()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(redactor)
    logger.addHandler(stream)

    if settings.log_to_file:
        path = Path(settings.log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(
            path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        rotating.setFormatter(formatter)
        rotating.addFilter(redactor)
        logger.addHandler(rotating)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _configured = True


def log_event(
    level: int,
    event: str,
    message: str,
    **fields: Any,
) -> None:
    logger = logging.getLogger("backoffice")
    safe_fields: dict[str, Any] = {}
    for key, value in fields.items():
        stored = redact(value) if isinstance(value, str) else value
        # LogRecord already owns names such as "filename" and "name".
        safe_fields[f"ctx_{key}" if key in _RESERVED else key] = stored
    logger.log(level, redact(message), extra={"event": event, **safe_fields})
