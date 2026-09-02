"""User data export/import API endpoints."""

import json
import logging

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.services.user_data import export_user_data, import_user_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user-data", tags=["user-data"])


@router.get("/export")
async def export_data(session: AsyncSession = Depends(get_session)):
    """Export user data (favorites, person names) as a JSON download."""
    data = await export_user_data(session)
    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": "attachment; filename=recasa-user-data.json",
        },
    )


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Import user data from a previously exported JSON file."""
    try:
        contents = await file.read()
        data = json.loads(contents)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return {"status": "error", "message": f"Invalid JSON file: {e}"}

    if not isinstance(data, dict) or "version" not in data:
        return {"status": "error", "message": "Not a valid recasa export file"}

    try:
        summary = await import_user_data(data, session)
    except ValueError as e:
        # Raised for an unsupported format version. A rejected file is a normal
        # outcome here, not a server fault, so it gets a message rather than a 500.
        return {"status": "error", "message": str(e)}
    return {"status": "ok", **summary}
