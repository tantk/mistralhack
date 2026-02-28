"""Compute DER with collar tolerance — standard practice in diarization evaluation."""
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

def build_collar_mask(segments, collar_s, n_frames, resolution):
    """Mark frames near segment boundaries as 'forgiven' (not scored)."""
    collar_frames = int(collar_s / resolution)
    mask = [False] * n_frames
    for seg in segments:
        # Mark frames around start boundary
        start_frame = int(seg["start"] / resolution)
        for f in range(max(0, start_frame - collar_frames), min(n_frames, start_frame + collar_frames)):
            mask[f] = True
        # Mark frames around end boundary
        end_frame = int(seg["end"] / resolution)
        for f in range(max(0, end_frame - collar_frames), min(n_frames, end_frame + collar_frames)):
            mask[f] = True
    return mask

def compute_der_with_collar(gt_segments, vx_segments, collar_s, n_frames):
    gt_frames = build_frame_labels(gt_segments, "speaker", n_frames, RESOLUTION)
    vx_frames = build_frame_labels(vx_segments, "speaker_id", n_frames, RESOLUTION)
    collar_mask = build_collar_mask(gt_segments, collar_s, n_frames, RESOLUTION)

    # Build mapping
    cooccurrence = Counter()
    for f in range(n_frames):
        if collar_mask[f]:
            continue
        for gt_spk in gt_frames[f]:
            for vx_spk in vx_frames[f]:
                cooccurrence[(vx_spk, gt_spk)] += 1

    vx_speakers = sorted({s["speaker_id"] for s in vx_segments})
    gt_speakers = sorted({s["speaker"] for s in gt_segments})

    mapping = {}
    for vx_spk in vx_speakers:
        best_gt, best_count = None, 0
        for gt_spk in gt_speakers:
            count = cooccurrence.get((vx_spk, gt_spk), 0)
            if count > best_count:
                best_count = count
                best_gt = gt_spk
        mapping[vx_spk] = best_gt

    total_gt = 0
    missed = 0
    false_alarm = 0
    confusion = 0

    for f in range(n_frames):
        if collar_mask[f]:
            continue

        gt_set = gt_frames[f]
        vx_set = vx_frames[f]
        vx_mapped = {mapping.get(s) for s in vx_set} - {None}

        if gt_set:
            total_gt += len(gt_set)
            for spk in gt_set:
                if not vx_set:
                    missed += 1
                elif spk not in vx_mapped:
                    confusion += 1

        if vx_set and not gt_set:
            false_alarm += len(vx_set)

    der = (missed + false_alarm + confusion) / total_gt if total_gt > 0 else 0
    return {
        "collar": collar_s,
        "der": der,
        "missed": missed * RESOLUTION,
        "false_alarm": false_alarm * RESOLUTION,
        "confusion": confusion * RESOLUTION,
        "total_gt": total_gt * RESOLUTION,
    }

print("=== DER with Collar Tolerance — AMI Meeting ===\n")
print(f"Collar = forgiveness window around GT segment boundaries (standard: 0.25s)\n")
print(f"{'Collar':>8} {'Missed':>10} {'FA':>10} {'Confusion':>10} {'DER':>10}")
print("-" * 55)

for collar in [0.0, 0.1, 0.25, 0.5, 1.0]:
    r = compute_der_with_collar(gt_segments, vx_segments, collar, n_frames)
    print(f"{collar:>7.2f}s {r['missed']:>9.1f}s {r['false_alarm']:>9.1f}s "
          f"{r['confusion']:>9.1f}s {r['der']:>9.1%}")

print(f"\nNote: 0.25s collar is the standard in NIST evaluations.")
print(f"It forgives timing errors within 250ms of segment boundaries.")
