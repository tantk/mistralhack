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

    try:
        collection = zvec.open(COLLECTION_PATH)
    except Exception:
        import shutil

        if Path(COLLECTION_PATH).exists():
            shutil.rmtree(COLLECTION_PATH)

        schema = zvec.CollectionSchema(
            name="voiceprints",
            fields=zvec.FieldSchema("name", zvec.DataType.STRING, nullable=True),
            vectors=zvec.VectorSchema(
                "embedding", zvec.DataType.VECTOR_FP32, EMBEDDING_DIM
            ),
        )
        collection = zvec.create_and_open(path=COLLECTION_PATH, schema=schema)
        collection.create_index("embedding", zvec.FlatIndexParam(metric_type=zvec.MetricType.COSINE))

    return collection


@app.on_event("startup")
def startup():
    global speakers
    zvec.init()
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

    doc = zvec.Doc(
        id=speaker_id,
        vectors={"embedding": req.embedding},
        fields={"name": req.name},
    )
    col.insert([doc])

    speakers.append({"id": speaker_id, "name": req.name})
    save_speakers()

    return {"speaker_id": speaker_id}


@app.post("/identify")
def identify(req: IdentifyRequest):
    col = get_or_create_collection()

    results = col.query(
        vectors=zvec.VectorQuery("embedding", vector=req.embedding),
        topk=req.top_k,
        output_fields=["name"],
    )

    matches = [
        {
            "name": doc.field("name") or "unknown",
            "id": doc.id,
            "similarity": doc.score if doc.score is not None else 0.0,
        }
        for doc in results
    ]
    return {"matches": matches}


@app.get("/speakers")
def list_speakers():
    return {"speakers": speakers}
