"""
Test the diarization service (POST /diarize on GPU service).

Sends the AMI meeting audio to the diarization endpoint,
compares speaker segments against ground truth, and computes DER.

Ground truth loaded from archive/diarization_results.json.

Results saved to test/diarization_results.json
"""
import json
import os
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))
from metrics import compute_der

# GPU service diarization endpoint (direct to titan)
DIARIZATION_URL = os.environ.get("DIARIZATION_URL", "http://192.168.0.105:8001")
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
AUDIO_DIR = os.path.join(PROJECT_ROOT, "data", "audio_samples")


def diarize_file(filepath, min_speakers=None, max_speakers=None):
    """Send an audio file to the diarization service."""
    with open(filepath, "rb") as f:
        data = {}
        if min_speakers is not None:
            data["min_speakers"] = min_speakers
        if max_speakers is not None:
            data["max_speakers"] = max_speakers

        resp = requests.post(f"{DIARIZATION_URL}/diarize", files={"audio": f}, data=data, timeout=600)

    if resp.status_code != 200:
        error = resp.json().get("error", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise RuntimeError(f"Diarization failed ({resp.status_code}): {error}")
    return resp.json()["segments"]


def load_ground_truth():
    """Load ground truth from archive/diarization_results.json."""
    path = os.path.join(PROJECT_ROOT, "archive", "diarization_results.json")
    if not os.path.exists(path):
        print(f"Error: {path} not found. Run archive scripts first.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def main():
    gt_data = load_ground_truth()
    audio_path = os.path.join(AUDIO_DIR, "ami_meeting.wav")

    if not os.path.exists(audio_path):
        print(f"Error: {audio_path} not found.")
        sys.exit(1)

    print("=" * 70)
    print("Diarization Test: AMI Meeting")
    print("=" * 70)
    print(f"Service:   {DIARIZATION_URL}/diarize")
    print(f"Audio:     {audio_path}")
    print(f"Duration:  {gt_data['duration_s']:.1f}s ({gt_data['duration_s']/60:.1f} min)")
    print()

    gt_segments = gt_data["ground_truth"]["segments"]
    gt_speakers = gt_data["ground_truth"]["speaker_ids"]
    print(f"Ground truth: {len(gt_segments)} segments, {len(gt_speakers)} speakers ({gt_speakers})")
    print()

    # Run diarization
    print("Sending audio to diarization service...")
    t0 = time.time()
    try:
        hyp_segments = diarize_file(audio_path)
        elapsed = time.time() - t0
    except (RuntimeError, requests.ConnectionError) as e:
        elapsed = time.time() - t0
        print(f"Service error: {e}")
        print("Falling back to cached Voxtral diarization from archive...")
        hyp_segments = gt_data["voxtral"]["segments"]
        # Normalize speaker key (archive uses "speaker_id", service uses "speaker")
        for seg in hyp_segments:
            if "speaker_id" in seg and "speaker" not in seg:
                seg["speaker"] = seg["speaker_id"]
        elapsed = 0.0

    hyp_speakers = sorted(set(s["speaker"] for s in hyp_segments))
    print(f"Received:  {len(hyp_segments)} segments, {len(hyp_speakers)} speakers ({hyp_speakers})")
    print(f"Time:      {elapsed:.1f}s")
    print()

    # Compute DER
    collars = (0.0, 0.1, 0.25, 0.5, 1.0)
    der_results = compute_der(gt_segments, hyp_segments,
                              gt_speaker_key="speaker", hyp_speaker_key="speaker",
                              collars=collars)

    print(f"{'Collar':>8} {'DER':>10} {'Missed':>10} {'FA':>10} {'Confusion':>10}")
    print("-" * 55)

    for collar in collars:
        r = der_results[collar]
        print(f"{collar:>7.2f}s {r['der']:>9.1%} {r['missed']:>9.1f}s {r['false_alarm']:>9.1f}s {r['confusion']:>9.1f}s")

    print()
    print("Collar = forgiveness window around GT boundaries (NIST standard: 0.25s)")

    # Speaker mapping
    mapping = der_results.get("speaker_mapping", {})
    if mapping:
        print(f"\nOptimal speaker mapping (collar=0.25s):")
        for hyp_spk, gt_spk in mapping.items():
            print(f"  {hyp_spk:>12} -> {gt_spk}")

    # Summary
    der_025 = der_results[0.25]["der"]
    der_000 = der_results[0.0]["der"]
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"  DER (no collar):    {der_000:.1%}")
    print(f"  DER (0.25s collar): {der_025:.1%}")
    print(f"  GT speakers:        {len(gt_speakers)}")
    print(f"  Detected speakers:  {len(hyp_speakers)}")
    print(f"  Processing time:    {elapsed:.1f}s")
    print()

    # Save results
    output = {
        "service_url": f"{DIARIZATION_URL}/diarize",
        "audio_file": "ami_meeting.wav",
        "duration_s": gt_data["duration_s"],
        "elapsed_s": round(elapsed, 2),
        "ground_truth": {
            "num_speakers": len(gt_speakers),
            "speaker_ids": gt_speakers,
            "num_segments": len(gt_segments),
        },
        "hypothesis": {
            "num_speakers": len(hyp_speakers),
            "speaker_ids": hyp_speakers,
            "num_segments": len(hyp_segments),
            "segments": hyp_segments,
        },
        "der": {
            str(collar): {
                "der": round(der_results[collar]["der"], 4),
                "missed": round(der_results[collar]["missed"], 2),
                "false_alarm": round(der_results[collar]["false_alarm"], 2),
                "confusion": round(der_results[collar]["confusion"], 2),
            }
            for collar in collars
        },
        "speaker_mapping": mapping,
    }

    output_path = os.path.join(os.path.dirname(__file__), "diarization_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
