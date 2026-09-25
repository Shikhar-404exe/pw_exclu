"""STRAIN FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()


app.include_router(router)
