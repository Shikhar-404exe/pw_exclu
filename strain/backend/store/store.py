"""SQLModel table definitions for STRAIN."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    doc_id: str = Field(index=True, unique=True)
    filename: str
    synthetic: bool = Field(default=True)
    generation: Optional[int] = None
    template_id: Optional[str] = None
    parent_doc_id: Optional[str] = None
    synthetic_date: Optional[str] = None  # ISO date string
    mutation_log_json: Optional[str] = None  # JSON string
    raw_text: str = Field(default="")

    @property
    def mutation_log(self) -> list:
        if self.mutation_log_json:
            return json.loads(self.mutation_log_json)
        return []


class Clause(SQLModel, table=True):
    __tablename__ = "clauses"

    id: Optional[int] = Field(default=None, primary_key=True)
    clause_id: str = Field(index=True, unique=True)
    doc_id: str = Field(index=True)
    ordinal: int
    heading: str = Field(default="")
    text: str
    normalised_text: str
    embedding_json: Optional[str] = None  # JSON float list
    strain_id: Optional[str] = None
    virulence_score: Optional[float] = None
    asymmetry_score: Optional[float] = None
    harshness_delta: Optional[float] = None
    outcome_factor: Optional[float] = None
    is_provisional_leaf: bool = Field(default=False)

    @property
    def embedding(self) -> list[float] | None:
        if self.embedding_json:
            return json.loads(self.embedding_json)
        return None


class Strain(SQLModel, table=True):
    __tablename__ = "strains"

    id: Optional[int] = Field(default=None, primary_key=True)
    strain_id: str = Field(index=True, unique=True)
    family_name: str
    clause_count: int = Field(default=0)
    root_clause_id: Optional[str] = None
    centroid_json: Optional[str] = None  # JSON float list

    @property
    def centroid(self) -> list[float] | None:
        if self.centroid_json:
            return json.loads(self.centroid_json)
        return None


class Edge(SQLModel, table=True):
    __tablename__ = "edges"

    id: Optional[int] = Field(default=None, primary_key=True)
    parent_clause_id: str = Field(index=True)
    child_clause_id: str = Field(index=True)
    strain_id: str = Field(index=True)
    distance: float
    mutation_label: str = Field(default="")
    mutation_type: str = Field(default="unknown")


class Outcome(SQLModel, table=True):
    __tablename__ = "outcomes"

    id: Optional[int] = Field(default=None, primary_key=True)
    clause_family: str = Field(index=True)
    jurisdiction: str
    year: int
    outcome: str  # upheld | voided | partially_voided
    holding_summary: str
    source_label: str
    illustrative: bool = Field(default=True)


"""Database engine and session management."""

# Data directory relative to repo root
# (store.py lives at strain/backend/store/store.py, so repo root is parents[3])
_REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = _REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "strain.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


def create_db_and_tables() -> None:
    """Create all tables if they don't exist."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yield a DB session."""
    with Session(engine) as session:
        yield session
