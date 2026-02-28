"""FAISS-based speaker voiceprint store.

Stores L2-normalized 192-dim speaker embeddings with cosine similarity
via IndexFlatIP (inner product on unit vectors = cosine similarity).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import faiss
import numpy as np

from app.config import VOICEPRINT_STORE_PATH

log = logging.getLogger(__name__)

EMBEDDING_DIM = 192
METADATA_FILE = "speakers.json"
INDEX_FILE = "voiceprints.index"


@dataclass
class SpeakerRecord:
    id: str
    name: str
    embedding_index: int  # row index in the FAISS index


class VoiceprintStore:
    """Manages speaker voiceprints with FAISS for fast similarity search."""

    def __init__(self, store_path: Path | None = None):
        self._path = store_path or VOICEPRINT_STORE_PATH
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
        """Add a speaker embedding to the store. Returns the speaker ID."""
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
        """Find the closest enrolled speakers for a given embedding.

        Returns list of {name, id, similarity} sorted by descending similarity.
        """
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
        """Return all enrolled speakers."""
        return [{"id": s.id, "name": s.name} for s in self._speakers]

    def remove(self, speaker_id: str) -> bool:
        """Remove a speaker by ID. Rebuilds the FAISS index."""
        target = None
        for s in self._speakers:
            if s.id == speaker_id:
                target = s
                break
        if not target:
            return False

        self._speakers.remove(target)

        # Rebuild index from remaining speakers
        if not self._speakers:
            self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
        else:
            old_index = self._index
            self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
            for i, speaker in enumerate(self._speakers):
                old_idx = speaker.embedding_index
                vec = faiss.rev_swig_ptr(old_index.get_xb(), old_index.ntotal * EMBEDDING_DIM)
                vec = vec.reshape(old_index.ntotal, EMBEDDING_DIM)
                self._index.add(vec[old_idx : old_idx + 1].copy())
                speaker.embedding_index = i

        self._save()
        log.info("Removed speaker '%s' (id=%s)", target.name, speaker_id)
        return True

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


# Module-level singleton
_store: VoiceprintStore | None = None


def get_voiceprint_store() -> VoiceprintStore:
    global _store
    if _store is None:
        _store = VoiceprintStore()
    return _store
