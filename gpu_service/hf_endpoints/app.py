"""
Slim GPU service for HF Inference Endpoints.
Exposes /diarize, /embed, /transcribe, and /transcribe/stream endpoints.
"""

import io
import json
import logging
import os
import threading
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
import librosa
import torch
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydub import AudioSegment
from sse_starlette.sse import EventSourceResponse

from voxtral_inference import VoxtralModel

logger = logging.getLogger("gpu_service")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HF_TOKEN = os.environ.get("HF_TOKEN", "")
PYANNOTE_MODEL = "pyannote/speaker-diarization-community-1"
FUNASR_MODEL = "iic/speech_campplus_sv_zh-cn_16k-common"
PYANNOTE_MIN_SPEAKERS = int(os.environ.get("PYANNOTE_MIN_SPEAKERS", "1"))
PYANNOTE_MAX_SPEAKERS = int(os.environ.get("PYANNOTE_MAX_SPEAKERS", "10"))
TARGET_SR = 16000

MODEL_DIR = os.environ.get("VOXTRAL_MODEL_DIR", "/repository/voxtral-model")

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
_diarize_pipeline = None
_embed_model = None
_voxtral: VoxtralModel | None = None


def _load_diarize_pipeline():
    global _diarize_pipeline
    if _diarize_pipeline is None:
        from pyannote.audio import Pipeline as PyannotePipeline

        _diarize_pipeline = PyannotePipeline.from_pretrained(
            PYANNOTE_MODEL, token=HF_TOKEN
        )
        _diarize_pipeline = _diarize_pipeline.to(torch.device("cuda"))
    return _diarize_pipeline


def _load_embed_model():
    global _embed_model
    if _embed_model is None:
        from funasr import AutoModel

        _embed_model = AutoModel(model=FUNASR_MODEL)
    return _embed_model


def _load_voxtral():
    global _voxtral
    if _voxtral is None:
        logger.info("Loading Voxtral from %s ...", MODEL_DIR)
        _voxtral = VoxtralModel(MODEL_DIR)
        logger.info("Voxtral model loaded.")
    return _voxtral


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------
def prepare_audio(raw_bytes: bytes) -> np.ndarray:
    """Read any audio format -> float32 mono @ 16 kHz."""
    audio, sr = sf.read(io.BytesIO(raw_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)
    return audio


def prepare_audio_slice(raw_bytes: bytes, start_time: float, end_time: float) -> np.ndarray:
    """Read audio, slice by time, return float32 mono @ 16 kHz."""
    seg = AudioSegment.from_file(io.BytesIO(raw_bytes))
    seg = seg[int(start_time * 1000):int(end_time * 1000)]
    seg = seg.set_frame_rate(TARGET_SR).set_channels(1).set_sample_width(2)
    return np.array(seg.get_array_of_samples(), dtype=np.float32) / 32768.0


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up diarization pipeline at startup (embedding model lazy-loads)
    _load_diarize_pipeline()
    yield


app = FastAPI(title="GPU Service (HF Endpoint)", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "gpu_available": torch.cuda.is_available()}


@app.post("/diarize")
async def diarize(
    audio: UploadFile = File(...),
    min_speakers: int | None = Form(None),
    max_speakers: int | None = Form(None),
):
    try:
        raw = await audio.read()
        audio_16k = prepare_audio(raw)

        pipeline = _load_diarize_pipeline()
        waveform = torch.from_numpy(audio_16k).unsqueeze(0).float()
        input_data = {"waveform": waveform, "sample_rate": TARGET_SR}

        result = pipeline(
            input_data,
            min_speakers=min_speakers or PYANNOTE_MIN_SPEAKERS,
            max_speakers=max_speakers or PYANNOTE_MAX_SPEAKERS,
        )
        # pyannote v4 compat
        diarization = getattr(result, "speaker_diarization", result)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(
                {
                    "speaker": speaker,
                    "start": round(turn.start, 3),
                    "end": round(turn.end, 3),
                    "duration": round(turn.end - turn.start, 3),
                }
            )
        segments.sort(key=lambda s: s["start"])
        return {"segments": segments}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/embed")
async def embed(
    audio: UploadFile = File(...),
    start_time: float | None = Form(None),
    end_time: float | None = Form(None),
):
    try:
        raw = await audio.read()
        if start_time is not None and end_time is not None:
            audio_16k = prepare_audio_slice(raw, start_time, end_time)
        else:
            audio_16k = prepare_audio(raw)

        model = _load_embed_model()
        result = model.generate(input=audio_16k, output_dir=None)
        raw_emb = result[0]["spk_embedding"]
        if hasattr(raw_emb, "cpu"):
            raw_emb = raw_emb.cpu().numpy()
        emb = np.array(raw_emb).flatten()

        # L2-normalize
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm

        return {"embedding": emb.tolist(), "dim": len(emb)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    try:
        raw = await audio.read()
        audio_16k = prepare_audio(raw)

        model = _load_voxtral()
        text = model.transcribe(audio_16k)

        return {"text": text}
    except Exception as e:
        logger.exception("Transcription failed")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/transcribe/stream")
async def transcribe_stream(audio: UploadFile = File(...)):
    try:
        raw = await audio.read()
        audio_16k = prepare_audio(raw)
    except Exception as e:
        logger.exception("Audio preparation failed")
        return JSONResponse(status_code=500, content={"error": str(e)})

    async def event_generator():
        try:
            model = _load_voxtral()
            full_text = ""

            # Run blocking generator in a thread
            tokens = []

            def _run():
                for tok in model.transcribe_stream(audio_16k):
                    tokens.append(tok)

            thread = threading.Thread(target=_run)
            thread.start()
            thread.join()

            for tok in tokens:
                full_text += tok
                yield {"event": "token", "data": json.dumps({"token": tok})}

            full_text = full_text.strip()
            yield {"event": "done", "data": json.dumps({"text": full_text})}
        except Exception as e:
            logger.exception("Streaming transcription failed")
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())
