import os
import sys
from mistralai import Mistral

api_key = os.environ.get("MISTRAL_API_KEY")
if not api_key:
    print("Error: MISTRAL_API_KEY environment variable not set.")
    print("Export it with: export MISTRAL_API_KEY='your-key-here'")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: python transcribe.py <audio_file>")
    print("Supported formats: mp3, wav, flac, ogg, m4a, webm")
    sys.exit(1)

audio_file = sys.argv[1]
if not os.path.exists(audio_file):
    print(f"Error: File '{audio_file}' not found.")
    sys.exit(1)

client = Mistral(api_key=api_key)

print(f"Transcribing: {audio_file}")
with open(audio_file, "rb") as f:
    result = client.audio.transcriptions.complete(
        model="voxtral-mini-latest",
        file={"content": f, "file_name": os.path.basename(audio_file)},
    )

print("\n--- Transcription ---")
print(result.text)
