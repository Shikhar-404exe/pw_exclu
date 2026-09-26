"""FastAPI route handlers for STRAIN API."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from strain.backend.store.store import (
    Clause,
    Document,
    Edge,
    Outcome,
    Strain,
    get_session,
)

logger = logging.getLogger("strain.api")
router = APIRouter()

#: Upload guardrails: overly large files exhaust memory/CPU during parsing
#: and embedding; only document types the pipeline can parse are accepted.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".pdf", ".docx", ".doc", ".txt"})


def _sanitised_upload_name(raw: str | None) -> str:
    """Strip any client-supplied path; keep a bare filename."""
    name = (raw or "upload.txt").strip().replace("\\", "/").split("/")[-1]
    return name or "upload.txt"


async def _read_upload_limited(file: UploadFile) -> tuple[str, bytes]:
    """Read an upload with size + type guards (413 / 400 on violation)."""
    name = _sanitised_upload_name(file.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Upload PDF, DOCX, or TXT.",
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content)} bytes). Maximum is {MAX_UPLOAD_BYTES} bytes.",
        )
    return name, content


# ─── Health ──────────────────────────────────────────────────────────────────

@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "STRAIN"}


# ─── Ingest ──────────────────────────────────────────────────────────────────

@router.post("/ingest")
async def ingest_document(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    """Ingest a PDF, DOCX, or TXT document into the pipeline."""
    from strain.backend.pipeline.diagnose import ingest_and_store

    name, content = await _read_upload_limited(file)
    suffix = Path(name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc_id = await ingest_and_store(tmp_path, name, session)
    finally:
        os.unlink(tmp_path)

    return {"doc_id": doc_id, "status": "ingested"}


# ─── Diagnose ─────────────────────────────────────────────────────────────────

@router.post("/diagnose")
async def diagnose_document(
    file: UploadFile = File(None),
    doc_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """Run full diagnosis on an uploaded file or existing doc_id."""
    from strain.backend.pipeline.diagnose import diagnose

    if file is not None:
        name, content = await _read_upload_limited(file)
        suffix = Path(name).suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            result = await diagnose(tmp_path, name, session)
        finally:
            os.unlink(tmp_path)
    elif doc_id:
        result = await diagnose(None, None, session, existing_doc_id=doc_id)
    else:
        raise HTTPException(status_code=400, detail="Provide file or doc_id")

    return result


# ─── Strains ──────────────────────────────────────────────────────────────────

@router.get("/strains")
def list_strains(session: Session = Depends(get_session)) -> dict:
    """List all known strains with summary stats."""
    strains = session.exec(select(Strain)).all()
    if not strains:
        return {"strains": [], "total": 0}

    # Bulk-load all edges and outcomes in two queries (avoid N+1)
    all_edges = session.exec(select(Edge)).all()
    all_outcomes = session.exec(select(Outcome)).all()

    edges_by_strain: dict[str, list[Edge]] = {}
    for e in all_edges:
        edges_by_strain.setdefault(e.strain_id, []).append(e)

    result = []
    for s in strains:
        edges = edges_by_strain.get(s.strain_id, [])
        outcomes = [
            o for o in all_outcomes
            if o.clause_family in s.family_name or s.family_name in o.clause_family
        ]
        result.append({
            "strain_id": s.strain_id,
            "family_name": s.family_name,
            "clause_count": s.clause_count,
            "edge_count": len(edges),
            "has_outcomes": len(outcomes) > 0,
            "outcome_summary": _summarise_outcomes(outcomes),
        })
    result.sort(key=lambda x: x["clause_count"], reverse=True)
    return {"strains": result, "total": len(result)}


@router.get("/strain/{strain_id}")
def get_strain(strain_id: str, session: Session = Depends(get_session)) -> dict:
    """Get full details for one strain including phylogeny and virulence."""
    strain = session.exec(
        select(Strain).where(Strain.strain_id == strain_id)
    ).first()
    if not strain:
        raise HTTPException(status_code=404, detail=f"Strain {strain_id} not found")

    clauses = session.exec(
        select(Clause).where(Clause.strain_id == strain_id)
    ).all()
    edges = session.exec(
        select(Edge).where(Edge.strain_id == strain_id)
    ).all()
    # Get outcome records — match by family_name
    all_outcomes = session.exec(select(Outcome)).all()
    outcomes = [o for o in all_outcomes if o.clause_family in strain.family_name or strain.family_name in o.clause_family]

    return {
        "strain_id": strain.strain_id,
        "family_name": strain.family_name,
        "clause_count": strain.clause_count,
        "root_clause_id": strain.root_clause_id,
        "clauses": [_clause_summary(c) for c in clauses],
        "edges": [
            {
                "parent_clause_id": e.parent_clause_id,
                "child_clause_id": e.child_clause_id,
                "distance": e.distance,
                "mutation_label": e.mutation_label,
                "mutation_type": e.mutation_type,
            }
            for e in edges
        ],
        "outcomes": [_outcome_dict(o) for o in outcomes],
        "virulence_components": {
            "description": "asymmetry + harshness_delta + outcome_factor",
            "weights": {"asymmetry": 0.4, "harshness_delta": 0.4, "outcome_factor": 0.2},
            "clauses": [
                {
                    "clause_id": c.clause_id,
                    "virulence_score": c.virulence_score,
                    "asymmetry_score": c.asymmetry_score,
                    "harshness_delta": c.harshness_delta,
                    "outcome_factor": c.outcome_factor,
                }
                for c in clauses
                if c.virulence_score is not None
            ],
        },
    }


# ─── Outbreak ─────────────────────────────────────────────────────────────────

@router.get("/outbreak")
def outbreak_dashboard(session: Session = Depends(get_session)) -> dict:
    """Population-level statistics for the outbreak dashboard."""
    strains = session.exec(select(Strain)).all()
    clauses = session.exec(select(Clause)).all()
    outcomes = session.exec(select(Outcome)).all()

    # Strain prevalence
    prevalence = [
        {"strain_id": s.strain_id, "family_name": s.family_name, "count": s.clause_count}
        for s in sorted(strains, key=lambda x: x.clause_count, reverse=True)
    ]

    # Harshness by generation (from documents)
    docs = session.exec(select(Document)).all()
    gen_harshness: dict[int, list[float]] = {}
    for c in clauses:
        if c.asymmetry_score is None:
            continue
        doc = next((d for d in docs if d.doc_id == c.doc_id), None)
        if doc and doc.generation is not None:
            gen_harshness.setdefault(doc.generation, []).append(c.asymmetry_score)

    harshness_trend = [
        {"generation": gen, "avg_harshness": round(sum(vals) / len(vals), 3)}
        for gen, vals in sorted(gen_harshness.items())
    ]

    # Outcome distribution
    outcome_counts = {"upheld": 0, "voided": 0, "partially_voided": 0}
    for o in outcomes:
        if o.outcome in outcome_counts:
            outcome_counts[o.outcome] += 1

    # Strain growth across generations
    strain_growth: dict[str, dict[int, int]] = {}
    for c in clauses:
        if not c.strain_id:
            continue
        doc = next((d for d in docs if d.doc_id == c.doc_id), None)
        if doc and doc.generation is not None:
            strain_growth.setdefault(c.strain_id, {}).setdefault(doc.generation, 0)
            strain_growth[c.strain_id][doc.generation] += 1

    growth_series = [
        {
            "strain_id": sid,
            "family_name": next(
                (s.family_name for s in strains if s.strain_id == sid), sid
            ),
            "by_generation": [
                {"generation": g, "count": cnt}
                for g, cnt in sorted(gens.items())
            ],
        }
        for sid, gens in list(strain_growth.items())[:10]  # top 10
    ]

    return {
        "prevalence": prevalence,
        "harshness_trend": harshness_trend,
        "outcome_distribution": [
            {"outcome": k, "count": v} for k, v in outcome_counts.items()
        ],
        "strain_growth": growth_series,
        "total_documents": len(docs),
        "total_clauses": len(clauses),
        "total_strains": len(strains),
    }


# ─── Sample documents ─────────────────────────────────────────────────────────

@router.get("/samples")
def list_samples() -> dict:
    """List the three demo sample documents available for diagnosis."""
    data_dir = Path(__file__).resolve().parents[3] / "data" / "samples"
    if not data_dir.exists():
        return {"samples": []}
    samples = [
        {"filename": f.name, "label": f.stem.replace("_", " ").title()}
        for f in sorted(data_dir.glob("*.txt"))[:3]
    ]
    return {"samples": samples}


@router.get("/samples/{filename}")
def get_sample(filename: str) -> dict:
    """Return text of a sample document."""
    data_dir = Path(__file__).resolve().parents[3] / "data" / "samples"
    # Confine reads to the samples directory (no traversal, no subpaths).
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=404, detail="Sample not found")
    path = (data_dir / filename).resolve()
    if data_dir.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"filename": path.name, "text": path.read_text(encoding="utf-8")}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clause_summary(c: Clause) -> dict:
    return {
        "clause_id": c.clause_id,
        "doc_id": c.doc_id,
        "ordinal": c.ordinal,
        "heading": c.heading,
        "text": c.text,
        "normalised_text": c.normalised_text,
        "strain_id": c.strain_id,
        "virulence_score": c.virulence_score,
        "asymmetry_score": c.asymmetry_score,
        "harshness_delta": c.harshness_delta,
        "is_provisional_leaf": c.is_provisional_leaf,
    }


def _outcome_dict(o: Outcome) -> dict:
    return {
        "clause_family": o.clause_family,
        "jurisdiction": o.jurisdiction,
        "year": o.year,
        "outcome": o.outcome,
        "holding_summary": o.holding_summary,
        "source_label": o.source_label,
        "illustrative": o.illustrative,
    }


def _summarise_outcomes(outcomes: list[Outcome]) -> dict:
    if not outcomes:
        return {"total": 0}
    counts = {"upheld": 0, "voided": 0, "partially_voided": 0}
    for o in outcomes:
        if o.outcome in counts:
            counts[o.outcome] += 1
    return {"total": len(outcomes), **counts}
