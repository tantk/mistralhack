"""Pipeline API — run the full VoiceGraph pipeline and retrieve results."""

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import get_db
from app.pipeline import run_pipeline
from app.pipeline.models import PipelineResult

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class PipelineRunRequest(BaseModel):
    attendees: list[str] = Field(default_factory=list)


@router.post("/{meeting_id}/run")
async def run_meeting_pipeline(meeting_id: int, body: PipelineRunRequest | None = None):
    """Run the full VoiceGraph pipeline on a completed meeting."""
    # Verify meeting exists
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT status FROM meetings WHERE id = ?", (meeting_id,)
        )
        if not rows:
            raise HTTPException(404, "Meeting not found")
        status = rows[0]["status"]
    finally:
        await db.close()

    if status == "recording":
        raise HTTPException(400, "Meeting must be completed before running pipeline")

    attendees = body.attendees if body else []
    result = await run_pipeline(meeting_id, attendees=attendees)

    if result.status == "error":
        raise HTTPException(500, result.error)

    return {
        "ok": True,
        "meeting_id": meeting_id,
        "speakers_resolved": len(result.resolutions),
        "ambiguities": len(result.ambiguities),
        "has_minutes": result.minutes is not None,
    }


@router.get("/{meeting_id}/minutes")
async def get_meeting_minutes(meeting_id: int):
    """Retrieve stored pipeline results / meeting minutes."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT result_json FROM meeting_minutes WHERE meeting_id = ?",
            (meeting_id,),
        )
    finally:
        await db.close()

    if not rows:
        raise HTTPException(404, "No pipeline results found for this meeting")

    return json.loads(rows[0]["result_json"])
