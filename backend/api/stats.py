"""Processing statistics."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.deps import get_db, require_user
from backend.database import repository
from backend.schemas import StatsOut
from fastapi import Request

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=StatsOut)
def stats(
    request: Request,
    _: str = Depends(require_user),
    session: Session = Depends(get_db),
) -> StatsOut:
    payload = repository.processing_stats(session)
    runner = request.app.state.runner
    return StatsOut(
        **payload,
        last_poll_at=runner.last_poll_at,
        last_success_at=runner.last_success_at,
    )
