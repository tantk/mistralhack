"""
Test the transcription service (POST /api/transcribe).

Sends audio files from data/audio_samples/ to the service,
compares output against reference text, and computes WER.

Uses:
  - People's Speech samples (sample_00..09.flac) with references from archive/transcriptions.json
  - AMI segments (ami_wer_00..09.flac) with references from archive/ami_evaluation.json

Results saved to test/transcription_results.json
"""
import json
import os
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))
from metrics import compute_wer, compute_wer_batch, normalize_text

SERVICE_URL = os.environ.get("SERVICE_URL", "https://tan.tail2e1adb.ts.net/api/transcribe")
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
AUDIO_DIR = os.path.join(PROJECT_ROOT, "data", "audio_samples")


def transcribe_file(filepath):
    """Send an audio file to the transcription service."""
    with open(filepath, "rb") as f:
        resp = requests.post(SERVICE_URL, files={"audio": f}, timeout=120)
    resp.raise_for_status()
    return resp.json()["text"]


def load_peoples_speech_refs():
    """Load reference transcriptions from archive/transcriptions.json."""
    path = os.path.join(PROJECT_ROOT, "archive", "transcriptions.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    return {r["file"]: r["reference"] for r in data}


def load_ami_refs():
    """Load AMI reference transcriptions from archive/ami_evaluation.json."""
    path = os.path.join(PROJECT_ROOT, "archive", "ami_evaluation.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    return {s["file"]: s["reference"] for s in data["wer"]["samples"]}


def evaluate_set(name, files_and_refs):
    """Evaluate a set of audio files against references."""
    print(f"\n{'=' * 70}")
    print(f"Transcription Test: {name}")
    print(f"{'=' * 70}")
    print(f"Service: {SERVICE_URL}\n")

    print(f"{'File':<20} {'WER':>8} {'CER':>8} {'Time':>7}  Transcription")
    print("-" * 80)

    references = []
    hypotheses = []
    per_file = []

    for filename, ref_text in files_and_refs:
        filepath = os.path.join(AUDIO_DIR, filename)
        if not os.path.exists(filepath):
            print(f"{filename:<20} SKIPPED (file not found)")
            continue

        t0 = time.time()
        hyp_text = transcribe_file(filepath)
        elapsed = time.time() - t0

        m = compute_wer(ref_text, hyp_text)

        print(f"{filename:<20} {m['norm_wer']:>7.1%} {m['norm_cer']:>7.1%} {elapsed:>6.1f}s  {hyp_text[:45]}")

        references.append(ref_text)
        hypotheses.append(hyp_text)
        per_file.append({
            "file": filename,
            "reference": ref_text,
            "hypothesis": hyp_text,
            "norm_wer": round(m["norm_wer"], 4),
            "norm_cer": round(m["norm_cer"], 4),
            "elapsed_s": round(elapsed, 2),
        })

    if not references:
        print("No files evaluated.")
        return None

    overall = compute_wer_batch(references, hypotheses)
    print("-" * 80)
    print(f"{'OVERALL':<20} {overall['norm_wer']:>7.1%} {overall['norm_cer']:>7.1%}")
    print(f"  Hits: {overall['hits']}  Sub: {overall['substitutions']}  "
          f"Del: {overall['deletions']}  Ins: {overall['insertions']}")

    return {
        "name": name,
        "service_url": SERVICE_URL,
        "num_files": len(per_file),
        "overall_wer": round(overall["norm_wer"], 4),
        "overall_cer": round(overall["norm_cer"], 4),
        "per_file": per_file,
    }


def main():
    all_results = {}

    # 1. People's Speech samples
    ps_refs = load_peoples_speech_refs()
    if ps_refs:
        ps_files = [(f, ps_refs[f]) for f in sorted(ps_refs) if os.path.exists(os.path.join(AUDIO_DIR, f))]
        if ps_files:
            result = evaluate_set("People's Speech (10 samples)", ps_files)
            if result:
                all_results["peoples_speech"] = result

    # 2. AMI segments
    ami_refs = load_ami_refs()
    if ami_refs:
        ami_files = [(f, ami_refs[f]) for f in sorted(ami_refs) if os.path.exists(os.path.join(AUDIO_DIR, f))]
        if ami_files:
            result = evaluate_set("AMI Meeting Segments (10 segments)", ami_files)
            if result:
                all_results["ami"] = result

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for key, res in all_results.items():
        print(f"  {res['name']}:")
        print(f"    WER: {res['overall_wer']:.1%}  |  CER: {res['overall_cer']:.1%}  |  Files: {res['num_files']}")
    print()

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), "transcription_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
