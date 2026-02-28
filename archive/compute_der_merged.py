"""Compute DER with speaker merging — merge over-segmented speakers."""
import json
from collections import Counter, defaultdict

with open("diarization_results.json") as f:
    data = json.load(f)

gt_segments = data["ground_truth"]["segments"]
vx_segments = data["voxtral"]["segments"]

RESOLUTION = 0.01
all_times = [s["end"] for s in gt_segments] + [s["end"] for s in vx_segments]
max_time = max(all_times)
n_frames = int(max_time / RESOLUTION) + 1

def build_frame_labels(segments, speaker_key, n_frames, resolution):
    frames = [set() for _ in range(n_frames)]
    for seg in segments:
        start_frame = int(seg["start"] / resolution)
        end_frame = int(seg["end"] / resolution)
        spk = seg[speaker_key]
        for f in range(start_frame, min(end_frame, n_frames)):
            frames[f].add(spk)
    return frames

def compute_der(vx_segments, gt_segments, n_frames, label=""):
    gt_frames = build_frame_labels(gt_segments, "speaker", n_frames, RESOLUTION)
    vx_frames = build_frame_labels(vx_segments, "speaker_id", n_frames, RESOLUTION)

    # Build co-occurrence for mapping
    cooccurrence = Counter()
    for f in range(n_frames):
        for gt_spk in gt_frames[f]:
            for vx_spk in vx_frames[f]:
                cooccurrence[(vx_spk, gt_spk)] += 1

    vx_speakers = sorted({s["speaker_id"] for s in vx_segments})
    gt_speakers = sorted({s["speaker"] for s in gt_segments})

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

    total_gt_speech = 0
    missed_speech = 0
    false_alarm = 0
    speaker_confusion = 0

    for f in range(n_frames):
        gt_set = gt_frames[f]
        vx_set = vx_frames[f]
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

    der = (missed_speech + false_alarm + speaker_confusion) / total_gt_speech if total_gt_speech > 0 else 0
    return {
        "label": label,
        "num_speakers": len(vx_speakers),
        "der": der,
        "missed": missed_speech * RESOLUTION,
        "false_alarm": false_alarm * RESOLUTION,
        "confusion": speaker_confusion * RESOLUTION,
        "total_gt": total_gt_speech * RESOLUTION,
        "mapping": mapping,
    }


# --- Strategy: merge speakers that never overlap and map to the same GT speaker ---

print("=== DER with Speaker Merging — AMI Meeting ===\n")

# Step 1: Find which voxtral speakers co-occur (overlap in time)
vx_speakers = sorted({s["speaker_id"] for s in vx_segments})
vx_frames = build_frame_labels(vx_segments, "speaker_id", n_frames, RESOLUTION)

# Build overlap matrix
overlaps = defaultdict(float)
for f in range(n_frames):
    spks = list(vx_frames[f])
    for i in range(len(spks)):
        for j in range(i + 1, len(spks)):
            key = tuple(sorted([spks[i], spks[j]]))
            overlaps[key] += RESOLUTION

# Build speech duration per speaker
speech_dur = defaultdict(float)
for f in range(n_frames):
    for spk in vx_frames[f]:
        speech_dur[spk] += RESOLUTION

print("Voxtral speaker durations:")
for spk in vx_speakers:
    print(f"  {spk:>12}: {speech_dur[spk]:.1f}s")

# Step 2: Merge speakers that never overlap (or overlap very little)
# Use union-find to group them
OVERLAP_THRESHOLD = 1.0  # seconds — allow up to 1s overlap for merging

# First compute baseline DER
baseline = compute_der(vx_segments, gt_segments, n_frames, "Baseline (no merging)")

# Use the baseline mapping to identify which voxtral speakers map to the same GT speaker
gt_groups = defaultdict(list)
for vx_spk, gt_spk in baseline["mapping"].items():
    if gt_spk:
        gt_groups[gt_spk].append(vx_spk)

print(f"\nSpeakers mapping to same GT speaker:")
merge_map = {}
for gt_spk, vx_spks in gt_groups.items():
    if len(vx_spks) > 1:
        # Check if they can be merged (low overlap between them)
        can_merge = True
        for i in range(len(vx_spks)):
            for j in range(i + 1, len(vx_spks)):
                key = tuple(sorted([vx_spks[i], vx_spks[j]]))
                overlap = overlaps.get(key, 0)
                if overlap > OVERLAP_THRESHOLD:
                    can_merge = False
        if can_merge:
            canonical = vx_spks[0]
            print(f"  {gt_spk}: {vx_spks} -> merging into {canonical} (low overlap)")
            for spk in vx_spks:
                merge_map[spk] = canonical
        else:
            print(f"  {gt_spk}: {vx_spks} -> NOT merging (overlap too high)")
    else:
        merge_map[vx_spks[0]] = vx_spks[0]

# For unmapped speakers, keep original
for spk in vx_speakers:
    if spk not in merge_map:
        # Check if any group could take it
        merge_map[spk] = spk

# Apply merging
merged_segments = []
for seg in vx_segments:
    merged_segments.append({
        **seg,
        "speaker_id": merge_map.get(seg["speaker_id"], seg["speaker_id"]),
    })

merged = compute_der(merged_segments, gt_segments, n_frames, "After merging")

# Print comparison
print(f"\n{'':40} {'Baseline':>12} {'Merged':>12} {'Change':>10}")
print("-" * 78)
print(f"{'Speakers detected':<40} {baseline['num_speakers']:>12} {merged['num_speakers']:>12}")
print(f"{'Missed speech (s)':<40} {baseline['missed']:>11.1f}s {merged['missed']:>11.1f}s")
print(f"{'False alarm (s)':<40} {baseline['false_alarm']:>11.1f}s {merged['false_alarm']:>11.1f}s")
print(f"{'Speaker confusion (s)':<40} {baseline['confusion']:>11.1f}s {merged['confusion']:>11.1f}s")
print(f"{'DER':<40} {baseline['der']:>11.1%} {merged['der']:>11.1%} {(merged['der']-baseline['der'])/baseline['der']*100:>+9.1f}%")
print(f"\nDER: {baseline['der']:.1%} -> {merged['der']:.1%}")
