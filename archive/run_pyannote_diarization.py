"""Run pyannote speaker diarization on the AMI meeting audio and compare with Voxtral."""
import json
import time
import os
from pyannote.audio import Pipeline
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate

AUDIO_PATH = "audio_samples/ami_meeting.wav"

# pyannote requires a HuggingFace token for gated models
hf_token = os.environ.get("HF_TOKEN")

print("Loading pyannote speaker-diarization pipeline...")
t0 = time.time()
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token=hf_token,
)
load_time = time.time() - t0
print(f"Model loaded in {load_time:.1f}s")

print(f"\nRunning diarization on {AUDIO_PATH}...")
t0 = time.time()
pyannote_result = pipeline(AUDIO_PATH)
diarize_time = time.time() - t0
print(f"Diarization completed in {diarize_time:.1f}s")

# Show pyannote output
pyannote_speakers = set()
pyannote_segments = []
print(f"\n=== pyannote Diarization Output ===\n")
for turn, _, speaker in pyannote_result.speaker_diarization.itertracks(yield_label=True):
    pyannote_speakers.add(speaker)
    pyannote_segments.append({
        "start": turn.start,
        "end": turn.end,
        "speaker_id": speaker,
    })
    if len(pyannote_segments) <= 20:
        print(f"  [{turn.start:.1f}s - {turn.end:.1f}s] {speaker}")

if len(pyannote_segments) > 20:
    print(f"  ... ({len(pyannote_segments)} segments total)")

print(f"\npyannote detected {len(pyannote_speakers)} speakers: {sorted(pyannote_speakers)}")

# Load ground truth and Voxtral results
with open("diarization_results.json") as f:
    data = json.load(f)

gt_segments = data["ground_truth"]["segments"]
vx_segments = data["voxtral"]["segments"]

# Build pyannote Annotations for evaluation
def build_annotation(segments, speaker_key):
    ann = Annotation()
    for seg in segments:
        ann[Segment(seg["start"], seg["end"])] = seg[speaker_key]
    return ann

reference = build_annotation(gt_segments, "speaker")
hypothesis_voxtral = build_annotation(vx_segments, "speaker_id")
hypothesis_pyannote = pyannote_result.speaker_diarization  # extract Annotation from DiarizeOutput

# Compare DER
print(f"\n{'='*70}")
print("DER Comparison: Voxtral vs pyannote")
print(f"{'='*70}\n")

print(f"{'':30} {'Voxtral':>12} {'pyannote':>12}")
print(f"{'Speakers detected':<30} {data['voxtral']['num_speakers']:>12} {len(pyannote_speakers):>12}")
print(f"{'Segments':<30} {len(vx_segments):>12} {len(pyannote_segments):>12}")
print()

print(f"{'Collar':<10} {'Voxtral DER':>12} {'pyannote DER':>13} {'Winner':>10}")
print("-" * 50)

for collar in [0.0, 0.25, 0.5]:
    metric_vx = DiarizationErrorRate(collar=collar, skip_overlap=False)
    der_vx = metric_vx(reference, hypothesis_voxtral)

    metric_pa = DiarizationErrorRate(collar=collar, skip_overlap=False)
    der_pa = metric_pa(reference, hypothesis_pyannote)

    winner = "pyannote" if der_pa < der_vx else "Voxtral" if der_vx < der_pa else "tie"
    print(f"{collar:.2f}s      {der_vx:>11.1%} {der_pa:>12.1%} {winner:>10}")

# Detailed breakdown at 0.25s collar
print(f"\n--- Detailed breakdown (collar=0.25s) ---\n")
for label, hyp in [("Voxtral", hypothesis_voxtral), ("pyannote", hypothesis_pyannote)]:
    metric = DiarizationErrorRate(collar=0.25, skip_overlap=False)
    der = metric(reference, hyp)
    components = metric.compute_components(reference, hyp)
    mapping = metric.optimal_mapping(reference, hyp)

    print(f"{label}:")
    print(f"  DER:        {der:.1%}")
    print(f"  Missed:     {components['missed detection']:.1f}s")
    print(f"  False alarm: {components['false alarm']:.1f}s")
    print(f"  Confusion:  {components['confusion']:.1f}s")
    print(f"  Mapping:    {dict(sorted(mapping.items()))}")
    print()

# Save pyannote results
output = {
    "pyannote": {
        "num_speakers": len(pyannote_speakers),
        "speaker_ids": sorted(pyannote_speakers),
        "num_segments": len(pyannote_segments),
        "diarize_time_s": round(diarize_time, 1),
        "segments": pyannote_segments,
    }
}
with open("pyannote_results.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"pyannote results saved to pyannote_results.json")
