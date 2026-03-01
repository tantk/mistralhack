import logging
import os
from pathlib import Path
from typing import Generator

import numpy as np
import torch
from transformers import AutoModelForSpeechSeq2Seq

from gpu_service.config import VOXTRAL_MODEL_ID, VOXTRAL_LOCAL_PATH, TARGET_SAMPLE_RATE

logger = logging.getLogger("gpu_service")

_model = None
_processor = None


def _load_processor(model_path: str):
    """
    Load VoxtralRealtimeProcessor with MistralCommonBackend tokenizer.
    The processor requires mistral-common's tekken tokenizer, not the standard HF tokenizer.
    """
    from transformers.models.voxtral_realtime.processing_voxtral_realtime import (
        MistralCommonBackend,
        VoxtralRealtimeProcessor,
    )
    from transformers import VoxtralRealtimeFeatureExtractor

    tekken_path = Path(model_path) / "tekken.json"
    if not tekken_path.exists():
        raise FileNotFoundError(f"tekken.json not found at {tekken_path}")

    tokenizer = MistralCommonBackend(tokenizer_path=str(tekken_path))
    feature_extractor = VoxtralRealtimeFeatureExtractor.from_pretrained(model_path)
    return VoxtralRealtimeProcessor(feature_extractor=feature_extractor, tokenizer=tokenizer)


def get_model():
    """Lazy-load Voxtral model + processor singleton. Uses local path if available. Requires CUDA."""
    global _model, _processor
    if _model is None:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available — GPU service requires a GPU, refusing to fall back to CPU")
        model_path = VOXTRAL_LOCAL_PATH if os.path.isdir(VOXTRAL_LOCAL_PATH) else VOXTRAL_MODEL_ID

        logger.info("Loading Voxtral model from %s on cuda...", model_path)
        _processor = _load_processor(model_path)
        _model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            trust_remote_code=True,
        ).to("cuda")
        logger.info("Voxtral model ready.")
    return _model, _processor


def _clean_text(text: str) -> str:
    """Strip Voxtral streaming markers."""
    return text.replace("[STREAMING_PAD]", "").replace("[STREAMING_WORD]", "")


def transcribe(audio_16k: np.ndarray, prompt: str = "Transcribe this audio.") -> str:
    """Non-streaming transcription. Returns cleaned text."""
    model, processor = get_model()
    device = next(model.parameters()).device

    inputs = processor(
        audio=audio_16k,
        sampling_rate=TARGET_SAMPLE_RATE,
        text=prompt,
        return_tensors="pt",
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=1024)

    # Decode only the new tokens (skip input prompt tokens)
    input_len = inputs.get("input_ids", inputs.get("decoder_input_ids", torch.tensor([[]]))).shape[-1]
    output_ids = generated_ids[:, input_len:]
    text = processor.batch_decode(output_ids, skip_special_tokens=True)[0]
    return _clean_text(text).strip()


def transcribe_stream(audio_16k: np.ndarray, prompt: str = "Transcribe this audio.") -> Generator[str, None, str]:
    """
    Streaming transcription via TextIteratorStreamer.
    Yields cleaned token strings. Returns final full text.
    """
    from threading import Thread
    from transformers import TextIteratorStreamer

    model, processor = get_model()
    device = next(model.parameters()).device

    inputs = processor(
        audio=audio_16k,
        sampling_rate=TARGET_SAMPLE_RATE,
        text=prompt,
        return_tensors="pt",
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    streamer = TextIteratorStreamer(processor.tokenizer, skip_prompt=True, skip_special_tokens=True)

    generation_kwargs = {**inputs, "max_new_tokens": 1024, "streamer": streamer}

    thread = Thread(target=model.generate, kwargs=generation_kwargs)
    thread.start()

    full_text = ""
    for token_text in streamer:
        clean = _clean_text(token_text)
        if clean:
            full_text += clean
            yield clean

    thread.join()
    return full_text.strip()
