# Make Meeting Analyses Great Again API Reference

## Architecture Overview

```
Browser ──► Orchestrator (Rust, port 7860) ──► Mistral API (transcription + analysis)
                │                           ──► HF Inference Endpoint (GPU)
                │                                 ├── Pyannote diarization
                │                                 └── FunASR speaker embeddings
                ▼
         Static frontend
```

All requests go through the **Orchestrator**, which handles auth, job management, SSE streaming, and voiceprint storage (local zvec). The GPU service runs as a stateless HF Inference Endpoint.

---

## Authentication

All `/api/` endpoints (except `/api/health`) require a Bearer token when `API_KEY` is set.

```
Authorization: Bearer <token>
```

For SSE/EventSource (which can't set headers), use a query parameter:

```
GET /api/jobs/{id}/events?token=<token>
```

If `API_KEY` is empty, auth is disabled (dev mode).

---

## Orchestrator Endpoints

### `GET /api/health`

Unauthenticated health check. Used by the frontend to probe backend availability.

**Response:** `200 OK`
```json
{
  "status": "ok"
}
```

---

### `POST /api/jobs`

Create a processing job. Uploads audio and starts the full pipeline:
**transcribe → diarize + align → acoustic match → agent resolution → analyze**

**Request:** `multipart/form-data`

| Field       | Type   | Required | Description |
|-------------|--------|----------|-------------|
| `audio`     | file   | yes      | Audio file (WAV, MP3, MP4, M4A, FLAC) |
| `attendees` | string | no       | JSON array of known attendee names |

**Response:** `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### `POST /api/transcribe`

Standalone transcription endpoint. Returns results directly without running the full pipeline.

Fallback chain: **Mistral API → GPU service → CPU** (self-hosted Voxtral, only if estimated processing time ≤ 1 minute).

**Request:** `multipart/form-data`

| Field   | Type | Required | Description |
|---------|------|----------|-------------|
| `audio` | file | yes      | Audio file  |

**Response:** `200 OK`
```json
{
  "text": "Hello world, this is a test.",
  "words": [
    {"word": "Hello", "start": 0.0, "end": 0.5},
    {"word": "world,", "start": 0.5, "end": 0.9}
  ],
  "language": "en",
  "duration_ms": 1800
}
```

---

### `GET /api/jobs/{id}/events`

SSE stream of pipeline events. Connect immediately after creating a job.

**Response:** `text/event-stream`

| Event | Data | When |
|-------|------|------|
| `phase_start` | `{"phase": "transcribing" \| "diarizing" \| "acoustic_matching" \| "resolving" \| "analyzing"}` | Pipeline enters a new phase |
| `transcript_token` | `{"token": "..."}` | Streaming transcription token |
| `transcript_complete` | `{"text", "words", "language", "duration_ms"}` | Full transcript ready |
| `diarization_complete` | `{"segments": Segment[]}` | Speaker-attributed segments ready |
| `tool_call` | `{"tool": "...", "args": {...}}` | Agent invoked a tool |
| `tool_result` | `{"tool": "...", "result": "..."}` | Tool returned a result |
| `speaker_resolved` | `{"label", "name", "confidence", "method"}` | Speaker identity resolved |
| `analysis_complete` | `{"decisions", "ambiguities", "action_items", "meeting_dynamics"}` | Analysis ready |
| `done` | `{}` | Pipeline finished |

---

### `GET /api/jobs/{id}/result`

Poll for job result (fallback when SSE is unavailable).

**Response:** `200 OK`
```json
{
  "status": "processing | complete | error",
  "phase": "transcribing",
  "transcript": "...",
  "segments": [],
  "decisions": [],
  "ambiguities": [],
  "action_items": [],
  "meeting_dynamics": {},
  "meeting_metadata": {},
  "error": null
}
```

---

### `POST /api/speakers/enroll`

Enroll a speaker voiceprint. Requires GPU service for embedding generation.

**Request:** `multipart/form-data`

| Field  | Type   | Required | Description |
|--------|--------|----------|-------------|
| `audio`| file   | yes      | Audio sample |
| `name` | string | yes      | Speaker name |

**Response:** `200 OK`
```json
{
  "speaker_id": "alice_chen_0",
  "name": "Alice Chen"
}
```

Returns `503` if GPU service is unavailable.

---

### `GET /api/speakers`

List all enrolled speaker voiceprints from the local zvec store.

**Response:** `200 OK`
```json
{
  "speakers": [
    {"id": "alice_chen_0", "name": "Alice Chen"}
  ]
}
```

---

## GPU Service (HF Inference Endpoint)

Stateless service for diarization and speaker embeddings. No auth. Used internally by the orchestrator.

### `GET /health`

```json
{
  "status": "ok",
  "gpu_available": true,
  "embedding_backend": "funasr_eres2netv2"
}
```

### `POST /diarize`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `audio` | file | yes | Audio file |
| `min_speakers` | int | no | Minimum speaker count |
| `max_speakers` | int | no | Maximum speaker count |

```json
{
  "segments": [
    {"speaker": "SPEAKER_0", "start": 0.0, "end": 3.5},
    {"speaker": "SPEAKER_1", "start": 3.5, "end": 7.2}
  ]
}
```

### `POST /embed`

| Field | Type | Required |
|-------|------|----------|
| `audio` | file | yes |

```json
{
  "embedding": [0.123, -0.456, "..."],
  "dim": 192
}
```

---

## Data Models

### Word
```json
{"word": "Hello", "start": 0.0, "end": 0.5}
```

### Segment
```json
{
  "speaker": "SPEAKER_0",
  "start": 0.0,
  "end": 3.5,
  "text": "Hello everyone, let's get started.",
  "is_overlap": false,
  "confidence": 0.95,
  "active_speakers": ["SPEAKER_0"]
}
```

### Decision
```json
{
  "timestamp": 12.0,
  "summary": "Adopt the new CI pipeline",
  "proposed_by": "Alice Chen",
  "seconded_by": "SPEAKER_1",
  "dissent_by": null,
  "status": "locked"
}
```
`status`: `"locked"` | `"open"` | `"contested"`

### Ambiguity
```json
{
  "timestamp": 45.0,
  "type": "commitment",
  "quote": "I'll look into it",
  "speaker": "SPEAKER_1",
  "confidence": 0.6,
  "candidates": ["will research", "noncommittal deflection"]
}
```
`type`: `"attributional"` | `"commitment"` | `"temporal"` | `"scope"`

### ActionItem
```json
{
  "owner": "Alice Chen",
  "task": "Draft the RFC",
  "deadline_mentioned": "Friday",
  "verbatim_quote": "I'll have the RFC draft done by Friday"
}
```

### MeetingDynamics
```json
{
  "talk_time_pct": {"Alice Chen": 45.2, "SPEAKER_1": 54.8},
  "interruption_count": 3
}
```

### MeetingMetadata
```json
{
  "title": "Q4 Planning Review",
  "date": "2026-02-28",
  "duration_seconds": 1800.0,
  "language": "en"
}
```

---

## Environment Variables

### Orchestrator

| Variable | Default | Description |
|----------|---------|-------------|
| `MISTRAL_API_KEY` | — | Mistral API key (required for pipeline) |
| `DIARIZATION_URL` | `http://192.168.0.105:8001` | GPU service / HF Inference Endpoint URL |
| `API_KEY` | *(empty = no auth)* | Bearer token for API auth |
| `PORT` | `7860` | Listen port |
| `VOICEPRINT_STORE_PATH` | `data/voiceprints` | Local zvec voiceprint store |

---

## Quick Start

```bash
# Full pipeline
JOB=$(curl -s -X POST https://your-space.hf.space/api/jobs \
  -H "Authorization: Bearer $API_KEY" \
  -F audio=@meeting.wav | jq -r .job_id)

# Stream events
curl -N "https://your-space.hf.space/api/jobs/$JOB/events?token=$API_KEY"

# Poll result
curl "https://your-space.hf.space/api/jobs/$JOB/result?token=$API_KEY"

# Standalone transcription
curl -X POST https://your-space.hf.space/api/transcribe \
  -H "Authorization: Bearer $API_KEY" \
  -F audio=@meeting.wav
```

**Direct diarization (no orchestrator):**
```bash
curl -X POST http://localhost:8001/diarize -F audio=@meeting.wav
```

**Voiceprint enrollment and identification:**
```bash
# Enroll a speaker
curl -X POST http://localhost:8001/voiceprint/enroll \
  -F audio=@alice_sample.wav -F name="Alice Chen"

# Identify from audio segment
curl -X POST http://localhost:8001/voiceprint/identify \
  -F audio=@meeting.wav -F start_time=5.0 -F end_time=10.0

# List enrolled speakers
curl http://localhost:8001/voiceprint/speakers
```

**Direct transcription (self-hosted Voxtral):**
```bash
# Non-streaming
curl -X POST http://localhost:8080/transcribe -F audio=@meeting.wav

# Streaming
curl -N -X POST http://localhost:8080/transcribe/stream -F audio=@meeting.wav
```
