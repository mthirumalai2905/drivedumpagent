"""Attachment records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.api.deps import get_db, pagination, require_user
from backend.database import repository
from backend.schemas import AttachmentOut

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.get("")
def list_attachments(
    limit: int = Query(50),
    offset: int = Query(0),
    _: str = Depends(require_user),
    session: Session = Depends(get_db),
) -> dict:
    bounded_limit, bounded_offset = pagination(limit, offset)
    rows, total = repository.list_attachments(
        session, limit=bounded_limit, offset=bounded_offset
    )
    return {
        "items": [AttachmentOut.model_validate(row).model_dump(mode="json") for row in rows],
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
    }
