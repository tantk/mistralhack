---
tags:
  - audio
  - speech-to-text
  - streaming
  - voxtral
  - mistral
language:
  - en
library_name: custom
pipeline_tag: automatic-speech-recognition
license: apache-2.0
---

# Voxtral Realtime 4B

Streaming speech-to-text model with ~4 billion parameters. Weights in BF16 safetensors format, extracted from [mistralai/Voxtral-Mini-4B-Realtime-2602](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602).

## Architecture

**Pipeline:**
```
WAV → 16kHz → Mel Spectrogram → Conv Stem → Encoder → Downsample 4x → Adapter → Decoder → Tokens
```

- **Audio Encoder**: ~0.6B params — causal transformer, 32 layers
- **Audio-Language Adapter**: 2-layer MLP with 4x downsample
- **LLM Decoder**: ~3.4B params — Ministral-3 based, 26 layers with GQA

### Audio Preprocessing

| Parameter | Value |
|-----------|-------|
| Sample rate | 16,000 Hz |
| Frame rate | 12.5 Hz |
| Mel bins | 128 |
| Hop length | 160 samples (10ms) |
| Window size | 400 samples (25ms) |
| 1 text token | 80ms of audio |

### Encoder (Causal Transformer)

| Parameter | Value |
|-----------|-------|
| dim | 1280 |
| layers | 32 |
| heads | 32 (MHA) |
| head_dim | 64 |
| hidden_dim | 5120 |
| FFN | SwiGLU |
| Norm | RMSNorm (eps=1e-5) |
| Position | RoPE (theta=1e6, interleaved) |
| Attention | causal, sliding window=750 |

Conv stem: `conv1d(128→1280, k=3, s=1)` → GELU → `conv1d(1280→1280, k=3, s=2)` → GELU

### Adapter

```
[seq/4, 5120] → Linear(5120→3072) → GELU → Linear(3072→3072) → [seq/4, 3072]
```

### Decoder (LLM)

| Parameter | Value |
|-----------|-------|
| dim | 3072 |
| layers | 26 |
| heads | 32 |
| KV heads | 8 (GQA 4:1) |
| head_dim | 128 |
| hidden_dim | 9216 |
| Norm | RMSNorm (eps=1e-5) |
| Position | RoPE (theta=1e6) |
| Attention | causal, sliding window=8192 |
| Vocab size | 131,072 |
| Tied embeddings | yes |

The decoder uses adaptive RMS normalization conditioned on transcription delay (6 delay tokens = 480ms).

## Weight Format

- **`consolidated.safetensors`** (8.3 GB) — 711 tensors, all BF16
- **`params.json`** — model config
- **`tekken.json`** (14.9 MB) — Tekken tokenizer

## Tokenizer (Tekken)

| Token | ID |
|-------|----|
| BOS | 1 |
| EOS | 2 |
| STREAMING_PAD | 32 |

Token IDs 0–999 are special tokens. IDs 1000+ index into the vocabulary (base64-encoded byte sequences in `tekken.json`).

### Audio Streaming Config

| Parameter | Value |
|-----------|-------|
| sampling_rate | 16,000 |
| frame_rate | 12.5 (80ms per token) |
| transcription_delay_ms | 480 (6 delay tokens) |
| left_pad_tokens | 32 |
| right_pad_tokens (offline) | 17 |

## Decode Schedule (Offline)

1. **Prompt**: `[BOS] + [STREAMING_PAD] × 38` (1 + 32 left-pad + 6 delay)
2. **Prefill**: Feed `audio_embed[i] + tok_embed(prompt[i])` for positions 0..L-2
3. **First token**: Greedy argmax from position L-1
4. **Autoregressive decode**: For each remaining audio position, feed `audio_embed[pos] + tok_embed(prev_token)`, greedy argmax
5. **Stop**: On EOS or end of audio span

## C Implementation

A pure C implementation of this model is available at [voxtral.c](https://github.com/tantk/mistralhack/tree/master/voxtral.c) — runs on Apple Silicon (Metal) and CPU (BLAS), with streaming microphone input.

## Credits

Original model by [Mistral AI](https://mistral.ai/): [`mistralai/Voxtral-Mini-4B-Realtime-2602`](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)

Built for the [Mistral Hackathon 2026](https://huggingface.co/mistral-hackaton-2026).
