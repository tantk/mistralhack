import io
import numpy as np
import soundfile as sf
import librosa
from gpu_service.config import TARGET_SAMPLE_RATE


def load_audio_bytes(raw_bytes: bytes) -> tuple[np.ndarray, int]:
    """Load WAV bytes → (float32 waveform, sample_rate)."""
    audio, sr = sf.read(io.BytesIO(raw_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # stereo → mono
    return audio, sr


def resample_to_16k(audio: np.ndarray, orig_sr: int) -> np.ndarray:
    """Resample to 16 kHz if needed."""
    if orig_sr == TARGET_SAMPLE_RATE:
        return audio
    return librosa.resample(audio, orig_sr=orig_sr, target_sr=TARGET_SAMPLE_RATE)


def prepare_audio(raw_bytes: bytes) -> np.ndarray:
    """Load + resample in one call. Returns 16 kHz mono float32."""
    audio, sr = load_audio_bytes(raw_bytes)
    return resample_to_16k(audio, sr)
