import logging
from contextlib import asynccontextmanager

# Patch torchaudio for SpeechBrain compatibility with torchaudio 2.10+
import torchaudio
if not hasattr(torchaudio, "list_audio_backends"):
    torchaudio.list_audio_backends = lambda: ["torchcodec"]

import torch
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from gpu_service.config import GPU_SERVICE_HOST, GPU_SERVICE_PORT, EMBEDDING_BACKEND
from gpu_service.audio_utils import prepare_audio
from gpu_service.diarize import diarize, get_pipeline
from gpu_service.embeddings import extract_embedding, get_extractor

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
async def embed_endpoint(audio: UploadFile = File(...)):
    try:
        raw = await audio.read()
        audio_16k = prepare_audio(raw)
        emb = extract_embedding(audio_16k)
        return {"embedding": emb.tolist(), "dim": len(emb)}
    except Exception as e:
        logger.exception("Embedding extraction failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=GPU_SERVICE_HOST, port=GPU_SERVICE_PORT)
