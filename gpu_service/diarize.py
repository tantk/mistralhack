import torch
import numpy as np
from pyannote.audio import Pipeline as PyannotePipeline
from gpu_service.config import (
    HF_TOKEN,
    PYANNOTE_MODEL,
    PYANNOTE_MIN_SPEAKERS,
    PYANNOTE_MAX_SPEAKERS,
    TARGET_SAMPLE_RATE,
)

_pipeline: PyannotePipeline | None = None


def get_pipeline() -> PyannotePipeline:
    """Lazy-load pyannote pipeline. Downloads model on first call."""
    global _pipeline
    if _pipeline is None:
        _pipeline = PyannotePipeline.from_pretrained(
            PYANNOTE_MODEL,
            token=HF_TOKEN,
        )
        if torch.cuda.is_available():
            _pipeline = _pipeline.to(torch.device("cuda"))
    return _pipeline


def diarize(
    audio_16k: np.ndarray,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[dict]:
    """
    Run pyannote diarization on 16 kHz mono audio.

    Returns list of segments:
        [{"speaker": "SPEAKER_00", "start": 0.0, "end": 5.2, "duration": 5.2}, ...]
    """
    pipeline = get_pipeline()

    waveform = torch.from_numpy(audio_16k).unsqueeze(0).float()
    input_data = {"waveform": waveform, "sample_rate": TARGET_SAMPLE_RATE}

    diarization = pipeline(
        input_data,
        min_speakers=min_speakers or PYANNOTE_MIN_SPEAKERS,
        max_speakers=max_speakers or PYANNOTE_MAX_SPEAKERS,
    )

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "speaker": speaker,
            "start": round(turn.start, 3),
            "end": round(turn.end, 3),
            "duration": round(turn.end - turn.start, 3),
        })

    segments.sort(key=lambda s: s["start"])
    return segments
