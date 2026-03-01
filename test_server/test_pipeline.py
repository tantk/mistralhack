<<<<<<< Updated upstream
"""
Test the orchestrator pipeline endpoints (POST /api/jobs, GET events, GET result).

Sends audio files through the full pipeline and validates:
  - Job creation returns a job_id
  - SSE stream emits expected events in order
  - Polling endpoint returns correct status progression
  - Final result contains all expected fields

Uses audio samples from data/audio_samples/ or data/peoples_speech/.

Results saved to test_server/pipeline_results.json
"""
import json
import os
import sys
import time
import threading
import requests

sys.path.insert(0, os.path.dirname(__file__))

SERVICE_URL = os.environ.get("SERVICE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
AUDIO_DIR = os.path.join(PROJECT_ROOT, "data", "audio_samples")
PEOPLES_SPEECH_DIR = os.path.join(PROJECT_ROOT, "data", "peoples_speech")


def auth_headers():
    if API_KEY:
        return {"Authorization": f"Bearer {API_KEY}"}
    return {}


def find_test_audio():
    """Find an audio file to use for testing. Prefer smaller files for faster tests."""
    # Prefer peoples_speech (small single-speaker clips)
    if os.path.isdir(PEOPLES_SPEECH_DIR):
        for f in sorted(os.listdir(PEOPLES_SPEECH_DIR)):
            if f.endswith((".wav", ".flac", ".mp3")):
                return os.path.join(PEOPLES_SPEECH_DIR, f)

    # Fall back to audio_samples
    if os.path.isdir(AUDIO_DIR):
        for f in sorted(os.listdir(AUDIO_DIR)):
            if f.endswith((".wav", ".flac", ".mp3")):
                return os.path.join(AUDIO_DIR, f)

    return None


def test_create_job(audio_path):
    """Test POST /api/jobs — should return a job_id."""
    print("\n--- Test: Create Job ---")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{SERVICE_URL}/api/jobs",
            files={"audio": f},
            headers=auth_headers(),
            timeout=30,
        )

    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    data = resp.json()
    assert "job_id" in data, f"Response missing job_id: {data}"
    print(f"  Job ID: {data['job_id']}")
    return data["job_id"]


def test_create_job_no_audio():
    """Test POST /api/jobs with no audio field — should return 400."""
    print("\n--- Test: Create Job (no audio) ---")
    resp = requests.post(
        f"{SERVICE_URL}/api/jobs",
        headers=auth_headers(),
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print("  Correctly rejected (400)")
    return True


def test_poll_job_not_found():
    """Test GET /api/jobs/{id}/result with invalid ID — should return 404."""
    print("\n--- Test: Poll Non-existent Job ---")
    resp = requests.get(
        f"{SERVICE_URL}/api/jobs/nonexistent-id/result",
        headers=auth_headers(),
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print("  Correctly returned 404")
    return True


def test_stream_job_not_found():
    """Test GET /api/jobs/{id}/events with invalid ID — should return 404."""
    print("\n--- Test: Stream Non-existent Job ---")
    resp = requests.get(
        f"{SERVICE_URL}/api/jobs/nonexistent-id/events",
        headers=auth_headers(),
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print("  Correctly returned 404")
    return True


def test_sse_stream(job_id=None, audio_path=None):
    """Test GET /api/jobs/{id}/events — collect all SSE events.

    If audio_path is provided, creates a new job and connects SSE immediately
    to avoid missing early events.
    """
    print("\n--- Test: SSE Event Stream ---")

    if audio_path:
        # Create job and start SSE listener concurrently to catch all events
        import threading

        events = []
        sse_ready = threading.Event()
        actual_job_id = [None]

        def sse_listener(jid_holder, ready_event):
            # Wait for job_id to be set
            ready_event.wait(timeout=30)
            jid = jid_holder[0]
            if not jid:
                return

            url = f"{SERVICE_URL}/api/jobs/{jid}/events"
            if API_KEY:
                url += f"?token={API_KEY}"

            try:
                resp = requests.get(url, stream=True, timeout=300)
                if resp.status_code != 200:
                    print(f"  SSE status {resp.status_code}")
                    return

                event_type = None
                data_buf = ""

                for line in resp.iter_lines(decode_unicode=True):
                    if line is None:
                        continue
                    line = line.strip() if isinstance(line, str) else line.decode().strip()

                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buf = line[5:].strip()
                    elif line == "" and event_type:
                        try:
                            data = json.loads(data_buf) if data_buf else {}
                        except json.JSONDecodeError:
                            data = {"raw": data_buf}
                        events.append({"event": event_type, "data": data})
                        if event_type == "done":
                            break
                        event_type = None
                        data_buf = ""
            except requests.Timeout:
                pass

        t = threading.Thread(target=sse_listener, args=(actual_job_id, sse_ready))
        t.start()

        # Create the job
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"{SERVICE_URL}/api/jobs",
                files={"audio": f},
                headers=auth_headers(),
                timeout=30,
            )
        resp.raise_for_status()
        jid = resp.json()["job_id"]
        actual_job_id[0] = jid
        print(f"  Job ID: {jid}")
        sse_ready.set()

        t.join(timeout=300)
        for e in events:
            print(f"  Event: {e['event']}")
        return events, jid
    else:
        # Use existing job_id
        url = f"{SERVICE_URL}/api/jobs/{job_id}/events"
        if API_KEY:
            url += f"?token={API_KEY}"

        events = []
        try:
            resp = requests.get(url, stream=True, timeout=300)
            assert resp.status_code == 200, f"SSE status {resp.status_code}"

            event_type = None
            data_buf = ""

            for line in resp.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                line = line.strip() if isinstance(line, str) else line.decode().strip()

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_buf = line[5:].strip()
                elif line == "" and event_type:
                    try:
                        data = json.loads(data_buf) if data_buf else {}
                    except json.JSONDecodeError:
                        data = {"raw": data_buf}
                    events.append({"event": event_type, "data": data})
                    print(f"  Event: {e['event']}")
                    if event_type == "done":
                        break
                    event_type = None
                    data_buf = ""

        except requests.Timeout:
            print("  TIMEOUT waiting for SSE events")

        return events, job_id


def test_poll_result(job_id, timeout=300):
    """Test GET /api/jobs/{id}/result — poll until complete or error."""
    print("\n--- Test: Poll Result ---")

    start = time.time()
    last_phase = None

    while time.time() - start < timeout:
        resp = requests.get(
            f"{SERVICE_URL}/api/jobs/{job_id}/result",
            headers=auth_headers(),
            timeout=30,
        )
        assert resp.status_code == 200, f"Poll status {resp.status_code}"
        data = resp.json()

        if data.get("phase") != last_phase:
            last_phase = data.get("phase")
            print(f"  Phase: {last_phase or 'done'} (status: {data['status']})")

        if data["status"] == "complete":
            print("  Job completed successfully")
            return data
        elif data["status"] == "error":
            print(f"  Job failed: {data.get('error')}")
            return data

        time.sleep(2)

    print("  TIMEOUT waiting for job to complete")
    return None


def validate_result(result):
    """Validate the final job result has all expected fields."""
    print("\n--- Validate Result Fields ---")
    checks = []

    # Status
    ok = result.get("status") == "complete"
    checks.append(("status == complete", ok))
    print(f"  {'PASS' if ok else 'FAIL'} status == complete")

    # Transcript
    ok = isinstance(result.get("transcript"), str) and len(result["transcript"]) > 0
    checks.append(("transcript is non-empty string", ok))
    print(f"  {'PASS' if ok else 'FAIL'} transcript: {result.get('transcript', '')[:60]}...")

    # Segments
    segs = result.get("segments")
    ok = isinstance(segs, list) and len(segs) > 0
    checks.append(("segments is non-empty list", ok))
    if ok:
        seg = segs[0]
        print(f"  PASS segments: {len(segs)} segments")
        # Check segment fields
        for field in ["speaker", "start", "end", "text"]:
            has = field in seg
            checks.append((f"segment has '{field}'", has))
            if not has:
                print(f"  FAIL segment missing '{field}'")
        # Check new fields (optional)
        for field in ["is_overlap", "confidence", "active_speakers"]:
            has = field in seg
            checks.append((f"segment has '{field}'", has))
            print(f"  {'PASS' if has else 'WARN'} segment field '{field}': {seg.get(field)}")
    else:
        print(f"  FAIL segments: {segs}")

    # Decisions
    ok = isinstance(result.get("decisions"), list)
    checks.append(("decisions is list", ok))
    print(f"  {'PASS' if ok else 'FAIL'} decisions: {len(result.get('decisions', []))} items")

    # Ambiguities
    ok = isinstance(result.get("ambiguities"), list)
    checks.append(("ambiguities is list", ok))
    print(f"  {'PASS' if ok else 'FAIL'} ambiguities: {len(result.get('ambiguities', []))} items")

    # Action items
    items = result.get("action_items")
    ok = isinstance(items, list)
    checks.append(("action_items is list", ok))
    if ok and len(items) > 0:
        item = items[0]
        for field in ["owner", "task"]:
            has = field in item
            checks.append((f"action_item has '{field}'", has))
            if not has:
                print(f"  FAIL action_item missing '{field}'")
        print(f"  PASS action_items: {len(items)} items")
    else:
        print(f"  {'PASS' if ok else 'FAIL'} action_items: {items}")

    # Meeting dynamics
    md = result.get("meeting_dynamics")
    ok = isinstance(md, dict)
    checks.append(("meeting_dynamics is dict", ok))
    if ok:
        has_talk = "talk_time_pct" in md
        has_int = "interruption_count" in md
        checks.append(("meeting_dynamics.talk_time_pct", has_talk))
        checks.append(("meeting_dynamics.interruption_count", has_int))
        print(f"  {'PASS' if has_talk else 'FAIL'} talk_time_pct: {md.get('talk_time_pct')}")
        print(f"  {'PASS' if has_int else 'FAIL'} interruption_count: {md.get('interruption_count')}")
    else:
        print(f"  FAIL meeting_dynamics: {md}")

    # Speakers array (new)
    speakers = result.get("speakers")
    ok = isinstance(speakers, list)
    checks.append(("speakers is list", ok))
    if ok and len(speakers) > 0:
        spk = speakers[0]
        for field in ["id", "name", "resolution_method"]:
            has = field in spk
            checks.append((f"speaker has '{field}'", has))
        print(f"  PASS speakers: {len(speakers)} speakers")
    else:
        print(f"  {'PASS' if ok else 'WARN'} speakers: {speakers}")

    # Meeting metadata (new)
    mm = result.get("meeting_metadata")
    ok = isinstance(mm, dict)
    checks.append(("meeting_metadata is dict", ok))
    if ok:
        print(f"  PASS meeting_metadata: {mm}")
    else:
        print(f"  WARN meeting_metadata: {mm}")

    # No error
    ok = result.get("error") is None
    checks.append(("error is null", ok))
    print(f"  {'PASS' if ok else 'FAIL'} error: {result.get('error')}")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return checks


def validate_sse_events(events):
    """Validate the SSE event sequence."""
    print("\n--- Validate SSE Event Sequence ---")
    checks = []

    event_types = [e["event"] for e in events]

    # Must start with phase_start
    ok = len(event_types) > 0 and event_types[0] == "phase_start"
    checks.append(("starts with phase_start", ok))
    print(f"  {'PASS' if ok else 'FAIL'} starts with phase_start")

    # Must end with done
    ok = len(event_types) > 0 and event_types[-1] == "done"
    checks.append(("ends with done", ok))
    print(f"  {'PASS' if ok else 'FAIL'} ends with done")

    # Must have transcript_complete
    ok = "transcript_complete" in event_types
    checks.append(("has transcript_complete", ok))
    print(f"  {'PASS' if ok else 'FAIL'} has transcript_complete")

    # Must have diarization_complete
    ok = "diarization_complete" in event_types
    checks.append(("has diarization_complete", ok))
    print(f"  {'PASS' if ok else 'FAIL'} has diarization_complete")

    # Must have analysis_complete
    ok = "analysis_complete" in event_types
    checks.append(("has analysis_complete", ok))
    print(f"  {'PASS' if ok else 'FAIL'} has analysis_complete")

    # Check phase order (acoustic_matching is optional phase 2.5)
    phases = [e["data"].get("phase") for e in events if e["event"] == "phase_start"]
    expected_full = ["transcribing", "diarizing", "acoustic_matching", "resolving", "analyzing"]
    expected_no_acoustic = ["transcribing", "diarizing", "resolving", "analyzing"]
    ok = phases == expected_full or phases == expected_no_acoustic
    checks.append(("phase order correct", ok))
    print(f"  {'PASS' if ok else 'FAIL'} phase order: {phases}")

    # Check transcript_complete has words field
    tc = next((e for e in events if e["event"] == "transcript_complete"), None)
    if tc:
        ok = "words" in tc["data"]
        checks.append(("transcript_complete has words", ok))
        print(f"  {'PASS' if ok else 'FAIL'} transcript_complete.words: {len(tc['data'].get('words', []))} words")

        ok = "language" in tc["data"]
        checks.append(("transcript_complete has language", ok))
        print(f"  {'PASS' if ok else 'FAIL'} transcript_complete.language: {tc['data'].get('language')}")

    # Check analysis_complete has meeting_dynamics
    ac = next((e for e in events if e["event"] == "analysis_complete"), None)
    if ac:
        ok = "meeting_dynamics" in ac["data"]
        checks.append(("analysis_complete has meeting_dynamics", ok))
        print(f"  {'PASS' if ok else 'FAIL'} analysis_complete.meeting_dynamics present")

        ok = "action_items" in ac["data"]
        checks.append(("analysis_complete has action_items", ok))
        print(f"  {'PASS' if ok else 'FAIL'} analysis_complete.action_items present")

    # Check for tool_call / tool_result events (optional, depends on API key)
    tool_calls = [e for e in events if e["event"] == "tool_call"]
    tool_results = [e for e in events if e["event"] == "tool_result"]
    speaker_resolved = [e for e in events if e["event"] == "speaker_resolved"]
    print(f"  INFO tool_calls: {len(tool_calls)}, tool_results: {len(tool_results)}, speaker_resolved: {len(speaker_resolved)}")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return checks


def test_transcribe_endpoint(audio_path):
    """Test POST /api/transcribe — standalone transcription without full pipeline."""
    print("\n--- Test: Standalone Transcribe ---")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{SERVICE_URL}/api/transcribe",
            files={"audio": f},
            headers=auth_headers(),
            timeout=120,
        )

    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    data = resp.json()

    # Validate text
    assert "text" in data, f"Response missing 'text': {data}"
    assert isinstance(data["text"], str) and len(data["text"]) > 0, f"text is empty"
    print(f"  Text: {data['text'][:80]}...")

    # Validate words
    assert "words" in data, f"Response missing 'words': {data}"
    assert isinstance(data["words"], list), f"words is not a list: {type(data['words'])}"
    if len(data["words"]) > 0:
        w = data["words"][0]
        for field in ["word", "start", "end"]:
            assert field in w, f"word object missing '{field}': {w}"
        print(f"  Words: {len(data['words'])} words (first: {w})")
    else:
        print("  Words: 0 (Voxtral fallback — no word timestamps)")

    # Validate language
    assert "language" in data, f"Response missing 'language': {data}"
    print(f"  Language: {data['language']}")

    # Validate duration_ms
    assert "duration_ms" in data, f"Response missing 'duration_ms': {data}"
    assert isinstance(data["duration_ms"], (int, float)), f"duration_ms not numeric"
    print(f"  Duration: {data['duration_ms']}ms")

    return data


def test_transcribe_no_audio():
    """Test POST /api/transcribe with no audio field — should return 400."""
    print("\n--- Test: Transcribe (no audio) ---")
    resp = requests.post(
        f"{SERVICE_URL}/api/transcribe",
        headers=auth_headers(),
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print("  Correctly rejected (400)")
    return True


def test_auth_rejection():
    """Test that auth is enforced when API_KEY is set."""
    if not API_KEY:
        print("\n--- Test: Auth Rejection (SKIPPED — no API_KEY set) ---")
        return None

    print("\n--- Test: Auth Rejection ---")
    resp = requests.post(
        f"{SERVICE_URL}/api/jobs",
        headers={"Authorization": "Bearer wrong-key"},
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    ok = resp.status_code == 401
    print(f"  {'PASS' if ok else 'FAIL'} returns 401 for bad key")
    return ok


def main():
    print("=" * 70)
    print("Pipeline Endpoint Tests")
    print("=" * 70)
    print(f"Service: {SERVICE_URL}")
    print(f"Auth: {'enabled' if API_KEY else 'disabled (dev mode)'}")

    all_results = {
        "service_url": SERVICE_URL,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tests": {},
    }

    # 1. Find test audio
    audio_path = find_test_audio()
    if not audio_path:
        print("\nERROR: No audio files found in data/audio_samples/ or data/peoples_speech/")
        return
    print(f"Audio: {os.path.basename(audio_path)}")

    # 2. Error case tests
    try:
        test_create_job_no_audio()
        all_results["tests"]["create_job_no_audio"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["create_job_no_audio"] = f"FAIL: {e}"

    try:
        test_poll_job_not_found()
        all_results["tests"]["poll_not_found"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["poll_not_found"] = f"FAIL: {e}"

    try:
        test_stream_job_not_found()
        all_results["tests"]["stream_not_found"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["stream_not_found"] = f"FAIL: {e}"

    # 3. Standalone transcription tests
    try:
        test_transcribe_no_audio()
        all_results["tests"]["transcribe_no_audio"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["transcribe_no_audio"] = f"FAIL: {e}"

    try:
        transcribe_result = test_transcribe_endpoint(audio_path)
        all_results["tests"]["transcribe_endpoint"] = "PASS"
        all_results["transcribe_result"] = transcribe_result
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["transcribe_endpoint"] = f"FAIL: {e}"

    # 4. Auth test
    auth_result = test_auth_rejection()
    if auth_result is not None:
        all_results["tests"]["auth_rejection"] = "PASS" if auth_result else "FAIL"

    # 5. Full pipeline test with SSE (creates job + connects SSE concurrently)
    print("\n" + "=" * 70)
    print("Full Pipeline Test (SSE)")
    print("=" * 70)

    try:
        events, job_id = test_sse_stream(audio_path=audio_path)
        all_results["tests"]["create_job"] = "PASS"
        all_results["job_id"] = job_id
        all_results["sse_events"] = events
        all_results["sse_event_count"] = len(events)

        sse_checks = validate_sse_events(events)
        sse_passed = sum(1 for _, ok in sse_checks if ok)
        all_results["tests"]["sse_validation"] = f"{sse_passed}/{len(sse_checks)}"

    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["sse_pipeline"] = f"FAIL: {e}"

    # 6. Full pipeline test with polling
    print("\n" + "=" * 70)
    print("Full Pipeline Test (Polling)")
    print("=" * 70)

    try:
        job_id2 = test_create_job(audio_path)
        all_results["tests"]["create_job_poll"] = "PASS"

        result = test_poll_result(job_id2)
        if result and result.get("status") == "complete":
            all_results["tests"]["poll_complete"] = "PASS"
            result_checks = validate_result(result)
            result_passed = sum(1 for _, ok in result_checks if ok)
            all_results["tests"]["result_validation"] = f"{result_passed}/{len(result_checks)}"
            all_results["final_result"] = result
        elif result and result.get("status") == "error":
            all_results["tests"]["poll_complete"] = f"ERROR: {result.get('error')}"
        else:
            all_results["tests"]["poll_complete"] = "TIMEOUT"

    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["poll_pipeline"] = f"FAIL: {e}"

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for test_name, status in all_results["tests"].items():
        print(f"  {test_name:<30} {status}")

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), "pipeline_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
=======
"""
Test the orchestrator pipeline endpoints (POST /api/jobs, GET events, GET result).

Sends audio files through the full pipeline and validates:
  - Job creation returns a job_id
  - SSE stream emits expected events in order
  - Polling endpoint returns correct status progression
  - Final result contains all expected fields

Uses audio samples from data/audio_samples/ or data/peoples_speech/.

Results saved to test_server/pipeline_results.json
"""
import json
import os
import sys
import time
import threading
import requests

sys.path.insert(0, os.path.dirname(__file__))

SERVICE_URL = os.environ.get("SERVICE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
AUDIO_DIR = os.path.join(PROJECT_ROOT, "data", "audio_samples")
PEOPLES_SPEECH_DIR = os.path.join(PROJECT_ROOT, "data", "peoples_speech")


def auth_headers():
    if API_KEY:
        return {"Authorization": f"Bearer {API_KEY}"}
    return {}


def find_test_audio():
    """Find an audio file to use for testing. Prefer smaller files for faster tests."""
    # Prefer peoples_speech (small single-speaker clips)
    if os.path.isdir(PEOPLES_SPEECH_DIR):
        for f in sorted(os.listdir(PEOPLES_SPEECH_DIR)):
            if f.endswith((".wav", ".flac", ".mp3")):
                return os.path.join(PEOPLES_SPEECH_DIR, f)

    # Fall back to audio_samples
    if os.path.isdir(AUDIO_DIR):
        for f in sorted(os.listdir(AUDIO_DIR)):
            if f.endswith((".wav", ".flac", ".mp3")):
                return os.path.join(AUDIO_DIR, f)

    return None


def test_create_job(audio_path):
    """Test POST /api/jobs — should return a job_id."""
    print("\n--- Test: Create Job ---")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{SERVICE_URL}/api/jobs",
            files={"audio": f},
            headers=auth_headers(),
            timeout=30,
        )

    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    data = resp.json()
    assert "job_id" in data, f"Response missing job_id: {data}"
    print(f"  Job ID: {data['job_id']}")
    return data["job_id"]


def test_create_job_no_audio():
    """Test POST /api/jobs with no audio field — should return 400."""
    print("\n--- Test: Create Job (no audio) ---")
    resp = requests.post(
        f"{SERVICE_URL}/api/jobs",
        headers=auth_headers(),
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print("  Correctly rejected (400)")
    return True


def test_poll_job_not_found():
    """Test GET /api/jobs/{id}/result with invalid ID — should return 404."""
    print("\n--- Test: Poll Non-existent Job ---")
    resp = requests.get(
        f"{SERVICE_URL}/api/jobs/nonexistent-id/result",
        headers=auth_headers(),
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print("  Correctly returned 404")
    return True


def test_stream_job_not_found():
    """Test GET /api/jobs/{id}/events with invalid ID — should return 404."""
    print("\n--- Test: Stream Non-existent Job ---")
    resp = requests.get(
        f"{SERVICE_URL}/api/jobs/nonexistent-id/events",
        headers=auth_headers(),
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print("  Correctly returned 404")
    return True


def test_sse_stream(job_id=None, audio_path=None):
    """Test GET /api/jobs/{id}/events — collect all SSE events.

    If audio_path is provided, creates a new job and connects SSE immediately
    to avoid missing early events.
    """
    print("\n--- Test: SSE Event Stream ---")

    if audio_path:
        # Create job and start SSE listener concurrently to catch all events
        import threading

        events = []
        sse_ready = threading.Event()
        actual_job_id = [None]

        def sse_listener(jid_holder, ready_event):
            # Wait for job_id to be set
            ready_event.wait(timeout=30)
            jid = jid_holder[0]
            if not jid:
                return

            url = f"{SERVICE_URL}/api/jobs/{jid}/events"
            if API_KEY:
                url += f"?token={API_KEY}"

            try:
                resp = requests.get(url, stream=True, timeout=300)
                if resp.status_code != 200:
                    print(f"  SSE status {resp.status_code}")
                    return

                event_type = None
                data_buf = ""

                for line in resp.iter_lines(decode_unicode=True):
                    if line is None:
                        continue
                    line = line.strip() if isinstance(line, str) else line.decode().strip()

                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buf = line[5:].strip()
                    elif line == "" and event_type:
                        try:
                            data = json.loads(data_buf) if data_buf else {}
                        except json.JSONDecodeError:
                            data = {"raw": data_buf}
                        events.append({"event": event_type, "data": data})
                        if event_type == "done":
                            break
                        event_type = None
                        data_buf = ""
            except requests.Timeout:
                pass

        t = threading.Thread(target=sse_listener, args=(actual_job_id, sse_ready))
        t.start()

        # Create the job
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"{SERVICE_URL}/api/jobs",
                files={"audio": f},
                headers=auth_headers(),
                timeout=30,
            )
        resp.raise_for_status()
        jid = resp.json()["job_id"]
        actual_job_id[0] = jid
        print(f"  Job ID: {jid}")
        sse_ready.set()

        t.join(timeout=300)
        for e in events:
            print(f"  Event: {e['event']}")
        return events, jid
    else:
        # Use existing job_id
        url = f"{SERVICE_URL}/api/jobs/{job_id}/events"
        if API_KEY:
            url += f"?token={API_KEY}"

        events = []
        try:
            resp = requests.get(url, stream=True, timeout=300)
            assert resp.status_code == 200, f"SSE status {resp.status_code}"

            event_type = None
            data_buf = ""

            for line in resp.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                line = line.strip() if isinstance(line, str) else line.decode().strip()

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_buf = line[5:].strip()
                elif line == "" and event_type:
                    try:
                        data = json.loads(data_buf) if data_buf else {}
                    except json.JSONDecodeError:
                        data = {"raw": data_buf}
                    events.append({"event": event_type, "data": data})
                    print(f"  Event: {e['event']}")
                    if event_type == "done":
                        break
                    event_type = None
                    data_buf = ""

        except requests.Timeout:
            print("  TIMEOUT waiting for SSE events")

        return events, job_id


def test_poll_result(job_id, timeout=300):
    """Test GET /api/jobs/{id}/result — poll until complete or error."""
    print("\n--- Test: Poll Result ---")

    start = time.time()
    last_phase = None

    while time.time() - start < timeout:
        resp = requests.get(
            f"{SERVICE_URL}/api/jobs/{job_id}/result",
            headers=auth_headers(),
            timeout=30,
        )
        assert resp.status_code == 200, f"Poll status {resp.status_code}"
        data = resp.json()

        if data.get("phase") != last_phase:
            last_phase = data.get("phase")
            print(f"  Phase: {last_phase or 'done'} (status: {data['status']})")

        if data["status"] == "complete":
            print("  Job completed successfully")
            return data
        elif data["status"] == "error":
            print(f"  Job failed: {data.get('error')}")
            return data

        time.sleep(2)

    print("  TIMEOUT waiting for job to complete")
    return None


def validate_result(result):
    """Validate the final job result has all expected fields."""
    print("\n--- Validate Result Fields ---")
    checks = []

    # Status
    ok = result.get("status") == "complete"
    checks.append(("status == complete", ok))
    print(f"  {'PASS' if ok else 'FAIL'} status == complete")

    # Transcript
    ok = isinstance(result.get("transcript"), str) and len(result["transcript"]) > 0
    checks.append(("transcript is non-empty string", ok))
    print(f"  {'PASS' if ok else 'FAIL'} transcript: {result.get('transcript', '')[:60]}...")

    # Segments
    segs = result.get("segments")
    ok = isinstance(segs, list) and len(segs) > 0
    checks.append(("segments is non-empty list", ok))
    if ok:
        seg = segs[0]
        print(f"  PASS segments: {len(segs)} segments")
        # Check segment fields
        for field in ["speaker", "start", "end", "text"]:
            has = field in seg
            checks.append((f"segment has '{field}'", has))
            if not has:
                print(f"  FAIL segment missing '{field}'")
        # Check new fields (optional)
        for field in ["is_overlap", "confidence", "active_speakers"]:
            has = field in seg
            checks.append((f"segment has '{field}'", has))
            print(f"  {'PASS' if has else 'WARN'} segment field '{field}': {seg.get(field)}")
    else:
        print(f"  FAIL segments: {segs}")

    # Decisions
    ok = isinstance(result.get("decisions"), list)
    checks.append(("decisions is list", ok))
    print(f"  {'PASS' if ok else 'FAIL'} decisions: {len(result.get('decisions', []))} items")

    # Ambiguities
    ok = isinstance(result.get("ambiguities"), list)
    checks.append(("ambiguities is list", ok))
    print(f"  {'PASS' if ok else 'FAIL'} ambiguities: {len(result.get('ambiguities', []))} items")

    # Action items
    items = result.get("action_items")
    ok = isinstance(items, list)
    checks.append(("action_items is list", ok))
    if ok and len(items) > 0:
        item = items[0]
        for field in ["owner", "task"]:
            has = field in item
            checks.append((f"action_item has '{field}'", has))
            if not has:
                print(f"  FAIL action_item missing '{field}'")
        print(f"  PASS action_items: {len(items)} items")
    else:
        print(f"  {'PASS' if ok else 'FAIL'} action_items: {items}")

    # Meeting dynamics
    md = result.get("meeting_dynamics")
    ok = isinstance(md, dict)
    checks.append(("meeting_dynamics is dict", ok))
    if ok:
        has_talk = "talk_time_pct" in md
        has_int = "interruption_count" in md
        checks.append(("meeting_dynamics.talk_time_pct", has_talk))
        checks.append(("meeting_dynamics.interruption_count", has_int))
        print(f"  {'PASS' if has_talk else 'FAIL'} talk_time_pct: {md.get('talk_time_pct')}")
        print(f"  {'PASS' if has_int else 'FAIL'} interruption_count: {md.get('interruption_count')}")
    else:
        print(f"  FAIL meeting_dynamics: {md}")

    # Speakers array (new)
    speakers = result.get("speakers")
    ok = isinstance(speakers, list)
    checks.append(("speakers is list", ok))
    if ok and len(speakers) > 0:
        spk = speakers[0]
        for field in ["id", "name", "resolution_method"]:
            has = field in spk
            checks.append((f"speaker has '{field}'", has))
        print(f"  PASS speakers: {len(speakers)} speakers")
    else:
        print(f"  {'PASS' if ok else 'WARN'} speakers: {speakers}")

    # Meeting metadata (new)
    mm = result.get("meeting_metadata")
    ok = isinstance(mm, dict)
    checks.append(("meeting_metadata is dict", ok))
    if ok:
        print(f"  PASS meeting_metadata: {mm}")
    else:
        print(f"  WARN meeting_metadata: {mm}")

    # No error
    ok = result.get("error") is None
    checks.append(("error is null", ok))
    print(f"  {'PASS' if ok else 'FAIL'} error: {result.get('error')}")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return checks


def validate_sse_events(events):
    """Validate the SSE event sequence."""
    print("\n--- Validate SSE Event Sequence ---")
    checks = []

    event_types = [e["event"] for e in events]

    # Must start with phase_start
    ok = len(event_types) > 0 and event_types[0] == "phase_start"
    checks.append(("starts with phase_start", ok))
    print(f"  {'PASS' if ok else 'FAIL'} starts with phase_start")

    # Must end with done
    ok = len(event_types) > 0 and event_types[-1] == "done"
    checks.append(("ends with done", ok))
    print(f"  {'PASS' if ok else 'FAIL'} ends with done")

    # Must have transcript_complete
    ok = "transcript_complete" in event_types
    checks.append(("has transcript_complete", ok))
    print(f"  {'PASS' if ok else 'FAIL'} has transcript_complete")

    # Must have diarization_complete
    ok = "diarization_complete" in event_types
    checks.append(("has diarization_complete", ok))
    print(f"  {'PASS' if ok else 'FAIL'} has diarization_complete")

    # Must have analysis_complete
    ok = "analysis_complete" in event_types
    checks.append(("has analysis_complete", ok))
    print(f"  {'PASS' if ok else 'FAIL'} has analysis_complete")

    # Check phase order (acoustic_matching is optional phase 2.5)
    phases = [e["data"].get("phase") for e in events if e["event"] == "phase_start"]
    expected_full = ["transcribing", "diarizing", "acoustic_matching", "resolving", "analyzing"]
    expected_no_acoustic = ["transcribing", "diarizing", "resolving", "analyzing"]
    ok = phases == expected_full or phases == expected_no_acoustic
    checks.append(("phase order correct", ok))
    print(f"  {'PASS' if ok else 'FAIL'} phase order: {phases}")

    # Check transcript_complete has words field
    tc = next((e for e in events if e["event"] == "transcript_complete"), None)
    if tc:
        ok = "words" in tc["data"]
        checks.append(("transcript_complete has words", ok))
        print(f"  {'PASS' if ok else 'FAIL'} transcript_complete.words: {len(tc['data'].get('words', []))} words")

        ok = "language" in tc["data"]
        checks.append(("transcript_complete has language", ok))
        print(f"  {'PASS' if ok else 'FAIL'} transcript_complete.language: {tc['data'].get('language')}")

    # Check analysis_complete has meeting_dynamics
    ac = next((e for e in events if e["event"] == "analysis_complete"), None)
    if ac:
        ok = "meeting_dynamics" in ac["data"]
        checks.append(("analysis_complete has meeting_dynamics", ok))
        print(f"  {'PASS' if ok else 'FAIL'} analysis_complete.meeting_dynamics present")

        ok = "action_items" in ac["data"]
        checks.append(("analysis_complete has action_items", ok))
        print(f"  {'PASS' if ok else 'FAIL'} analysis_complete.action_items present")

    # Check for tool_call / tool_result events (optional, depends on API key)
    tool_calls = [e for e in events if e["event"] == "tool_call"]
    tool_results = [e for e in events if e["event"] == "tool_result"]
    speaker_resolved = [e for e in events if e["event"] == "speaker_resolved"]
    print(f"  INFO tool_calls: {len(tool_calls)}, tool_results: {len(tool_results)}, speaker_resolved: {len(speaker_resolved)}")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return checks


def test_auth_rejection():
    """Test that auth is enforced when API_KEY is set."""
    if not API_KEY:
        print("\n--- Test: Auth Rejection (SKIPPED — no API_KEY set) ---")
        return None

    print("\n--- Test: Auth Rejection ---")
    resp = requests.post(
        f"{SERVICE_URL}/api/jobs",
        headers={"Authorization": "Bearer wrong-key"},
        timeout=10,
    )
    print(f"  Status: {resp.status_code}")
    ok = resp.status_code == 401
    print(f"  {'PASS' if ok else 'FAIL'} returns 401 for bad key")
    return ok


def main():
    print("=" * 70)
    print("Pipeline Endpoint Tests")
    print("=" * 70)
    print(f"Service: {SERVICE_URL}")
    print(f"Auth: {'enabled' if API_KEY else 'disabled (dev mode)'}")

    all_results = {
        "service_url": SERVICE_URL,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tests": {},
    }

    # 1. Find test audio
    audio_path = find_test_audio()
    if not audio_path:
        print("\nERROR: No audio files found in data/audio_samples/ or data/peoples_speech/")
        return
    print(f"Audio: {os.path.basename(audio_path)}")

    # 2. Error case tests
    try:
        test_create_job_no_audio()
        all_results["tests"]["create_job_no_audio"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["create_job_no_audio"] = f"FAIL: {e}"

    try:
        test_poll_job_not_found()
        all_results["tests"]["poll_not_found"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["poll_not_found"] = f"FAIL: {e}"

    try:
        test_stream_job_not_found()
        all_results["tests"]["stream_not_found"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["stream_not_found"] = f"FAIL: {e}"

    # 3. Auth test
    auth_result = test_auth_rejection()
    if auth_result is not None:
        all_results["tests"]["auth_rejection"] = "PASS" if auth_result else "FAIL"

    # 4. Full pipeline test with SSE (creates job + connects SSE concurrently)
    print("\n" + "=" * 70)
    print("Full Pipeline Test (SSE)")
    print("=" * 70)

    try:
        events, job_id = test_sse_stream(audio_path=audio_path)
        all_results["tests"]["create_job"] = "PASS"
        all_results["job_id"] = job_id
        all_results["sse_events"] = events
        all_results["sse_event_count"] = len(events)

        sse_checks = validate_sse_events(events)
        sse_passed = sum(1 for _, ok in sse_checks if ok)
        all_results["tests"]["sse_validation"] = f"{sse_passed}/{len(sse_checks)}"

    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["sse_pipeline"] = f"FAIL: {e}"

    # 5. Full pipeline test with polling
    print("\n" + "=" * 70)
    print("Full Pipeline Test (Polling)")
    print("=" * 70)

    try:
        job_id2 = test_create_job(audio_path)
        all_results["tests"]["create_job_poll"] = "PASS"

        result = test_poll_result(job_id2)
        if result and result.get("status") == "complete":
            all_results["tests"]["poll_complete"] = "PASS"
            result_checks = validate_result(result)
            result_passed = sum(1 for _, ok in result_checks if ok)
            all_results["tests"]["result_validation"] = f"{result_passed}/{len(result_checks)}"
            all_results["final_result"] = result
        elif result and result.get("status") == "error":
            all_results["tests"]["poll_complete"] = f"ERROR: {result.get('error')}"
        else:
            all_results["tests"]["poll_complete"] = "TIMEOUT"

    except Exception as e:
        print(f"  FAIL: {e}")
        all_results["tests"]["poll_pipeline"] = f"FAIL: {e}"

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for test_name, status in all_results["tests"].items():
        print(f"  {test_name:<30} {status}")

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), "pipeline_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
>>>>>>> Stashed changes
