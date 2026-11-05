"""Single-process polling loop with an in-process run lock."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from app.core.errors import AlreadyRunningError, AppError
from app.core.logging import log_event
from app.core.time import utcnow
from app.services.email_processor import CycleResult, EmailProcessor


@dataclass
class AgentRunner:
    processor: EmailProcessor
    last_poll_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    _running: bool = False
    _guard: asyncio.Lock | None = None

    def __post_init__(self) -> None:
        self._guard = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._running

    async def run_once(self, *, reprocess_failed: bool = False) -> CycleResult:
        assert self._guard is not None
        async with self._guard:
            if self._running:
                raise AlreadyRunningError("A processing cycle is already running")
            self._running = True
        try:
            self.last_poll_at = utcnow()
            result = await self.processor.run_cycle(reprocess_failed=reprocess_failed)
            if result.detail == "completed":
                self.last_success_at = utcnow()
                self.last_error = None
            elif result.detail not in {"locked", "google_not_configured", ""}:
                self.last_error = result.detail
            return result
        except AppError as exc:
            self.last_error = str(exc)
            log_event(logging.ERROR, "poll_failed", str(exc), status="failed")
            raise
        except Exception as exc:
            self.last_error = "Processing cycle failed"
            log_event(
                logging.ERROR,
                "poll_failed",
                "Processing cycle failed",
                status="failed",
                error_type=type(exc).__name__,
            )
            raise AppError("Processing cycle failed") from exc
        finally:
            async with self._guard:
                self._running = False


async def poll_forever(stop: asyncio.Event, runner: AgentRunner, interval_seconds: int) -> None:
    while not stop.is_set():
        try:
            await runner.run_once()
        except AlreadyRunningError:
            pass
        except Exception:
            log_event(
                logging.ERROR,
                "poll_failed",
                "Background poll failed and will retry on the next interval",
                status="failed",
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
