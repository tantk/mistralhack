"""
Test the GPU service voiceprint endpoints.

Endpoints tested:
  - POST /voiceprint/enroll   — enroll a speaker voiceprint
  - POST /voiceprint/identify — identify a speaker from audio
  - GET  /voiceprint/speakers — list enrolled speakers

Uses audio samples from data/audio_samples/ or data/peoples_speech/.

Results saved to test_server/voiceprint_results.json
"""
import json
import os
import sys
import time
import requests

GPU_SERVICE_URL = os.environ.get("DIARIZATION_URL", "http://192.168.0.105:8001")
ORCHESTRATOR_URL = os.environ.get("SERVICE_URL", "http://localhost:8000")
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
AUDIO_DIR = os.path.join(PROJECT_ROOT, "data", "audio_samples")
PEOPLES_SPEECH_DIR = os.path.join(PROJECT_ROOT, "data", "peoples_speech")


def find_audio_files(count=2):
    """Find audio files for testing (need at least 2 for enroll + identify)."""
    files = []
    for d in [AUDIO_DIR, PEOPLES_SPEECH_DIR]:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith((".wav", ".flac", ".mp3")):
                files.append(os.path.join(d, f))
                if len(files) >= count:
                    return files
    return files


def test_health():
    """Test GPU service health and check embedding backend."""
    print("\n--- Test: GPU Service Health ---")
    resp = requests.get(f"{GPU_SERVICE_URL}/health", timeout=10)
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"Health check failed: {resp.status_code}"

    data = resp.json()
    print(f"  GPU available: {data.get('gpu_available')}")
    print(f"  Embedding backend: {data.get('embedding_backend')}")
    return data


def test_enroll(audio_path, name):
    """Test POST /voiceprint/enroll — enroll a speaker."""
    print(f"\n--- Test: Enroll Speaker '{name}' ---")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{GPU_SERVICE_URL}/voiceprint/enroll",
            files={"audio": f},
            data={"name": name},
            timeout=60,
        )

    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"Enroll failed: {resp.status_code} {resp.text}"

    data = resp.json()
    assert "speaker_id" in data, f"Missing speaker_id: {data}"
    assert "name" in data, f"Missing name: {data}"
    assert data["name"] == name, f"Name mismatch: {data['name']} != {name}"

    print(f"  Speaker ID: {data['speaker_id']}")
    print(f"  Name: {data['name']}")
    return data


def test_list_speakers():
    """Test GET /voiceprint/speakers — list enrolled speakers."""
    print("\n--- Test: List Speakers ---")
    resp = requests.get(f"{GPU_SERVICE_URL}/voiceprint/speakers", timeout=10)
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"List failed: {resp.status_code}"

    data = resp.json()
    assert "speakers" in data, f"Missing speakers: {data}"

    speakers = data["speakers"]
    print(f"  Enrolled speakers: {len(speakers)}")
    for s in speakers:
        print(f"    - {s}")
    return data


def test_identify(audio_path, start_time=None, end_time=None):
    """Test POST /voiceprint/identify — identify a speaker from audio."""
    print("\n--- Test: Identify Speaker ---")
    form_data = {}
    if start_time is not None:
        form_data["start_time"] = str(start_time)
    if end_time is not None:
        form_data["end_time"] = str(end_time)

    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{GPU_SERVICE_URL}/voiceprint/identify",
            files={"audio": f},
            data=form_data,
            timeout=60,
        )

    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"Identify failed: {resp.status_code} {resp.text}"

    data = resp.json()
    assert "matches" in data, f"Missing matches: {data}"

    matches = data["matches"]
    print(f"  Matches: {len(matches)}")
    for m in matches:
        print(f"    - {m.get('name', '?')}: similarity={m.get('similarity', 0):.3f}")
    return data


def test_identify_with_time_range(audio_path):
    """Test identify with start_time and end_time slicing."""
    print("\n--- Test: Identify with Time Range ---")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{GPU_SERVICE_URL}/voiceprint/identify",
            files={"audio": f},
            data={"start_time": "0.0", "end_time": "5.0"},
            timeout=60,
        )

    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"Identify (sliced) failed: {resp.status_code} {resp.text}"

    data = resp.json()
    assert "matches" in data, f"Missing matches: {data}"
    print(f"  Matches (0-5s slice): {len(data['matches'])}")
    for m in data["matches"]:
        print(f"    - {m.get('name', '?')}: similarity={m.get('similarity', 0):.3f}")
    return data


def test_identify_no_enrollments(audio_path):
    """Test identify when no speakers are enrolled — should return empty matches."""
    print("\n--- Test: Identify with No Enrollments ---")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{GPU_SERVICE_URL}/voiceprint/identify",
            files={"audio": f},
            timeout=60,
        )

    print(f"  Status: {resp.status_code}")
    # Should still return 200 with empty matches, not an error
    if resp.status_code == 200:
        data = resp.json()
        print(f"  Matches: {len(data.get('matches', []))}")
        return data
    else:
        print(f"  Response: {resp.text[:200]}")
        return None


def test_orchestrator_enroll(audio_path, name):
    """Test POST /api/speakers/enroll on the Rust orchestrator."""
    print(f"\n--- Test: Orchestrator Enroll '{name}' ---")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{ORCHESTRATOR_URL}/api/speakers/enroll",
            files={"audio": f},
            data={"name": name},
            timeout=60,
        )
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"Enroll failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "speaker_id" in data, f"Missing speaker_id: {data}"
    print(f"  Speaker ID: {data['speaker_id']}")
    print(f"  Name: {data.get('name')}")
    return data


def test_orchestrator_list_speakers():
    """Test GET /api/speakers on the Rust orchestrator."""
    print("\n--- Test: Orchestrator List Speakers ---")
    resp = requests.get(f"{ORCHESTRATOR_URL}/api/speakers", timeout=10)
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"List failed: {resp.status_code}"
    data = resp.json()
    speakers = data.get("speakers", [])
    print(f"  Speakers: {len(speakers)}")
    for s in speakers:
        print(f"    - {s}")
    return data


def main():
    print("=" * 70)
    print("Voiceprint Endpoint Tests")
    print("=" * 70)
    print(f"GPU Service: {GPU_SERVICE_URL}")

    all_results = {
        "service_url": GPU_SERVICE_URL,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tests": {},
    }

    # 1. Health check
    try:
        health = test_health()
        all_results["tests"]["health"] = "PASS"
        all_results["health"] = health
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["health"] = f"FAIL: {e}"
        print("\nGPU Service is not reachable. Cannot run voiceprint tests.")
        save_results(all_results)
        return

    # 2. Find audio files
    audio_files = find_audio_files(2)
    if len(audio_files) < 1:
        print("\nERROR: No audio files found")
        save_results(all_results)
        return
    print(f"\nAudio files: {[os.path.basename(f) for f in audio_files]}")

    # 3. List speakers (before enrollment)
    try:
        before = test_list_speakers()
        all_results["tests"]["list_speakers_initial"] = "PASS"
        all_results["speakers_before"] = before
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["list_speakers_initial"] = f"FAIL: {e}"

    # 4. Identify before enrollment (should work with empty results)
    try:
        result = test_identify_no_enrollments(audio_files[0])
        all_results["tests"]["identify_no_enrollments"] = "PASS" if result else "WARN"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["identify_no_enrollments"] = f"FAIL: {e}"

    # 5. Enroll speakers
    enrolled_names = ["Test Speaker A", "Test Speaker B"]
    for i, name in enumerate(enrolled_names):
        if i >= len(audio_files):
            break
        try:
            enroll_result = test_enroll(audio_files[i], name)
            all_results["tests"][f"enroll_{name}"] = "PASS"
        except Exception as e:
            print(f"  FAIL: {e}")
            all_results["tests"][f"enroll_{name}"] = f"FAIL: {e}"

    # 6. List speakers (after enrollment)
    try:
        after = test_list_speakers()
        all_results["tests"]["list_speakers_after"] = "PASS"
        all_results["speakers_after"] = after
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["list_speakers_after"] = f"FAIL: {e}"

    # 7. Identify (should now return matches)
    try:
        identify_result = test_identify(audio_files[0])
        all_results["tests"]["identify_after_enroll"] = "PASS"
        all_results["identify_result"] = identify_result
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["identify_after_enroll"] = f"FAIL: {e}"

    # 8. Identify with time range
    try:
        sliced_result = test_identify_with_time_range(audio_files[0])
        all_results["tests"]["identify_time_range"] = "PASS"
        all_results["identify_sliced_result"] = sliced_result
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["identify_time_range"] = f"FAIL: {e}"

    # 9. Test orchestrator proxy endpoints
    print(f"\n{'=' * 70}")
    print("Orchestrator Speaker Endpoints")
    print(f"{'=' * 70}")

    try:
        result = test_orchestrator_list_speakers()
        all_results["tests"]["orch_list_speakers"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["orch_list_speakers"] = f"FAIL: {e}"

    try:
        result = test_orchestrator_enroll(audio_files[0], "Orchestrator Test Speaker")
        all_results["tests"]["orch_enroll"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["orch_enroll"] = f"FAIL: {e}"

    try:
        result = test_orchestrator_list_speakers()
        all_results["tests"]["orch_list_after_enroll"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["orch_list_after_enroll"] = f"FAIL: {e}"

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for test_name, status in all_results["tests"].items():
        print(f"  {test_name:<35} {status}")

    save_results(all_results)


def save_results(results):
    output_path = os.path.join(os.path.dirname(__file__), "voiceprint_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
