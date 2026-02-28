# MeetingMind — Architecture

## Deployment Overview

```
GitHub (master)
    │
    │  push triggers GitHub Action
    ▼
HF Space: mistral-hackaton-2026/meetingmind
    │  Docker build (multi-stage)
    ▼
┌─────────────────────────────────────────────────┐
│  Container (port 7860)                          │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │  Rust Orchestrator (Axum)                 │  │
│  │  - /api/health (no auth)                  │  │
│  │  - /api/jobs, /api/jobs/{id}/events, ...  │  │
│  │  - /api/speakers/enroll, /api/speakers    │  │
│  │  - Static frontend (React SPA)            │  │
│  └─────────┬─────────────────┬───────────────┘  │
│            │                 │                   │
│   Local zvec store     Bearer token auth         │
│   (data/voiceprints/)  (API_KEY env)             │
└────────────┼─────────────────┼───────────────────┘
             │                 │
             ▼                 ▼
   Mistral API           HF Inference Endpoint
   ├── voxtral-mini      ├── POST /diarize (Pyannote)
   │   (transcription)   └── POST /embed  (FunASR ERes2NetV2)
   └── mistral-large
       (agent + analysis)
```

## Pipeline

The orchestrator runs a sequential pipeline per job:

| Phase | Service | What happens |
|-------|---------|-------------|
| **transcribing** | Mistral API (`voxtral-mini-latest`) | Audio → text with word-level timestamps. Auto-chunks audio >30 min |
| **diarizing** | HF Inference Endpoint (Pyannote) | Speaker diarization, drift correction, word-level alignment |
| **acoustic_matching** | HF Inference Endpoint (FunASR) + local zvec | Proactive voiceprint matching per speaker segment |
| **resolving** | Mistral API (`mistral-large-latest`) | Agentic tool-calling loop (5 tools, max 5 iterations) |
| **analyzing** | Mistral API (`mistral-large-latest`) | Extract decisions, ambiguities, action items, dynamics |

### Degraded Mode (No GPU)

When the HF Inference Endpoint is unavailable:

| Feature | With GPU | Without GPU |
|---------|----------|-------------|
| Transcription | Mistral API | Mistral API (unchanged) |
| Diarization | Pyannote | Mistral API `diarize=true` (lower quality) |
| Acoustic matching | ERes2NetV2 embeddings + zvec | Skipped |
| Speaker enrollment | Available | Returns 503 |
| Agent resolution | Semantic + acoustic | Semantic only |

## Key Components

### Orchestrator (`orchestrator/src/`)

| Module | Purpose |
|--------|---------|
| `main.rs` | Server setup, auth middleware, health endpoint, static file serving |
| `pipeline/types.rs` | Domain types, SSE events, GPU health cache, config |
| `pipeline/routes.rs` | HTTP handlers — job CRUD, SSE streaming, speaker enrollment |
| `pipeline/orchestrator.rs` | Pipeline coordinator — runs all phases sequentially |
| `pipeline/transcription.rs` | Mistral API transcription, audio chunking (>30 min), WAV parsing |
| `pipeline/diarization.rs` | GPU diarization, Mistral fallback, drift detection, word-speaker alignment |
| `pipeline/agent.rs` | 5-tool agent loop, speaker resolution, merge logic |
| `pipeline/alignment.rs` | Transcript-to-diarization alignment (LLM or proportional fallback) |
| `pipeline/analysis.rs` | Decision/ambiguity/action-item extraction, meeting dynamics |
| `pipeline/voiceprint.rs` | zvec-backed local voiceprint store (192-dim embeddings) |

### GPU Service (`gpu_service/hf_endpoint/`)

Stateless FastAPI service deployed as an HF Inference Endpoint. Exposes only:
- `POST /diarize` — Pyannote speaker diarization
- `POST /embed` — FunASR speaker embeddings (192-dim)
- `GET /health` — GPU availability check

### Frontend (`src/`)

React + Vite + Zustand + Zod. Key files:

| File | Purpose |
|------|---------|
| `api/backend.ts` | Backend URL discovery (HF Space vs local, with probe + cache) |
| `api/client.ts` | Zod schemas, auth helpers, `submitJob()` |
| `hooks/useSSE.ts` | SSE event stream + polling fallback |
| `store/appStore.ts` | Zustand store — all pipeline state |
| `components/Upload.tsx` | Drag-and-drop audio upload |
| `components/Processing.tsx` | Live progress + transcript + agent activity |
| `components/Results.tsx` | Tabbed results view |
| `components/Timeline.tsx` | Speaker-lane timeline with audio player |
| `components/Ledger.tsx` | Decision log + action items |
| `components/Clarification.tsx` | Ambiguity review (client-side only) |

## Environment Variables

### Orchestrator (required in HF Space settings)

| Variable | Default | Description |
|----------|---------|-------------|
| `MISTRAL_API_KEY` | — | Mistral API key (required) |
| `DIARIZATION_URL` | `http://192.168.0.105:8001` | HF Inference Endpoint URL |
| `API_KEY` | *(empty = no auth)* | Bearer token for API auth |
| `PORT` | `7860` | Listen port |
| `VOICEPRINT_STORE_PATH` | `data/voiceprints` | Local zvec store path |

### Frontend (build-time)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_HF_SPACE_URL` | `https://mistral-hackaton-2026-meetingmind.hf.space` | Override HF Space URL for backend discovery |

## Deploy

Push to `master` auto-deploys to HF Spaces via GitHub Action (`.github/workflows/deploy-hf.yml`).

Manual deploy: `./scripts/deploy-hf.sh`

## Legacy / Archived

The `archive/` directory contains previous iterations:
- `archive/gpu_service_legacy/` — Python voiceprint store (FAISS) and transcription module, replaced by orchestrator zvec + Mistral API
- `archive/server_legacy/` — Gen-2 Python FastAPI server (SQLite, WebSocket), fully replaced by Rust orchestrator
- `archive/scripts_legacy/` — LAN deployment scripts (systemd, port-proxy), replaced by HF Spaces Docker deploy
- `archive/server/` — Gen-1 prototype
- Evaluation scripts, AMI benchmark results
