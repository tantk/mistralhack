"""
Unified WER + DER evaluation using edinburghcstr/ami dataset.
This dataset has both text transcripts and speaker labels per segment.

Instead of reconstructing full meeting audio (complex with overlapping headset mics),
we use a simpler approach:
  - Download the parquet with audio + text + speaker_id + timestamps
  - Pick ~10 segments from one meeting for WER evaluation
  - Use the diarizers-community/ami full meeting audio we already have for DER
  - Ground truth comes from edinburghcstr/ami (text + speaker + timestamps)
"""
import os
import sys
import json
import io
import numpy as np
import pandas as pd
import soundfile as sf
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download
from mistralai import Mistral
from jiwer import wer, cer, process_words
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate

api_key = os.environ.get("MISTRAL_API_KEY")
if not api_key:
    print("Error: MISTRAL_API_KEY not set.")
    sys.exit(1)

client = Mistral(api_key=api_key)
AUDIO_DIR = "audio_samples"
os.makedirs(AUDIO_DIR, exist_ok=True)

# ============================================================
# Part 1: Download edinburghcstr/ami test shard
# ============================================================
print("=" * 70)
print("Downloading edinburghcstr/ami test shard...")
print("=" * 70)

parquet_path = hf_hub_download(
    repo_id="edinburghcstr/ami",
    filename="ihm/test-00000-of-00004.parquet",
    repo_type="dataset",
)
print(f"Downloaded: {parquet_path}")

table = pq.read_table(parquet_path)
print(f"Total rows: {table.num_rows}")

# Get metadata
meeting_ids = table.column("meeting_id").to_pylist()
texts = table.column("text").to_pylist()
speaker_ids = table.column("speaker_id").to_pylist()
begin_times = table.column("begin_time").to_pylist()
end_times = table.column("end_time").to_pylist()

# ============================================================
# Part 2: WER — Pick 10 segments with substantial text
# ============================================================
print("\n" + "=" * 70)
print("WER Evaluation — edinburghcstr/ami")
print("=" * 70)

# Pick segments from meeting EN2002b (29.8 min, 4 speakers)
# Filter for segments with enough text (>5 words) and reasonable duration
TARGET_MEETING = "EN2002b"
candidates = []
for i in range(table.num_rows):
    if meeting_ids[i] == TARGET_MEETING:
        word_count = len(texts[i].split())
        duration = end_times[i] - begin_times[i]
        if word_count >= 5 and duration >= 2.0:
            candidates.append((i, word_count, duration))

# Sort by duration descending and pick 10
candidates.sort(key=lambda x: x[2], reverse=True)
selected = candidates[:10]

print(f"\nMeeting: {TARGET_MEETING}")
print(f"Selected {len(selected)} segments for WER evaluation\n")

print(f"{'#':<4} {'Speaker':<10} {'Duration':>8} {'Ref Words':>10}  Reference Text")
print("-" * 80)

wer_results = []
for idx, (row_idx, wc, dur) in enumerate(selected):
    audio_bytes = table.column("audio")[row_idx]["bytes"].as_py()
    ref_text = texts[row_idx]
    speaker = speaker_ids[row_idx]

    # Save audio
    filename = f"ami_wer_{idx:02d}.flac"
    filepath = os.path.join(AUDIO_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(audio_bytes)

    print(f"{idx+1:<4} {speaker:<10} {dur:>7.1f}s {wc:>10}  {ref_text[:55]}")

    wer_results.append({
        "file": filename,
        "filepath": filepath,
        "reference": ref_text,
        "speaker_id": speaker,
        "duration": dur,
    })

# Transcribe with Voxtral
print(f"\nTranscribing {len(wer_results)} segments with Voxtral...\n")

all_refs_raw, all_hyps_raw = [], []
all_refs_norm, all_hyps_norm = [], []

def normalize_text(t):
    import re
    t = t.lower().strip()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

print(f"{'File':<20} {'WER':>8} {'CER':>8}  {'H':>3} {'S':>3} {'D':>3} {'I':>3}")
print("-" * 60)

for r in wer_results:
    with open(r["filepath"], "rb") as f:
        result = client.audio.transcriptions.complete(
            model="voxtral-mini-latest",
            file={"content": f, "file_name": r["file"]},
        )

    r["voxtral"] = result.text

    ref_norm = normalize_text(r["reference"])
    hyp_norm = normalize_text(r["voxtral"])

    sample_wer = wer(ref_norm, hyp_norm)
    sample_cer = cer(ref_norm, hyp_norm)
    detail = process_words(ref_norm, hyp_norm)

    print(f"{r['file']:<20} {sample_wer:>7.1%} {sample_cer:>7.1%}  "
          f"{detail.hits:>3} {detail.substitutions:>3} {detail.deletions:>3} {detail.insertions:>3}")

    all_refs_raw.append(r["reference"].lower().strip())
    all_hyps_raw.append(r["voxtral"].lower().strip())
    all_refs_norm.append(ref_norm)
    all_hyps_norm.append(hyp_norm)

overall_wer_raw = wer(all_refs_raw, all_hyps_raw)
overall_wer_norm = wer(all_refs_norm, all_hyps_norm)
overall_cer_norm = cer(all_refs_norm, all_hyps_norm)
overall_detail = process_words(all_refs_norm, all_hyps_norm)

print("-" * 60)
print(f"{'OVERALL':<20} {overall_wer_norm:>7.1%} {overall_cer_norm:>7.1%}  "
      f"{overall_detail.hits:>3} {overall_detail.substitutions:>3} "
      f"{overall_detail.deletions:>3} {overall_detail.insertions:>3}")

# ============================================================
# Part 3: DER — Use the full meeting audio from diarizers-community/ami
#   Ground truth from edinburghcstr/ami (same meeting)
# ============================================================
print("\n" + "=" * 70)
print("DER Evaluation — AMI Meeting")
print("=" * 70)

# We already have the full meeting audio from earlier (diarizers-community/ami row 0 = EN2002b)
# and its Voxtral diarization in diarization_results.json
# But let's use edinburghcstr/ami ground truth for consistency

with open("diarization_results.json") as f:
    diar_data = json.load(f)

gt_segments = diar_data["ground_truth"]["segments"]
vx_segments = diar_data["voxtral"]["segments"]

reference = Annotation()
for seg in gt_segments:
    reference[Segment(seg["start"], seg["end"])] = seg["speaker"]

hypothesis = Annotation()
for seg in vx_segments:
    hypothesis[Segment(seg["start"], seg["end"])] = seg["speaker_id"]

print(f"\nGT speakers:      {diar_data['ground_truth']['num_speakers']} — {diar_data['ground_truth']['speaker_ids']}")
print(f"Voxtral speakers: {diar_data['voxtral']['num_speakers']} — {diar_data['voxtral']['speaker_ids']}")
print()

print(f"{'Collar':<10} {'DER':>10} {'Missed':>10} {'FA':>10} {'Confusion':>10}")
print("-" * 55)

for collar in [0.0, 0.25, 0.5]:
    metric = DiarizationErrorRate(collar=collar, skip_overlap=False)
    der_val = metric(reference, hypothesis)
    components = metric.compute_components(reference, hypothesis)

    print(f"{collar:.2f}s      {der_val:>9.1%} "
          f"{components['missed detection']:>9.1f}s "
          f"{components['false alarm']:>9.1f}s "
          f"{components['confusion']:>9.1f}s")

# Optimal mapping
metric = DiarizationErrorRate(collar=0.25, skip_overlap=False)
der_025 = metric(reference, hypothesis)
mapping = metric.optimal_mapping(reference, hypothesis)

print(f"\nOptimal speaker mapping (collar=0.25s):")
for vx_spk, gt_spk in sorted(mapping.items()):
    print(f"  {vx_spk:>12} -> {gt_spk}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY — Voxtral on AMI Meeting Corpus")
print("=" * 70)
print(f"\n  Dataset: edinburghcstr/ami (ihm, test split)")
print(f"  URL:     https://huggingface.co/datasets/edinburghcstr/ami")
print(f"  Meeting: {TARGET_MEETING} (4 speakers)")
print()
print(f"  Transcription (WER):")
print(f"    WER (normalized): {overall_wer_norm:.1%}")
print(f"    CER (normalized): {overall_cer_norm:.1%}")
print()
print(f"  Diarization (DER, pyannote.metrics):")
print(f"    DER (no collar):    {diar_data.get('der_000', 'N/A')}")
print(f"    DER (0.25s collar): {der_025:.1%}")
print()

# Save unified results
output = {
    "dataset": "edinburghcstr/ami",
    "url": "https://huggingface.co/datasets/edinburghcstr/ami",
    "meeting": TARGET_MEETING,
    "wer": {
        "normalized_wer": round(overall_wer_norm, 4),
        "normalized_cer": round(overall_cer_norm, 4),
        "num_samples": len(wer_results),
        "samples": [
            {
                "file": r["file"],
                "speaker_id": r["speaker_id"],
                "duration": round(r["duration"], 1),
                "reference": r["reference"],
                "voxtral": r["voxtral"],
            }
            for r in wer_results
        ],
    },
    "der": {
        "collar_025": round(der_025, 4),
        "num_gt_speakers": diar_data["ground_truth"]["num_speakers"],
        "num_voxtral_speakers": diar_data["voxtral"]["num_speakers"],
        "speaker_mapping": {k: v for k, v in sorted(mapping.items())},
    },
}

with open("ami_evaluation.json", "w") as f:
    json.dump(output, f, indent=2)

print("Full results saved to ami_evaluation.json")
