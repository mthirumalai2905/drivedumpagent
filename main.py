"""Local and Render entrypoint."""

import os

import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    port = int(os.environ.get("PORT", settings.app_port))
    host = "0.0.0.0" if settings.app_env == "production" else settings.app_host
    uvicorn.run("app.http:app", host=host, port=port, factory=False)


if __name__ == "__main__":
    main()
