# MeetingMind API Reference

## Architecture Overview

```
Browser ──► Orchestrator (Rust :3000) ──► Voxtral Transcription (Rust :8080)
                │                     ──► GPU Service (Python :8001)
                │                     ──► Mistral Cloud API
                ▼
         Static frontend
```

All public-facing requests go through the **Orchestrator**, which handles auth, job management, and SSE streaming. Internal services (Voxtral, GPU Service) run on the LAN without auth.

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

## Orchestrator — `localhost:3000`

### `POST /api/jobs`

Create a processing job. Uploads audio and starts the full pipeline (transcribe → diarize → analyze).

**Request:** `multipart/form-data`

| Field   | Type | Required | Description          |
|---------|------|----------|----------------------|
| `audio` | file | yes      | WAV audio file       |

**Response:** `200 OK`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

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
data: {"text": "Hello world", "duration_ms": 4200}

event: phase_start
data: {"phase": "diarizing"}

event: diarization_complete
data: {"segments": [{"speaker": "SPEAKER_0", "start": 0.0, "end": 3.5, "text": "Hello world"}]}

event: phase_start
data: {"phase": "analyzing"}

event: analysis_complete
data: {
  "decisions": [{"timestamp": 12.0, "summary": "Use React", "proposed_by": "SPEAKER_0", "seconded_by": "SPEAKER_1", "dissent_by": null, "status": "locked"}],
  "ambiguities": [{"timestamp": 45.0, "type": "commitment", "quote": "I'll look into it", "speaker": "SPEAKER_1", "confidence": 0.6, "candidates": ["will research", "noncommittal"]}],
  "action_items": ["SPEAKER_0: Draft the RFC by Friday"]
}

event: done
data: {}
```

**Event types:**

| Event                  | Data fields                                                         | When                              |
|------------------------|---------------------------------------------------------------------|-----------------------------------|
| `phase_start`          | `phase`: `"transcribing"` \| `"diarizing"` \| `"analyzing"`        | Pipeline enters a new phase       |
| `transcript_token`     | `token`: string                                                     | Each token as transcription streams |
| `transcript_complete`  | `text`: string, `duration_ms`: number                               | Full transcript ready             |
| `diarization_complete` | `segments`: Segment[]                                               | Speaker-attributed segments ready |
| `analysis_complete`    | `decisions`: Decision[], `ambiguities`: Ambiguity[], `action_items`: string[] | Meeting analysis ready |
| `done`                 | `{}`                                                                | Pipeline finished                 |

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
  "error": null
}
```

`status` is one of: `"processing"`, `"complete"`, `"error"`.

When `"complete"`, all fields are populated.

---

## Voxtral Transcription Server — `localhost:8080`

Internal service. No auth.

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

**curl example:**
```bash
curl -N -X POST http://localhost:8080/transcribe/stream \
  -F audio=@meeting.wav \
  -F prompt="Transcribe this audio."
```

---

## GPU Service — `localhost:8001`

Internal Python service for diarization and speaker embeddings. No auth.

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
  "embedding": [0.123, -0.456, ...],
  "dim": 192
}
```

---

## Data Models

### Segment
```json
{
  "speaker": "SPEAKER_0",
  "start": 0.0,
  "end": 3.5,
  "text": "Hello everyone, let's get started."
}
```

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

---

## Environment Variables

### Orchestrator
| Variable          | Default                        | Description                    |
|-------------------|--------------------------------|--------------------------------|
| `API_KEY`         | *(empty = no auth)*            | Bearer token for auth          |
| `VOXTRAL_URL`     | `http://192.168.0.105:8080`    | Transcription server address   |
| `DIARIZATION_URL` | `http://192.168.0.105:8001`    | GPU service address            |
| `MISTRAL_API_KEY` | *(empty)*                      | Mistral cloud API key          |

### Transcription Server (CLI args)
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
JOB=$(curl -s -X POST http://localhost:3000/api/jobs \
  -H "Authorization: Bearer $API_KEY" \
  -F audio=@meeting.wav | jq -r .job_id)

# 2. Stream events
curl -N "http://localhost:3000/api/jobs/$JOB/events?token=$API_KEY"
```

**Direct transcription (no orchestrator):**
```bash
# Non-streaming
curl -X POST http://localhost:8080/transcribe -F audio=@meeting.wav

# Streaming
curl -N -X POST http://localhost:8080/transcribe/stream -F audio=@meeting.wav
```
