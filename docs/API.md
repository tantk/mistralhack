# MeetingMind API Reference

## Architecture Overview

```
Browser ──► Orchestrator (Rust :8000) ──► Mistral API (transcription + analysis)
                │                     ──► GPU Service (Python :8001)
                │                           ├── Pyannote diarization
                │                           ├── ERes2NetV2 embeddings
                │                           └── Voiceprint store (FAISS)
                ▼
         Static frontend
```

All public-facing requests go through the **Orchestrator**, which handles auth, job management, and SSE streaming. The GPU Service runs on the LAN without auth. An optional self-hosted **Voxtral Transcription Server** (:8080) can be used as a fallback when `MISTRAL_API_KEY` is not set.

---

## Authentication

All orchestrator endpoints require a Bearer token when `API_KEY` is set.

```
Authorization: Bearer <token>
```

For SSE/EventSource (which can't set headers), use a query parameter:

```
GET /api/jobs/{id}/events?token=<token>
```

If `API_KEY` is empty, auth is disabled (dev mode).

---

## Orchestrator — `localhost:8000`

### `POST /api/jobs`

Create a processing job. Uploads audio and starts the full pipeline:
**transcribe → diarize + align → agent resolution → analyze**

**Request:** `multipart/form-data`

| Field   | Type | Required | Description          |
|---------|------|----------|----------------------|
| `audio` | file | yes      | Audio file (WAV, FLAC, etc.) |

**Response:** `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### `POST /api/transcribe`

Standalone transcription endpoint. Returns transcription results directly without running the full pipeline (no diarization, speaker resolution, or analysis). Useful for real-time transcription, testing, and lightweight integrations.

Fallback chain: **GPU service → Mistral API → CPU** (self-hosted Voxtral on CPU, only if estimated processing time ≤ 1 minute). Returns an error if all backends fail or CPU processing would be too slow.

**Request:** `multipart/form-data`

| Field   | Type | Required | Description          |
|---------|------|----------|----------------------|
| `audio` | file | yes      | Audio file (WAV, FLAC, etc.) |

**Response:** `200 OK`
```json
{
  "text": "Hello world, this is a test.",
  "words": [
    {"word": "Hello", "start": 0.0, "end": 0.5},
    {"word": "world,", "start": 0.5, "end": 0.9},
    {"word": "this", "start": 1.0, "end": 1.2},
    {"word": "is", "start": 1.2, "end": 1.3},
    {"word": "a", "start": 1.3, "end": 1.4},
    {"word": "test.", "start": 1.4, "end": 1.8}
  ],
  "language": "en",
  "duration_ms": 1800
}
```

| Field         | Type          | Description |
|---------------|---------------|-------------|
| `text`        | string        | Full transcript text |
| `words`       | Word[]        | Word-level timestamps (populated via Mistral API; empty array if GPU/CPU was used) |
| `language`    | string \| null | Detected language (populated via Mistral API; null if GPU/CPU was used) |
| `duration_ms` | number        | Audio duration in milliseconds (populated via Mistral API; 0 if GPU/CPU was used) |

**Errors:**
- `400 Bad Request` — no `audio` field in multipart
- `500 Internal Server Error` — transcription failed

---

### `GET /api/jobs/{id}/events`

SSE stream of pipeline events. Connect immediately after creating a job.

**Response:** `text/event-stream`

```
event: phase_start
data: {"phase": "transcribing"}

event: transcript_token
data: {"token": "Hello "}

event: transcript_token
data: {"token": "world"}

event: transcript_complete
data: {"text": "Hello world", "words": [{"word": "Hello", "start": 0.0, "end": 0.5}, {"word": "world", "start": 0.5, "end": 1.0}], "language": "en", "duration_ms": 4200}

event: phase_start
data: {"phase": "diarizing"}

event: diarization_complete
data: {"segments": [{"speaker": "SPEAKER_0", "start": 0.0, "end": 3.5, "text": "Hello world", "is_overlap": false, "confidence": 0.95, "active_speakers": ["SPEAKER_0"]}]}

event: phase_start
data: {"phase": "resolving"}

event: tool_call
data: {"tool": "resolve_speaker", "args": {"diarization_speaker": "SPEAKER_0", "resolved_name": "Alice Chen", "confidence": 0.92, "evidence": "Introduced herself at 0:05"}}

event: tool_result
data: {"tool": "resolve_speaker", "result": "Resolved SPEAKER_0 → Alice Chen"}

event: speaker_resolved
data: {"label": "SPEAKER_0", "name": "Alice Chen", "confidence": 0.92, "method": "semantic"}

event: phase_start
data: {"phase": "analyzing"}

event: analysis_complete
data: {
  "decisions": [{"timestamp": 12.0, "summary": "Use React", "proposed_by": "Alice Chen", "seconded_by": "SPEAKER_1", "dissent_by": null, "status": "locked"}],
  "ambiguities": [{"timestamp": 45.0, "type": "commitment", "quote": "I'll look into it", "speaker": "SPEAKER_1", "confidence": 0.6, "candidates": ["will research", "noncommittal"]}],
  "action_items": [{"owner": "Alice Chen", "task": "Draft the RFC", "deadline_mentioned": "Friday", "verbatim_quote": "I'll have the RFC draft done by Friday"}],
  "meeting_dynamics": {"talk_time_pct": {"Alice Chen": 45.2, "SPEAKER_1": 54.8}, "interruption_count": 3}
}

event: done
data: {}
```

**Event types:**

| Event                  | Data fields | When |
|------------------------|-------------|------|
| `phase_start`          | `phase`: `"transcribing"` \| `"diarizing"` \| `"resolving"` \| `"analyzing"` | Pipeline enters a new phase |
| `transcript_token`     | `token`: string | Each token as transcription streams (self-hosted Voxtral only) |
| `transcript_complete`  | `text`: string, `words`: Word[], `language`: string \| null, `duration_ms`: number | Full transcript ready |
| `diarization_complete` | `segments`: Segment[] | Speaker-attributed segments ready |
| `tool_call`            | `tool`: string, `args`: object | Agent invoked a tool during speaker resolution |
| `tool_result`          | `tool`: string, `result`: string | Tool returned a result |
| `speaker_resolved`     | `label`: string, `name`: string, `confidence`: number, `method`: string | Agent resolved a speaker identity |
| `analysis_complete`    | `decisions`: Decision[], `ambiguities`: Ambiguity[], `action_items`: ActionItem[], `meeting_dynamics`: MeetingDynamics | Meeting analysis ready |
| `done`                 | `{}` | Pipeline finished |

---

### `GET /api/jobs/{id}/result`

Poll for job result (fallback when SSE is unavailable).

**Response:** `200 OK`
```json
{
  "status": "processing",
  "phase": "transcribing",
  "transcript": null,
  "segments": null,
  "decisions": null,
  "ambiguities": null,
  "action_items": null,
  "meeting_dynamics": null,
  "error": null
}
```

`status` is one of: `"processing"`, `"complete"`, `"error"`.

When `"complete"`, all fields are populated:
- `transcript`: string — full transcript text
- `segments`: Segment[] — speaker-attributed segments (with resolved names if available)
- `decisions`: Decision[] — identified decisions
- `ambiguities`: Ambiguity[] — flagged ambiguities
- `action_items`: ActionItem[] — extracted action items
- `meeting_dynamics`: MeetingDynamics — talk time and interruption stats
- `meeting_metadata`: MeetingMetadata — title (inferred from content), date (ISO 8601 if mentioned), duration, language. `title` and `date` are populated when extractable from the conversation; otherwise `null`.
- `error`: null

When `"error"`, only `error` is populated with a message.

---

## GPU Service — `localhost:8001`

Internal Python service for diarization, speaker embeddings, and voiceprint management. No auth.

### `GET /health`

**Response:**
```json
{
  "status": "ok",
  "gpu_available": true,
  "embedding_backend": "funasr_eres2netv2"
}
```

### `POST /diarize`

Speaker diarization — identifies who spoke when.

**Request:** `multipart/form-data`

| Field          | Type   | Required | Description             |
|----------------|--------|----------|-------------------------|
| `audio`        | file   | yes      | Audio file              |
| `min_speakers` | int    | no       | Minimum speaker count   |
| `max_speakers` | int    | no       | Maximum speaker count   |

**Response:**
```json
{
  "segments": [
    {"speaker": "SPEAKER_0", "start": 0.0, "end": 3.5},
    {"speaker": "SPEAKER_1", "start": 3.5, "end": 7.2}
  ]
}
```

### `POST /embed`

Generate speaker embedding vector from audio.

**Request:** `multipart/form-data`

| Field   | Type | Required |
|---------|------|----------|
| `audio` | file | yes      |

**Response:**
```json
{
  "embedding": [0.123, -0.456, "..."],
  "dim": 192
}
```

### `POST /voiceprint/identify`

Identify a speaker by matching audio against enrolled voiceprints. Optionally slice to a time range.

**Request:** `multipart/form-data`

| Field        | Type  | Required | Description                     |
|--------------|-------|----------|---------------------------------|
| `audio`      | file  | yes      | Audio file                      |
| `start_time` | float | no       | Start time in seconds (for slicing) |
| `end_time`   | float | no       | End time in seconds (for slicing)   |

**Response:**
```json
{
  "matches": [
    {"name": "Alice Chen", "similarity": 0.92},
    {"name": "Bob Smith", "similarity": 0.71}
  ]
}
```

### `POST /voiceprint/enroll`

Enroll a new speaker voiceprint from audio.

**Request:** `multipart/form-data`

| Field  | Type   | Required | Description       |
|--------|--------|----------|-------------------|
| `audio`| file   | yes      | Audio file        |
| `name` | string | yes      | Speaker name      |

**Response:**
```json
{
  "speaker_id": "alice_chen_0",
  "name": "Alice Chen"
}
```

### `GET /voiceprint/speakers`

List all enrolled speaker voiceprints.

**Response:**
```json
{
  "speakers": [
    {"id": "alice_chen_0", "name": "Alice Chen"},
    {"id": "bob_smith_0", "name": "Bob Smith"}
  ]
}
```

---

## Voxtral Transcription Server — `localhost:8080` (Optional)

Self-hosted fallback transcription server. Used when `MISTRAL_API_KEY` is not set. No auth. Does not provide word-level timestamps.

### `GET /health`

**Response:**
```json
{
  "status": "ok",
  "model": "mistralai/Voxtral-Mini-4B-Realtime-2602"
}
```

### `POST /transcribe`

Non-streaming transcription. Returns full text at once.

**Request:** `multipart/form-data`

| Field    | Type   | Required | Default                   |
|----------|--------|----------|---------------------------|
| `audio`  | file   | yes      |                           |
| `prompt` | string | no       | `"Transcribe this audio."` |

**Response:**
```json
{
  "text": "The transcribed text appears here."
}
```

### `POST /transcribe/stream`

Streaming transcription via SSE. Tokens arrive incrementally.

**Request:** same as `/transcribe`

**Response:** `text/event-stream`
```
event: token
data: {"token": "The "}

event: token
data: {"token": "transcribed "}

event: token
data: {"token": "text."}

event: done
data: {"text": "The transcribed text."}
```

| Event   | Data                   | Description                |
|---------|------------------------|----------------------------|
| `token` | `{"token": "..."}` | Incremental text chunk     |
| `done`  | `{"text": "..."}`  | Final assembled transcript |
| `error` | `{"error": "..."}`  | Error during inference     |

---

## Data Models

### Word
```json
{
  "word": "Hello",
  "start": 0.0,
  "end": 0.5
}
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

| Field             | Type     | Description |
|-------------------|----------|-------------|
| `speaker`         | string   | Speaker label or resolved name |
| `start`           | number   | Start time in seconds |
| `end`             | number   | End time in seconds |
| `text`            | string   | Segment text |
| `is_overlap`      | boolean  | Whether multiple speakers were active (default: false) |
| `confidence`      | number   | Alignment confidence 0-1 (default: 0) |
| `active_speakers` | string[] | All active speakers during overlap (default: []) |

### Decision
```json
{
  "timestamp": 12.0,
  "summary": "Adopt the new CI pipeline",
  "proposed_by": "SPEAKER_0",
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

| Field                | Type          | Description |
|----------------------|---------------|-------------|
| `owner`              | string        | Who is responsible |
| `task`               | string        | What needs to be done |
| `deadline_mentioned` | string \| null | Deadline if mentioned in conversation |
| `verbatim_quote`     | string \| null | Exact quote from the transcript |

### MeetingDynamics
```json
{
  "talk_time_pct": {
    "Alice Chen": 45.2,
    "SPEAKER_1": 54.8
  },
  "interruption_count": 3
}
```

| Field               | Type                    | Description |
|---------------------|-------------------------|-------------|
| `talk_time_pct`     | Record<string, number>  | Talk time percentage per speaker |
| `interruption_count`| number                  | Number of speaker interruptions |

---

## Pipeline Phases

The orchestrator runs a 4-phase pipeline:

| Phase          | Service              | Description |
|----------------|----------------------|-------------|
| `transcribing` | Mistral API (or self-hosted Voxtral) | Audio → text with word timestamps and language detection. Audio >30 min is automatically chunked (25 min chunks, 30s overlap) — transparent to the client. |
| `diarizing`    | GPU Service (Pyannote) | Speaker diarization + word-level alignment |
| `resolving`    | Mistral Large (agentic loop) | Multi-turn tool-calling to resolve speaker identities |
| `analyzing`    | Mistral Large | Extract decisions, ambiguities, action items |

### Degraded Mode (No GPU)

When the GPU service is unavailable, the pipeline degrades gracefully instead of failing:

| Feature | With GPU | Without GPU |
|---------|----------|-------------|
| Transcription | GPU Voxtral or Mistral API | Mistral API (unchanged) |
| Diarization | Pyannote (GPU) | Mistral API `diarize=true` (lower quality) |
| Acoustic matching | ERes2NetV2 embeddings | Skipped |
| Speaker enrollment | Available | Returns 503 |
| Agent resolution | Semantic + acoustic | Semantic only |

GPU health is checked per-phase with a 60s cache TTL and 15min inactivity reset. Each pipeline phase independently adapts to GPU state changes (recovery or failure mid-pipeline).

### Agent Tools (resolving phase)

The Mistral agent has access to 5 tools during speaker resolution:

| Tool                   | Description |
|------------------------|-------------|
| `resolve_speaker`      | Map a diarization label (e.g., SPEAKER_0) to a real name |
| `request_reanalysis`   | Re-analyze an audio segment via voiceprint matching |
| `merge_speakers`       | Merge two speaker labels that represent the same person |
| `flag_ambiguity`       | Flag an unresolvable speaker identity |
| `extract_action_items` | Extract structured action items from the conversation |

---

## Environment Variables

### Orchestrator
| Variable          | Default                        | Description                    |
|-------------------|--------------------------------|--------------------------------|
| `API_KEY`         | *(empty = no auth)*            | Bearer token for auth          |
| `VOXTRAL_URL`     | `http://192.168.0.105:8080`    | Self-hosted transcription server (fallback) |
| `DIARIZATION_URL` | `http://192.168.0.105:8001`    | GPU service address            |
| `MISTRAL_API_KEY` | *(empty)*                      | Mistral cloud API key (enables Mistral transcription + agent) |

### GPU Service
| Variable             | Default       | Description                    |
|----------------------|---------------|--------------------------------|
| `GPU_SERVICE_HOST`   | `0.0.0.0`    | Bind address                   |
| `GPU_SERVICE_PORT`   | `8001`        | Bind port                      |
| `EMBEDDING_BACKEND`  | `funasr`      | Embedding model (`funasr` or `speechbrain`) |

### Voxtral Transcription Server (CLI args)
| Flag             | Default                                       |
|------------------|-----------------------------------------------|
| `--host`         | `0.0.0.0`                                     |
| `--port`         | `8080`                                        |
| `--model-id`     | `mistralai/Voxtral-Mini-4B-Realtime-2602`     |
| `--quant`        | `q4k` (`q4k` \| `q5k` \| `q8k` \| `none`)   |
| `--gpu`          | off                                           |
| `--model-path`   | *(download from HF)*                          |
| `--tokenizer`    | *(use bundled)*                               |

---

## Quick Start Examples

**Full pipeline via orchestrator:**
```bash
# 1. Create job
JOB=$(curl -s -X POST http://localhost:8000/api/jobs \
  -H "Authorization: Bearer $API_KEY" \
  -F audio=@meeting.wav | jq -r .job_id)

# 2. Stream events
curl -N "http://localhost:8000/api/jobs/$JOB/events?token=$API_KEY"

# 3. Poll result (alternative to streaming)
curl "http://localhost:8000/api/jobs/$JOB/result?token=$API_KEY"
```

**Standalone transcription (no pipeline):**
```bash
curl -X POST http://localhost:8000/api/transcribe \
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
