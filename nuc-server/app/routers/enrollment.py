"""Speaker enrollment API — manage voiceprint identities."""

import logging

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import DIARIZATION_URL
from app.pipeline.voiceprint_store import get_voiceprint_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/speakers", tags=["speakers"])

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


async def _extract_embedding(wav_bytes: bytes) -> list[float]:
    """Send audio to titan's /embed endpoint and return the 192-d embedding."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{DIARIZATION_URL}/embed",
            files={"audio": ("enroll.wav", wav_bytes, "audio/wav")},
        )
        resp.raise_for_status()
    return resp.json()["embedding"]


@router.post("/enroll")
async def enroll_speaker(
    name: str = Form(...),
    audio: UploadFile = File(...),
):
    """Enroll a speaker: upload a voice sample, extract embedding, store in FAISS."""
    import io
    import numpy as np
    from pydub import AudioSegment

    raw = await audio.read()

    # Convert to 16kHz mono WAV if needed
    try:
        seg = AudioSegment.from_file(io.BytesIO(raw))
        seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        buf = io.BytesIO()
        seg.export(buf, format="wav")
        wav_bytes = buf.getvalue()
    except Exception:
        wav_bytes = raw

    try:
        embedding_list = await _extract_embedding(wav_bytes)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Embedding service error: {e.response.status_code}")
    except httpx.ConnectError:
        raise HTTPException(502, "Cannot reach embedding service")

    embedding = np.array(embedding_list, dtype=np.float32)
    store = get_voiceprint_store()
    speaker_id = store.enroll(name, embedding)

    return {"id": speaker_id, "name": name}


@router.get("")
async def list_speakers():
    """List all enrolled speakers."""
    store = get_voiceprint_store()
    return store.list_speakers()


@router.delete("/{speaker_id}")
async def delete_speaker(speaker_id: str):
    """Remove an enrolled speaker."""
    store = get_voiceprint_store()
    if not store.remove(speaker_id):
        raise HTTPException(404, "Speaker not found")
    return {"ok": True}
