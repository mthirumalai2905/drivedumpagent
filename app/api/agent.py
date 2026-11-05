"""Manual processing trigger."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import require_user
from app.core.errors import AlreadyRunningError, AppError
from app.schemas import RunRequest, RunResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/run", response_model=RunResponse)
async def run_cycle(
    request: Request,
    payload: RunRequest | None = None,
    _: str = Depends(require_user),
) -> RunResponse:
    host = request.client.host if request.client else "unknown"
    if not request.app.state.run_limiter.allow(host):
        raise HTTPException(status_code=429, detail="Too many requests")
    body = payload or RunRequest()
    try:
        result = await request.app.state.runner.run_once(
            reprocess_failed=body.reprocess_failed
        )
    except AlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AppError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RunResponse(
        discovered=result.discovered,
        matched=result.matched,
        uploaded=result.uploaded,
        failed=result.failed,
        skipped=result.skipped,
        locked=result.locked,
        detail=result.detail,
    )
