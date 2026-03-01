---
title: MeetingMind
emoji: 🎙️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
---

# MeetingMind

AI-powered meeting analysis — upload audio and get speaker-attributed transcripts, decisions, action items, and meeting dynamics.

Built with Rust (Axum), React, and Mistral AI for the Mistral hackathon.

## How It Works

1. Audio is transcribed with Mistral (`voxtral-mini-latest`).
2. Speaker diarization and embeddings come from the GPU endpoint (`/diarize`, `/embed`).
3. The orchestrator resolves speakers, extracts decisions/action items, and streams progress via SSE.

## zvec Voiceprint Store

`zvec` is used in the Rust orchestrator as an in-process local vector store for speaker voiceprints (`data/voiceprints` by default).

- On speaker enrollment, a 192-d embedding is inserted into zvec with speaker metadata.
- During acoustic matching, new embeddings are queried against zvec using cosine similarity (top-k nearest matches).
- This enables fast, local speaker re-identification across meetings without an external vector database.
