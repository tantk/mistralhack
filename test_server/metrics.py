"""
Shared WER and DER computation utilities.

WER (Word Error Rate) = (S + D + I) / N
  S = substitutions, D = deletions, I = insertions, N = reference word count

DER (Diarization Error Rate) = (missed + false_alarm + confusion) / total_gt_speech
  Computed with pyannote.metrics (NIST standard)
"""
import re
from jiwer import wer, cer, process_words
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate


# ── Text normalization for WER ──

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


def _convert_number_words(parts):
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
        elif 10 <= val <= 90 and val % 10 == 0:
            current += val
        else:
            current += val
    total += current
    return str(total)


def normalize_text(text):
    """Normalize text for WER comparison: lowercase, remove punctuation, number words to digits."""
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
            normalized.append(_convert_number_words(num_parts))
        else:
            normalized.append(words[i])
            i += 1
    return ' '.join(normalized)


def compute_wer(reference, hypothesis):
    """Compute WER between two strings (with normalization).

    Returns dict with raw_wer, norm_wer, norm_cer, and detail counts.
    """
    ref_raw = reference.lower().strip()
    hyp_raw = hypothesis.lower().strip()
    ref_norm = normalize_text(reference)
    hyp_norm = normalize_text(hypothesis)

    detail = process_words(ref_norm, hyp_norm)

    return {
        "raw_wer": wer(ref_raw, hyp_raw),
        "norm_wer": wer(ref_norm, hyp_norm),
        "norm_cer": cer(ref_norm, hyp_norm),
        "hits": detail.hits,
        "substitutions": detail.substitutions,
        "deletions": detail.deletions,
        "insertions": detail.insertions,
    }


def compute_wer_batch(references, hypotheses):
    """Compute overall WER across multiple reference/hypothesis pairs."""
    refs_norm = [normalize_text(r) for r in references]
    hyps_norm = [normalize_text(h) for h in hypotheses]

    detail = process_words(refs_norm, hyps_norm)
    return {
        "norm_wer": wer(refs_norm, hyps_norm),
        "norm_cer": cer(refs_norm, hyps_norm),
        "hits": detail.hits,
        "substitutions": detail.substitutions,
        "deletions": detail.deletions,
        "insertions": detail.insertions,
    }


# ── DER computation ──

def build_annotation(segments, speaker_key="speaker"):
    """Convert a list of segment dicts to a pyannote Annotation."""
    ann = Annotation()
    for seg in segments:
        ann[Segment(seg["start"], seg["end"])] = seg[speaker_key]
    return ann


def compute_der(gt_segments, hyp_segments, gt_speaker_key="speaker", hyp_speaker_key="speaker",
                collars=(0.0, 0.25, 0.5)):
    """Compute DER at multiple collar values.

    Returns dict keyed by collar value with DER and components.
    """
    reference = build_annotation(gt_segments, gt_speaker_key)
    hypothesis = build_annotation(hyp_segments, hyp_speaker_key)

    results = {}
    for collar in collars:
        metric = DiarizationErrorRate(collar=collar, skip_overlap=False)
        der_val = metric(reference, hypothesis)
        components = metric.compute_components(reference, hypothesis)

        results[collar] = {
            "der": der_val,
            "missed": components["missed detection"],
            "false_alarm": components["false alarm"],
            "confusion": components["confusion"],
            "total": components["total"],
        }

    # Optimal speaker mapping at collar=0.25s
    metric = DiarizationErrorRate(collar=0.25, skip_overlap=False)
    metric(reference, hypothesis)
    mapping = metric.optimal_mapping(reference, hypothesis)
    results["speaker_mapping"] = {k: v for k, v in sorted(mapping.items())}

    return results
