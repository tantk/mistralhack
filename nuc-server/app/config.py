from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

MISTRAL_RS_URL = os.getenv("MISTRAL_RS_URL", "http://192.168.1.100:8080")
DIARIZATION_URL = os.getenv("DIARIZATION_URL", "http://192.168.1.100:8001")
DATABASE_PATH = os.getenv("DATABASE_PATH", "meetings.db")
AUDIO_STORAGE_PATH = Path(os.getenv("AUDIO_STORAGE_PATH", "audio_storage"))

AUDIO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
