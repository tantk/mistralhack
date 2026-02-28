import logging

import httpx

from app.config import MISTRAL_RS_URL

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


async def transcribe_audio(wav_bytes: bytes) -> str:
    """Send a WAV audio chunk to the Rust backend and return the transcript text."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{MISTRAL_RS_URL}/transcribe",
            files={"audio": ("chunk.wav", wav_bytes, "audio/wav")},
        )
        resp.raise_for_status()

    result = resp.json()
    text = result["text"]
    log.info("Transcription received: %d chars", len(text))
    return text.strip()
