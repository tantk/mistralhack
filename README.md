---
title: MeetingMind
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
---

# MeetingMind

MeetingMind is an AI-powered meeting intelligence system that turns uploaded audio into:
- timestamped transcript,
- speaker-attributed timeline,
- decisions,
- ambiguities requiring clarification,
- action items, and
- meeting dynamics metrics.

It is built as a multi-service stack with a Rust orchestrator, React frontend, and Python GPU service.

Architecture diagram: [meetingmind-architecture.html](meetingmind-architecture.html)

## Repository Overview

- `src/`: React + TypeScript frontend (Vite, Zustand, Zod, Framer Motion)
- `orchestrator/`: Rust Axum API + pipeline coordinator + static frontend serving
- `gpu_service/`: FastAPI GPU microservice (`/diarize`, `/embed`, optional transcription endpoints)
- `docs/`: API and hackathon documentation
- `e2e/`: Playwright end-to-end coverage
- `test_server/`: Python service-level tests for pipeline and GPU fallback behavior
- `archive/`: legacy implementations and evaluation artifacts

## End-to-End Architecture

Frontend talks to one backend surface (`/api` on orchestrator):

1. `POST /api/jobs` uploads meeting audio.
2. Frontend subscribes to `GET /api/jobs/{id}/events` (SSE).
3. If SSE is unavailable, frontend polls `GET /api/jobs/{id}/result`.
4. Orchestrator executes sequential phases:
	- transcribing
	- diarizing
	- acoustic_matching
	- resolving
	- analyzing
5. Orchestrator calls external/internal services:
	- Mistral API (`voxtral-mini-latest`, `mistral-large-latest`)
	- GPU service (`/diarize`, `/embed`)
	- local zvec voiceprint store
6. Final structured meeting output is returned through SSE completion + `/result`.

## Active Services

### 1) Rust Orchestrator (`orchestrator/`)

Primary API and pipeline runtime.

Key routes:
- `GET /api/health`
- `POST /api/transcribe`
- `POST /api/jobs`
- `GET /api/jobs/{id}/events`
- `GET /api/jobs/{id}/result`
- `POST /api/speakers/enroll`
- `GET /api/speakers`

Key modules:
- `orchestrator/src/pipeline/routes.rs`: HTTP handlers and SSE adapter
- `orchestrator/src/pipeline/orchestrator.rs`: phase orchestration and fallbacks
- `orchestrator/src/pipeline/transcription.rs`: Mistral transcription handling
- `orchestrator/src/pipeline/diarization.rs`: diarization + alignment
- `orchestrator/src/pipeline/agent.rs`: speaker resolution tool loop
- `orchestrator/src/pipeline/analysis.rs`: decisions, action items, ambiguities
- `orchestrator/src/pipeline/voiceprint.rs`: zvec-backed voiceprint store

### 2) Frontend (`src/`)

React app for upload, live processing, and results exploration.

Core files:
- `src/api/client.ts`: typed API boundaries and auth headers
- `src/api/backend.ts`: backend URL resolution (HF Space / local `/api`)
- `src/hooks/useSSE.ts`: SSE stream and polling fallback state hydration
- `src/store/appStore.ts`: Zustand application state
- `src/components/Upload.tsx`: file upload + attendees input
- `src/components/Processing.tsx`: live transcript and agent activity
- `src/components/Results.tsx`: timeline, ledger, and clarifications views

### 3) GPU Service (`gpu_service/`)

FastAPI GPU worker used by orchestrator for speaker tasks.

Primary routes:
- `GET /health`
- `POST /diarize`
- `POST /embed`

Additional legacy-compatible routes remain in service (`/voiceprint/*`, `/transcribe*`) but orchestrator uses `/diarize` and `/embed` for production flow.

## Processing Pipeline Details

### Phase 1 — Transcription
- Mistral transcription generates text + optional words/timestamps.
- Partial transcript tokens are streamed over SSE (`transcript_token`).

### Phase 2 — Diarization and Alignment
- Primary: GPU `/diarize`.
- Fallback: Mistral diarization when GPU unavailable.
- Transcript is aligned to speakers and grouped into segments.

### Phase 2.5 — Acoustic Matching
- For each diarization speaker, orchestrator extracts representative segment embedding via GPU `/embed`.
- Embeddings queried against zvec store for candidate speaker identity.

### Phase 3 — Resolution
- Agent loop resolves labels to attendee names using semantic + acoustic evidence.
- Threshold fallback applies when agent resolution fails.

### Phase 4 — Analysis
- Extracts decisions, ambiguities, action items, and meeting dynamics.
- Produces final structured result object.

## Voiceprint Storage (zvec)

zvec is used as a local in-process vector database.

- Default path: `data/voiceprints`
- Embedding dimension: 192 (GPU embedding model output)
- Usage:
  - enroll speaker embeddings
  - top-k cosine search for speaker re-identification

This avoids a separate external vector database for hackathon deployment.

## Environment Variables

### Orchestrator

- `MISTRAL_API_KEY` (required for transcription/analysis and fallback diarization)
- `DIARIZATION_URL` (GPU service URL)
- `GPU_TOKEN` (optional bearer token for GPU service)
- `API_KEY` (optional API auth; empty disables auth in dev)
- `PORT` (default `7860`)
- `VOICEPRINT_STORE_PATH` (default `data/voiceprints`)

### Frontend

- `VITE_HF_SPACE_URL` (optional override for remote backend probe)

### GPU Service

See `gpu_service/config.py` and `gpu_service/requirements.txt` for runtime dependencies and model config requirements.

## Local Development

### Frontend

```bash
npm install
npm run dev
```

### Orchestrator

```bash
cd orchestrator
cargo run
```

### GPU Service (optional but recommended)

```bash
pip install -r gpu_service/requirements.txt
python -m gpu_service.server
```

## Production/Container

- Docker entry is configured via root `Dockerfile` / `Dockerfile.hf`.
- HF Spaces deployment expects orchestrator to serve API and static frontend on one port.

## API Contract Summary

### `POST /api/jobs`
Multipart form:
- `audio` (required)
- `attendees` (optional JSON array string)

Returns:
```json
{ "job_id": "..." }
```

### `GET /api/jobs/{id}/events`
Server-sent events including:
- `phase_start`
- `transcript_token`
- `transcript_complete`
- `diarization_complete`
- `acoustic_matches_complete`
- `segments_resolved`
- `tool_call`
- `tool_result`
- `speaker_resolved`
- `analysis_complete`
- `done`

### `GET /api/jobs/{id}/result`
Returns accumulated job state with:
- `status` (`processing|complete|error`)
- `phase`
- partial/final result fields (`transcript`, `segments`, `decisions`, etc.)

## Validation Checklist

Minimum checks before merging:

```bash
npm run build
cd orchestrator && cargo test
curl http://localhost:7860/api/health
```

Optional:

```bash
npm run test:e2e
```

## Known Legacy Areas

- `archive/` contains previous Python-first and legacy Rust components.
- Those files are useful for reference/evaluation but are not part of the active runtime path.

## Security Notes

- Do not commit secrets.
- Keep `.env` local only.
- Use `API_KEY` for gating non-public deployments.
- Use `GPU_TOKEN` when GPU endpoint is protected.
