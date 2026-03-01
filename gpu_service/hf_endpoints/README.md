---
tags:
  - audio
  - speech-to-text
  - speaker-diarization
  - speaker-embedding
  - voxtral
  - pyannote
  - funasr
  - meetingmind
library_name: custom
pipeline_tag: automatic-speech-recognition
---

# MeetingMind GPU Endpoint

GPU-accelerated speech-to-text, speaker diarization, and embedding extraction for the MeetingMind pipeline. Runs as an HF Inference Endpoint on a T4 GPU with scale-to-zero.

**Model weights**: [`mistral-hackaton-2026/voxtral_model`](https://huggingface.co/mistral-hackaton-2026/voxtral_model) — Voxtral Realtime 4B (BF16 safetensors, loaded from `/repository/voxtral-model/`)

## API

### `GET /health`

Returns service status and GPU availability.

```bash
curl -H "Authorization: Bearer $HF_TOKEN" $ENDPOINT_URL/health
```

```json
{"status": "ok", "gpu_available": true}
```

### `POST /transcribe`

Speech-to-text using Voxtral Realtime 4B. Returns full transcription.

```bash
curl -X POST \
  -H "Authorization: Bearer $HF_TOKEN" \
  -F audio=@speech.wav \
  $ENDPOINT_URL/transcribe
```

```json
{"text": "Hello, this is a test of the voxtral speech to text system."}
```

### `POST /transcribe/stream`

Streaming speech-to-text via SSE. Tokens are emitted as they are generated.

```bash
curl -X POST \
  -H "Authorization: Bearer $HF_TOKEN" \
  -F audio=@speech.wav \
  $ENDPOINT_URL/transcribe/stream
```

Events: `token` (partial), `done` (final text), `error`.

### `POST /diarize`

Speaker diarization using pyannote v4. Accepts any audio format (FLAC, WAV, MP3, etc.).

```bash
curl -X POST \
  -H "Authorization: Bearer $HF_TOKEN" \
  -F audio=@meeting.flac \
  -F min_speakers=2 \
  -F max_speakers=6 \
  $ENDPOINT_URL/diarize
```

```json
{
  "segments": [
    {"speaker": "SPEAKER_00", "start": 0.5, "end": 3.2, "duration": 2.7},
    {"speaker": "SPEAKER_01", "start": 3.4, "end": 7.1, "duration": 3.7}
  ]
}
```

### `POST /embed`

Speaker embedding extraction using FunASR CAM++. Returns L2-normalized 192-dim vectors for voiceprint matching.

```bash
curl -X POST \
  -H "Authorization: Bearer $HF_TOKEN" \
  -F audio=@meeting.flac \
  -F start_time=1.0 \
  -F end_time=5.0 \
  $ENDPOINT_URL/embed
```

```json
{"embedding": [0.012, -0.034, ...], "dim": 192}
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HF_TOKEN` | (required) | Hugging Face token for pyannote model access |
| `VOXTRAL_MODEL_DIR` | `/repository/voxtral-model` | Path to Voxtral model weights |
| `PYANNOTE_MIN_SPEAKERS` | `1` | Minimum speakers for diarization |
| `PYANNOTE_MAX_SPEAKERS` | `10` | Maximum speakers for diarization |

## Architecture

- **Base image**: `pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime`
- **Transcription**: Voxtral Realtime 4B via direct safetensors loading (~8GB VRAM)
- **Diarization**: pyannote/speaker-diarization-community-1 (~2GB VRAM)
- **Embeddings**: FunASR CAM++ sv_zh-cn_16k-common (~200MB)
- **Scale-to-zero**: 15 min idle timeout (~$0.60/hr when active)
