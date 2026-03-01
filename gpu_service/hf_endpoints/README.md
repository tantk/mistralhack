---
tags:
  - audio
  - speaker-diarization
  - speaker-embedding
  - pyannote
  - funasr
  - meetingmind
library_name: custom
pipeline_tag: audio-classification
---

# MeetingMind GPU Service

GPU-accelerated speaker diarization and embedding extraction for the MeetingMind pipeline. Runs as an HF Inference Endpoint on a T4 GPU with scale-to-zero.

## API

### `GET /health`

Returns service status and GPU availability.

```bash
curl -H "Authorization: Bearer $HF_TOKEN" $ENDPOINT_URL/health
```

```json
{"status": "ok", "gpu_available": true}
```

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
| `PYANNOTE_MIN_SPEAKERS` | `1` | Minimum speakers for diarization |
| `PYANNOTE_MAX_SPEAKERS` | `10` | Maximum speakers for diarization |

## Architecture

- **Base image**: `pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime`
- **Diarization**: pyannote/speaker-diarization-community-1 (~2GB VRAM)
- **Embeddings**: FunASR CAM++ sv_zh-cn_16k-common (~200MB)
- **Total VRAM**: ~3GB (fits T4 16GB with headroom)
- **Scale-to-zero**: 15 min idle timeout (~$0.60/hr when active)
