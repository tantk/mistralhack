import json
import os
import uuid
from pathlib import Path

import zvec
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="MeetingMind VectorDB")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data/voiceprints"))
SPEAKERS_FILE = DATA_DIR / "speakers.json"
COLLECTION_PATH = str(DATA_DIR / "collection")
EMBEDDING_DIM = 192

collection: zvec.Collection | None = None
speakers: list[dict] = []


def load_speakers() -> list[dict]:
    if SPEAKERS_FILE.exists():
        return json.loads(SPEAKERS_FILE.read_text())
    return []


def save_speakers():
    SPEAKERS_FILE.write_text(json.dumps(speakers))


def get_or_create_collection() -> zvec.Collection:
    global collection
    if collection is not None:
        return collection

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zvec.init()

    try:
        collection = zvec.open(COLLECTION_PATH)
    except Exception:
        if Path(COLLECTION_PATH).exists():
            import shutil
            shutil.rmtree(COLLECTION_PATH)

        schema = zvec.CollectionSchema("voiceprints")
        schema.add_field(zvec.VectorSchema.fp32("embedding", EMBEDDING_DIM))
        schema.add_field(zvec.FieldSchema.string("name"))
        collection = zvec.create_and_open(COLLECTION_PATH, schema)
        collection.create_index(
            "embedding",
            zvec.IndexParams.flat(zvec.MetricType.Cosine, zvec.QuantizeType.Undefined),
        )

    return collection


@app.on_event("startup")
def startup():
    global speakers
    speakers = load_speakers()
    get_or_create_collection()


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
    col = get_or_create_collection()
    speaker_id = str(uuid.uuid4())

    doc = (
        zvec.Doc.id(speaker_id)
        .with_vector("embedding", req.embedding)
        .with_string("name", req.name)
    )
    col.insert([doc])

    speakers.append({"id": speaker_id, "name": req.name})
    save_speakers()

    return {"speaker_id": speaker_id}


@app.post("/identify")
def identify(req: IdentifyRequest):
    col = get_or_create_collection()

    query = (
        zvec.VectorQuery("embedding")
        .topk(req.top_k)
        .output_fields(["name"])
        .vector(req.embedding)
    )
    results = col.query(query)

    matches = [
        {
            "name": doc.get_string("name"),
            "id": doc.pk(),
            "similarity": doc.score(),
        }
        for doc in results
    ]
    return {"matches": matches}


@app.get("/speakers")
def list_speakers():
    return {"speakers": speakers}
