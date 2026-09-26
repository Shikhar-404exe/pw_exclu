"""STRAIN FastAPI application entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from strain.backend.api.routes import router
from strain.backend.store.store import create_db_and_tables

app = FastAPI(
    title="STRAIN",
    description=(
        "Diagnostic tool for unfair contract clauses. "
        "Corpus is synthetic; relationships shown are textual kinship, not proven copying."
    ),
    version="0.1.0",
)

# CORS: allow localhost in dev; in production the frontend is served from the
# same origin (same Cloud Run container) so CORS is irrelevant there.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()
    # Warm the embedding model now, not inside the first request: importing
    # torch/sentence-transformers and loading ~90MB of weights takes many
    # seconds — longer than the frontend's read timeouts. A try/except keeps
    # environments without working native deps (or without the model on disk)
    # booting fine; those requests pay inference latency on demand instead.
    try:
        from strain.backend.pipeline.embed import get_embedding_provider

        provider = get_embedding_provider()
        provider.encode(["warmup: the tenant shall pay rent on time each month."])
        print("Embedding model warmed up OK")
    except Exception as e:  # noqa: BLE001 — never fail boot for warmup
        print(f"Embedding model warmup skipped: {e}")


# API routes under /api
app.include_router(router, prefix="/api")

# ── Serve React SPA (production) ──────────────────────────────────────────────
# The built frontend lives at strain/frontend/dist (copied in by Dockerfile).
# In local dev (npm run dev on :5173) this block is effectively unused.
_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

if _FRONTEND_DIST.exists():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    # Catch-all: serve index.html for all non-API routes (React Router)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        index = _FRONTEND_DIST / "index.html"
        return FileResponse(str(index))
