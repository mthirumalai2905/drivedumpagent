"""Processing activity."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination, require_user
from app.database import repository
from app.schemas import LogOut

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def list_logs(
    limit: int = Query(50),
    offset: int = Query(0),
    status: str = Query("all"),
    _: str = Depends(require_user),
    session: Session = Depends(get_db),
) -> dict:
    bounded_limit, bounded_offset = pagination(limit, offset)
    selected = status if status in {"success", "failed", "pending", "all"} else "all"
    rows, total = repository.list_logs(
        session,
        limit=bounded_limit,
        offset=bounded_offset,
        status=None if selected == "all" else selected,
    )
    items = []
    for entry, email, attachment in rows:
        items.append(
            LogOut(
                id=entry.id,
                created_at=entry.created_at,
                event_type=entry.event_type,
                status=entry.status,
                message=entry.message[:500],
                subject=email.subject if email else None,
                sender=email.sender if email else None,
                filename=attachment.sanitized_filename if attachment else None,
                upload_status=attachment.upload_status if attachment else None,
                error_message=attachment.error_message if attachment else None,
            ).model_dump(mode="json")
        )
    return {
        "items": items,
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
    }
