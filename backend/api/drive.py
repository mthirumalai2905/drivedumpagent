"""Create a Drive folder this application is allowed to use."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import require_user
from backend.core.errors import IntegrationError
from backend.schemas import CreateFolderRequest, CreateFolderResponse

router = APIRouter(prefix="/api/drive", tags=["drive"])
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}$")


@router.post("/folder", response_model=CreateFolderResponse)
async def create_folder(
    request: Request,
    payload: CreateFolderRequest,
    _: str = Depends(require_user),
) -> CreateFolderResponse:
    if request.app.state.drive is None:
        raise HTTPException(status_code=409, detail="Google Drive credentials are not configured")
    if not _NAME.match(payload.name.strip()):
        raise HTTPException(status_code=422, detail="Folder name contains unsupported characters")
    try:
        created = await request.app.state.drive.create_folder(payload.name.strip())
    except IntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    folder_id = str(created.get("id") or "")
    if not folder_id:
        raise HTTPException(status_code=502, detail="Google Drive did not return a folder id")
    request.app.state.health_cache = None
    return CreateFolderResponse(
        id=folder_id,
        name=str(created.get("name") or payload.name),
        detail="Set GOOGLE_DRIVE_FOLDER_ID to this id and restart the application.",
    )
