#!/usr/bin/env python3
"""
Test voiceprint speaker identification using VoxCeleb mini dataset.

Flow:
1. Extract embeddings from audio locally (transformers Wav2Vec2 or ECAPA-TDNN)
2. Enroll first N clips per speaker into vectordb service (/enroll)
3. Identify remaining clips (/identify) and check accuracy

Usage:
    python test_server/test_voiceprint.py [--vectordb-url URL]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import requests
import torch

DATA_DIR = Path(__file__).parent.parent / "data" / "voxceleb_mini"
ENROLL_COUNT = 3  # clips per speaker used for enrollment
RESULTS_FILE = Path(__file__).parent / "voiceprint_results.json"

DEFAULT_VECTORDB_URL = "https://tantk-meetingmind-vectordb.hf.space"

# Embedding model (loaded once)
_feature_extractor = None
_embed_model = None
EMBED_MODEL_NAME = "microsoft/wavlm-base-sv"  # speaker verification model, 512-dim


def _load_embed_model():
    global _feature_extractor, _embed_model
    if _embed_model is None:
        from transformers import AutoFeatureExtractor, AutoModel
        print(f"  Loading embedding model: {EMBED_MODEL_NAME}...")
        _feature_extractor = AutoFeatureExtractor.from_pretrained(EMBED_MODEL_NAME)
        _embed_model = AutoModel.from_pretrained(EMBED_MODEL_NAME)
        _embed_model.eval()
        print(f"  Model loaded.")
    return _feature_extractor, _embed_model


def get_embedding_local(audio_path: str) -> list[float]:
    """Extract speaker embedding from audio file using local model."""
    import librosa
    audio, sr = librosa.load(audio_path, sr=16000, mono=True)
    feature_extractor, model = _load_embed_model()
    inputs = feature_extractor(audio, sampling_rate=16000, return_tensors="pt", padding=True)
    with torch.no_grad():
        outputs = model(**inputs)
    # Mean pool over time dimension → single embedding vector
    emb = outputs.last_hidden_state.mean(dim=1).squeeze().numpy()
    # L2 normalize
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb.tolist()


def enroll_speaker(vectordb_url: str, name: str, embedding: list[float]) -> str:
    """Enroll a speaker embedding in the vectordb service."""
    resp = requests.post(
        f"{vectordb_url}/enroll",
        json={"name": name, "embedding": embedding},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["speaker_id"]


def identify_speaker(vectordb_url: str, embedding: list[float], top_k: int = 3) -> list[dict]:
    """Identify a speaker from embedding via vectordb service."""
    resp = requests.post(
        f"{vectordb_url}/identify",
        json={"embedding": embedding, "top_k": top_k},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["matches"]


def main():
    parser = argparse.ArgumentParser(description="Test voiceprint speaker ID")
    parser.add_argument("--vectordb-url", default=DEFAULT_VECTORDB_URL)
    parser.add_argument("--enroll-count", type=int, default=ENROLL_COUNT)
    args = parser.parse_args()

    # Discover speakers
    speakers = sorted([d.name for d in DATA_DIR.iterdir() if d.is_dir()])
    if not speakers:
        print(f"ERROR: No speaker directories in {DATA_DIR}")
        sys.exit(1)
    print(f"Found {len(speakers)} speakers: {speakers}")

    # Pre-load embedding model
    print("\nLoading embedding model...")
    _load_embed_model()

    # Check vectordb health
    resp = requests.get(f"{args.vectordb_url}/health", timeout=10)
    if resp.status_code != 200:
        print(f"ERROR: VectorDB not healthy: {resp.text}")
        sys.exit(1)
    print(f"VectorDB healthy at {args.vectordb_url}")

    results = {
        "config": {
            "embed_model": EMBED_MODEL_NAME,
            "vectordb_url": args.vectordb_url,
            "enroll_count": args.enroll_count,
            "speakers": speakers,
        },
        "enrollments": [],
        "identifications": [],
        "summary": {},
    }

    # Phase 1: Extract embeddings for all clips
    print(f"\n{'='*60}")
    print("Phase 1: Extracting embeddings from all clips")
    print(f"{'='*60}")

    embeddings = {}  # speaker -> [(filename, embedding)]
    for speaker in speakers:
        speaker_dir = DATA_DIR / speaker
        clips = sorted(speaker_dir.glob("*.wav"))
        embeddings[speaker] = []
        for clip in clips:
            print(f"  {speaker}/{clip.name}...", end=" ", flush=True)
            try:
                emb = get_embedding_local(str(clip))
                embeddings[speaker].append((clip.name, emb))
                print(f"OK (dim={len(emb)})")
            except Exception as e:
                print(f"FAIL: {e}")

    # Phase 2: Enroll speakers (first N clips each)
    print(f"\n{'='*60}")
    print(f"Phase 2: Enrolling speakers ({args.enroll_count} clips each)")
    print(f"{'='*60}")

    for speaker in speakers:
        enroll_clips = embeddings[speaker][:args.enroll_count]
        for fname, emb in enroll_clips:
            print(f"  Enrolling {speaker} ({fname})...", end=" ", flush=True)
            try:
                sid = enroll_speaker(args.vectordb_url, speaker, emb)
                results["enrollments"].append({
                    "speaker": speaker,
                    "file": fname,
                    "speaker_id": sid,
                })
                print(f"OK (id={sid[:8]}...)")
            except Exception as e:
                print(f"FAIL: {e}")

    # Phase 3: Identify remaining clips
    print(f"\n{'='*60}")
    print("Phase 3: Identifying remaining clips")
    print(f"{'='*60}")

    correct = 0
    total = 0

    for speaker in speakers:
        test_clips = embeddings[speaker][args.enroll_count:]
        if not test_clips:
            print(f"  {speaker}: no test clips (all used for enrollment)")
            continue

        for fname, emb in test_clips:
            total += 1
            print(f"  {speaker}/{fname}...", end=" ", flush=True)
            try:
                matches = identify_speaker(args.vectordb_url, emb, top_k=3)
                top_match = matches[0] if matches else {"name": "none", "similarity": 0}
                is_correct = top_match["name"] == speaker
                if is_correct:
                    correct += 1
                    status = "CORRECT"
                else:
                    status = f"WRONG (got {top_match['name']})"

                print(f"{status} (sim={top_match['similarity']:.3f})")
                results["identifications"].append({
                    "true_speaker": speaker,
                    "file": fname,
                    "predicted": top_match["name"],
                    "similarity": top_match["similarity"],
                    "correct": is_correct,
                    "top_3": [{"name": m["name"], "similarity": m["similarity"]} for m in matches],
                })
            except Exception as e:
                print(f"ERROR: {e}")

    # Summary
    accuracy = correct / total if total > 0 else 0
    print(f"\n{'='*60}")
    print(f"RESULTS: {correct}/{total} correct ({accuracy:.1%} accuracy)")
    print(f"{'='*60}")

    results["summary"] = {
        "total_test_clips": total,
        "correct": correct,
        "accuracy": accuracy,
    }

    # Per-speaker breakdown
    for speaker in speakers:
        speaker_ids = [r for r in results["identifications"] if r["true_speaker"] == speaker]
        sc = sum(1 for r in speaker_ids if r["correct"])
        st = len(speaker_ids)
        if st > 0:
            print(f"  {speaker}: {sc}/{st} ({sc/st:.0%})")
            results["summary"][speaker] = {"correct": sc, "total": st, "accuracy": sc / st}

    # Save results
    RESULTS_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
