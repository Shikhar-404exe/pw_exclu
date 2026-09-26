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
from typing import Any

import numpy as np
from sqlmodel import Session, select

from strain.backend.pipeline.analyse import (
    WEIGHTS,
    _normalised_edit_distance,
    assess_asymmetry,
    assess_harshness_vs_root,
    assess_outcome_factor,
    extract_clause_features,
)
from strain.backend.pipeline.embed import get_embedding_provider
from strain.backend.pipeline.outcomes import SeedOutcomeProvider
from strain.backend.pipeline.segment import (
    TOPIC_LABELS,
    ClauseRecord,
    _is_topic_heading,
    classify_kind,
    classify_topic,
    detect_scope,
    detect_topics,
    is_compound,
    read_document,
    segment,
)
from strain.backend.store.store import Clause, Document, Strain

UNCLASSIFIED_THRESHOLD = 0.6  # cosine distance above this → unclassified (per AGENTS.md algorithm contract)

#: Component kinds that stay out of ordinary legal-risk scoring.
NON_OPERATIVE_KINDS = ("preamble", "schedule", "signature", "witness", "footer")

_EXCLUSION_REASONS = {
    "preamble": "Preamble identifies the parties and property; it creates no obligations and is not scored.",
    "schedule": "Property schedule describes the premises; it creates no obligations and is not scored.",
    "signature": "Signature blocks execute the document; they are not operative clauses and are not scored.",
    "witness": "Witness blocks attest execution; they are not operative clauses and are not scored.",
    "footer": "Document footer/notice text; not an operative clause and not scored.",
}


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
                topic=classify_topic(c.text, c.heading)[0],
                kind=classify_kind(c.text, c.heading),
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
    for cr, emb in zip(raw_clauses, embeddings, strict=True):
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
    for cr, emb in zip(raw_clauses, embeddings, strict=True):
        result = _diagnose_clause(
            cr, emb, strain_infos, session
        )
        diagnosed_clauses.append(result)

    # Single commit for all provisional-leaf updates staged above.
    session.commit()

    # Sort by virulence (highest first)
    diagnosed_clauses.sort(key=lambda x: x.get("virulence_score") or 0, reverse=True)

    # Build handoff panel from top 3 operative clauses (preamble, signature,
    # witness and schedule segments are context, not operative clauses, so
    # they never lead the handoff).
    rankable = [c for c in diagnosed_clauses if c.get("kind", "operative") == "operative"]
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

    # Operative counts exclude preambles, signatures, witnesses and other
    # non-operative segments — the report statistics must reflect scored
    # operative clauses, not document furniture.
    operative = [c for c in diagnosed_clauses if c.get("kind", "operative") == "operative"]
    excluded = [c for c in diagnosed_clauses if c.get("kind", "operative") != "operative"]

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
        "operative_count": len(operative),
        "excluded_count": len(excluded),
        "clauses": diagnosed_clauses,
        "handoff_panel": handoff,
    }


def _topic_with_confidence(cr: ClauseRecord) -> tuple[str, str]:
    """Topic id + confidence, ignoring non-topic headings."""
    heading = cr.heading if _is_topic_heading(cr.heading) else ""
    topic = cr.topic or "other"
    _, conf = classify_topic(cr.text, heading)
    if topic == "other":
        conf = "low"
    return topic, conf


def _confidence_rank(label: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(label, 1)


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
    topic, topic_confidence = _topic_with_confidence(cr)
    topic_label = TOPIC_LABELS.get(topic, topic)
    base = {
        "clause_id": cr.clause_id,
        "doc_id": cr.doc_id,
        "ordinal": cr.ordinal,
        "heading": cr.heading,
        "text": cr.text,
        "topics": detect_topics(cr.text),
        "topic": topic,
        "topic_label": topic_label,
        "topic_confidence": topic_confidence,
        "kind": cr.kind,
        "is_compound": is_compound(cr.text),
        "is_preamble": cr.heading.startswith("Preamble") or cr.kind == "preamble",
    }

    # Non-operative components are identified, never scored.
    if cr.kind in NON_OPERATIVE_KINDS:
        return {
            **base,
            "strain_id": None,
            "family_name": None,
            "status": "excluded",
            "exclusion_reason": _EXCLUSION_REASONS.get(
                cr.kind, "Non-operative document component; not scored."
            ),
            "confidence": None,
            "virulence_score": None,
            "asymmetry_score": None,
            "harshness_delta": None,
            "outcome_factor": None,
            "risk_confidence": None,
            "evidence": None,
            "evidence_limitations": [],
            "outcomes": [],
            "neutralising_wording": None,
            "neutralising_note": None,
        }

    emb = np.array(embedding, dtype=np.float32)
    emb_norm = emb / (np.linalg.norm(emb) + 1e-9)

    best_strain = None
    best_distance = float("inf")

    for strain, centroid_norm in strain_infos:
        # Skip strains embedded in a different vector space (e.g. after an
        # embedding-model change): incomparable centroids must not crash
        # matching, they simply cannot match this clause.
        if centroid_norm.shape != emb_norm.shape:
            continue
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
            **base,
            "strain_id": None,
            "family_name": None,
            "status": "unclassified",
            "unclassified_message": (
                "This clause could not be confidently assigned to any known strain family "
                f"(nearest distance {best_distance:.2f} exceeds the {UNCLASSIFIED_THRESHOLD:.2f} threshold). "
                "It may be unique to this document or use unusual wording. "
                "Its topic classification above still applies."
            ),
            "confidence": confidence,
            "virulence_score": None,
            "asymmetry_score": None,
            "harshness_delta": None,
            "outcome_factor": None,
            "risk_confidence": None,
            "evidence": None,
            "evidence_limitations": ["No strain family assigned; risk components not computed."],
            "outcomes": [],
            "neutralising_wording": None,
            "neutralising_note": None,
        }

    strain = best_strain
    # Evidence-based component assessments (Stage 4 calibration).
    asym = assess_asymmetry(cr.normalised_text)

    # Get root text for the feature-level harshness diff.
    root_text = None
    if strain.root_clause_id:
        root_clause = session.exec(
            select(Clause).where(Clause.clause_id == strain.root_clause_id)
        ).first()
        if root_clause:
            root_text = root_clause.normalised_text
    harsh = assess_harshness_vs_root(cr.normalised_text, root_text)
    out = assess_outcome_factor(strain.strain_id, strain.family_name)

    asymmetry = asym["score"]
    harshness_delta = harsh["score"]
    outcome_factor = out["value"]

    virulence = (
        WEIGHTS["asymmetry"] * asymmetry
        + WEIGHTS["harshness_delta"] * min(harshness_delta * 2, 100.0)
        + WEIGHTS["outcome_factor"] * outcome_factor
    )

    risk_confidence = min(
        _confidence_rank(asym["confidence"]),
        _confidence_rank(harsh["confidence"]),
        _confidence_rank(out["confidence"]),
    )
    risk_confidence_label = {1: "low", 2: "medium", 3: "high"}[risk_confidence]
    evidence_limitations = []
    if asym["confidence"] == "low":
        evidence_limitations.append(
            "Asymmetry inferred from limited markers: " + asym["rationale"]
        )
    if harsh["confidence"] == "low":
        evidence_limitations.append(
            "Harshness comparison limited: " + harsh["rationale"]
        )
    if out["records"] == 0:
        evidence_limitations.append(
            "No illustrative outcome records for this family."
        )
    elif out["records"] < 3:
        evidence_limitations.append(
            f"Only {out['records']} illustrative scenario(s); treat as background, not a probability."
        )

    # Same-family reference variant with semantic preservation gates.
    neutralising, neutralising_note = _select_reference_variant(
        cr, strain.strain_id, asymmetry, session
    )

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
        **base,
        "strain_id": strain.strain_id,
        "family_name": strain.family_name,
        "status": "classified",
        "confidence": confidence,
        "virulence_score": round(virulence, 2),
        "asymmetry_score": round(asymmetry, 2),
        "harshness_delta": round(harshness_delta, 2),
        "outcome_factor": round(outcome_factor, 2),
        "risk_confidence": risk_confidence_label,
        "virulence_components": {
            "weights": WEIGHTS,
            "asymmetry": round(asymmetry, 2),
            "harshness_delta": round(harshness_delta, 2),
            "outcome_factor": round(outcome_factor, 2),
        },
        "evidence": {
            "asymmetry": {
                "value": round(asymmetry, 2),
                "confidence": asym["confidence"],
                "features": asym["features"],
                "rationale": asym["rationale"],
            },
            "harshness": {
                "value": round(harshness_delta, 2),
                "confidence": harsh["confidence"],
                "features": harsh["features"],
                "rationale": harsh["rationale"],
            },
            "outcome": {
                "value": round(outcome_factor, 2),
                "confidence": out["confidence"],
                "records": out["records"],
                "voided": out["voided"],
                "basis": out["basis"],
                "verified_sources": out["verified_sources"],
                "rationale": out["rationale"],
            },
        },
        "evidence_limitations": evidence_limitations,
        "outcomes": outcomes,
        "nearest_variant": nearest,
        "neutralising_wording": neutralising,
        "neutralising_note": neutralising_note,
    }


# Minimum normalised-text similarity (0–1) for a reference variant to be
# shown alongside a clause. Below this, wording is too different for a
# meaningful comparison.
REFERENCE_SIMILARITY_THRESHOLD = 0.45

# A candidate must beat the source asymmetry by at least this margin to
# count as lower-risk.
REFERENCE_IMPROVEMENT_MARGIN = 5.0

NO_VARIANT_MESSAGE = (
    "No sufficiently similar, meaning-preserving lower-risk variant "
    "was found in this dataset."
)


def _compare_material_terms(src_feats: dict, cand_feats: dict) -> list[str]:
    """List material differences between source and candidate clause features.

    Any non-empty result disqualifies the candidate as a meaning-preserving
    comparison: durations, amounts, notice/cure timelines, penalties,
    deposit terms, parties and renewal conditions must all agree.
    """
    diffs: list[str] = []
    st, ct = src_feats.get("term_months"), cand_feats.get("term_months")
    if st is not None and ct is not None and abs(st - ct) > 0.5:
        diffs.append(f"tenancy length differs ({st:g} vs {ct:g} months)")
    elif (st is None) != (ct is None):
        diffs.append("tenancy length present in only one variant")
    sn = src_feats.get("notice_days") or []
    cn = cand_feats.get("notice_days") or []
    if sn and cn and abs(min(sn) - min(cn)) > 1:
        diffs.append(f"notice timeline differs ({min(sn):g} vs {min(cn):g} days)")
    for key, label in (
        ("cure_present", "cure/remedy right"),
        ("grace_present", "grace period"),
        ("penalty_present", "penalty provision"),
        ("forfeiture_present", "deposit forfeiture"),
        ("interest_present", "interest on arrears"),
        ("discretion_landlord", "landlord discretion"),
        ("entry_unrestricted", "unrestricted entry"),
        ("renewal_mutual", "mutual-consent renewal"),
        ("deposit_refundable", "deposit refundability"),
        ("unilateral_landlord", "unilateral landlord termination"),
        ("unilateral_tenant", "unilateral tenant termination"),
    ):
        if bool(src_feats.get(key)) != bool(cand_feats.get(key)):
            which = "source" if src_feats.get(key) else "candidate"
            diffs.append(f"{label} present only in {which}")
    if src_feats.get("cure_days") and cand_feats.get("cure_days") and abs(src_feats["cure_days"] - cand_feats["cure_days"]) > 0.5:
        diffs.append(
            f"cure period differs ({src_feats['cure_days']:g} vs "
            f"{cand_feats['cure_days']:g} days)"
        )
    if src_feats.get("deposit_refund_days") and cand_feats.get("deposit_refund_days") and abs(src_feats["deposit_refund_days"] - cand_feats["deposit_refund_days"]) > 1:
        diffs.append("deposit refund timeline differs")
    if len(src_feats.get("amounts", [])) != len(cand_feats.get("amounts", [])):
        diffs.append("monetary amounts differ in count — verify figures match")
    return diffs


def _select_reference_variant(
    source_cr: ClauseRecord,
    strain_id: str,
    source_asymmetry: float,
    session: Session,
) -> tuple[dict | None, str | None]:
    """Select a same-family reference variant with semantic preservation gates.

    A candidate must (a) share the source clause topic, (b) reach the text
    similarity threshold, (c) beat the source asymmetry by the improvement
    margin, and (d) preserve all material terms. Returns (variant, None) on
    success — Mode 1 "related reference variant", labelled as such — or
    (None, reason) when nothing qualifies. Mode 2 (generated rewrites) is
    deliberately not produced: inventing clause text is unsafe, so absence
    is reported with NO_VARIANT_MESSAGE instead.
    """
    members = session.exec(
        select(Clause).where(
            Clause.strain_id == strain_id,
            Clause.asymmetry_score.isnot(None),  # type: ignore[arg-type]
        )
    ).all()
    src_feats = extract_clause_features(source_cr.normalised_text)
    src_topic = source_cr.topic or "other"

    examined = 0
    rejected: list[str] = []
    viable: list[tuple[float, Clause]] = []
    for c in members:
        if c.doc_id == source_cr.doc_id or not c.text:
            continue
        cand_topic, _ = classify_topic(c.text, c.heading)
        if src_topic != "other" and cand_topic != src_topic:
            continue
        examined += 1
        sim = 1.0 - _normalised_edit_distance(c.normalised_text, source_cr.normalised_text)
        if sim < REFERENCE_SIMILARITY_THRESHOLD:
            rejected.append(f"{c.clause_id} too dissimilar ({sim:.2f})")
            continue
        if (c.asymmetry_score or 50.0) >= source_asymmetry - REFERENCE_IMPROVEMENT_MARGIN:
            rejected.append(f"{c.clause_id} not lower-risk enough")
            continue
        cand_feats = extract_clause_features(c.normalised_text)
        diffs = _compare_material_terms(src_feats, cand_feats)
        if diffs:
            rejected.append(f"{c.clause_id} changes material terms: {diffs[0]}")
            continue
        viable.append((sim, c))

    if not viable:
        reason = NO_VARIANT_MESSAGE
        if examined == 0:
            reason += " No comparable scored clauses exist in this strain family."
        elif rejected:
            reason += f" Closest rejections: {'; '.join(rejected[:2])}."
        return None, reason

    viable.sort(key=lambda t: t[0], reverse=True)
    best = viable[0][1]
    return {
        "mode": "reference",
        "clause_id": best.clause_id,
        "doc_id": best.doc_id,
        "text": best.text,
        "asymmetry_score": best.asymmetry_score,
        "source_doc_id": best.doc_id,
        "material_differences": [],
        "note": (
            "Related lower-risk variant from the same textual family, shown "
            "verbatim with its source. A reference point for discussion — not "
            "a validated fair rewrite."
        ),
    }, None


def _get_outcomes_for_strain(strain_id: str, family_name: str) -> list[dict]:
    """Get illustrative outcome records for this strain.

    Every record is explicitly marked illustrative with no verified source.
    These scenarios show the *kind* of pattern recorded in the dataset —
    never a real court decision about the user's clause.
    """
    provider = SeedOutcomeProvider()
    outcomes = provider.get_outcomes(strain_id) + provider.get_outcomes(family_name)
    # Deduplicate
    seen: set[str] = set()
    unique = []
    for o in outcomes:
        k = f"{o.get('clause_family')}:{o.get('year')}:{o.get('holding_summary', '')[:40]}"
        if k not in seen:
            seen.add(k)
            record = dict(o)
            record["illustrative"] = True
            record["verified"] = False
            record["source_disclosure"] = (
                "Illustrative dataset scenario — not a verified judgment. "
                "No independently verified legal source in this dataset."
            )
            unique.append(record)
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


_ABSOLUTE_DATE_PAT = re.compile(
    r"\b(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
    r"|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{4}"
    r"|\d{1,2}(?:st|nd|rd|th)\s+day\s+of\s+"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December),?\s+\d{2,4})\b",
    re.IGNORECASE,
)

_DAY_OF_MONTH_PAT = re.compile(
    r"(?:on or before|before|by|due on|no later than)\s+(?:the\s+)?"
    r"(\d{1,2})(?:st|nd|rd|th)?(?:\s+day)?(?!\s*(?:January|February|March|April|"
    r"May|June|July|August|September|October|November|December|[/\-\.]\d))",
    re.IGNORECASE,
)

_EXECUTION_CUE = re.compile(
    r"execut|made and|entered into|dated|signed|first written|stamp", re.IGNORECASE)
_COMMENCEMENT_CUE = re.compile(
    r"commenc|with effect|effect from|term begins|begins on|comes? into force", re.IGNORECASE)
_EXPIRY_CUE = re.compile(
    r"expir|until|valid (till|until|up ?to)|end of (the )?(term|tenancy|lease|agreement)|"
    r"termination of (this|the)", re.IGNORECASE)
_PAYMENT_CUE = re.compile(
    r"payable|due|remit|\bpay\b|payment", re.IGNORECASE)


def _type_absolute_date(window: str) -> str:
    """Classify an explicit date mention (never assume it is a deadline)."""
    if _EXECUTION_CUE.search(window):
        return "execution"
    if _COMMENCEMENT_CUE.search(window):
        return "commencement"
    if _EXPIRY_CUE.search(window):
        return "expiry"
    if _PAYMENT_CUE.search(window):
        return "payment_due"
    return "explicit_other"


def _parse_anchor_date(date_text: str) -> date | None:
    raw = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_text).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _format_day(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


_SMALL_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                  "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                  "eleven": 11, "twelve": 12}


def _find_duration_match(text: str, amount: int, unit: str):
    """Locate the regex match for a parsed (amount, unit) duration."""
    word = next((k for k, v in _SMALL_NUMBERS.items() if v == amount), None)
    if word:
        return re.search(
            rf"\(?{amount}\)?\s*{unit}|\b{word}\s*{unit}",
            text, re.IGNORECASE)
    return re.search(rf"\(?{amount}\)?\s*{unit}", text, re.IGNORECASE)


def _extract_typed_dates(all_clauses: list[ClauseRecord]) -> tuple[list[dict], dict | None]:
    """Extract typed key dates with anchor discipline.

    Returns (entries, anchor) where anchor is {"date", "label"} or None.
    Duration-based dates are computed ONLY from a reliable anchor (an
    explicit execution or commencement date in the document). Without one,
    durations stay unresolved — an anchor is never invented. An eleven-month
    term is labelled by its own provision ("Tenancy expires"), never
    assumed to be a lock-in.
    """
    from strain.backend.pipeline.analyse import parse_durations

    entries: list[dict] = []
    anchor: dict | None = None

    # Pass 1: explicit dates, typed by surrounding cues.
    for cr in all_clauses:
        for m in _ABSOLUTE_DATE_PAT.finditer(cr.text):
            window = cr.text[max(0, m.start() - 80): m.end() + 80]
            dtype = _type_absolute_date(window)
            parsed = _parse_anchor_date(m.group(0))
            entries.append({
                "date": m.group(0),
                "parsed_date": parsed.isoformat() if parsed else None,
                "label": {
                    "execution": "Execution date",
                    "commencement": "Commencement date",
                    "expiry": "Expiry date",
                    "payment_due": "Payment due",
                    "explicit_other": "Date mentioned",
                }[dtype],
                "date_type": dtype,
                "basis": "explicit",
                "detail": None,
                "clause_id": cr.clause_id,
                "heading": cr.heading,
            })
            if anchor is None and dtype in ("execution", "commencement") and parsed:
                anchor = {"date": parsed, "label": "execution" if dtype == "execution" else "commencement"}

    # Pass 2: day-of-month recurrences ("payable on or before the 5th").
    for cr in all_clauses:
        for m in _DAY_OF_MONTH_PAT.finditer(cr.text):
            window = cr.text[max(0, m.start() - 60): m.end() + 40]
            if not _PAYMENT_CUE.search(window):
                continue
            entries.append({
                "date": None,
                "parsed_date": None,
                "label": "Monthly payment due",
                "date_type": "payment_due",
                "basis": "explicit",
                "detail": f"day {int(m.group(1))} of each month (recurring)",
                "clause_id": cr.clause_id,
                "heading": cr.heading,
            })

    # Pass 3: durations near tenancy cues, resolved against the anchor only.
    # The label follows the cue NEAREST the duration: "remain in force for
    # eleven months" is a tenancy expiry even when the same sentence mentions
    # termination. An eleven-month term is never assumed to be a lock-in.
    _CUE_LABELS = (
        (re.compile(r"lock[\s-]*in", re.IGNORECASE), "lockin_end", "Lock-in ends"),
        (re.compile(r"remain in force|term of|duration of|valid for|validity|tenure|"
                    r"minimum (occupancy|period)", re.IGNORECASE), "expiry", "Tenancy expires"),
        (re.compile(r"expir", re.IGNORECASE), "expiry", "Tenancy expires"),
        (re.compile(r"notice", re.IGNORECASE), "notice_deadline", "Notice deadline"),
        (re.compile(r"terminat", re.IGNORECASE), "notice_deadline", "Notice deadline"),
        (re.compile(r"cure|grace|remedy", re.IGNORECASE), "cure_deadline", "Cure deadline"),
        (re.compile(r"renewal|\brenew\b", re.IGNORECASE), "renewal_notice", "Renewal notice deadline"),
        (re.compile(r"escalation", re.IGNORECASE), "payment_due", "Rent revision due"),
    )
    seen_kinds: set[str] = set()
    for cr in all_clauses:
        for amount, unit in parse_durations(cr.text):
            dm = _find_duration_match(cr.text, amount, unit)
            center = (dm.start() + dm.end()) / 2 if dm else 0
            lo = max(0, int(center) - 70)
            hi = int(center) + 50
            window = cr.text[lo:hi]
            best = None
            best_dist = None
            for pat, dtype, label in _CUE_LABELS:
                for cm in pat.finditer(window):
                    dist = abs((lo + cm.start() + cm.end()) / 2 - center)
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best = (dtype, label)
            if best is None:
                continue
            dtype, label = best
            if dtype in seen_kinds:
                continue
            seen_kinds.add(dtype)
            # Only tenancy/lock-in durations start at the anchor (execution or
            # commencement). Notice, cure and renewal periods run from a
            # future event (giving notice, breach, renewal decision), so
            # anchoring them to execution would invent precision.
            if dtype in ("expiry", "lockin_end") and anchor is not None:
                target = _add_duration(anchor["date"], amount, unit)
                today = date.today()
                days = (target - today).days
                detail = (
                    "already passed" if days < 0
                    else (f"{days} days away" if days < 45 else f"{round(days / 30)} months away")
                )
                entries.append({
                    "date": _format_day(target),
                    "parsed_date": target.isoformat(),
                    "label": label,
                    "date_type": dtype,
                    "basis": "calculated",
                    "detail": (
                        f"{amount} {unit} after {anchor['label']} "
                        f"({anchor['date'].strftime('%d %B %Y')}); approximate — subject to "
                        f"the contract's inclusive/exclusive date convention. {detail}"
                    ),
                    "clause_id": cr.clause_id,
                    "heading": cr.heading,
                })
                continue
            entries.append({
                "date": None,
                "parsed_date": None,
                "label": label,
                "date_type": "relative_unresolved",
                "basis": "unresolved",
                "detail": (
                    f"{amount} {unit} — runs from a future event (notice given, breach, "
                    "renewal decision) or an undated start; absolute date cannot be determined"
                ),
                "clause_id": cr.clause_id,
                "heading": cr.heading,
            })

    # Order: execution, commencement, expiry, payment, deadlines, other, unresolved.
    order = {"execution": 0, "commencement": 1, "expiry": 2, "payment_due": 3,
             "notice_deadline": 4, "lockin_end": 5, "renewal_notice": 6,
             "cure_deadline": 7, "explicit_other": 8, "relative_unresolved": 9}
    entries.sort(key=lambda e: order.get(e["date_type"], 8))
    return entries, anchor


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


def _build_handoff_panel(top_clauses: list[dict], all_clauses: list[ClauseRecord]) -> dict:
    """Build the terminal handoff panel for the diagnosis report."""

    # Detect any deadline-like dates in the full document, plus relative
    # deadlines ("3-day grace period", "within 15 days", ...).
    from strain.backend.pipeline.segment import _RELATIVE_DEADLINE_PAT

    detected_dates = []
    for cr in all_clauses:
        for m in _ABSOLUTE_DATE_PAT.finditer(cr.text):
            window = cr.text[max(0, m.start() - 80): m.end() + 80]
            detected_dates.append(
                {"date": m.group(0), "clause_id": cr.clause_id,
                 "heading": cr.heading, "kind": "absolute",
                 "date_type": _type_absolute_date(window)}
            )
        detected_dates.extend(
            {"date": m.group(0).strip(), "clause_id": cr.clause_id,
             "heading": cr.heading, "kind": "relative",
             "date_type": "relative_unresolved"}
            for m in _RELATIVE_DEADLINE_PAT.finditer(cr.text)
        )

    # Typed key dates (execution vs deadlines vs calculated expiries).
    # Execution dates are labelled as such — never presented as deadlines.
    key_dates, _anchor = _extract_typed_dates(all_clauses)

    # Build per-clause lawyer questions, routed by clause topic first
    # (an ownership declaration must never receive rent-payment questions),
    # falling back to strain family and then generic questions.
    items = []
    for clause in top_clauses:
        family = clause.get("family_name") or "this clause"
        questions = _lawyer_questions_for_family(family, clause)
        items.append(
            {
                "clause_id": clause.get("clause_id"),
                "heading": clause.get("heading"),
                "family_name": family,
                "topic": clause.get("topic") or "other",
                "topic_label": clause.get("topic_label") or "Other / Unclassified",
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
        "detected_deadlines": detected_dates[:8],  # legacy list, kept for compatibility
        "key_dates": key_dates,
        "legal_referral_note": (
            "The above questions are to help you have a productive conversation "
            "with a qualified lawyer. A lawyer can assess how these clauses interact "
            "with applicable local rent control legislation and your specific situation."
        ),
    }


_TOPIC_QUESTIONS: dict[str, list[str]] = {
    "term_renewal": [
        "Is the stated tenancy length correct, and what exactly renews or ends on expiry?",
        "Does renewal require your written agreement, or can it happen automatically?",
        "Is this treated as a lock-in (no early exit) or an ordinary fixed term — and which does the wording support?",
    ],
    "rent_payment": [
        "Is the stated rent lawful and does it match what was verbally agreed?",
        "What interest or penalty applies to late payment, and is that rate permitted?",
        "Is there a grace period for late payment, and what triggers eviction for arrears?",
    ],
    "deposit_refund": [
        "Is this deposit amount permitted under the applicable State rent control Act?",
        "Under what conditions can the landlord make deductions, and is that list exhaustive?",
        "What is the timeline for return of the deposit and is there a penalty for late return?",
    ],
    "termination_notice": [
        "Is this notice period lawful under local rent legislation?",
        "Does the notice requirement apply equally to both parties?",
        "What counts as valid delivery of a notice under this agreement?",
    ],
    "eviction_possession": [
        "Under what conditions can the landlord take back possession, and is a court order required?",
        "What handover condition is expected, and who decides whether it is met?",
        "Does this clause limit any statutory protection against eviction?",
    ],
    "late_penalty": [
        "Is this penalty a genuine pre-estimate of loss or an unenforceable punishment?",
        "Does the penalty apply proportionately, or is the full amount forfeited on any breach?",
        "Can this amount be reduced by a court or forum if challenged?",
    ],
    "maintenance_repairs": [
        "Which repairs is the landlord legally obliged to carry out regardless of this clause?",
        "What is the process for reporting a repair need and getting it done?",
        "Can you withhold rent or make deductions if repairs are not done?",
    ],
    "utilities": [
        "Which outgoings are yours and which are the landlord's, and is that split lawful?",
        "Can unpaid utility bills be used as grounds to terminate your tenancy?",
        "Who is liable for society charges, property tax, and municipal levies?",
    ],
    "landlord_access": [
        "What notice must the landlord give before entering, and is this clause lawful?",
        "Under what circumstances can entry happen without prior notice?",
        "What remedies are available if this clause is violated?",
    ],
    "subletting": [
        "Does this restriction require the landlord's consent, and can consent be unreasonably withheld?",
        "What are the consequences of a breach — termination, forfeiture, or both?",
        "Does the clause distinguish between full subletting and sharing with family or guests?",
    ],
    "permitted_use": [
        "Does this use restriction go beyond ordinary residential use?",
        "Could ordinary activities (working from home, guests, family) breach this clause?",
        "What happens on a breach — cure, penalty, or termination?",
    ],
    "ownership_authority": [
        "Has the landlord's ownership and authority to let been verified (title, encumbrance)?",
        "Does the declaration cover the entire premises described in the schedule?",
        "What happens to your tenancy if the ownership claim proves incorrect?",
    ],
    "dispute_resolution": [
        "Is this arbitration clause enforceable under the Arbitration and Conciliation Act, 1996?",
        "Do you waive any rights by agreeing to this dispute resolution mechanism?",
        "Is the choice of arbitrator/forum neutral and accessible to you?",
    ],
    "property_schedule": [
        "Does the description match the actual premises (area, floor, parking, fixtures)?",
        "Are there ambiguities in the schedule that could cause handover disputes?",
        "Do the documents attached to the schedule exist and match?",
    ],
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
    # Topic routing comes first: questions must match what the clause is
    # about, not merely which textual family it resembles.
    topic = (clause.get("topic") or "").lower()
    if topic in _TOPIC_QUESTIONS:
        return _TOPIC_QUESTIONS[topic]
    for key, questions in _FAMILY_QUESTIONS.items():
        if key.lower() in family_name.lower():
            return questions
    return _DEFAULT_QUESTIONS
