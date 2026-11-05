"""Short retries for temporary API failures."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from backend.core.errors import IntegrationError

T = Callable[[], Awaitable]


async def retry_async(operation: T, *, attempts: int = 3):
    last_error: IntegrationError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except IntegrationError as exc:
            last_error = exc
            if not exc.retryable or attempt == attempts:
                raise
            await asyncio.sleep(min(2 ** (attempt - 1), 4))
    if last_error:
        raise last_error
    raise IntegrationError("operation failed", retryable=False)
