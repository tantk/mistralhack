from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

MISTRAL_RS_URL = os.getenv("MISTRAL_RS_URL", "http://192.168.0.105:8080")
DIARIZATION_URL = os.getenv("DIARIZATION_URL", "http://192.168.0.105:8001")
DATABASE_PATH = os.getenv("DATABASE_PATH", "meetings.db")
AUDIO_STORAGE_PATH = Path(os.getenv("AUDIO_STORAGE_PATH", "audio_storage"))
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
VOICEPRINT_STORE_PATH = Path(os.getenv("VOICEPRINT_STORE_PATH", "voiceprint_store"))
API_KEY = os.getenv("API_KEY", "")

AUDIO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
VOICEPRINT_STORE_PATH.mkdir(parents=True, exist_ok=True)
