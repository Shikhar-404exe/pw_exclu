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


def orient_edge(
    date_i: date, date_j: date, text_i: str, text_j: str
) -> int:
    """Decide parent/child orientation for a phylogeny edge.

    Returns -1 when clause i is the parent, +1 when clause j is. Earlier
    document date wins; ties break toward lower structural complexity
    (fewer sub-clause markers read as ancestral). Pure function, extracted
    so orientation and tie-handling are unit-testable.
    """
    if date_i < date_j:
        return -1
    if date_j < date_i:
        return 1
    comp_i = _structural_complexity(text_i)
    comp_j = _structural_complexity(text_j)
    return -1 if comp_i <= comp_j else 1


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

            # Orient: earlier date = parent (ties → simpler text).
            date_i = doc_dates[ci.clause_id]
            date_j = doc_dates[cj.clause_id]

            if orient_edge(date_i, date_j, ci.text, cj.text) <= 0:
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


def _detect_deposit_change(parent: str, child: str) -> str | None:
    """Detect hardened deposit terms: forfeiture added, refund slowed, or
    refundability removed."""
    p = extract_clause_features(parent)
    c = extract_clause_features(child)
    if c["forfeiture_present"] and not p["forfeiture_present"]:
        return "added deposit forfeiture on breach"
    if p["deposit_refundable"] and not c["deposit_refundable"]:
        return "removed deposit refundability"
    if p["deposit_refund_days"] and c["deposit_refund_days"]:
        if c["deposit_refund_days"] > p["deposit_refund_days"]:
            return (
                f"lengthened deposit refund timeline from "
                f"{p['deposit_refund_days']:g} to {c['deposit_refund_days']:g} days"
            )
    return None


def _detect_protection_change(parent: str, child: str) -> str | None:
    """Detect added or removed tenant protections (grace, mutual consent,
    notice requirements, cure rights) that other detectors miss."""
    p = extract_clause_features(parent)
    c = extract_clause_features(child)
    removed = []
    if p["grace_present"] and not c["grace_present"]:
        removed.append("grace period")
    if p["renewal_mutual"] and not c["renewal_mutual"]:
        removed.append("mutual-consent requirement")
    if p["cure_present"] and not c["cure_present"]:
        removed.append("cure/remedy right")
    if removed:
        return "removed tenant protection: " + ", ".join(removed)
    added = []
    if c["grace_present"] and not p["grace_present"]:
        added.append("grace period")
    if c["renewal_mutual"] and not p["renewal_mutual"]:
        added.append("mutual-consent requirement")
    if c["cure_present"] and not p["cure_present"]:
        added.append("cure/remedy right")
    if added:
        return "added tenant protection: " + ", ".join(added)
    return None


def _detect_rent_deadline_change(parent: str, child: str) -> str | None:
    """Detect changed rent/payment due timing (day-of-month or grace)."""
    due_pat = re.compile(
        r"(?:on or before|before|by|due on|no later than)\s+(?:the\s+)?"
        r"\(?(\d+|first|second|third|fourth|fifth|seventh|tenth)(?:st|nd|rd|th)?\)?"
        r"\s*(day)?",
        re.IGNORECASE,
    )
    ord_map = {"first": 1, "second": 2, "third": 3, "fourth": 4,
               "fifth": 5, "seventh": 7, "tenth": 10}

    def _due_days(text: str) -> list[int]:
        days = []
        for m in due_pat.finditer(text):
            raw = m.group(1).lower()
            days.append(ord_map.get(raw, int(raw) if raw.isdigit() else 0))
        return [d for d in days if d > 0]

    p_days, c_days = _due_days(parent), _due_days(child)
    if p_days and c_days and min(c_days) != min(p_days):
        direction = "advanced" if min(c_days) < min(p_days) else "deferred"
        return (
            f"{direction} rent due date from day {min(p_days)} "
            f"to day {min(c_days)} of the month"
        )
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

    result = _detect_deposit_change(p, c)
    if result:
        return "deposit_change", result

    result = _detect_obligation_flip(p, c)
    if result:
        return "obligation_flip", result

    result = _detect_deadline_change(p, c)
    if result:
        return "deadline_change", result

    result = _detect_rent_deadline_change(p, c)
    if result:
        return "rent_deadline_change", result

    result = _detect_broadened_discretion(p, c)
    if result:
        return "broadened_discretion", result

    result = _detect_protection_change(p, c)
    if result:
        return "protection_change", result

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

# ─── Clause feature extraction ────────────────────────────────────────────
# One shared extractor feeds asymmetry evidence, harshness-vs-root diffs and
# material-term comparison for neutralising candidates. Features describe
# *directed* rights and burdens (who gains, who pays) rather than raw word
# counts, so ordinary consideration duties (paying agreed rent) do not read
# as unfairness by themselves.

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}

_DURATION_TOKEN_PAT = re.compile(
    r"\(?(\d+)\)?\s*(days?|weeks?|months?|years?)"
    r"|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty)\s*(days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)


def _word_number(word: str) -> int | None:
    return _WORD_NUMBERS.get(word.lower())


def parse_durations(text: str) -> list[tuple[int, str]]:
    """Extract (amount, unit) durations, supporting digits, (parenthesised)
    digits and written-out numbers ("eleven (11) months" → 11 months)."""
    out: list[tuple[int, str]] = []
    for m in _DURATION_TOKEN_PAT.finditer(text or ""):
        if m.group(1) is not None:
            amount = int(m.group(1))
            unit = m.group(2)
        else:
            amount = _word_number(m.group(3)) or 0
            unit = m.group(4)
        if amount > 0:
            out.append((amount, unit.lower()))
    return out


def _to_days(amount: int, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("year"):
        return amount * 365.0
    if unit.startswith("month"):
        return amount * 30.0
    if unit.startswith("week"):
        return amount * 7.0
    return float(amount)


def extract_clause_features(normalised_text: str) -> dict:
    """Extract directed rights/burdens and material terms from clause text.

    Pure-Python, deterministic. Burden lists hold short canonical feature
    ids; numeric fields hold measured values or None when absent.
    """
    t = normalised_text or ""
    low = t.lower()
    feats: dict = {
        "tenant_burdens": [],
        "landlord_burdens": [],
        "mutual": [],
        "routine": [],
        "notice_days": [],
        "cure_days": None,
        "cure_present": False,
        "grace_present": False,
        "penalty_present": False,
        "forfeiture_present": False,
        "interest_present": False,
        "discretion_landlord": False,
        "entry_unrestricted": False,
        "entry_notice_hours": None,
        "unilateral_landlord": False,
        "unilateral_tenant": False,
        "term_months": None,
        "renewal_mutual": False,
        "deposit_refund_days": None,
        "deposit_refundable": False,
        "amounts": [],
    }

    landlord_near = bool(re.search(
        r"landlord|lessor|owner|licensor|\[PARTY_A\]|PARTY_A", t, re.IGNORECASE))
    tenant_near = bool(re.search(
        r"tenant|lessee|occupant|licensee|resident|\[PARTY_B\]|PARTY_B", t, re.IGNORECASE))

    # Mutual provisions (rights/duties applying to both sides equally).
    if re.search(r"either party|both parties|mutual|each party", low):
        if re.search(r"terminat", low):
            feats["mutual"].append("mutual termination right")
        if re.search(r"renew|extend", low):
            feats["mutual"].append("mutual renewal")
        if re.search(r"notice", low):
            feats["mutual"].append("mutual notice duty")
        if re.search(r"consent", low):
            feats["mutual"].append("mutual consent requirement")
        if not feats["mutual"]:
            feats["mutual"].append("mutual provision")

    # Routine consideration duties (substance of the bargain, not harshness).
    if tenant_near and re.search(r"\brent\b.*(pay|remit)|pay.*\brent\b", low):
        feats["routine"].append("tenant pays agreed rent")
    if tenant_near and re.search(r"deposit", low) and not re.search(r"forfeit", low):
        feats["routine"].append("tenant pays deposit")
    if re.search(r"electricity|water|gas", low) and re.search(r"pay|bear|borne", low):
        feats["routine"].append("utility allocation")
    if re.search(r"residential purposes?", low):
        feats["routine"].append("residential use")
    if landlord_near and re.search(r"structural|major.*repair", low):
        feats["routine"].append("landlord structural repairs")

    # Harsh markers directed at the tenant.
    if re.search(r"penalty|late fee|liquidated damages?", low):
        feats["tenant_burdens"].append("late penalty")
        feats["penalty_present"] = True
    if re.search(r"forfeit", low):
        feats["tenant_burdens"].append("deposit forfeiture")
        feats["forfeiture_present"] = True
    if re.search(r"interest (at|on|of)|per annum|compound interest", low):
        feats["tenant_burdens"].append("interest on arrears")
        feats["interest_present"] = True
    if re.search(r"sole discretion|absolute discretion|at its option|"
                 r"without (assigning |giving )?any reason|deems? (fit|sufficient)", low):
        if landlord_near or not tenant_near:
            feats["tenant_burdens"].append("landlord discretion")
            feats["discretion_landlord"] = True
    if re.search(r"at any time without (prior )?notice|without (prior )?notice.*(enter|inspect|visit)|"
                 r"enter.*at all times|access.*at all times", low):
        feats["tenant_burdens"].append("unrestricted landlord entry")
        feats["entry_unrestricted"] = True
    # Unilateral termination: one party may end while the other may not.
    if re.search(r"terminat", low) and not feats["mutual"]:
        if landlord_near and not tenant_near:
            feats["tenant_burdens"].append("unilateral landlord termination")
            feats["unilateral_landlord"] = True
        elif tenant_near and not landlord_near:
            feats["landlord_burdens"].append("unilateral tenant termination")
            feats["unilateral_tenant"] = True
    # Cure / grace protections.
    if re.search(r"\bcure\b|remedy|rectif|opportunity to correct|make good the breach", low):
        feats["cure_present"] = True
    if re.search(r"grace period", low):
        feats["grace_present"] = True
    # Notice periods near operative cues.
    for amount, unit in parse_durations(t):
        for m in re.finditer(
            r"\(?%d\)?\s*%s\b" % (amount, unit.rstrip("s")),
            t, re.IGNORECASE,
        ):
            span = t[max(0, m.start() - 60): m.end() + 40]
            if re.search(
                r"notice|terminat|vacat|evict|cure|remedy|pay|deliver|"
                r"hand ?over|refund|return.*deposit|intimat|inform",
                span, re.IGNORECASE,
            ):
                feats["notice_days"].append(_to_days(amount, unit))
                break
    # Cure days specifically.
    cure_m = re.search(
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|twenty|thirty)\s*(days?|weeks?|months?)[^.]{0,60}?"
        r"(cure|remedy|rectif|make good)",
        low,
    )
    if cure_m:
        raw = cure_m.group(1)
        feats["cure_days"] = float(raw) if raw.isdigit() else float(_word_number(raw) or 0)
    # Term length.
    term_m = re.search(
        r"(remain in force|term of|duration of|valid for|validity|lock[\s-]*in|"
        r"minimum (occupancy|period|tenure))[^.]{0,80}?"
        r"\(?(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\)?\s*"
        r"(days?|weeks?|months?|years?)",
        low,
    )
    if term_m:
        raw_n, raw_u = term_m.group(3), term_m.group(4)
        n = int(raw_n) if raw_n.isdigit() else (_word_number(raw_n) or 0)
        if raw_u.startswith("year"):
            months = n * 12.0
        elif raw_u.startswith("week"):
            months = n * 7.0 / 30.0
        elif raw_u.startswith("day"):
            months = n / 30.0
        else:
            months = float(n)
        feats["term_months"] = round(months, 2)
    if re.search(r"mutual.*consent|consent.*mutual|mutually agreed", low):
        feats["renewal_mutual"] = True
    # Deposit refund terms.
    if re.search(r"refund", low):
        feats["deposit_refundable"] = True
        rd = re.search(
            r"refund[^.]{0,80}?\(?(\d+|seven|ten|fifteen|twenty|thirty|forty|sixty)\)?\s*"
            r"(days?|weeks?|months?)", low)
        if rd:
            raw = rd.group(1)
            num = {"seven": 7, "ten": 10, "fifteen": 15, "twenty": 20,
                   "thirty": 30, "forty": 40, "sixty": 60}.get(raw, None)
            num = float(raw) if raw.isdigit() else num
            if num:
                feats["deposit_refund_days"] = num
    # Entry notice.
    entry_m = re.search(
        r"\(?(\d+|twenty-four|twenty four|forty-eight|forty eight|seventy-two|seventy two)\)?\s*"
        r"hours?[^.]{0,60}?(notice|intimation)", low)
    if entry_m:
        raw = entry_m.group(1).replace(" ", "")
        num = {"twentyfour": 24, "fortyeight": 48, "seventytwo": 72}.get(raw, None)
        feats["entry_notice_hours"] = float(raw) if raw.isdigit() else num
    # Monetary amounts (material terms; normalised form keeps [AMOUNT]).
    feats["amounts"] = re.findall(r"\[AMOUNT\]", t)

    return feats


def _harsh_marker_count(feats: dict) -> tuple[int, int]:
    """Count one-sided harsh markers (landlord-advantage, tenant-advantage)."""
    adv_landlord = len(feats["tenant_burdens"])
    adv_tenant = len(feats["landlord_burdens"])
    return adv_landlord, adv_tenant


def assess_asymmetry(normalised_text: str) -> dict:
    """Evidence-based asymmetry assessment.

    Returns {score, confidence, features, rationale}. Routine consideration
    duties (paying agreed rent/deposit) are NOT unfairness evidence on their
    own; only directed harsh markers move the score. Absence of any marker
    yields a low score with low confidence — never a silent midpoint
    presented as a measurement.
    """
    feats = extract_clause_features(normalised_text)
    adv_l, adv_t = _harsh_marker_count(feats)
    total = adv_l + adv_t
    features = (
        [f"tenant burden: {b}" for b in feats["tenant_burdens"]]
        + [f"landlord burden: {b}" for b in feats["landlord_burdens"]]
        + [f"balanced: {m}" for m in feats["mutual"]]
        + [f"routine: {r}" for r in feats["routine"]]
    )
    if total == 0:
        if feats["mutual"]:
            return {
                "score": 35.0,
                "confidence": "high",
                "features": features,
                "rationale": (
                    "Rights and duties apply to both parties equally; "
                    "no one-sided term detected."
                ),
            }
        return {
            "score": 15.0,
            "confidence": "low",
            "features": features,
            "rationale": (
                "No party-directed harsh markers detected; no imbalance "
                "evidenced (routine duties are not unfairness evidence)."
            ),
        }
    net = adv_l - adv_t
    score = 50.0 + 50.0 * net / max(total, 1)
    score = max(5.0, min(100.0, round(score, 2)))
    side = "tenant" if net > 0 else ("landlord" if net < 0 else "neither party")
    return {
        "score": score,
        "confidence": "high" if total >= 2 else "medium",
        "features": features,
        "rationale": (
            f"One-sided markers weigh against the {side} "
            f"({adv_l} landlord-advantage vs {adv_t} tenant-advantage)."
        ),
    }


def assess_harshness_vs_root(normalised_text: str, root_normalised_text: str | None) -> dict:
    """Feature-level harshness delta vs the strain root.

    Positive only when the clause adds a burden or removes a protection the
    root had. A routine clause in a harsh family scores 0 — family
    membership alone is never evidence. Missing root yields 0 with low
    confidence, stated explicitly.
    """
    if not root_normalised_text:
        return {
            "score": 0.0,
            "confidence": "low",
            "features": [],
            "rationale": "No family root available for comparison; no delta asserted.",
        }
    cur = extract_clause_features(normalised_text)
    root = extract_clause_features(root_normalised_text)
    delta = 0.0
    evidence: list[str] = []

    added = [b for b in cur["tenant_burdens"] if b not in root["tenant_burdens"]]
    for b in added:
        delta += 25.0
        evidence.append(f"added burden vs root: {b}")
    if root["cure_present"] and not cur["cure_present"]:
        delta += 20.0
        evidence.append("cure/remedy protection present in root but removed here")
    if root["grace_present"] and not cur["grace_present"]:
        delta += 10.0
        evidence.append("grace period present in root but removed here")
    if root["renewal_mutual"] and not cur["renewal_mutual"]:
        delta += 10.0
        evidence.append("mutual-consent protection present in root but removed here")
    if cur["discretion_landlord"] and not root["discretion_landlord"]:
        delta += 15.0
        evidence.append("landlord discretion broadened vs root")
    if cur["entry_unrestricted"] and not root["entry_unrestricted"]:
        delta += 20.0
        evidence.append("entry rights broadened vs root (notice removed)")
    if cur["forfeiture_present"] and not root["forfeiture_present"]:
        delta += 25.0
        evidence.append("deposit forfeiture added vs root")
    # Shortened notice/cure timelines.
    if root["notice_days"] and cur["notice_days"]:
        if min(cur["notice_days"]) < min(root["notice_days"]) and min(root["notice_days"]) > 0:
            ratio = min(cur["notice_days"]) / min(root["notice_days"])
            if ratio < 1.0:
                delta += round(30.0 * (1.0 - ratio), 2)
                evidence.append(
                    f"notice timeline shortened vs root "
                    f"({min(root['notice_days']):g} → {min(cur['notice_days']):g} days)"
                )
    if root["deposit_refund_days"] and cur["deposit_refund_days"]:
        if cur["deposit_refund_days"] > root["deposit_refund_days"]:
            delta += 10.0
            evidence.append("deposit refund timeline lengthened vs root")

    delta = min(100.0, round(delta, 2))
    if delta == 0.0:
        return {
            "score": 0.0,
            "confidence": "high",
            "features": evidence,
            "rationale": "No added burden or removed protection vs the family root.",
        }
    return {
        "score": delta,
        "confidence": "medium",
        "features": evidence,
        "rationale": "Adverse changes vs the family root: " + "; ".join(evidence) + ".",
    }


def assess_outcome_factor(strain_id: str, family_name: str) -> dict:
    """Outcome evidence with explicit provenance.

    The value keeps the legacy voided-share semantics, but sparse or absent
    data is labelled as such: counts are shown, nothing is presented as a
    real-world probability, and no verified source is ever claimed.
    """
    evidence = _outcome_factor_for_strain_with_records(strain_id, family_name)
    n = evidence["records"]
    if n == 0:
        return {
            "value": 0.0,
            "confidence": "low",
            "records": 0,
            "voided": 0,
            "basis": "illustrative-only",
            "verified_sources": [],
            "rationale": "No illustrative outcome records for this family; no litigation signal asserted.",
        }
    return {
        "value": evidence["value"],
        "confidence": "high" if n >= 3 else "low",
        "records": n,
        "voided": evidence["voided"],
        "basis": "illustrative-only",
        "verified_sources": [],
        "rationale": (
            f"Based on {n} illustrative dataset scenario(s) "
            f"({evidence['voided']} voided/partially voided). "
            "Illustrative only — not a verified judgment, not a real-world probability."
        ),
    }


def _outcome_factor_for_strain_with_records(strain_id: str, family_name: str) -> dict:
    provider = SeedOutcomeProvider()
    outcomes = provider.get_outcomes(strain_id) + provider.get_outcomes(family_name)
    seen = set()
    unique = []
    for o in outcomes:
        k = (o.get("clause_family"), o.get("year"), o.get("holding_summary", "")[:40])
        if k not in seen:
            seen.add(k)
            unique.append(o)
    if not unique:
        return {"value": 0.0, "records": 0, "voided": 0}
    voided = sum(1 for o in unique if o.get("outcome") in ("voided", "partially_voided"))
    return {"value": (voided / len(unique)) * 100.0, "records": len(unique), "voided": voided}


def _asymmetry_score_for_text(text: str) -> float:
    """
    Asymmetry score: how much more is imposed on tenant vs landlord.
    Returns value in [0, 100]. Lower = less one-sided against the tenant.

    Evidence-based (see assess_asymmetry); kept as a thin wrapper for
    backward compatibility with corpus scoring and existing callers.
    """
    return float(assess_asymmetry(text)["score"])


def _outcome_factor_for_strain(strain_id: str, family_name: str) -> float:
    """
    Outcome factor: fraction of outcome records that were voided.
    Returns [0, 100]. 0 = all upheld (or no records), 100 = all voided.

    Thin wrapper (see assess_outcome_factor for evidence + provenance).
    """
    return float(_outcome_factor_for_strain_with_records(strain_id, family_name)["value"])


def score_all_clauses(session: Session) -> None:
    """
    Compute virulence scores for every clause and persist to DB.
    Also populates Outcome records from seed file.
    """
    strains = {s.strain_id: s for s in session.exec(select(Strain)).all()}
    clauses = session.exec(select(Clause)).all()

    # Map each strain to its root clause text (harshness is a feature-level
    # diff against the root's text). Missing roots stay absent so the
    # assessor can state the uncertainty instead of assuming a midpoint.
    root_texts: dict[str, str] = {}
    for sid, strain in strains.items():
        if strain.root_clause_id:
            root_clause = session.exec(
                select(Clause).where(Clause.clause_id == strain.root_clause_id)
            ).first()
            if root_clause and root_clause.normalised_text:
                root_texts[sid] = root_clause.normalised_text

    for clause in clauses:
        if not clause.strain_id:
            continue

        strain = strains.get(clause.strain_id)
        family_name = strain.family_name if strain else clause.strain_id

        asym = assess_asymmetry(clause.normalised_text)
        asymmetry = asym["score"]
        harsh = assess_harshness_vs_root(
            clause.normalised_text, root_texts.get(clause.strain_id)
        )
        harshness_delta = harsh["score"]
        out = assess_outcome_factor(clause.strain_id, family_name)
        outcome_factor = out["value"]

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
