import os
import sys
import json
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download
from mistralai import Mistral

NUM_SAMPLES = 10
AUDIO_DIR = "audio_samples"

# Check API key
api_key = os.environ.get("MISTRAL_API_KEY")
if not api_key:
    print("Error: MISTRAL_API_KEY not set.")
    print("Run: export MISTRAL_API_KEY='your-key-here'")
    sys.exit(1)

# Download the parquet file for microset
print("Downloading People's Speech microset parquet...")
parquet_path = hf_hub_download(
    repo_id="MLCommons/peoples_speech",
    filename="microset/train-00000-of-00001.parquet",
    repo_type="dataset",
)
print(f"Downloaded to: {parquet_path}")

# Read the parquet and extract audio
table = pq.read_table(parquet_path)
print(f"Total rows: {table.num_rows}, using first {NUM_SAMPLES}")

os.makedirs(AUDIO_DIR, exist_ok=True)

samples = []
for i in range(NUM_SAMPLES):
    audio_bytes = table.column("audio")[i]["bytes"].as_py()
    text = table.column("text")[i].as_py()
    duration_ms = table.column("duration_ms")[i].as_py()

    # The audio is stored as FLAC bytes
    filename = f"sample_{i:02d}.flac"
    filepath = os.path.join(AUDIO_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(audio_bytes)

    samples.append({
        "filepath": filepath,
        "reference": text,
        "duration_ms": duration_ms,
    })
    print(f"  Saved {filename} ({duration_ms}ms) - \"{text[:60]}...\"" if len(text) > 60 else f"  Saved {filename} ({duration_ms}ms) - \"{text}\"")

# Transcribe with Mistral Voxtral
print(f"\nTranscribing {NUM_SAMPLES} samples with Voxtral...\n")
client = Mistral(api_key=api_key)

results = []
for i, s in enumerate(samples):
    print(f"[{i+1}/{NUM_SAMPLES}] {os.path.basename(s['filepath'])} ({s['duration_ms']}ms)")
    print(f"  Reference : {s['reference']}")

    with open(s["filepath"], "rb") as f:
        result = client.audio.transcriptions.complete(
            model="voxtral-mini-latest",
            file={"content": f, "file_name": os.path.basename(s["filepath"])},
        )

    print(f"  Voxtral   : {result.text}")
    print()

    results.append({
        "file": os.path.basename(s["filepath"]),
        "duration_ms": s["duration_ms"],
        "reference": s["reference"],
        "voxtral": result.text,
    })

# Save results to JSON
output_path = "transcriptions.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"Results saved to {output_path}")

print("Done!")
