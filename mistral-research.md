# Mistral AI — Complete Research

## Overview

Mistral AI is a Paris-based AI company founded by former researchers from Google DeepMind and Meta. They focus on open-source models released under Apache 2.0, with a full stack covering text, code, vision, audio, OCR, embeddings, moderation, and image generation.

Models are available via their own API (La Plateforme), as well as AWS Bedrock, Azure, Google Cloud, HuggingFace, IBM WatsonX, Snowflake, and more.

API Console: https://console.mistral.ai/

---

## Models

### Flagship / Large Models

| Model | Params | Context | Price (Input / Output per 1M tokens) | Notes |
|---|---|---|---|---|
| Mistral Large 3 (2512) | 675B total, 41B active (MoE) | — | $0.50 / $1.50 | Sparse mixture-of-experts, Apache 2.0 |
| Mistral Large 3 (older) | — | — | $2.00 / $6.00 | Previous generation |
| Mistral Medium 3.1 | — | — | $0.40 / $2.00 | Great at coding/STEM, long docs |
| Mistral Medium 3 | — | — | $0.40 / $2.00 | Versatile, GPT-4 class at fraction of cost |
| Pixtral Large | — | — | ~$2.00 / $6.00 | Frontier multimodal (text + vision), Nov 2024 |

### Small / Edge Models

| Model | Params | Context | Price (Input / Output per 1M tokens) | Notes |
|---|---|---|---|---|
| Mistral Small 3.2 24B | 24B | 128K | $0.06 / $0.18 | Best cost-performance ratio, multimodal |
| Mistral Small 3.1 24B | 24B | 128K | $0.35 / $0.56 | Multimodal |
| Mistral Small Creative | — | 33K | $0.10 / $0.30 | Creative writing & character interaction |
| Ministral 14B | 14B | — | — | Edge model, vision capable |
| Ministral 8B | 8B | — | $0.10 / $0.10 | Edge model, vision capable |
| Ministral 3B | 3B | — | ~$0.02 | Ultra-light edge model |
| Mistral Nemo | — | — | $0.02 (input) | Cheapest model, multilingual |
| Saba | — | — | $0.20 / $0.60 | Released Feb 2025 |

### Reasoning Models

| Model | Notes |
|---|---|
| Magistral Small | Chain-of-thought reasoning, open-source, released Jun 2025 |
| Magistral Medium | Stronger reasoning, closed-source, released Jun 2025 |

### Code Models

| Model | Params | Context | Price (Input / Output per 1M tokens) | Notes |
|---|---|---|---|---|
| Devstral 2 | — | — | — | Frontier code agent, SWE tasks, Dec 2025 |
| Devstral Small 2 | 24B | 256K | $0.10 / $0.30 | Beats Qwen 3 Coder Flash (30B), Apache 2.0, image inputs |
| Devstral Small 1.1 | — | — | $0.10 / $0.30 | Jul 2025 |
| Devstral Medium | — | — | $0.40 / $2.00 | Jul 2025 |
| Codestral 2 | — | — | — | Code completion & FIM, 80+ languages |
| Codestral 2508 | — | — | $0.30 / $0.90 | Aug 2025 |

---

## Voice / Audio Models (Voxtral)

### Transcription Models (Voxtral Transcribe 2 — Feb 2026)

| Model | API ID | Use Case | Price | Notes |
|---|---|---|---|---|
| Voxtral Mini Transcribe V2 | `voxtral-mini-2602` | Batch transcription | $0.003/min | ~4% WER, diarization, word timestamps |
| Voxtral Realtime | — | Live/streaming | $0.006/min | Sub-200ms latency possible, 4B params |

#### Voxtral Mini Transcribe V2 Features
- State-of-the-art accuracy (~4% word error rate on FLEURS)
- Speaker diarization (identifies who said what)
- Context biasing for up to 100 custom words/phrases
- Word-level timestamps
- 13 languages: EN, ZH, HI, ES, AR, FR, PT, RU, DE, JA, KO, IT, NL
- Outperforms GPT-4o mini Transcribe, Gemini 2.5 Flash, Assembly Universal, Deepgram Nova
- 3x faster than ElevenLabs Scribe v2 at 1/5 the cost
- Supports MP3, WAV, M4A, FLAC, OGG up to 1GB per file

#### Voxtral Realtime Features
- Natively streaming architecture with custom causal audio encoder
- Configurable delay: 240ms to 2.4s (balance latency vs accuracy)
- At 480ms delay: within 1-2% WER (near-offline accuracy)
- 4B parameters — runs on a single GPU with >=16GB memory
- Open weights under Apache 2.0 (on HuggingFace)
- Ideal for voice agents and real-time applications

### Multimodal Audio Models

| Model | Params | Price (Input / Output per 1M tokens) | Notes |
|---|---|---|---|
| Voxtral Small 24B | 24B | $0.10 / $0.30 | Audio understanding, Q&A from speech, summarization |
| Voxtral Mini 3B | 3B | Self-hostable | Edge-friendly, ~9.5GB GPU RAM in bf16 |

#### Capabilities
- Answer questions directly from audio
- Summarize meetings/calls
- Translate speech
- 32K token context — handles up to 30 min audio (transcription) or 40 min (understanding)
- Function calling from voice
- Released Jul 2025, Apache 2.0

---

## Specialized Services

### OCR

| Model | Price | Notes |
|---|---|---|
| Mistral OCR 3 | $2.00 / 1K pages | Forms, handwriting, low-quality scans, tables |

- Major upgrade over OCR 2 (Dec 2025)
- Markdown output with HTML-based table reconstruction
- 50% discount with Batch API

### Embeddings

- Converts text to numerical vector representations
- Ideal for semantic search, RAG, sentiment analysis, text classification
- E5-Mistral variant can be self-hosted and fine-tuned

### Moderation

- Fine-tuned content safety model
- 9 safety categories (hate/discrimination, violence/threats, etc.)
- Multilingual support
- Works on raw text and conversational content

### Image Generation

- Built-in agent tool for generating images
- Enabled through agents/conversations API
- Create an agent with image generation tool enabled

---

## Pricing Summary

### Text Models — What $15 Gets You

| Tier | Model | $15 Budget |
|---|---|---|
| Cheapest | Mistral Small 3.2 ($0.06/$0.18) | ~250M input or ~83M output tokens |
| Cheapest | Ministral 8B ($0.10/$0.10) | ~150M input/output tokens |
| Budget | Mistral Small Creative ($0.10/$0.30) | ~150M input or ~50M output tokens |
| Mid-tier | Codestral 2508 ($0.30/$0.90) | ~50M input or ~16M output tokens |
| Mid-tier | Mistral Medium 3.1 ($0.40/$2.00) | ~37M input or ~7.5M output tokens |
| Premium | Mistral Large 3 ($2.00/$6.00) | ~7.5M input or ~2.5M output tokens |

### Voice Models — What $15 Gets You

| Model | $15 Budget |
|---|---|
| Voxtral Mini Transcribe V2 ($0.003/min) | ~83 hours of audio |
| Voxtral Realtime ($0.006/min) | ~41 hours of audio |

### Cost Comparisons
- Mistral Medium 3 ($0.40/$2.00) vs OpenAI GPT-4 ($2.50/$10.00) — similar quality, ~5x cheaper
- Voxtral ($0.003/min) vs Whisper ($0.006/min) — half the price, better accuracy
- Voxtral vs ElevenLabs Scribe v2 — 1/5 the cost, 3x faster

---

## Key Differentiators

- **Open-source first** — Most models released under Apache 2.0
- **MoE architecture** — Large 3 has 675B total params but only 41B active (fast + efficient)
- **Full stack** — Text, code, vision, audio, OCR, embeddings, moderation, image generation
- **Self-hostable** — Many models run on consumer GPUs via HuggingFace
- **Multi-cloud** — AWS Bedrock, Azure, Google Cloud, HuggingFace, IBM WatsonX, Snowflake, etc.
- **Edge-friendly** — Ministral and Voxtral Mini designed for on-device deployment

---

## Useful Links

- Models: https://mistral.ai/models
- Documentation: https://docs.mistral.ai/getting-started/models
- Pricing: https://mistral.ai/pricing
- API Console: https://console.mistral.ai/
- HuggingFace: https://huggingface.co/mistralai
- Voxtral Realtime Weights: https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602
- Voxtral Transcribe Docs: https://docs.mistral.ai/models/voxtral-mini-transcribe-26-02

---

---

## Local Transcription API (Voxtral Realtime on titan)

The Voxtral Mini 4B Realtime model is self-hosted on titan (Windows GPU machine) via mistral.rs.

### Endpoint

```
POST http://192.168.0.105:8080/transcribe
```

Multipart form data with:
- `audio` (required) — the audio file
- `prompt` (optional) — custom instruction, defaults to "Transcribe this audio."

### Examples

Basic transcription:
```bash
curl -X POST http://192.168.0.105:8080/transcribe \
  -F "audio=@recording.wav"
```

With a custom prompt:
```bash
curl -X POST http://192.168.0.105:8080/transcribe \
  -F "audio=@recording.wav" \
  -F "prompt=Transcribe this audio with punctuation and speaker labels."
```

### Response

```json
{"text": "Hello, this is the transcribed text."}
```

---

*Research compiled February 28, 2026*
