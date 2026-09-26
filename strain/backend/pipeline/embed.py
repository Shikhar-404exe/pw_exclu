"""
Embedding pipeline: embeds all clause normalised_text and persists vectors.

Includes the embedding provider interface and local sentence-transformers
implementation (merged from providers/embeddings.py). Embeddings are cached
by SHA-256 of the input text in data/embedding_cache.json.
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path

from sqlmodel import Session, select

from strain.backend.store.store import Clause


# ─── Embedding provider ─────────────────────────────────────────────────────

# Cache file location
_CACHE_PATH = Path(__file__).resolve().parents[3] / "data" / "embedding_cache.json"


class EmbeddingProvider(ABC):
    @abstractmethod
    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode a list of texts to embedding vectors."""

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]


class SentenceTransformerProvider(EmbeddingProvider):
    """
    Uses sentence-transformers all-MiniLM-L6-v2 (offline after first download).
    Caches embeddings by SHA-256 of the input text.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self) -> None:
        self._model = None
        self._cache: dict[str, list[float]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if _CACHE_PATH.exists():
            with open(_CACHE_PATH, encoding="utf-8") as f:
                self._cache = json.load(f)

    def _save_cache(self) -> None:
        _CACHE_PATH.parent.mkdir(exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._cache, f)

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def encode(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices = []
        uncached_texts = []

        for i, text in enumerate(texts):
            key = self._hash(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            model = self._get_model()
            embeddings = model.encode(uncached_texts, show_progress_bar=False)
            for idx, emb in zip(uncached_indices, embeddings):
                vec = emb.tolist()
                key = self._hash(texts[idx])
                self._cache[key] = vec
                results[idx] = vec
            self._save_cache()

        return results  # type: ignore[return-value]


class OfflineEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic offline fallback used when sentence-transformers is
    unavailable. Hash-based pseudo-embeddings: stable for identical texts,
    not semantically meaningful. Only for smoke tests, never for evaluation.
    """

    DIM = 64

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vec = [(digest[i % len(digest)] / 255.0) - 0.5 for i in range(self.DIM)]
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


_default_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _default_provider
    if _default_provider is None:
        try:
            _default_provider = SentenceTransformerProvider()
        except ImportError:
            _default_provider = OfflineEmbeddingProvider()
    return _default_provider


# ─── Pipeline steps ─────────────────────────────────────────────────────────

def embed_clauses(session: Session, batch_size: int = 64) -> None:
    """
    Embed all clauses that don't have embeddings yet.
    Writes embedding_json back to the DB.
    """
    provider = get_embedding_provider()

    # Find clauses without embeddings
    all_clauses = session.exec(select(Clause)).all()
    unembedded = [c for c in all_clauses if not c.embedding_json]

    if not unembedded:
        return

    texts = [c.normalised_text for c in unembedded]

    # Batch encode
    for start in range(0, len(texts), batch_size):
        batch_clauses = unembedded[start : start + batch_size]
        batch_texts = texts[start : start + batch_size]
        embeddings = provider.encode(batch_texts)

        for clause, emb in zip(batch_clauses, embeddings):
            clause.embedding_json = json.dumps(emb)
            session.add(clause)

    session.commit()


def get_clause_embeddings(
    session: Session,
) -> tuple[list[str], list[list[float]]]:
    """
    Return (clause_ids, embeddings) for all embedded clauses.
    """
    clauses = session.exec(
        select(Clause).where(Clause.embedding_json.isnot(None))  # type: ignore[arg-type]
    ).all()
    ids = [c.clause_id for c in clauses]
    vectors = [json.loads(c.embedding_json) for c in clauses]  # type: ignore[arg-type]
    return ids, vectors
