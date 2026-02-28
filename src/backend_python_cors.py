# ============================================================
# Python GPU backend — CORS patch (add to your existing FastAPI app)
# ============================================================
# In your main.py (or wherever you create the FastAPI app), add:

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ── ADD THIS BLOCK ──────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # Lock down to your Vite dev origin in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ────────────────────────────────────────────────────────────

# Your existing /diarize and /embed routes stay unchanged.
# The Rust orchestrator calls these internally; the frontend never hits this service directly.
