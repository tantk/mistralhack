"""Compute Diarization Error Rate (DER) on the AMI meeting."""
import json

with open("diarization_results.json") as f:
    data = json.load(f)

gt_segments = data["ground_truth"]["segments"]
vx_segments = data["voxtral"]["segments"]

# DER = (missed speech + false alarm + speaker confusion) / total ground truth speech
# We evaluate on a frame-by-frame basis (10ms resolution)

RESOLUTION = 0.01  # 10ms frames

# Find the time range
all_times = [s["end"] for s in gt_segments] + [s["end"] for s in vx_segments]
max_time = max(all_times)
n_frames = int(max_time / RESOLUTION) + 1

print(f"=== Diarization Error Rate (DER) — AMI Meeting ===\n")
print(f"Duration: {max_time:.1f}s ({max_time/60:.1f} min)")
print(f"Resolution: {RESOLUTION*1000:.0f}ms ({n_frames} frames)")
print(f"Ground truth: {data['ground_truth']['num_speakers']} speakers, {len(gt_segments)} segments")
print(f"Voxtral:      {data['voxtral']['num_speakers']} speakers, {len(vx_segments)} segments")

# Build frame-level labels
# For each frame, store the set of active speakers

def build_frame_labels(segments, speaker_key, n_frames, resolution):
    """Build a list of sets — one set of speaker IDs per frame."""
    frames = [set() for _ in range(n_frames)]
    for seg in segments:
        start_frame = int(seg["start"] / resolution)
        end_frame = int(seg["end"] / resolution)
        spk = seg[speaker_key]
        for f in range(start_frame, min(end_frame, n_frames)):
            frames[f].add(spk)
    return frames

gt_frames = build_frame_labels(gt_segments, "speaker", n_frames, RESOLUTION)
vx_frames = build_frame_labels(vx_segments, "speaker_id", n_frames, RESOLUTION)

# To compute speaker confusion, we need an optimal mapping from voxtral speakers to GT speakers.
# Use a greedy approach: map each voxtral speaker to the GT speaker with maximum overlap.

from collections import Counter

# Count co-occurrences
cooccurrence = Counter()
for f in range(n_frames):
    for gt_spk in gt_frames[f]:
        for vx_spk in vx_frames[f]:
            cooccurrence[(vx_spk, gt_spk)] += 1

# Greedy mapping: assign each voxtral speaker to the best GT speaker
vx_speakers = sorted(data["voxtral"]["speaker_ids"])
gt_speakers = sorted(data["ground_truth"]["speaker_ids"])

# Many-to-one mapping (multiple voxtral speakers can map to same GT speaker)
mapping = {}
for vx_spk in vx_speakers:
    best_gt = None
    best_count = 0
    for gt_spk in gt_speakers:
        count = cooccurrence.get((vx_spk, gt_spk), 0)
        if count > best_count:
            best_count = count
            best_gt = gt_spk
    mapping[vx_spk] = best_gt

print(f"\nSpeaker mapping (Voxtral -> Ground Truth):")
for vx_spk, gt_spk in sorted(mapping.items()):
    overlap = cooccurrence.get((vx_spk, gt_spk), 0) * RESOLUTION
    print(f"  {vx_spk:>12} -> {gt_spk or 'None':<12} ({overlap:.1f}s overlap)")

# Compute DER components
total_gt_speech = 0      # frames where GT has speech
missed_speech = 0        # GT has speech, Voxtral has nothing
false_alarm = 0          # GT has no speech, Voxtral has speech
speaker_confusion = 0    # Both have speech, but mapped speakers don't match

for f in range(n_frames):
    gt_set = gt_frames[f]
    vx_set = vx_frames[f]

    # Map voxtral speakers to GT space
    vx_mapped = {mapping.get(s) for s in vx_set} - {None}

    if gt_set:
        total_gt_speech += len(gt_set)

        for spk in gt_set:
            if not vx_set:
                missed_speech += 1
            elif spk not in vx_mapped:
                speaker_confusion += 1

    if vx_set and not gt_set:
        false_alarm += len(vx_set)

total_gt_seconds = total_gt_speech * RESOLUTION
missed_seconds = missed_speech * RESOLUTION
fa_seconds = false_alarm * RESOLUTION
confusion_seconds = speaker_confusion * RESOLUTION

der = (missed_speech + false_alarm + speaker_confusion) / total_gt_speech if total_gt_speech > 0 else 0

print(f"\n{'Component':<25} {'Frames':>10} {'Seconds':>10} {'Rate':>10}")
print("-" * 60)
print(f"{'Total GT speech':<25} {total_gt_speech:>10} {total_gt_seconds:>9.1f}s")
print(f"{'Missed speech':<25} {missed_speech:>10} {missed_seconds:>9.1f}s {missed_speech/total_gt_speech:>9.1%}")
print(f"{'False alarm':<25} {false_alarm:>10} {fa_seconds:>9.1f}s {false_alarm/total_gt_speech:>9.1%}")
print(f"{'Speaker confusion':<25} {speaker_confusion:>10} {confusion_seconds:>9.1f}s {speaker_confusion/total_gt_speech:>9.1%}")
print("-" * 60)
print(f"{'DER':<25} {'':>10} {'':>10} {der:>9.1%}")
print(f"\nDER = (missed + false_alarm + confusion) / total_gt_speech")
print(f"    = ({missed_seconds:.1f} + {fa_seconds:.1f} + {confusion_seconds:.1f}) / {total_gt_seconds:.1f}")
