import io
import logging
from contextlib import asynccontextmanager
from typing import Optional

# Patch torchaudio for SpeechBrain compatibility with torchaudio 2.10+
import torchaudio
if not hasattr(torchaudio, "list_audio_backends"):
    torchaudio.list_audio_backends = lambda: ["torchcodec"]

import numpy as np
import torch
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydub import AudioSegment

from gpu_service.config import GPU_SERVICE_HOST, GPU_SERVICE_PORT, EMBEDDING_BACKEND
from gpu_service.audio_utils import prepare_audio
from gpu_service.diarize import diarize, get_pipeline
from gpu_service.embeddings import extract_embedding, get_extractor
from gpu_service.voiceprint_store import get_voiceprint_store

logger = logging.getLogger("gpu_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pre-loading diarization pipeline...")
    get_pipeline()
    logger.info("Diarization pipeline ready. Embedding extractor will lazy-load on first request.")
    yield


app = FastAPI(title="GPU Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "gpu_available": torch.cuda.is_available(),
        "embedding_backend": EMBEDDING_BACKEND,
    }


@app.post("/diarize")
async def diarize_endpoint(
    audio: UploadFile = File(...),
    min_speakers: int = Form(None),
    max_speakers: int = Form(None),
):
    try:
        raw = await audio.read()
        audio_16k = prepare_audio(raw)
        segments = diarize(audio_16k, min_speakers=min_speakers, max_speakers=max_speakers)
        return {"segments": segments}
    except Exception as e:
        logger.exception("Diarization failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/embed")
async def embed_endpoint(
    audio: UploadFile = File(...),
    start_time: Optional[float] = Form(None),
    end_time: Optional[float] = Form(None),
):
    try:
        raw = await audio.read()
        if start_time is not None and end_time is not None:
            audio_seg = AudioSegment.from_file(io.BytesIO(raw))
            audio_seg = audio_seg[int(start_time * 1000):int(end_time * 1000)]
            audio_seg = audio_seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            audio_16k = np.array(audio_seg.get_array_of_samples(), dtype=np.float32) / 32768.0
        else:
            audio_16k = prepare_audio(raw)
        emb = extract_embedding(audio_16k)
        return {"embedding": emb.tolist(), "dim": len(emb)}
    except Exception as e:
        logger.exception("Embedding extraction failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/voiceprint/identify")
async def voiceprint_identify(
    audio: UploadFile = File(...),
    start_time: Optional[float] = Form(None),
    end_time: Optional[float] = Form(None),
):
    try:
        raw = await audio.read()
        audio_seg = AudioSegment.from_file(io.BytesIO(raw))

        # Slice audio if time range provided
        if start_time is not None and end_time is not None:
            start_ms = int(start_time * 1000)
            end_ms = int(end_time * 1000)
            audio_seg = audio_seg[start_ms:end_ms]

        # Convert sliced audio to 16kHz numpy for embedding
        audio_seg = audio_seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        samples = np.array(audio_seg.get_array_of_samples(), dtype=np.float32) / 32768.0

        emb = extract_embedding(samples)
        store = get_voiceprint_store()
        matches = store.identify(emb)
        return {"matches": matches}
    except Exception as e:
        logger.exception("Voiceprint identify failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/voiceprint/enroll")
async def voiceprint_enroll(
    audio: UploadFile = File(...),
    name: str = Form(...),
):
    try:
        raw = await audio.read()
        audio_16k = prepare_audio(raw)
        emb = extract_embedding(audio_16k)
        store = get_voiceprint_store()
        speaker_id = store.enroll(name, emb)
        return {"speaker_id": speaker_id, "name": name}
    except Exception as e:
        logger.exception("Voiceprint enroll failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/voiceprint/speakers")
async def voiceprint_speakers():
    try:
        store = get_voiceprint_store()
        return {"speakers": store.list_speakers()}
    except Exception as e:
        logger.exception("Voiceprint list failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=GPU_SERVICE_HOST, port=GPU_SERVICE_PORT)
