import os
import sys
import json
import io
import numpy as np
import pyarrow.parquet as pq
import soundfile as sf
from mistralai import Mistral

AUDIO_DIR = "audio_samples"

api_key = os.environ.get("MISTRAL_API_KEY")
if not api_key:
    print("Error: MISTRAL_API_KEY not set.")
    sys.exit(1)

# Load AMI test shard
parquet_path = os.path.expanduser(
    "~/.cache/huggingface/hub/datasets--diarizers-community--ami/"
    "snapshots/8cdaae2eaf968f3b000b6eb1204ab9b8db006ed0/ihm/test-00000-of-00003.parquet"
)
print("Loading AMI meeting data...")
table = pq.read_table(parquet_path)

# Use row 5 — shortest meeting (13.4 min, 4 speakers, 195 segments)
ROW = 5
audio_col = table.column("audio")[ROW]
audio_bytes = audio_col["bytes"].as_py()
speakers_gt = table.column("speakers")[ROW].as_py()
starts_gt = table.column("timestamps_start")[ROW].as_py()
ends_gt = table.column("timestamps_end")[ROW].as_py()

# Save audio to file
os.makedirs(AUDIO_DIR, exist_ok=True)
audio_path = os.path.join(AUDIO_DIR, "ami_meeting.wav")
data, sr = sf.read(io.BytesIO(audio_bytes))
sf.write(audio_path, data, sr)
duration = len(data) / sr
print(f"Saved {audio_path} ({duration:.1f}s / {duration/60:.1f}min, sr={sr})")

# Show ground truth summary
unique_speakers = sorted(set(speakers_gt))
print(f"\nGround truth: {len(starts_gt)} segments, {len(unique_speakers)} speakers")
print(f"Speakers: {unique_speakers}")
print("\nFirst 10 ground truth segments:")
for i in range(min(10, len(starts_gt))):
    print(f"  [{starts_gt[i]:.1f}s - {ends_gt[i]:.1f}s] {speakers_gt[i]}")

# Transcribe with Voxtral diarization
print(f"\nTranscribing with Voxtral diarization ({duration/60:.1f} min)...\n")
client = Mistral(api_key=api_key)

with open(audio_path, "rb") as f:
    result = client.audio.transcriptions.complete(
        model="voxtral-mini-latest",
        file={"content": f, "file_name": "ami_meeting.wav"},
        diarize=True,
        timestamp_granularities=["segment"],
    )

print("=== Voxtral Diarization Output ===\n")
voxtral_speakers = set()
for seg in result.segments:
    voxtral_speakers.add(seg.speaker_id)
    print(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.speaker_id}: {seg.text.strip()[:80]}")

print(f"\nVoxtral detected {len(voxtral_speakers)} speakers: {sorted(voxtral_speakers)}")
print(f"Ground truth has {len(unique_speakers)} speakers: {unique_speakers}")

# Save full results
output = {
    "meeting": f"AMI test row {ROW}",
    "duration_s": round(duration, 1),
    "ground_truth": {
        "num_speakers": len(unique_speakers),
        "speaker_ids": unique_speakers,
        "num_segments": len(starts_gt),
        "segments": [
            {"start": round(s, 2), "end": round(e, 2), "speaker": sp}
            for s, e, sp in zip(starts_gt, ends_gt, speakers_gt)
        ],
    },
    "voxtral": {
        "num_speakers": len(voxtral_speakers),
        "speaker_ids": sorted(voxtral_speakers),
        "num_segments": len(result.segments),
        "segments": [
            {
                "start": seg.start,
                "end": seg.end,
                "speaker_id": seg.speaker_id,
                "text": seg.text.strip(),
            }
            for seg in result.segments
        ],
    },
}
with open("diarization_results.json", "w") as f:
    json.dump(output, f, indent=2)

print("\nFull results saved to diarization_results.json")
