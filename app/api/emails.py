"""Processed email records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_db, pagination, require_user
from app.database import repository
from app.schemas import EmailOut
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("")
def list_emails(
    request: Request,
    limit: int = Query(50),
    offset: int = Query(0),
    _: str = Depends(require_user),
    session: Session = Depends(get_db),
) -> dict:
    del request
    bounded_limit, bounded_offset = pagination(limit, offset)
    rows, total = repository.list_emails(session, limit=bounded_limit, offset=bounded_offset)
    return {
        "items": [EmailOut.model_validate(row).model_dump(mode="json") for row in rows],
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
    }
