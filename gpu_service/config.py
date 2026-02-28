import os

# Server
GPU_SERVICE_HOST = os.getenv("GPU_SERVICE_HOST", "0.0.0.0")
GPU_SERVICE_PORT = int(os.getenv("GPU_SERVICE_PORT", "8001"))

# Pyannote (gated model — requires HF_TOKEN)
HF_TOKEN = os.getenv("HF_TOKEN", "")
PYANNOTE_MODEL = "pyannote/speaker-diarization-community-1"
PYANNOTE_MIN_SPEAKERS = int(os.getenv("PYANNOTE_MIN_SPEAKERS", "1"))
PYANNOTE_MAX_SPEAKERS = int(os.getenv("PYANNOTE_MAX_SPEAKERS", "10"))

# Speaker embeddings
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "funasr")  # "speechbrain" or "funasr"
SPEECHBRAIN_MODEL = "speechbrain/spkrec-ecapa-voxceleb"
SPEECHBRAIN_CACHE = "gpu_service/data/speechbrain_cache"
FUNASR_MODEL = "iic/speech_campplus_sv_zh-cn_16k-common"

# Voxtral transcription
VOXTRAL_MODEL_ID = os.getenv("VOXTRAL_MODEL_ID", "mistralai/Voxtral-Mini-4B-Realtime-2602")
VOXTRAL_LOCAL_PATH = os.getenv("VOXTRAL_LOCAL_PATH", "models/Voxtral-Mini-4B-Realtime-2602")

# Audio
TARGET_SAMPLE_RATE = 16000
MIN_SEGMENT_DURATION_SEC = 0.5
