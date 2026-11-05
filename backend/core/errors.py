"""Application errors whose messages are safe to show to an operator."""


class AppError(Exception):
    """Expected failure with a message that contains no secrets."""


class ConfigurationError(AppError):
    """Startup configuration is missing or invalid."""


class IntegrationError(AppError):
    """A remote API failed. The message must already be redacted."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class GoogleAuthError(IntegrationError):
    """OAuth refresh failed, expired, or was revoked."""


class AlreadyRunningError(AppError):
    """A processing cycle is already in progress in this process."""
