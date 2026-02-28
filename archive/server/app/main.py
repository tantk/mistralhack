import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.auth import APIKeyMiddleware
from app.database import init_db
from app.routers import meetings, transcribe, pipeline, enrollment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("access")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Meeting Minutes", lifespan=lifespan)
app.add_middleware(APIKeyMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    client = request.headers.get("cf-connecting-ip") \
        or request.headers.get("x-forwarded-for") \
        or request.client.host
    log.info(
        "%s %s %s → %d (%.2fs)",
        client, request.method, request.url.path, response.status_code, duration,
    )
    return response


app.include_router(meetings.router)
app.include_router(transcribe.router)
app.include_router(pipeline.router)
app.include_router(enrollment.router)

static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
