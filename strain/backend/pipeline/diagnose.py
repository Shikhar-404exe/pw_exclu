"""
Diagnosis pipeline: takes a new document through the full pipeline and
produces a structured diagnosis report.
"""
from __future__ import annotations

import calendar
import json
import re
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlmodel import Session, select

from strain.backend.pipeline.segment import (
    ClauseRecord,
    detect_scope,
    detect_topics,
    is_compound,
    read_document,
    segment,
)
from strain.backend.pipeline.analyse import _asymmetry_score_for_text, WEIGHTS, _outcome_factor_for_strain
from strain.backend.pipeline.embed import get_embedding_provider
from strain.backend.pipeline.outcomes import SeedOutcomeProvider
from strain.backend.store.store import Clause, Document, Edge, Outcome, Strain

UNCLASSIFIED_THRESHOLD = 0.6  # cosine distance above this → unclassified (per AGENTS.md algorithm contract)


async def ingest_and_store(
    file_path: str,
    filename: str,
    session: Session,
) -> str:
    """
    Ingest a document: segment, store clauses, return doc_id.
    Does NOT run embedding/clustering (that's a batch pipeline step).
    """
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    text = read_document(file_path)
    clauses = segment(text, doc_id)

    doc = Document(
        doc_id=doc_id,
        filename=filename,
        synthetic=False,
        generation=None,
        raw_text=text,
    )
    session.add(doc)

    for cr in clauses:
        clause = Clause(
            clause_id=cr.clause_id,
            doc_id=cr.doc_id,
            ordinal=cr.ordinal,
            heading=cr.heading,
            text=cr.text,
            normalised_text=cr.normalised_text,
        )
        session.add(clause)

    session.commit()
    return doc_id


async def diagnose(
    file_path: str | None,
    filename: str | None,
    session: Session,
    existing_doc_id: str | None = None,
) -> dict:
    """
    Full diagnosis of a document.
    Returns structured report with per-clause diagnosis.
    """
    if existing_doc_id:
        doc_id = existing_doc_id
        doc = session.exec(
            select(Document).where(Document.doc_id == doc_id)
        ).first()
        if not doc:
            return {"error": "Document not found", "doc_id": doc_id}
        clauses = session.exec(
            select(Clause).where(Clause.doc_id == doc_id)
        ).all()
        raw_clauses: list[ClauseRecord] = [
            ClauseRecord(
                clause_id=c.clause_id,
                doc_id=c.doc_id,
                ordinal=c.ordinal,
                heading=c.heading,
                text=c.text,
                normalised_text=c.normalised_text,
            )
            for c in clauses
        ]
    else:
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        text = read_document(file_path)
        raw_clauses = segment(text, doc_id)

        doc = Document(
            doc_id=doc_id,
            filename=filename or "upload",
            synthetic=False,
            raw_text=text,
        )
        session.add(doc)
        for cr in raw_clauses:
            c = Clause(
                clause_id=cr.clause_id,
                doc_id=cr.doc_id,
                ordinal=cr.ordinal,
                heading=cr.heading,
                text=cr.text,
                normalised_text=cr.normalised_text,
            )
            session.add(c)
        session.commit()

    # Embed new clauses
    provider = get_embedding_provider()
    texts = [cr.normalised_text for cr in raw_clauses]
    embeddings = provider.encode(texts)

    # Persist embeddings
    for cr, emb in zip(raw_clauses, embeddings):
        existing_clause = session.exec(
            select(Clause).where(Clause.clause_id == cr.clause_id)
        ).first()
        if existing_clause:
            existing_clause.embedding_json = json.dumps(emb)
            session.add(existing_clause)
    session.commit()

    # Get all strain centroids. Materialise (strain, centroid) pairs up front:
    # a commit later in this function expires ORM instances, so the per-clause
    # loop must not re-read attributes off shared Strain rows (that pattern
    # caused ~19k lazy reloads). Plain tuples are immune to expiry.
    strains = session.exec(select(Strain)).all()
    strain_infos: list[tuple[Strain, Any]] = []
    for s in strains:
        if not s.centroid_json:
            continue
        centroid = np.array(json.loads(s.centroid_json), dtype=np.float32)
        norm = float(np.linalg.norm(centroid)) + 1e-9
        strain_infos.append((s, centroid / norm))

    # Diagnose each clause
    diagnosed_clauses = []
    for cr, emb in zip(raw_clauses, embeddings):
        result = _diagnose_clause(
            cr, emb, strain_infos, session
        )
        diagnosed_clauses.append(result)

    # Single commit for all provisional-leaf updates staged above.
    session.commit()

    # Sort by virulence (highest first)
    diagnosed_clauses.sort(key=lambda x: x.get("virulence_score") or 0, reverse=True)

    # Build handoff panel from top 3 operative clauses (preamble is
    # context, not an operative clause, so it never leads the handoff).
    rankable = [c for c in diagnosed_clauses if not c.get("is_preamble")]
    top_3 = (rankable or diagnosed_clauses)[:3]
    handoff = _build_handoff_panel(top_3, raw_clauses)

    # Geographic scope: v1 covers Indian rental agreements only.
    full_text = " ".join(cr.text for cr in raw_clauses)
    scope = detect_scope(full_text)
    scope_note = None
    if not scope["in_scope"]:
        markers = ", ".join(scope["markers"][:4])
        scope_note = (
            f"This document mentions {markers}, which is outside the Indian "
            "residential rental agreements this corpus covers. Textual kinship "
            "analysis still runs, but litigation history and legal framing are "
            "India-based and may not apply."
        )

    return {
        "doc_id": doc_id,
        "filename": filename or "upload",
        "synthetic": False,
        "corpus_note": (
            "The corpus is synthetic. Relationships shown are textual kinship "
            "between clause patterns, not proven copying or descent."
        ),
        "scope": {
            "in_scope": scope["in_scope"],
            "markers": scope["markers"],
            "note": scope_note,
        },
        "clause_count": len(diagnosed_clauses),
        "clauses": diagnosed_clauses,
        "handoff_panel": handoff,
    }


def _diagnose_clause(
    cr: ClauseRecord,
    embedding: list[float],
    strain_infos: list[tuple[Strain, Any]],
    session: Session,
) -> dict:
    """Assign a single clause to a strain and compute virulence.

    `strain_infos` are pre-materialised (strain, normalised-centroid) pairs
    (see diagnose()); this helper never triggers lazy reloads off them.
    DB updates are staged via session.add() — the caller commits once.
    """
    emb = np.array(embedding, dtype=np.float32)
    emb_norm = emb / (np.linalg.norm(emb) + 1e-9)

    best_strain = None
    best_distance = float("inf")

    for strain, centroid_norm in strain_infos:
        # Cosine distance = 1 - cosine_similarity
        cos_sim = float(np.dot(emb_norm, centroid_norm))
        cos_dist = 1.0 - cos_sim
        if cos_dist < best_distance:
            best_distance = cos_dist
            best_strain = strain

    unclassified = best_distance > UNCLASSIFIED_THRESHOLD or best_strain is None
    confidence = round(max(0.0, 1.0 - best_distance), 3)

    if unclassified:
        return {
            "clause_id": cr.clause_id,
            "doc_id": cr.doc_id,
            "ordinal": cr.ordinal,
            "heading": cr.heading,
            "text": cr.text,
            "topics": detect_topics(cr.text),
            "is_compound": is_compound(cr.text),
            "is_preamble": cr.heading.startswith("Preamble"),
            "strain_id": None,
            "family_name": None,
            "status": "unclassified",
            "unclassified_message": (
                "This clause could not be confidently assigned to any known strain family. "
                "It may be unique to this document or use unusual wording."
            ),
            "confidence": confidence,
            "virulence_score": None,
            "asymmetry_score": None,
            "harshness_delta": None,
            "outcomes": [],
            "neutralising_wording": None,
        }

    strain = best_strain
    # Compute virulence for this specific clause
    asymmetry = _asymmetry_score_for_text(cr.normalised_text)

    # Get root asymmetry
    root_asym = 50.0
    if strain.root_clause_id:
        root_clause = session.exec(
            select(Clause).where(Clause.clause_id == strain.root_clause_id)
        ).first()
        if root_clause:
            root_asym = _asymmetry_score_for_text(root_clause.normalised_text)

    harshness_delta = max(asymmetry - root_asym, 0.0)
    outcome_factor = _outcome_factor_for_strain(strain.strain_id, strain.family_name)

    virulence = (
        WEIGHTS["asymmetry"] * asymmetry
        + WEIGHTS["harshness_delta"] * min(harshness_delta * 2, 100.0)
        + WEIGHTS["outcome_factor"] * outcome_factor
    )

    # Get neutralising wording (lowest asymmetry variant in same strain)
    neutralising = _find_neutralising_wording(strain.strain_id, session)

    # Get litigation history
    outcomes = _get_outcomes_for_strain(strain.strain_id, strain.family_name)

    # Get nearest existing variant
    nearest = _find_nearest_variant(emb_norm, strain.strain_id, session)

    # Attach as provisional leaf if not already in DB for this strain.
    # Staged only — diagnose() commits once after all clauses.
    existing = session.exec(
        select(Clause).where(Clause.clause_id == cr.clause_id)
    ).first()
    if existing:
        existing.strain_id = strain.strain_id
        existing.virulence_score = round(virulence, 2)
        existing.asymmetry_score = round(asymmetry, 2)
        existing.harshness_delta = round(harshness_delta, 2)
        existing.outcome_factor = round(outcome_factor, 2)
        existing.is_provisional_leaf = True
        session.add(existing)

    return {
        "clause_id": cr.clause_id,
        "doc_id": cr.doc_id,
        "ordinal": cr.ordinal,
        "heading": cr.heading,
        "text": cr.text,
        "topics": detect_topics(cr.text),
        "is_compound": is_compound(cr.text),
        "is_preamble": cr.heading.startswith("Preamble"),
        "strain_id": strain.strain_id,
        "family_name": strain.family_name,
        "status": "classified",
        "confidence": confidence,
        "virulence_score": round(virulence, 2),
        "asymmetry_score": round(asymmetry, 2),
        "harshness_delta": round(harshness_delta, 2),
        "outcome_factor": round(outcome_factor, 2),
        "virulence_components": {
            "weights": WEIGHTS,
            "asymmetry": round(asymmetry, 2),
            "harshness_delta": round(harshness_delta, 2),
            "outcome_factor": round(outcome_factor, 2),
        },
        "outcomes": outcomes,
        "nearest_variant": nearest,
        "neutralising_wording": neutralising,
    }


def _find_neutralising_wording(
    strain_id: str, session: Session
) -> dict | None:
    """Find the most tenant-friendly clause in the strain family."""
    clauses = session.exec(
        select(Clause).where(
            Clause.strain_id == strain_id,
            Clause.asymmetry_score.isnot(None),  # type: ignore[arg-type]
        )
    ).all()

    if not clauses:
        return None

    # Lowest asymmetry = most tenant-friendly
    best = min(clauses, key=lambda c: c.asymmetry_score or 50.0)
    return {
        "clause_id": best.clause_id,
        "doc_id": best.doc_id,
        "text": best.text,
        "asymmetry_score": best.asymmetry_score,
        "source_doc_id": best.doc_id,
    }


def _get_outcomes_for_strain(strain_id: str, family_name: str) -> list[dict]:
    """Get illustrative outcome records for this strain."""
    provider = SeedOutcomeProvider()
    outcomes = provider.get_outcomes(strain_id) + provider.get_outcomes(family_name)
    # Deduplicate
    seen: set[str] = set()
    unique = []
    for o in outcomes:
        k = f"{o.get('clause_family')}:{o.get('year')}:{o.get('holding_summary', '')[:40]}"
        if k not in seen:
            seen.add(k)
            unique.append(o)
    return unique


def _find_nearest_variant(
    emb_norm: np.ndarray, strain_id: str, session: Session
) -> dict | None:
    """Find the closest existing clause in the strain to the new clause."""
    clauses = session.exec(
        select(Clause).where(
            Clause.strain_id == strain_id,
            Clause.embedding_json.isnot(None),  # type: ignore[arg-type]
        )
    ).all()

    best_sim = -1.0
    best_clause = None

    for c in clauses:
        if not c.embedding_json:
            continue
        cv = np.array(json.loads(c.embedding_json), dtype=np.float32)
        cv_norm = cv / (np.linalg.norm(cv) + 1e-9)
        sim = float(np.dot(emb_norm, cv_norm))
        if sim > best_sim:
            best_sim = sim
            best_clause = c

    if not best_clause:
        return None

    return {
        "clause_id": best_clause.clause_id,
        "doc_id": best_clause.doc_id,
        "text": best_clause.text,
        "similarity": round(best_sim, 3),
    }


_DURATION_PAT = re.compile(
    r"\b(\d+)\s*(days?|weeks?|months?|years?)\b", re.IGNORECASE
)
_DURATION_LABEL_KW = re.compile(
    r"lock[\s-]*in|notice|lease|tenancy|term|cure|grace|vacat|terminat|renewal|escalation",
    re.IGNORECASE,
)


def _parse_signing_date(detected: list[dict]) -> date:
    """Best-effort signing date: first parseable absolute date, else today."""
    fmts = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d")
    for entry in detected:
        if entry.get("kind") != "absolute":
            continue
        raw = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", entry["date"]).strip()
        for fmt in fmts:
            try:
                from datetime import datetime as _dt
                return _dt.strptime(raw, fmt).date()
            except ValueError:
                continue
    return date.today()


def _add_duration(base: date, amount: int, unit: str) -> date:
    """Add a duration to a date using calendar arithmetic."""
    unit = unit.lower()
    if unit.startswith("year"):
        months = amount * 12
    elif unit.startswith("month"):
        months = amount
    elif unit.startswith("week"):
        return base + timedelta(days=amount * 7)
    else:
        return base + timedelta(days=amount)
    total = (base.month - 1) + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _derive_dates_from_durations(
    all_clauses: list[ClauseRecord], detected: list[dict]
) -> list[dict]:
    """Convert duration mentions near tenancy keywords into absolute dates.

    Returns entries with kind="derived", a human label ("Lock-in expires",
    "Notice period ends", ...) and a relative detail ("5 months away").
    At most 3 derived entries are returned.
    """
    base = _parse_signing_date(detected)
    today = date.today()
    derived = []
    seen_labels: set[str] = set()
    for cr in all_clauses:
        for m in _DURATION_PAT.finditer(cr.text):
            window = cr.text[max(0, m.start() - 60) : m.end() + 60]
            if not _DURATION_LABEL_KW.search(window):
                continue
            amount, unit = int(m.group(1)), m.group(2)
            lowered = window.lower()
            if "lock" in lowered:
                label = "Lock-in expires"
            elif "notice" in lowered:
                label = "Notice period ends"
            elif "cure" in lowered or "grace" in lowered:
                label = "Cure/grace period ends"
            elif "escalation" in lowered or "renewal" in lowered:
                label = "Rent revision due"
            else:
                label = "Tenancy period ends"
            if label in seen_labels:
                continue
            seen_labels.add(label)
            target = _add_duration(base, amount, unit)
            days = (target - today).days
            if days < 0:
                detail = "already passed"
            elif days < 45:
                detail = f"{days} days away"
            else:
                detail = f"{round(days / 30)} months away"
            derived.append(
                {
                    "date": f"{target.day} {target.strftime('%B %Y')}",
                    "clause_id": cr.clause_id,
                    "heading": cr.heading,
                    "kind": "derived",
                    "label": label,
                    "detail": detail,
                }
            )
            if len(derived) >= 3:
                return derived
    return derived


def _build_handoff_panel(top_clauses: list[dict], all_clauses: list[ClauseRecord]) -> dict:
    """Build the terminal handoff panel for the diagnosis report."""

    # Detect any deadline-like dates in the full document, plus relative
    # deadlines ("3-day grace period", "within 15 days", ...).
    from strain.backend.pipeline.segment import _RELATIVE_DEADLINE_PAT

    date_pat = re.compile(
        r"\b(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
        r"|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{4}"
        r"|\d{1,2}(?:st|nd|rd|th)\s+day\s+of\s+"
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December),?\s+\d{2,4})\b",
        re.IGNORECASE,
    )
    detected_dates = []
    for cr in all_clauses:
        for m in date_pat.finditer(cr.text):
            detected_dates.append(
                {"date": m.group(0), "clause_id": cr.clause_id,
                 "heading": cr.heading, "kind": "absolute"}
            )
        for m in _RELATIVE_DEADLINE_PAT.finditer(cr.text):
            detected_dates.append(
                {"date": m.group(0).strip(), "clause_id": cr.clause_id,
                 "heading": cr.heading, "kind": "relative"}
            )

    # Duration patterns ("11 months lock-in", "60 days notice", ...) become
    # absolute dates by adding them to the document's signing date (the first
    # absolute date found; today if none). These power the "Key Dates" block.
    detected_dates.extend(
        _derive_dates_from_durations(all_clauses, detected_dates)
    )

    # Build per-clause lawyer questions based on strain family
    items = []
    for clause in top_clauses:
        family = clause.get("family_name") or "this clause"
        questions = _lawyer_questions_for_family(family, clause)
        items.append(
            {
                "clause_id": clause.get("clause_id"),
                "heading": clause.get("heading"),
                "family_name": family,
                "virulence_score": clause.get("virulence_score"),
                "text_excerpt": (clause.get("text") or "")[:200],
                "lawyer_questions": questions,
            }
        )

    return {
        "top_risk_clauses": items,
        "documents_to_bring": [
            "Copy of this rental agreement (all pages)",
            "Any previous correspondence with the landlord",
            "Payment receipts for deposit and rent",
            "Photographs of the property at time of possession",
            "Any addendums or side letters",
        ],
        "detected_deadlines": detected_dates[:8],  # top 8
        "legal_referral_note": (
            "The above questions are to help you have a productive conversation "
            "with a qualified lawyer. A lawyer can assess how these clauses interact "
            "with applicable local rent control legislation and your specific situation."
        ),
    }


_FAMILY_QUESTIONS: dict[str, list[str]] = {
    "Rent Payment": [
        "Is the stated rent lawful and does it match what was verbally agreed?",
        "What interest or penalty applies to late payment, and is that rate permitted?",
        "Is there a grace period for late payment, and what triggers eviction for arrears?",
    ],
    "Penalty": [
        "Is this penalty a genuine pre-estimate of loss or an unenforceable punishment?",
        "Does the penalty apply proportionately, or is the full amount forfeited on any breach?",
        "Can this amount be reduced by a court or forum if challenged?",
    ],
    "Rent Escalation": [
        "Is this increase capped, and does it require your written agreement?",
        "How does the escalated rent compare to prevailing market rates in the area?",
        "What happens if you do not accept the escalated rent?",
    ],
    "Utilities": [
        "Which outgoings are yours and which are the landlord's, and is that split lawful?",
        "Can unpaid utility bills be used as grounds to terminate your tenancy?",
        "Who is liable for society charges, property tax, and municipal levies?",
    ],
    "Subletting": [
        "Does this restriction require the landlord's consent, and can consent be unreasonably withheld?",
        "What are the consequences of a breach — termination, forfeiture, or both?",
        "Does the clause distinguish between full subletting and sharing with family or guests?",
    ],
    "Security Deposit": [
        "Is this deposit amount permitted under the applicable State rent control Act?",
        "Under what conditions can the landlord make deductions, and is that list exhaustive?",
        "What is the timeline for return of the deposit and is there a penalty for late return?",
    ],
    "Notice Period": [
        "Is this notice period lawful under local rent legislation?",
        "Does the notice requirement apply equally to both parties?",
        "What counts as valid delivery of a notice under this agreement?",
    ],
    "Lock-in Period": [
        "Is early termination possible and under what conditions?",
        "What penalties apply if you need to vacate before the lock-in expires?",
        "Does this lock-in clause comply with local tenancy law?",
    ],
    "Repairs & Maintenance": [
        "Which repairs is the landlord legally obliged to carry out regardless of this clause?",
        "What is the process for reporting a repair need and getting it done?",
        "Can you withhold rent or make deductions if repairs are not done?",
    ],
    "Landlord Entry Rights": [
        "What notice must the landlord give before entering, and is this clause lawful?",
        "Under what circumstances can entry happen without prior notice?",
        "What remedies are available if this clause is violated?",
    ],
    "Termination": [
        "What are the valid grounds for termination by each party?",
        "Is this clause consistent with local rent control legislation on security of tenure?",
        "What happens to your deposit if the landlord terminates?",
    ],
    "Dispute Resolution": [
        "Is this arbitration clause enforceable under the Arbitration and Conciliation Act, 1996?",
        "Do you waive any rights by agreeing to this dispute resolution mechanism?",
        "Is the choice of arbitrator/forum neutral and accessible to you?",
    ],
}

_DEFAULT_QUESTIONS = [
    "Is this clause enforceable under applicable local law?",
    "Does this clause give one party significantly more power than the other?",
    "Are there any conditions or limits missing that should protect your rights?",
]


def _lawyer_questions_for_family(family_name: str, clause: dict) -> list[str]:
    for key, questions in _FAMILY_QUESTIONS.items():
        if key.lower() in family_name.lower():
            return questions
    return _DEFAULT_QUESTIONS
