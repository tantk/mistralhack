"""
Evaluate Voxtral transcription and diarization quality.

Metrics:
  - WER (Word Error Rate): measures transcription accuracy
  - DER (Diarization Error Rate): measures speaker attribution accuracy

Uses:
  - jiwer for WER computation
  - pyannote.metrics for DER computation (NIST standard)
"""
import json
from jiwer import wer, cer, process_words
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate

# ============================================================
# 1. WER — Word Error Rate (People's Speech transcriptions)
# ============================================================
#
# WER = (S + D + I) / N
#
#   S = substitutions (wrong word)
#   D = deletions     (word in reference but not in hypothesis)
#   I = insertions    (word in hypothesis but not in reference)
#   N = total words in reference
#
# Lower is better. 0% = perfect.
#
# Text normalization applied:
#   - lowercase
#   - remove punctuation
#   - normalize number words to digits ("twenty one" -> "21")

import re

WORD_TO_NUM = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    "million": "1000000",
}

def convert_number_words(parts):
    total = 0
    current = 0
    for p in parts:
        val = int(WORD_TO_NUM[p])
        if val == 100:
            current = (current if current else 1) * 100
        elif val == 1000:
            current = (current if current else 1) * 1000
            total += current
            current = 0
        elif val == 1000000:
            current = (current if current else 1) * 1000000
            total += current
            current = 0
        elif val >= 10 and val <= 90 and val % 10 == 0:
            current += val
        else:
            current += val
    total += current
    return str(total)

def normalize_text(text):
    t = text.lower().strip()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'\bpoint\s+(\w+)', lambda m: f"0.{WORD_TO_NUM.get(m.group(1), m.group(1))}", t)
    words = t.split()
    normalized = []
    i = 0
    while i < len(words):
        if words[i] in WORD_TO_NUM:
            num_parts = []
            while i < len(words) and words[i] in WORD_TO_NUM:
                num_parts.append(words[i])
                i += 1
            normalized.append(convert_number_words(num_parts))
        else:
            normalized.append(words[i])
            i += 1
    return ' '.join(normalized)


def compute_wer_report(transcriptions_path):
    with open(transcriptions_path) as f:
        results = json.load(f)

    print("=" * 70)
    print("WER (Word Error Rate) — People's Speech + Voxtral")
    print("=" * 70)
    print()
    print(f"{'File':<20} {'Raw WER':>8} {'Norm WER':>9} {'Norm CER':>9}  {'H':>3} {'S':>3} {'D':>3} {'I':>3}")
    print("-" * 70)

    all_refs_raw, all_hyps_raw = [], []
    all_refs_norm, all_hyps_norm = [], []

    for r in results:
        ref_raw = r["reference"].lower().strip()
        hyp_raw = r["voxtral"].lower().strip()
        ref_norm = normalize_text(r["reference"])
        hyp_norm = normalize_text(r["voxtral"])

        raw_w = wer(ref_raw, hyp_raw)
        norm_w = wer(ref_norm, hyp_norm)
        norm_c = cer(ref_norm, hyp_norm)
        detail = process_words(ref_norm, hyp_norm)

        print(f"{r['file']:<20} {raw_w:>7.1%} {norm_w:>8.1%} {norm_c:>8.1%}  "
              f"{detail.hits:>3} {detail.substitutions:>3} {detail.deletions:>3} {detail.insertions:>3}")

        all_refs_raw.append(ref_raw)
        all_hyps_raw.append(hyp_raw)
        all_refs_norm.append(ref_norm)
        all_hyps_norm.append(hyp_norm)

    raw_overall = wer(all_refs_raw, all_hyps_raw)
    norm_overall = wer(all_refs_norm, all_hyps_norm)
    norm_cer_overall = cer(all_refs_norm, all_hyps_norm)
    overall_detail = process_words(all_refs_norm, all_hyps_norm)

    print("-" * 70)
    print(f"{'OVERALL':<20} {raw_overall:>7.1%} {norm_overall:>8.1%} {norm_cer_overall:>8.1%}  "
          f"{overall_detail.hits:>3} {overall_detail.substitutions:>3} "
          f"{overall_detail.deletions:>3} {overall_detail.insertions:>3}")
    print()
    return {"raw_wer": raw_overall, "norm_wer": norm_overall, "norm_cer": norm_cer_overall}


# ============================================================
# 2. DER — Diarization Error Rate (AMI meeting + Voxtral)
# ============================================================
#
# DER = (missed + false_alarm + confusion) / total_gt_speech
#
#   missed speech     = GT has speech, system has nothing
#   false alarm       = GT has no speech, system detects speech
#   speaker confusion = both have speech, but wrong speaker
#
# Collar: forgiveness window around GT segment boundaries.
#   Standard NIST collar = 0.25s. Forgives small timing errors.
#
# Lower is better. 0% = perfect.
#
# Computed using pyannote.metrics (reference implementation).

def build_pyannote_annotation(segments, speaker_key):
    """Convert segment list to pyannote Annotation."""
    ann = Annotation()
    for seg in segments:
        ann[Segment(seg["start"], seg["end"])] = seg[speaker_key]
    return ann


def compute_der_report(diarization_path):
    with open(diarization_path) as f:
        data = json.load(f)

    gt_segments = data["ground_truth"]["segments"]
    vx_segments = data["voxtral"]["segments"]

    # Build pyannote annotations
    reference = build_pyannote_annotation(gt_segments, "speaker")
    hypothesis = build_pyannote_annotation(vx_segments, "speaker_id")

    print("=" * 70)
    print("DER (Diarization Error Rate) — AMI Meeting + Voxtral")
    print("  Computed with pyannote.metrics (NIST-standard)")
    print("=" * 70)
    print()

    gt_speakers = sorted(data["ground_truth"]["speaker_ids"])
    vx_speakers = sorted(data["voxtral"]["speaker_ids"])
    duration = data["duration_s"]

    print(f"Meeting duration:  {duration:.1f}s ({duration/60:.1f} min)")
    print(f"GT speakers:       {len(gt_speakers)} — {gt_speakers}")
    print(f"Voxtral speakers:  {len(vx_speakers)} — {vx_speakers}")
    print(f"GT segments:       {len(gt_segments)}")
    print(f"Voxtral segments:  {len(vx_segments)}")
    print()

    # Compute DER at different collar values
    print(f"{'Collar':>8} {'DER':>10} {'Missed':>10} {'FA':>10} {'Confusion':>10}")
    print("-" * 55)

    results = {}
    for collar in [0.0, 0.1, 0.25, 0.5, 1.0]:
        metric = DiarizationErrorRate(collar=collar, skip_overlap=False)
        der_val = metric(reference, hypothesis)
        components = metric.compute_components(reference, hypothesis)

        missed = components["missed detection"]
        fa = components["false alarm"]
        confusion = components["confusion"]
        total = components["total"]

        print(f"{collar:>7.2f}s {der_val:>9.1%} {missed:>9.1f}s {fa:>9.1f}s {confusion:>9.1f}s")

        if collar == 0.25:
            results["der_025"] = der_val
        if collar == 0.0:
            results["der_000"] = der_val

    print()
    print("Collar = forgiveness window around GT boundaries (NIST standard: 0.25s)")
    print()

    # Also compute with skip_overlap=True (ignore overlapping speech regions)
    print("--- With overlapping speech excluded ---")
    print(f"{'Collar':>8} {'DER':>10}")
    print("-" * 20)
    for collar in [0.0, 0.25]:
        metric = DiarizationErrorRate(collar=collar, skip_overlap=True)
        der_val = metric(reference, hypothesis)
        label = " (standard)" if collar == 0.25 else ""
        print(f"{collar:>7.2f}s {der_val:>9.1%}{label}")
    print()

    # Show optimal speaker mapping from pyannote
    metric = DiarizationErrorRate(collar=0.25, skip_overlap=False)
    metric(reference, hypothesis)
    mapping = metric.optimal_mapping(reference, hypothesis)
    print("Optimal speaker mapping (pyannote, collar=0.25s):")
    for vx_spk, gt_spk in sorted(mapping.items()):
        print(f"  {vx_spk:>12} -> {gt_spk}")
    print()

    return results


# ============================================================
# 3. Run both evaluations
# ============================================================

if __name__ == "__main__":
    wer_results = compute_wer_report("transcriptions.json")
    print()
    der_results = compute_der_report("diarization_results.json")

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print(f"  Transcription (WER):")
    print(f"    Raw WER:        {wer_results['raw_wer']:.1%}")
    print(f"    Normalized WER: {wer_results['norm_wer']:.1%}")
    print(f"    Normalized CER: {wer_results['norm_cer']:.1%}")
    print()
    print(f"  Diarization (DER, pyannote.metrics):")
    print(f"    DER (no collar):    {der_results['der_000']:.1%}")
    print(f"    DER (0.25s collar): {der_results['der_025']:.1%}")
    print()
