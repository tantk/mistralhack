# VoiceGraph — Infrastructure Architecture

## Network Topology

```
┌──────────────────────────────────────────────────────────────────────┐
│                          INTERNET                                    │
│                                                                      │
│   External devices (no VPN, no Tailscale)                            │
│   curl https://tan.tail2e1adb.ts.net/api/transcribe                  │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       │  Tailscale Funnel (HTTPS, public)
                       │
┌──────────────────────▼───────────────────────────────────────────────┐
│  tan — NUC Linux Server (Intel NUC)                                  │
│  Hostname: tan                                                       │
│  LAN: 192.168.0.121  |  Tailscale: 100.121.213.25                    │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  server (FastAPI + Uvicorn)                            │      │
│  │  Port: 8000                                                │      │
│  │  systemd: server.service (user)                        │      │
│  │                                                            │      │
│  │  Endpoints:                                                │      │
│  │    GET  /                     → Web UI (static)            │      │
│  │    POST /api/transcribe       → Proxy to titan (HTTP API)  │      │
│  │    WS   /ws/transcribe/{id}   → Real-time meeting stream   │      │
│  │    POST /api/meetings         → CRUD meetings              │      │
│  │    POST /api/meetings/{id}/diarize → Trigger diarization   │      │
│  └────────────────────────────────────────────────────────────┘      │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  Tailscale Funnel                                          │      │
│  │  Public URL: https://tan.tail2e1adb.ts.net                 │      │
│  │  Proxies HTTPS → http://127.0.0.1:8000                     │      │
│  │  Persistent config (survives reboots)                      │      │
│  └────────────────────────────────────────────────────────────┘      │
│                                                                      │
│  Storage:                                                            │
│    meetings.db         — SQLite (meetings + transcript segments)      │
│    audio_storage/      — WAV files per meeting                       │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       │  LAN: 192.168.0.x (preferred, lower latency)
                       │  Tailscale: 100.67.74.52 (fallback)
                       │
┌──────────────────────▼───────────────────────────────────────────────┐
│  titan — Windows GPU Machine                                         │
│  LAN: 192.168.0.105  |  Tailscale: 100.67.74.52                     │
│  WSL2 gateway: 172.17.144.1                                          │
│                                                                      │
│  ┌─────────────────────────────────┐  ┌────────────────────────────┐ │
│  │  Voxtral Transcription (Rust)   │  │  Diarization (Python)      │ │
│  │  mistral.rs + Voxtral Mini 4B   │  │  Pyannote 3.1 (CUDA)      │ │
│  │  Port: 8080                     │  │  Port: 8001                │ │
│  │                                 │  │                            │ │
│  │  POST /transcribe               │  │  POST /diarize             │ │
│  │    → multipart: audio file      │  │    → multipart: audio file │ │
│  │    ← {"text": "..."}            │  │    ← {"segments": [...]}   │ │
│  │                                 │  │                            │ │
│  │  GET /health                    │  │                            │ │
│  │    ← {"status":"ok",            │  │                            │ │
│  │       "model":"...Voxtral..."}  │  │                            │ │
│  └─────────────────────────────────┘  └────────────────────────────┘ │
│                                                                      │
│  Runs inside WSL2 (Ubuntu) on Windows host                           │
│  NVIDIA GPU passthrough via CUDA                                     │
└──────────────────────────────────────────────────────────────────────┘
```

## Request Flow

### External device → Transcription

```
External device
  │
  │  HTTPS POST /api/transcribe  (audio file)
  ▼
Tailscale Funnel (tan.tail2e1adb.ts.net)
  │
  │  HTTP → localhost:8000
  ▼
NUC FastAPI (server)
  │
  │  HTTP POST /transcribe  (multipart)
  ▼
titan:8080 (mistral.rs / Voxtral)
  │
  │  {"text": "transcribed text"}
  ▼
Response back through the chain
```

### Browser → Real-time meeting transcription

```
Browser (LAN)
  │
  │  WebSocket /ws/transcribe/{meeting_id}
  ▼
NUC FastAPI
  │  1. Receives audio chunks (WebM)
  │  2. Converts WebM → WAV (16kHz mono)
  │  3. Sends WAV to titan:8080/transcribe
  │  4. Stores segment in SQLite
  │  5. Sends transcript back via WebSocket
  │
  │  On meeting end + diarize request:
  │  6. Sends full audio to titan:8001/diarize
  │  7. Merges speaker labels with transcript by timestamp overlap
  ▼
titan (GPU)
  ├── :8080  Voxtral (real-time transcription)
  └── :8001  Pyannote (speaker diarization)
```

## Machines

| Name | Role | OS | IP (LAN) | IP (Tailscale) | Hardware |
|------|------|----|-----------|----------------|----------|
| **tan** | API gateway, web UI, orchestrator | Linux (Ubuntu) | 192.168.0.121 | 100.121.213.25 | Intel NUC |
| **titan** | GPU inference (transcription + diarization) | Windows + WSL2 | 192.168.0.105 | 100.67.74.52 | NVIDIA GPU |

## Services

### tan (NUC)

| Service | Type | Port | Command |
|---------|------|------|---------|
| server | systemd user service | 8000 | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Tailscale Funnel | tailscale config | 443→8000 | `tailscale funnel --bg 8000` |

```bash
# Manage NUC server
systemctl --user status server
systemctl --user restart server
journalctl --user -u server -f

# Manage funnel
tailscale funnel status
tailscale funnel --bg 8000        # enable
tailscale funnel --https=443 off  # disable
```

### titan (Windows GPU)

| Service | Port | Backend |
|---------|------|---------|
| Voxtral transcription | 8080 | Rust (mistral.rs) serving Voxtral-Mini-4B-Realtime-2602 |
| Speaker diarization | 8001 | Python (FastAPI) running pyannote/speaker-diarization-3.1 |

## Configuration

### NUC `.env` (server/.env)

```bash
# titan - Windows GPU machine
# Tailscale: 100.67.74.52 | LAN: 192.168.0.105 | WSL gateway: 172.17.144.1
MISTRAL_RS_URL=http://192.168.0.105:8080    # LAN preferred (Tailscale fallback: 100.67.74.52:8080)
DIARIZATION_URL=http://192.168.0.105:8001   # LAN preferred (Tailscale fallback: 100.67.74.52:8001)
DATABASE_PATH=meetings.db
AUDIO_STORAGE_PATH=audio_storage
```

## API Reference

### Public endpoint (via Tailscale Funnel)

**Transcribe audio:**
```bash
curl -X POST https://tan.tail2e1adb.ts.net/api/transcribe \
  -F "audio=@recording.wav"
```

**Response:**
```json
{"text": "Hello, this is the transcribed text."}
```

### Direct to titan (LAN only)

```bash
# Transcription
curl -X POST http://192.168.0.105:8080/transcribe \
  -F "audio=@recording.wav"

# With custom prompt
curl -X POST http://192.168.0.105:8080/transcribe \
  -F "audio=@recording.wav" \
  -F "prompt=Transcribe with punctuation and speaker labels."

# Health check
curl http://192.168.0.105:8080/health
```

## Dependencies

### NUC (Python 3.14)

```
fastapi, uvicorn[standard], aiosqlite, httpx, pydub, python-multipart, websockets, python-dotenv
```

Also requires: `ffmpeg`, `audioop-lts` (Python 3.13+ compatibility)

### titan (WSL2)

- **Rust backend:** mistral.rs + Voxtral model weights
- **Python diarization:** pyannote.audio, torch (CUDA), soundfile
- **System:** NVIDIA drivers (Windows host), CUDA toolkit (WSL2)
