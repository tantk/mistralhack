import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.services.diarization import merge_diarization, run_diarization

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/meetings", tags=["meetings"])


class MeetingCreate(BaseModel):
    title: str


@router.post("")
async def create_meeting(body: MeetingCreate):
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO meetings (title) VALUES (?)", (body.title,)
        )
        await db.commit()
        meeting_id = cursor.lastrowid
    finally:
        await db.close()
    return {"id": meeting_id, "title": body.title, "status": "recording"}


@router.get("")
async def list_meetings():
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, title, created_at, status FROM meetings ORDER BY created_at DESC"
        )
    finally:
        await db.close()
    return [dict(r) for r in rows]


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: int):
    db = await get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
        )
        if not row:
            raise HTTPException(404, "Meeting not found")
        meeting = dict(row[0])

        segments = await db.execute_fetchall(
            "SELECT id, start_time, end_time, text, speaker, created_at "
            "FROM transcript_segments WHERE meeting_id = ? ORDER BY start_time",
            (meeting_id,),
        )
    finally:
        await db.close()
    meeting["segments"] = [dict(s) for s in segments]
    return meeting


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: int):
    db = await get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT audio_path FROM meetings WHERE id = ?", (meeting_id,)
        )
        if not row:
            raise HTTPException(404, "Meeting not found")

        audio_path = row[0]["audio_path"]
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)

        await db.execute(
            "DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,)
        )
        await db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@router.post("/{meeting_id}/end")
async def end_meeting(meeting_id: int):
    db = await get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT status FROM meetings WHERE id = ?", (meeting_id,)
        )
        if not row:
            raise HTTPException(404, "Meeting not found")
        await db.execute(
            "UPDATE meetings SET status = 'completed' WHERE id = ?", (meeting_id,)
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}


@router.post("/{meeting_id}/diarize")
async def diarize_meeting(meeting_id: int):
    db = await get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT audio_path, status FROM meetings WHERE id = ?", (meeting_id,)
        )
        if not row:
            raise HTTPException(404, "Meeting not found")
        meeting = dict(row[0])
    finally:
        await db.close()

    if meeting["status"] not in ("completed", "diarized"):
        raise HTTPException(400, "Meeting must be completed before diarization")
    if not meeting["audio_path"] or not os.path.exists(meeting["audio_path"]):
        raise HTTPException(400, "No audio file found for this meeting")

    speaker_segments = await run_diarization(meeting["audio_path"])
    await merge_diarization(meeting_id, speaker_segments)
    return {"ok": True, "speaker_segments": len(speaker_segments)}
