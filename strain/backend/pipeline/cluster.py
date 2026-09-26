"""
Clustering pipeline: assigns clauses to strain families via HDBSCAN.
"""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter

import numpy as np
from sqlmodel import Session, select

from strain.backend.pipeline.embed import get_clause_embeddings
from strain.backend.store.store import Clause, Strain

# ─── HDBSCAN configuration ────────────────────────────────────────────────────
# With ~4850 clauses across 18 clause types × ~6 templates,
# we expect 15–30 semantically coherent families.
_MIN_CLUSTER_SIZE = 30
_MIN_SAMPLES = 5
_CLUSTER_SELECTION_EPSILON = 0.05  # merge sub-clusters closer than this


def _make_clusterer():
    """Build an HDBSCAN clusterer with the configured parameters.

    Prefers the ``hdbscan`` package; falls back to
    ``sklearn.cluster.HDBSCAN`` (same algorithm) when the former cannot
    be imported in this environment.
    """
    kwargs = {
        "min_cluster_size": _MIN_CLUSTER_SIZE,
        "min_samples": _MIN_SAMPLES,
        "metric": "euclidean",  # on L2-normalised vectors this is equivalent to cosine
        "cluster_selection_method": "leaf",  # leaf = fewer, larger clusters
        "cluster_selection_epsilon": _CLUSTER_SELECTION_EPSILON,
    }
    try:
        import hdbscan as hdb

        return hdb.HDBSCAN(**kwargs)
    except ImportError:
        from sklearn.cluster import HDBSCAN as SklearnHDBSCAN

        return SklearnHDBSCAN(**kwargs)


def cluster_clauses(session: Session) -> None:
    """
    Cluster all embedded clauses into strains using HDBSCAN with cosine metric.
    Writes strain_id back to each Clause and creates/updates Strain records.
    """
    clause_ids, vectors = get_clause_embeddings(session)
    if len(clause_ids) < _MIN_CLUSTER_SIZE:
        # Too few clauses — everything is a singleton
        _assign_singletons(session, clause_ids)
        return

    X = np.array(vectors, dtype=np.float32)

    clusterer = _make_clusterer()

    # L2-normalise for cosine similarity
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    X_norm = X / norms

    labels = clusterer.fit_predict(X_norm)

    # Map cluster label → stable strain_id
    label_to_strain: dict[int, str] = {}
    existing_strains = {s.strain_id: s for s in session.exec(select(Strain)).all()}

    # Build a mapping: for each cluster, try to reuse an existing strain_id
    # by checking if any clause in that cluster already has a strain_id.
    for label in set(labels):
        if label == -1:
            continue
        member_indices = [i for i, lab in enumerate(labels) if lab == label]
        member_ids = [clause_ids[i] for i in member_indices]

        # Find existing strain assignment for any member
        existing_sid = None
        for cid in member_ids:
            c = session.exec(select(Clause).where(Clause.clause_id == cid)).first()
            if c and c.strain_id and c.strain_id in existing_strains:
                existing_sid = c.strain_id
                break

        if existing_sid:
            label_to_strain[label] = existing_sid
        else:
            # Generate new stable strain_id
            label_to_strain[label] = f"strain-{uuid.uuid4().hex[:8]}"

    # Assign strain_ids
    clauses_by_id = {
        c.clause_id: c
        for c in session.exec(select(Clause)).all()
    }

    for clause_id, label in zip(clause_ids, labels, strict=True):
        clause = clauses_by_id.get(clause_id)
        if not clause:
            continue

        if label == -1:
            # Noise → singleton strain
            sid = f"singleton-{uuid.uuid4().hex[:8]}"
        else:
            sid = label_to_strain[label]

        clause.strain_id = sid
        session.add(clause)

    session.commit()

    # Create/update Strain records
    _upsert_strains(session)


def _assign_singletons(session: Session, clause_ids: list[str]) -> None:
    for cid in clause_ids:
        clause = session.exec(select(Clause).where(Clause.clause_id == cid)).first()
        if clause and not clause.strain_id:
            clause.strain_id = f"singleton-{uuid.uuid4().hex[:8]}"
            session.add(clause)
    session.commit()
    _upsert_strains(session)


def _upsert_strains(session: Session) -> None:
    """Create/update Strain records from current clause assignments."""
    clauses = session.exec(select(Clause)).all()

    strain_clauses: dict[str, list[Clause]] = {}
    for c in clauses:
        if c.strain_id:
            strain_clauses.setdefault(c.strain_id, []).append(c)

    # Prune stale Strain rows left behind by re-clustering (a rerun assigns
    # fresh strain_ids; rows with zero member clauses would otherwise pollute
    # /strains and the atlas).
    for existing in session.exec(select(Strain)).all():
        if existing.strain_id not in strain_clauses:
            session.delete(existing)

    for strain_id, members in strain_clauses.items():
        existing = session.exec(
            select(Strain).where(Strain.strain_id == strain_id)
        ).first()

        family_name = _generate_family_name(strain_id, members)

        # Compute centroid
        embeddings = [json.loads(c.embedding_json) for c in members if c.embedding_json]
        if embeddings:
            centroid = np.mean(embeddings, axis=0).tolist()
            centroid_json = json.dumps(centroid)
        else:
            centroid_json = None

        if existing:
            existing.family_name = family_name
            existing.clause_count = len(members)
            existing.centroid_json = centroid_json
            session.add(existing)
        else:
            strain = Strain(
                strain_id=strain_id,
                family_name=family_name,
                clause_count=len(members),
                centroid_json=centroid_json,
            )
            session.add(strain)

    session.commit()


_FAMILY_NAME_KEYWORDS = {
    "rent": "Rent Payment",
    "deposit": "Security Deposit",
    "lock": "Lock-in Period",
    "notice": "Notice Period",
    "repair": "Repairs & Maintenance",
    "entry": "Landlord Entry Rights",
    "sublet": "Subletting Restriction",
    "terminat": "Termination",
    "dispute": "Dispute Resolution",
    "penalty": "Penalty Clause",
    "escalat": "Rent Escalation",
    "utilities": "Utilities",
    "maintenan": "Maintenance Obligation",
}


def _generate_family_name(strain_id: str, members: list[Clause]) -> str:
    """Generate a human-readable family name from the most common heading tokens."""
    if strain_id.startswith("singleton-"):
        if members:
            h = members[0].heading.strip()
            return h[:40] if h else "Unclassified Clause"
        return "Unclassified Clause"

    # Check headings first
    all_headings = " ".join(c.heading for c in members).lower()
    for kw, name in _FAMILY_NAME_KEYWORDS.items():
        if kw in all_headings:
            return name

    # Fall back to common words in normalised text
    all_text = " ".join(c.normalised_text for c in members).lower()
    for kw, name in _FAMILY_NAME_KEYWORDS.items():
        if kw in all_text:
            return name

    # Last resort: top word from headings
    words = re.findall(r"[a-z]{4,}", all_headings)
    if words:
        most_common = Counter(words).most_common(1)[0][0]
        return most_common.title() + " Clause"

    return f"Strain Family ({strain_id[-6:]})"
