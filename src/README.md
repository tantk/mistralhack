# Make Meeting Analyses Great Again — Frontend

## Backend Compatibility Analysis

### What the plan got right
- Rust as the single orchestrator the frontend hits is the correct call — avoids CORS complexity with two backends
- SSE + polling fallback is pragmatic and production-appropriate
- Job queue in-memory is fine for a hackathon demo

### Issues identified and fixed

#### 1. Python GPU service is never hit directly by the frontend
The plan correctly states Rust orchestrates everything, but it wasn't explicit that `/diarize` and `/embed` are **internal** calls from Rust → Python. The `backend_jobs.rs` makes this explicit: `call_python_diarize` and `call_python_embed` are internal async calls. CORS on the Python service is technically optional (Rust → Python is server-to-server), but add it anyway for local dev curl testing.

#### 2. SSE polling fallback uses `/result` not `/status`
The original plan said `GET /jobs/:id/status`. Changed to `/result` which returns the full accumulated state — otherwise the polling fallback can't recover mid-pipeline results if it kicks in after transcription already completed.

#### 3. Word reveal must not block on SSE transcript
`useWordReveal` starts immediately when `transcript` is set in the store, regardless of SSE vs polling path. Both paths call `store.setTranscript()`, so the word reveal is transport-agnostic.

#### 4. WaveSurfer instance lifecycle
Single instance per session. `wavesurfer.load()` is called on URL change, not `destroy()` + `create()`. Prevents memory leaks and flickering on re-upload.

#### 5. Zustand `useStore.getState()` in Results.tsx
Used inside `Results.tsx` for `pendingClarifs` badge to avoid subscribing the entire Results to ambiguity resolution state on every keypress. This is intentional — call `.getState()` for non-reactive reads inside event handlers/derived values.

---

## Stack
- Vite + React 19 + TypeScript
- Zustand 5
- Framer Motion 11
- WaveSurfer.js 7
- Zod (runtime API validation)

## Project Structure
```
src/
  api/client.ts          Zod schemas + typed fetch
  store/appStore.ts      Zustand state machine
  hooks/
    useSSE.ts            EventSource + polling fallback
    useWordReveal.ts     rAF word reveal
  components/
    Upload.tsx
    Processing.tsx
    Timeline.tsx
    Ledger.tsx
    Clarification.tsx
    AudioPlayer.tsx
    Results.tsx
  App.tsx
  index.css
```

## Dev setup
```bash
npm install
npm run dev
# Vite proxies /api → http://localhost:8080 (your Rust backend)
```

## Backend changes required
See `backend_jobs.rs` for the Rust job queue + SSE module (~150 lines including types).
See `backend_python_cors.py` for the one-liner Python CORS addition.

### Cargo.toml additions
```toml
axum = { version = "0.7", features = ["multipart"] }
tower-http = { version = "0.5", features = ["cors"] }
tokio-stream = { version = "0.1", features = ["sync"] }
uuid = { version = "1", features = ["v4"] }
broadcast = "0.1"
```
