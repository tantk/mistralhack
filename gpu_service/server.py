import asyncio
import io
import json
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
from sse_starlette.sse import EventSourceResponse

from gpu_service.config import GPU_SERVICE_HOST, GPU_SERVICE_PORT, EMBEDDING_BACKEND
from gpu_service.audio_utils import prepare_audio
from gpu_service.diarize import diarize, get_pipeline
from gpu_service.embeddings import extract_embedding, get_extractor
from gpu_service.transcribe import get_model as get_transcription_model, transcribe, transcribe_stream
from gpu_service.voiceprint_store import get_voiceprint_store

logger = logging.getLogger("gpu_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pre-loading diarization pipeline...")
    get_pipeline()
    logger.info("Diarization pipeline ready.")
    logger.info("Pre-loading Voxtral transcription model...")
    get_transcription_model()
    logger.info("Voxtral model ready. Embedding extractor will lazy-load on first request.")
    yield


app = FastAPI(title="GPU Diarization, Embedding & Transcription Service", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health():
    from gpu_service.config import VOXTRAL_MODEL_ID
    if not torch.cuda.is_available():
        return JSONResponse(status_code=503, content={
            "status": "error",
            "error": "CUDA not available — GPU required",
        })
    return {
        "status": "ok",
        "gpu_available": True,
        "embedding_backend": EMBEDDING_BACKEND,
        "transcription_model": VOXTRAL_MODEL_ID,
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


@app.post("/transcribe")
async def transcribe_endpoint(
    audio: UploadFile = File(...),
    prompt: str = Form("Transcribe this audio."),
):
    try:
        raw = await audio.read()
        audio_16k = prepare_audio(raw)
        text = transcribe(audio_16k, prompt=prompt)
        return {"text": text}
    except Exception as e:
        logger.exception("Transcription failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/transcribe/stream")
async def transcribe_stream_endpoint(
    audio: UploadFile = File(...),
    prompt: str = Form("Transcribe this audio."),
):
    try:
        raw = await audio.read()
        audio_16k = prepare_audio(raw)
    except Exception as e:
        logger.exception("Audio preparation failed")
        return JSONResponse(status_code=500, content={"error": str(e)})

    async def event_generator():
        loop = asyncio.get_event_loop()
        full_text = ""
        try:
            gen = transcribe_stream(audio_16k, prompt=prompt)
            # Run the blocking generator in a thread
            import queue
            import threading

            q = queue.Queue()
            sentinel = object()

            def _run():
                try:
                    for token in gen:
                        q.put(token)
                except Exception as exc:
                    q.put(exc)
                finally:
                    q.put(sentinel)

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is sentinel:
                    break
                if isinstance(item, Exception):
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": str(item)}),
                    }
                    return
                full_text += item
                yield {
                    "event": "token",
                    "data": json.dumps({"token": item}),
                }

            yield {
                "event": "done",
                "data": json.dumps({"text": full_text.strip()}),
            }
        except Exception as e:
            logger.exception("Streaming transcription failed")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=GPU_SERVICE_HOST, port=GPU_SERVICE_PORT)
