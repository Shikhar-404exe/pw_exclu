"""
Shared pytest fixtures for STRAIN test suite.

Provides in-memory SQLite sessions and a FastAPI TestClient that can run
without a seeded corpus — making the unit-test layer fully self-contained
and cold-start safe.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# ─── In-memory database ───────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def in_memory_engine():
    """SQLite in-memory engine with a fresh schema for every test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def session(in_memory_engine):
    """DB session backed by the in-memory engine."""
    with Session(in_memory_engine) as s:
        yield s


# ─── FastAPI test client ───────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def client(session):
    """
    FastAPI TestClient with the DB session overridden to use in-memory SQLite.

    All API route tests should use this fixture so they never depend on the
    seeded corpus or the on-disk strain.db.
    """
    from strain.backend.main import app
    from strain.backend.store.store import get_session

    def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
