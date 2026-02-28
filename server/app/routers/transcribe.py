import io
import json
import logging
import time

from fastapi import APIRouter, File, UploadFile, WebSocket, WebSocketDisconnect
from pydub import AudioSegment

from app.config import AUDIO_STORAGE_PATH
from app.database import get_db
from app.services.inference import transcribe_audio

log = logging.getLogger(__name__)
router = APIRouter()


def webm_to_wav(webm_bytes: bytes) -> bytes:
    """Convert WebM/Opus audio to WAV (16kHz mono) for mistral.rs."""
    audio = AudioSegment.from_file(io.BytesIO(webm_bytes), format="webm")
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    buf = io.BytesIO()
    audio.export(buf, format="wav")
    return buf.getvalue()


@router.post("/api/transcribe")
async def api_transcribe(audio: UploadFile = File(...)):
    """Standalone transcription endpoint — accepts audio, returns text."""
    raw = await audio.read()
    try:
        wav_bytes = webm_to_wav(raw)
    except Exception:
        # Already WAV or other format, try passing through directly
        wav_bytes = raw
    text = await transcribe_audio(wav_bytes)
    return {"text": text}


@router.websocket("/ws/transcribe/{meeting_id}")
async def ws_transcribe(websocket: WebSocket, meeting_id: int):
    await websocket.accept()

    # Verify meeting exists
    db = await get_db()
    try:
        row = await db.execute_fetchall(
            "SELECT id FROM meetings WHERE id = ?", (meeting_id,)
        )
        if not row:
            await websocket.close(code=4004, reason="Meeting not found")
            return
    finally:
        await db.close()

    # Prepare audio file for concatenation
    audio_file_path = AUDIO_STORAGE_PATH / f"meeting_{meeting_id}.wav"
    combined_audio = AudioSegment.empty()
    chunk_index = 0
    meeting_start = time.time()

    try:
        while True:
            data = await websocket.receive_bytes()
            chunk_start = time.time() - meeting_start

            try:
                wav_bytes = webm_to_wav(data)
            except Exception as e:
                log.error("Audio conversion failed: %s", e)
                await websocket.send_json({"error": "Audio conversion failed"})
                continue

            # Append to combined audio for later diarization
            chunk_audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
            chunk_duration = len(chunk_audio) / 1000.0
            combined_audio += chunk_audio
            combined_audio.export(str(audio_file_path), format="wav")

            # Update meeting audio path
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE meetings SET audio_path = ? WHERE id = ?",
                    (str(audio_file_path), meeting_id),
                )
                await db.commit()
            finally:
                await db.close()

            # Send to mistral.rs for transcription
            try:
                text = await transcribe_audio(wav_bytes)
            except Exception as e:
                log.error("Transcription failed: %s", e)
                await websocket.send_json({"error": "Transcription failed"})
                continue

            if not text:
                continue

            chunk_end = chunk_start + chunk_duration

            # Save segment to database
            db = await get_db()
            try:
                cursor = await db.execute(
                    "INSERT INTO transcript_segments (meeting_id, start_time, end_time, text) "
                    "VALUES (?, ?, ?, ?)",
                    (meeting_id, round(chunk_start, 2), round(chunk_end, 2), text),
                )
                await db.commit()
                segment_id = cursor.lastrowid
            finally:
                await db.close()

            # Send transcript back to browser
            await websocket.send_json(
                {
                    "segment_id": segment_id,
                    "start_time": round(chunk_start, 2),
                    "end_time": round(chunk_end, 2),
                    "text": text,
                    "chunk_index": chunk_index,
                }
            )
            chunk_index += 1

    except WebSocketDisconnect:
        log.info("WebSocket disconnected for meeting %d", meeting_id)
