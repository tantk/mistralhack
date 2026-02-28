import logging

import httpx

from app.config import DIARIZATION_URL
from app.database import get_db

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


async def run_diarization(audio_path: str) -> list[dict]:
    """Send the full meeting audio to the diarization service.

    Returns a list of speaker segments:
        [{"speaker": "SPEAKER_0", "start": 0.5, "end": 4.2}, ...]
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        with open(audio_path, "rb") as f:
            resp = await client.post(
                f"{DIARIZATION_URL}/diarize",
                files={"file": ("meeting.wav", f, "audio/wav")},
            )
        resp.raise_for_status()

    segments = resp.json()["segments"]
    log.info("Diarization returned %d speaker segments", len(segments))
    return segments


async def merge_diarization(meeting_id: int, speaker_segments: list[dict]):
    """Assign speaker labels to transcript segments by timestamp overlap."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, start_time, end_time FROM transcript_segments "
            "WHERE meeting_id = ? ORDER BY start_time",
            (meeting_id,),
        )

        for row in rows:
            seg_start = row["start_time"]
            seg_end = row["end_time"]
            if seg_start is None or seg_end is None:
                continue

            best_speaker = None
            best_overlap = 0.0

            for sp in speaker_segments:
                overlap_start = max(seg_start, sp["start"])
                overlap_end = min(seg_end, sp["end"])
                overlap = max(0.0, overlap_end - overlap_start)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = sp["speaker"]

            if best_speaker:
                await db.execute(
                    "UPDATE transcript_segments SET speaker = ? WHERE id = ?",
                    (best_speaker, row["id"]),
                )

        await db.execute(
            "UPDATE meetings SET status = 'diarized' WHERE id = ?",
            (meeting_id,),
        )
        await db.commit()
    finally:
        await db.close()
