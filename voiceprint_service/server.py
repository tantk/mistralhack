import json
import os
import uuid
from pathlib import Path

import zvec
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="MeetingMind VectorDB")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data/voiceprints"))
SPEAKERS_FILE = DATA_DIR / "speakers.json"
COLLECTION_PATH = str(DATA_DIR / "collection")
DIM_FILE = DATA_DIR / "embedding_dim.txt"

collection: zvec.Collection | None = None
speakers: list[dict] = []
embedding_dim: int = 0  # auto-detected from first enroll


def load_speakers() -> list[dict]:
    if SPEAKERS_FILE.exists():
        return json.loads(SPEAKERS_FILE.read_text())
    return []


def save_speakers():
    SPEAKERS_FILE.write_text(json.dumps(speakers))


def _read_dim() -> int:
    if DIM_FILE.exists():
        return int(DIM_FILE.read_text().strip())
    return 0


def _write_dim(dim: int):
    DIM_FILE.write_text(str(dim))


def _create_collection(dim: int) -> zvec.Collection:
    import shutil
    if Path(COLLECTION_PATH).exists():
        shutil.rmtree(COLLECTION_PATH)

    schema = zvec.CollectionSchema(
        name="voiceprints",
        fields=zvec.FieldSchema("name", zvec.DataType.STRING, nullable=True),
        vectors=zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, dim),
    )
    col = zvec.create_and_open(path=COLLECTION_PATH, schema=schema)
    col.create_index("embedding", zvec.FlatIndexParam(metric_type=zvec.MetricType.COSINE))
    return col


def get_or_create_collection(dim: int = 0) -> zvec.Collection:
    global collection, embedding_dim

    # If dimension changed, close old and recreate
    if dim > 0 and embedding_dim > 0 and dim != embedding_dim:
        if collection is not None:
            collection = None  # release old handle before rmtree
        collection = _create_collection(dim)
        embedding_dim = dim
        _write_dim(dim)
        speakers.clear()
        save_speakers()
        return collection

    if collection is not None:
        return collection

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-detect dim: from arg, saved file, or default 192
    if dim > 0:
        embedding_dim = dim
    elif embedding_dim == 0:
        embedding_dim = _read_dim() or 192
    _write_dim(embedding_dim)

    try:
        collection = zvec.open(COLLECTION_PATH)
    except Exception:
        collection = _create_collection(embedding_dim)

    return collection


@app.on_event("startup")
def startup():
    global speakers
    zvec.init()
    speakers = load_speakers()
    # Collection created lazily on first enroll/identify (so we know the dim)


# ─── Request / response models ──────────────────────────────────────


class EnrollRequest(BaseModel):
    name: str
    embedding: list[float]


class IdentifyRequest(BaseModel):
    embedding: list[float]
    top_k: int = 3


# ─── Endpoints ──────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/enroll")
def enroll(req: EnrollRequest):
    try:
        dim = len(req.embedding)
        col = get_or_create_collection(dim=dim)
        speaker_id = str(uuid.uuid4())

        doc = zvec.Doc(
            id=speaker_id,
            vectors={"embedding": req.embedding},
            fields={"name": req.name},
        )
        col.insert([doc])

        speakers.append({"id": speaker_id, "name": req.name})
        save_speakers()

        return {"speaker_id": speaker_id}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.post("/identify")
def identify(req: IdentifyRequest):
    try:
        dim = len(req.embedding)
        col = get_or_create_collection(dim=dim)

        results = col.query(
            vectors=zvec.VectorQuery("embedding", vector=req.embedding),
            topk=req.top_k,
            output_fields=["name"],
        )

        matches = [
            {
                "name": doc.field("name") or "unknown",
                "id": doc.id,
                "similarity": 1.0 - doc.score if doc.score is not None else 0.0,
            }
            for doc in results
        ]
        return {"matches": matches}
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.get("/speakers")
def list_speakers():
    return {"speakers": speakers}
