"""FAISS-based speaker voiceprint store for GPU service.

Stores L2-normalized 192-dim speaker embeddings with cosine similarity
via IndexFlatIP (inner product on unit vectors = cosine similarity).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

log = logging.getLogger(__name__)

EMBEDDING_DIM = 192
METADATA_FILE = "speakers.json"
INDEX_FILE = "voiceprints.index"
STORE_PATH = Path(os.getenv("VOICEPRINT_STORE_PATH", "gpu_service/data/voiceprints"))


@dataclass
class SpeakerRecord:
    id: str
    name: str
    embedding_index: int


class VoiceprintStore:
    """Manages speaker voiceprints with FAISS for fast similarity search."""

    def __init__(self, store_path: Path | None = None):
        self._path = store_path or STORE_PATH
        self._path.mkdir(parents=True, exist_ok=True)
        self._index: faiss.IndexFlatIP | None = None
        self._speakers: list[SpeakerRecord] = []
        self._load()

    def _meta_path(self) -> Path:
        return self._path / METADATA_FILE

    def _index_path(self) -> Path:
        return self._path / INDEX_FILE

    def _load(self):
        meta_path = self._meta_path()
        index_path = self._index_path()

        if meta_path.exists() and index_path.exists():
            with open(meta_path) as f:
                data = json.load(f)
            self._speakers = [
                SpeakerRecord(id=s["id"], name=s["name"], embedding_index=s["embedding_index"])
                for s in data
            ]
            self._index = faiss.read_index(str(index_path))
            log.info("Loaded voiceprint store: %d speakers", len(self._speakers))
        else:
            self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
            self._speakers = []
            log.info("Initialized empty voiceprint store")

    def _save(self):
        data = [
            {"id": s.id, "name": s.name, "embedding_index": s.embedding_index}
            for s in self._speakers
        ]
        with open(self._meta_path(), "w") as f:
            json.dump(data, f, indent=2)
        faiss.write_index(self._index, str(self._index_path()))

    def enroll(self, name: str, embedding: np.ndarray) -> str:
        embedding = self._normalize(embedding)
        vec = embedding.reshape(1, -1).astype(np.float32)

        idx = self._index.ntotal
        self._index.add(vec)

        speaker_id = uuid.uuid4().hex[:12]
        self._speakers.append(SpeakerRecord(id=speaker_id, name=name, embedding_index=idx))
        self._save()
        log.info("Enrolled speaker '%s' (id=%s, index=%d)", name, speaker_id, idx)
        return speaker_id

    def identify(self, embedding: np.ndarray, top_k: int = 3) -> list[dict]:
        if self._index.ntotal == 0:
            return []

        embedding = self._normalize(embedding)
        vec = embedding.reshape(1, -1).astype(np.float32)
        k = min(top_k, self._index.ntotal)

        similarities, indices = self._index.search(vec, k)

        results = []
        for sim, idx in zip(similarities[0], indices[0]):
            if idx < 0:
                continue
            speaker = self._speaker_at(int(idx))
            if speaker:
                results.append({
                    "name": speaker.name,
                    "id": speaker.id,
                    "similarity": float(sim),
                })
        return results

    def list_speakers(self) -> list[dict]:
        return [{"id": s.id, "name": s.name} for s in self._speakers]

    def _speaker_at(self, embedding_index: int) -> SpeakerRecord | None:
        for s in self._speakers:
            if s.embedding_index == embedding_index:
                return s
        return None

    @staticmethod
    def _normalize(vec: np.ndarray) -> np.ndarray:
        vec = vec.astype(np.float32).flatten()
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec


_store: VoiceprintStore | None = None


def get_voiceprint_store() -> VoiceprintStore:
    global _store
    if _store is None:
        _store = VoiceprintStore()
    return _store
