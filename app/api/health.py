"""Health endpoints. The public probe does not call Google or DeepSeek."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import require_user
from app.core.time import utcnow
from app.schemas import HealthResponse
from app.services.status import build_integration_report

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse | JSONResponse:
    settings = request.app.state.settings
    session = request.app.state.session_factory()
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "app": settings.app_name,
                "environment": settings.app_env,
                "time": utcnow().isoformat(),
            },
        )
    finally:
        session.close()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.app_env,
        time=utcnow(),
    )


@router.get("/health/integrations")
async def integrations(request: Request, _: str = Depends(require_user)):
    return await build_integration_report(request.app.state)
