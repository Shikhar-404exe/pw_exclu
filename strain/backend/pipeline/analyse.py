"""
Analysis pipeline: phylogeny reconstruction, mutation labelling, virulence scoring.

Merged from pipeline/phylogeny.py, pipeline/mutate_label.py and
pipeline/virulence.py. Three public entry points:

- build_phylogeny(session)
- label_all_edges(session)
- score_all_clauses(session)

All existing logic, docstrings and helpers are preserved — the algorithms
are unchanged.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import date

import numpy as np
from sqlmodel import Session, select

from strain.backend.pipeline.outcomes import SeedOutcomeProvider
from strain.backend.store.store import Clause, Document, Edge, Outcome, Strain

WEIGHTS = {"asymmetry": 0.4, "harshness_delta": 0.4, "outcome_factor": 0.2}


# ─── Phylogeny reconstruction ───────────────────────────────────────────────
# Builds the mutation tree within each strain.
#
# Algorithm:
# 1. Pairwise normalised edit distance between clauses in the same strain.
# 2. Minimum spanning tree (scipy) over those distances.
# 3. Orient each edge: earlier synthetic_date = parent.
#    Tie-break: lower structural complexity (fewer sub-clauses) = parent.
# 4. Write to edges table.

def _normalised_edit_distance(a: str, b: str) -> float:
    """Normalised Levenshtein distance in [0, 1]."""
    from Levenshtein import distance as lev_distance
    if not a and not b:
        return 0.0
    d = lev_distance(a, b)
    max_len = max(len(a), len(b))
    return d / max_len if max_len > 0 else 0.0


def _structural_complexity(text: str) -> int:
    """Count sub-clause markers as a proxy for structural complexity."""
    return len(re.findall(r"(?:^\s*[a-z]\.|^\s*\([a-z]\)|\b\(i+\))", text, re.MULTILINE))


def _parse_date(date_str: str | None) -> date:
    """Parse ISO date string, defaulting to today if missing."""
    if not date_str:
        return date.today()
    try:
        return date.fromisoformat(date_str[:10])
    except ValueError:
        return date.today()


def build_phylogeny(session: Session) -> None:
    """
    Reconstruct phylogeny trees for all strains and write to edges table.
    Clears existing edges first.
    """
    # Clear existing edges
    existing_edges = session.exec(select(Edge)).all()
    for e in existing_edges:
        session.delete(e)
    session.commit()

    strains = session.exec(select(Strain)).all()

    for strain in strains:
        if strain.strain_id.startswith("singleton-"):
            # Singletons have no edges
            continue

        # Get all clauses in this strain with embeddings
        clauses = session.exec(
            select(Clause).where(Clause.strain_id == strain.strain_id)
        ).all()

        if len(clauses) < 2:
            continue

        # Get document dates for each clause
        doc_dates: dict[str, date] = {}
        for c in clauses:
            doc = session.exec(
                select(Document).where(Document.doc_id == c.doc_id)
            ).first()
            if doc:
                doc_dates[c.clause_id] = _parse_date(doc.synthetic_date)
            else:
                doc_dates[c.clause_id] = date.today()

        # Build pairwise distance matrix
        n = len(clauses)
        dist_matrix = np.zeros((n, n), dtype=np.float32)
        for i in range(n):
            for j in range(i + 1, n):
                d = _normalised_edit_distance(
                    clauses[i].normalised_text, clauses[j].normalised_text
                )
                dist_matrix[i, j] = d
                dist_matrix[j, i] = d

        # Minimum spanning tree
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import minimum_spanning_tree

        sparse = csr_matrix(dist_matrix)
        mst = minimum_spanning_tree(sparse)
        mst_array = mst.toarray()

        # Extract edges and orient by date
        edges_to_add: list[Edge] = []
        rows, cols = np.where(mst_array > 0)
        for r, c in zip(rows, cols):
            ci = clauses[r]
            cj = clauses[c]
            distance = float(mst_array[r, c])

            # Orient: earlier date = parent
            date_i = doc_dates[ci.clause_id]
            date_j = doc_dates[cj.clause_id]

            if date_i < date_j:
                parent, child = ci, cj
            elif date_j < date_i:
                parent, child = cj, ci
            else:
                # Tie-break: lower structural complexity = parent
                comp_i = _structural_complexity(ci.text)
                comp_j = _structural_complexity(cj.text)
                if comp_i <= comp_j:
                    parent, child = ci, cj
                else:
                    parent, child = cj, ci

            edge = Edge(
                parent_clause_id=parent.clause_id,
                child_clause_id=child.clause_id,
                strain_id=strain.strain_id,
                distance=distance,
                mutation_label="",  # filled by mutate_label step
                mutation_type="unknown",
            )
            edges_to_add.append(edge)

        for e in edges_to_add:
            session.add(e)

    session.commit()

    # Update root clause for each strain
    _update_strain_roots(session)


def _update_strain_roots(session: Session) -> None:
    """Mark the root clause of each strain (no incoming edges)."""
    strains = session.exec(select(Strain)).all()

    for strain in strains:
        if strain.strain_id.startswith("singleton-"):
            clauses = session.exec(
                select(Clause).where(Clause.strain_id == strain.strain_id)
            ).all()
            if clauses:
                strain.root_clause_id = clauses[0].clause_id
            session.add(strain)
            continue

        edges = session.exec(
            select(Edge).where(Edge.strain_id == strain.strain_id)
        ).all()
        child_ids = {e.child_clause_id for e in edges}
        parent_ids = {e.parent_clause_id for e in edges}

        roots = parent_ids - child_ids
        if roots:
            strain.root_clause_id = next(iter(roots))
        else:
            # Fallback: pick clause from earliest doc
            clauses = session.exec(
                select(Clause).where(Clause.strain_id == strain.strain_id)
            ).all()
            if clauses:
                strain.root_clause_id = clauses[0].clause_id

        session.add(strain)

    session.commit()


# ─── Mutation label generation ──────────────────────────────────────────────
# Mutation label generation for each edge in the phylogeny.
#
# Rule-based detectors decide the mutation TYPE.
# LLMProvider.phrase_label() only phrases the result (offline fallback: passthrough).

def _detect_deadline_change(parent: str, child: str) -> str | None:
    """Detect if a time period was shortened."""
    time_pat = re.compile(
        r"\b(\d+)\s*(day|days|month|months|week|weeks|hour|hours)\b", re.IGNORECASE
    )
    parent_times = [(int(m.group(1)), m.group(2).lower().rstrip("s"))
                    for m in time_pat.finditer(parent)]
    child_times = [(int(m.group(1)), m.group(2).lower().rstrip("s"))
                   for m in time_pat.finditer(child)]

    if not parent_times or not child_times:
        return None

    # Normalise to days
    unit_days = {"day": 1, "week": 7, "month": 30, "hour": 0}

    def to_days(val, unit):
        return val * unit_days.get(unit, 1)

    parent_days = [to_days(v, u) for v, u in parent_times]
    child_days = [to_days(v, u) for v, u in child_times]

    if max(parent_days) > 0 and max(child_days) < max(parent_days):
        orig = f"{parent_times[parent_days.index(max(parent_days))][0]} {parent_times[parent_days.index(max(parent_days))][1]}s"
        new = f"{child_times[child_days.index(max(child_days))][0]} {child_times[child_days.index(max(child_days))][1]}s"
        return f"shortened notice/deadline window from {orig} to {new}"

    if max(parent_days) > 0 and max(child_days) > max(parent_days):
        orig = f"{parent_times[parent_days.index(max(parent_days))][0]} {parent_times[parent_days.index(max(parent_days))][1]}s"
        new = f"{child_times[child_days.index(max(child_days))][0]} {child_times[child_days.index(max(child_days))][1]}s"
        return f"extended deadline from {orig} to {new}"

    return None


def _detect_obligation_flip(parent: str, child: str) -> str | None:
    """Detect if an obligation was shifted between parties."""
    landlord_kw = re.compile(
        r"(\b(landlord|lessor|owner|party\s*a)\b|\[PARTY_A\]|PARTY_A)", re.IGNORECASE
    )
    tenant_kw = re.compile(
        r"(\b(tenant|lessee|occupant|party\s*b)\b|\[PARTY_B\]|PARTY_B)", re.IGNORECASE
    )
    obligation_kw = re.compile(
        r"\b(shall|must|will|responsible|liable|obliged|required)\b", re.IGNORECASE
    )

    def party_obligation_counts(text):
        words = text.split()
        ll_count = 0
        tn_count = 0
        for i, w in enumerate(words):
            window = " ".join(words[max(0, i-3):i+4])
            if obligation_kw.search(window):
                if landlord_kw.search(window):
                    ll_count += 1
                if tenant_kw.search(window):
                    tn_count += 1
        return ll_count, tn_count

    p_ll, p_tn = party_obligation_counts(parent)
    c_ll, c_tn = party_obligation_counts(child)

    if p_ll > p_tn and c_tn > c_ll and (p_ll > 0 or c_tn > 0):
        return "obligation shifted from landlord to tenant"
    if p_tn > p_ll and c_ll > c_tn and (p_tn > 0 or c_ll > 0):
        return "obligation shifted from tenant to landlord (more favourable)"
    return None


def _detect_penalty_addition(parent: str, child: str) -> str | None:
    """Detect if a penalty clause was added."""
    penalty_kw = re.compile(
        r"\b(penalty|penalise|penalize|forfeit|forfeiture|liquidated\s+damage|"
        r"deduction|withhold|blacklist)\b",
        re.IGNORECASE,
    )
    p_count = len(penalty_kw.findall(parent))
    c_count = len(penalty_kw.findall(child))
    if c_count > p_count:
        return f"added penalty provision ({c_count - p_count} new penalty term(s))"
    return None


def _detect_cure_period_removal(parent: str, child: str) -> str | None:
    """Detect if a cure/remedy period was removed."""
    cure_kw = re.compile(
        r"\b(cure|remedy|rectif|remediat|opportunity\s+to\s+correct|notice\s+to\s+cure)\b",
        re.IGNORECASE,
    )
    has_cure_parent = bool(cure_kw.search(parent))
    has_cure_child = bool(cure_kw.search(child))
    if has_cure_parent and not has_cure_child:
        return "removed cure/remedy period for breach"
    return None


def _detect_broadened_discretion(parent: str, child: str) -> str | None:
    """Detect if landlord discretion was broadened."""
    discretion_kw = re.compile(
        r"\b(sole\s+discretion|absolute\s+discretion|at\s+its\s+option|"
        r"may\s+at\s+any\s+time|without\s+notice|without\s+reason)\b",
        re.IGNORECASE,
    )
    p_count = len(discretion_kw.findall(parent))
    c_count = len(discretion_kw.findall(child))
    if c_count > p_count:
        return "broadened landlord discretionary power"
    return None


def _is_cosmetic(parent: str, child: str) -> bool:
    """True if the edit distance after normalisation is very small."""
    from Levenshtein import distance as lev_distance
    max_len = max(len(parent), len(child), 1)
    return lev_distance(parent, child) / max_len < 0.08


def detect_mutation(parent_text: str, child_text: str) -> tuple[str, str]:
    """
    Apply all rule detectors in order.
    Returns (mutation_type, rule_output_string).
    """
    p = parent_text
    c = child_text

    result = _detect_cure_period_removal(p, c)
    if result:
        return "cure_period_removal", result

    result = _detect_penalty_addition(p, c)
    if result:
        return "penalty_addition", result

    result = _detect_obligation_flip(p, c)
    if result:
        return "obligation_flip", result

    result = _detect_deadline_change(p, c)
    if result:
        return "deadline_change", result

    result = _detect_broadened_discretion(p, c)
    if result:
        return "broadened_discretion", result

    if _is_cosmetic(p, c):
        return "cosmetic", "cosmetic rewording"

    return "general_change", "modified clause wording"


class LLMProvider(ABC):
    """Abstract interface for any LLM backend."""

    @abstractmethod
    def phrase_label(self, rule_output: str, parent_text: str, child_text: str) -> str:
        """
        Given a rule-detected mutation description and both clause texts,
        return a polished one-line human-readable mutation label.

        The LLM must NOT decide the mutation type — only phrase it.
        The rule_output already contains the semantic decision.
        """


class OfflineLabelComposer(LLMProvider):
    """
    Deterministic offline fallback.

    Returns the rule_output as a well-capitalised sentence.
    No model needed, never fails without a key.
    """

    def phrase_label(self, rule_output: str, parent_text: str, child_text: str) -> str:
        if not rule_output:
            return "Cosmetic rewording"
        label = rule_output.strip().rstrip(".")
        return label[0].upper() + label[1:] if label else "Cosmetic rewording"


def get_llm_provider() -> LLMProvider:
    """
    Return the active LLM provider.

    Checks for OPENAI_API_KEY / ANTHROPIC_API_KEY in env.
    Falls back to OfflineLabelComposer if neither is set.
    """
    import os

    if os.getenv("OPENAI_API_KEY"):
        try:
            from strain.backend.providers._openai_provider import OpenAILabelComposer
            return OpenAILabelComposer()
        except ImportError:
            pass

    return OfflineLabelComposer()


def label_all_edges(session: Session) -> None:
    """
    Label every edge in the edges table with a mutation type and human label.
    """
    llm = get_llm_provider()
    edges = session.exec(select(Edge)).all()

    clauses_by_id = {
        c.clause_id: c
        for c in session.exec(select(Clause)).all()
    }

    for edge in edges:
        parent = clauses_by_id.get(edge.parent_clause_id)
        child = clauses_by_id.get(edge.child_clause_id)

        if not parent or not child:
            edge.mutation_label = "Unknown mutation"
            edge.mutation_type = "unknown"
            session.add(edge)
            continue

        mut_type, rule_output = detect_mutation(
            parent.normalised_text, child.normalised_text
        )
        label = llm.phrase_label(rule_output, parent.text, child.text)

        edge.mutation_label = label
        edge.mutation_type = mut_type
        session.add(edge)

    session.commit()


# ─── Virulence scoring ──────────────────────────────────────────────────────
# Virulence scoring: computes asymmetry, harshness delta, and combined virulence score.
#
# All component weights are exposed. No hidden weighting.
# Formula: virulence = 0.4*asymmetry + 0.4*harshness_delta + 0.2*outcome_factor
# Each component is normalised to [0, 100].

# Keywords that indicate obligations / powers per party.
# Includes the [PARTY_A]/[PARTY_B] normalisation tokens (underscore breaks \b,
# so the bracketed/upper-case forms are matched explicitly).
_LANDLORD_KW = re.compile(
    r"(\b(landlord|lessor|owner|party\s*a|licensor)\b|\[PARTY_A\]|PARTY_A)",
    re.IGNORECASE,
)
_TENANT_KW = re.compile(
    r"(\b(tenant|lessee|occupant|party\s*b|licensee)\b|\[PARTY_B\]|PARTY_B)",
    re.IGNORECASE,
)
_OBLIGATION_KW = re.compile(
    r"\b(shall|must|will|is\s+responsible|is\s+liable|obliged|required|agrees\s+to)\b",
    re.IGNORECASE,
)
_DISCRETION_KW = re.compile(
    r"\b(sole\s+discretion|absolute\s+discretion|may\s+at\s+any\s+time|"
    r"without\s+notice|without\s+reason|at\s+its\s+option)\b",
    re.IGNORECASE,
)


def _asymmetry_score_for_text(text: str) -> float:
    """
    Asymmetry score: how much more is imposed on tenant vs landlord.
    Returns value in [0, 100]. 50 = balanced, >50 = tenant-hostile.
    """
    words = text.split()
    landlord_obligations = 0
    tenant_obligations = 0
    landlord_discretion = 0

    for i, w in enumerate(words):
        window = " ".join(words[max(0, i - 4) : i + 5])
        has_obligation = bool(_OBLIGATION_KW.search(window))
        has_discretion = bool(_DISCRETION_KW.search(window))

        if has_obligation:
            if _LANDLORD_KW.search(window):
                landlord_obligations += 1
            if _TENANT_KW.search(window):
                tenant_obligations += 1
        if has_discretion and _LANDLORD_KW.search(window):
            landlord_discretion += 1

    total = landlord_obligations + tenant_obligations
    if total == 0:
        # No explicit party markers found — neutral default
        return 50.0

    tenant_fraction = tenant_obligations / total  # 0 = all on landlord, 1 = all on tenant

    # Discretion further shifts the score
    discretion_penalty = min(landlord_discretion * 5, 20)

    raw = tenant_fraction * 100 + discretion_penalty
    return min(raw, 100.0)


def _outcome_factor_for_strain(strain_id: str, family_name: str) -> float:
    """
    Outcome factor: fraction of outcome records that were voided.
    Returns [0, 100]. 0 = all upheld, 100 = all voided.
    """
    provider = SeedOutcomeProvider()
    outcomes = provider.get_outcomes(strain_id) + provider.get_outcomes(family_name)
    # Deduplicate
    seen = set()
    unique = []
    for o in outcomes:
        k = (o.get("clause_family"), o.get("year"), o.get("holding_summary", "")[:40])
        if k not in seen:
            seen.add(k)
            unique.append(o)

    if not unique:
        return 0.0

    voided = sum(1 for o in unique if o.get("outcome") in ("voided", "partially_voided"))
    return (voided / len(unique)) * 100.0


def score_all_clauses(session: Session) -> None:
    """
    Compute virulence scores for every clause and persist to DB.
    Also populates Outcome records from seed file.
    """
    strains = {s.strain_id: s for s in session.exec(select(Strain)).all()}
    clauses = session.exec(select(Clause)).all()

    # Pre-compute root asymmetry for each strain
    root_asymmetry: dict[str, float] = {}
    for sid, strain in strains.items():
        if strain.root_clause_id:
            root_clause = session.exec(
                select(Clause).where(Clause.clause_id == strain.root_clause_id)
            ).first()
            if root_clause:
                root_asymmetry[sid] = _asymmetry_score_for_text(root_clause.normalised_text)
            else:
                root_asymmetry[sid] = 50.0
        else:
            root_asymmetry[sid] = 50.0

    for clause in clauses:
        if not clause.strain_id:
            continue

        strain = strains.get(clause.strain_id)
        family_name = strain.family_name if strain else clause.strain_id

        asymmetry = _asymmetry_score_for_text(clause.normalised_text)
        root_asym = root_asymmetry.get(clause.strain_id, 50.0)
        harshness_delta = max(asymmetry - root_asym, 0.0)  # only count increases
        outcome_factor = _outcome_factor_for_strain(clause.strain_id, family_name)

        virulence = (
            WEIGHTS["asymmetry"] * asymmetry
            + WEIGHTS["harshness_delta"] * min(harshness_delta * 2, 100.0)
            + WEIGHTS["outcome_factor"] * outcome_factor
        )

        clause.asymmetry_score = round(asymmetry, 2)
        clause.harshness_delta = round(harshness_delta, 2)
        clause.outcome_factor = round(outcome_factor, 2)
        clause.virulence_score = round(virulence, 2)
        session.add(clause)

    session.commit()

    # Seed outcomes into DB from seed file
    _seed_outcomes_to_db(session)


def _seed_outcomes_to_db(session: Session) -> None:
    """Load outcome records from seed file into DB if not already present."""
    from strain.backend.pipeline.outcomes import SeedOutcomeProvider

    existing_count = len(session.exec(select(Outcome)).all())
    if existing_count > 0:
        return

    provider = SeedOutcomeProvider()
    for record in provider.get_all():
        outcome = Outcome(
            clause_family=record.get("clause_family", ""),
            jurisdiction=record.get("jurisdiction", ""),
            year=record.get("year", 0),
            outcome=record.get("outcome", ""),
            holding_summary=record.get("holding_summary", ""),
            source_label=record.get("source_label", ""),
            illustrative=True,
        )
        session.add(outcome)
    session.commit()
