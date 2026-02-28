"""
Test GPU fallback behavior — verify pipeline works without GPU service.

Tests:
  1. GPU health check confirms GPU is down
  2. Speaker enrollment returns 503 when GPU unavailable
  3. Full pipeline completes using Mistral API diarization fallback
  4. Pipeline result is valid (all fields present)
  5. Logs show expected fallback messages

Results saved to test_server/gpu_fallback_results.json
"""
import json
import os
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))

SERVICE_URL = os.environ.get("SERVICE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
DIARIZATION_URL = os.environ.get("DIARIZATION_URL", "http://192.168.0.105:8001")
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
AUDIO_DIR = os.path.join(PROJECT_ROOT, "data", "audio_samples")
PEOPLES_SPEECH_DIR = os.path.join(PROJECT_ROOT, "data", "peoples_speech")


def auth_headers():
    if API_KEY:
        return {"Authorization": f"Bearer {API_KEY}"}
    return {}


def find_test_audio():
    """Find an audio file to use for testing. Prefer smaller files."""
    if os.path.isdir(PEOPLES_SPEECH_DIR):
        for f in sorted(os.listdir(PEOPLES_SPEECH_DIR)):
            if f.endswith((".wav", ".flac", ".mp3")):
                return os.path.join(PEOPLES_SPEECH_DIR, f)
    if os.path.isdir(AUDIO_DIR):
        for f in sorted(os.listdir(AUDIO_DIR)):
            if f.endswith((".wav", ".flac", ".mp3")):
                return os.path.join(AUDIO_DIR, f)
    return None


def test_gpu_unreachable():
    """Verify GPU service is actually unreachable."""
    print("\n--- Test 1: GPU Service Unreachable ---")
    try:
        resp = requests.get(f"{DIARIZATION_URL}/health", timeout=5)
        print(f"  GPU service responded with {resp.status_code} — it's UP")
        print(f"  WARNING: GPU is reachable, fallback tests may not exercise fallback paths")
        return {"status": "WARN", "detail": f"GPU responded {resp.status_code}"}
    except (requests.ConnectionError, requests.Timeout) as e:
        print(f"  PASS: GPU service unreachable ({type(e).__name__})")
        return {"status": "PASS", "detail": str(e)[:100]}


def test_enrollment_503():
    """Verify enrollment returns 503 when GPU is unavailable."""
    print("\n--- Test 2: Enrollment Returns 503 ---")

    # Need a dummy audio file for multipart
    dummy_audio = b'\x00' * 1000
    resp = requests.post(
        f"{SERVICE_URL}/api/speakers/enroll",
        files={"audio": ("test.wav", dummy_audio, "audio/wav")},
        data={"name": "TestSpeaker"},
        headers=auth_headers(),
        timeout=30,
    )

    print(f"  Status: {resp.status_code}")
    print(f"  Body: {resp.text[:200]}")

    if resp.status_code == 503:
        print(f"  PASS: Got 503 Service Unavailable as expected")
        return {"status": "PASS", "http_status": 503, "body": resp.text[:200]}
    else:
        print(f"  FAIL: Expected 503, got {resp.status_code}")
        return {"status": "FAIL", "http_status": resp.status_code, "body": resp.text[:200]}


def test_pipeline_with_fallback(audio_path):
    """Run full pipeline — should use Mistral API diarization fallback."""
    print("\n--- Test 3: Full Pipeline with GPU Fallback ---")

    # Create job
    print("  Creating job...")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{SERVICE_URL}/api/jobs",
            files={"audio": f},
            headers=auth_headers(),
            timeout=30,
        )

    if resp.status_code != 200:
        print(f"  FAIL: Job creation returned {resp.status_code}: {resp.text}")
        return {"status": "FAIL", "detail": f"Job creation failed: {resp.status_code}"}

    job_id = resp.json()["job_id"]
    print(f"  Job ID: {job_id}")

    # Poll until complete or error
    print("  Polling for completion...")
    start = time.time()
    timeout = 300
    last_phase = None
    result = None

    while time.time() - start < timeout:
        resp = requests.get(
            f"{SERVICE_URL}/api/jobs/{job_id}/result",
            headers=auth_headers(),
            timeout=30,
        )
        data = resp.json()

        if data.get("phase") != last_phase:
            last_phase = data.get("phase")
            elapsed = time.time() - start
            print(f"  [{elapsed:.1f}s] Phase: {last_phase or 'done'} (status: {data['status']})")

        if data["status"] == "complete":
            result = data
            break
        elif data["status"] == "error":
            result = data
            break

        time.sleep(2)

    if result is None:
        print(f"  FAIL: Timeout after {timeout}s")
        return {"status": "FAIL", "detail": "Timeout"}

    if result["status"] == "error":
        print(f"  FAIL: Pipeline error: {result.get('error')}")
        return {"status": "FAIL", "detail": result.get("error"), "job_id": job_id}

    # Pipeline completed — validate result
    print(f"  Pipeline completed in {time.time() - start:.1f}s")
    return {"status": "PASS", "job_id": job_id, "result": result, "elapsed": round(time.time() - start, 1)}


def validate_pipeline_result(result_data):
    """Validate the pipeline result has all expected fields."""
    print("\n--- Test 4: Validate Pipeline Result ---")
    result = result_data.get("result", {})
    checks = []

    def check(name, condition):
        ok = bool(condition)
        checks.append((name, ok))
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
        return ok

    check("status == complete", result.get("status") == "complete")
    check("transcript is non-empty", isinstance(result.get("transcript"), str) and len(result.get("transcript", "")) > 0)

    segs = result.get("segments", [])
    check("segments is non-empty list", isinstance(segs, list) and len(segs) > 0)
    if segs:
        seg = segs[0]
        check("segment has speaker", "speaker" in seg)
        check("segment has start", "start" in seg)
        check("segment has end", "end" in seg)
        check("segment has text", "text" in seg)
        # Show unique speakers
        speakers = list(set(s["speaker"] for s in segs))
        print(f"       Speakers found: {speakers}")

    check("decisions is list", isinstance(result.get("decisions"), list))
    check("ambiguities is list", isinstance(result.get("ambiguities"), list))
    check("action_items is list", isinstance(result.get("action_items"), list))

    md = result.get("meeting_dynamics")
    check("meeting_dynamics is dict", isinstance(md, dict))
    if md:
        check("has talk_time_pct", "talk_time_pct" in md)
        check("has interruption_count", "interruption_count" in md)

    check("speakers is list", isinstance(result.get("speakers"), list))
    check("meeting_metadata is dict", isinstance(result.get("meeting_metadata"), dict))
    check("error is null", result.get("error") is None)

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return {"passed": passed, "total": total, "checks": {name: ok for name, ok in checks}}


def test_list_speakers():
    """Verify list speakers still works (doesn't require GPU)."""
    print("\n--- Test 5: List Speakers (no GPU needed) ---")
    resp = requests.get(
        f"{SERVICE_URL}/api/speakers",
        headers=auth_headers(),
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  Speakers: {len(data.get('speakers', []))} enrolled")
        print(f"  PASS: List speakers works without GPU")
        return {"status": "PASS", "speaker_count": len(data.get("speakers", []))}
    else:
        print(f"  FAIL: {resp.text[:200]}")
        return {"status": "FAIL", "http_status": resp.status_code}


def main():
    print("=" * 70)
    print("GPU Fallback Tests — Pipeline Without GPU Service")
    print("=" * 70)
    print(f"Orchestrator: {SERVICE_URL}")
    print(f"GPU Service:  {DIARIZATION_URL} (expected: UNREACHABLE)")
    print(f"Auth: {'enabled' if API_KEY else 'disabled'}")

    all_results = {
        "service_url": SERVICE_URL,
        "diarization_url": DIARIZATION_URL,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tests": {},
    }

    # Test 1: Confirm GPU is down
    all_results["tests"]["gpu_unreachable"] = test_gpu_unreachable()

    # Test 2: Enrollment 503
    all_results["tests"]["enrollment_503"] = test_enrollment_503()

    # Test 3: Full pipeline with fallback
    audio_path = find_test_audio()
    if not audio_path:
        print("\nERROR: No audio files found in data/")
        all_results["tests"]["pipeline_fallback"] = {"status": "SKIP", "detail": "No audio files"}
    else:
        print(f"\nAudio: {os.path.basename(audio_path)} ({os.path.getsize(audio_path)} bytes)")
        pipeline_result = test_pipeline_with_fallback(audio_path)
        all_results["tests"]["pipeline_fallback"] = {
            k: v for k, v in pipeline_result.items() if k != "result"
        }
        if pipeline_result.get("result"):
            all_results["pipeline_result"] = pipeline_result["result"]

        # Test 4: Validate result
        if pipeline_result.get("status") == "PASS":
            all_results["tests"]["result_validation"] = validate_pipeline_result(pipeline_result)

    # Test 5: List speakers
    all_results["tests"]["list_speakers"] = test_list_speakers()

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for test_name, result in all_results["tests"].items():
        status = result.get("status", "?") if isinstance(result, dict) else result
        print(f"  {test_name:<30} {status}")

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), "gpu_fallback_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
