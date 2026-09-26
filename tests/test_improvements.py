"""
Real-world robustness tests: inline headers, preamble, written dates,
relative deadlines, scope detection, topic/compound flags, and
family-specific lawyer questions.

Motivated by a real Philippine rental contract that the old pipeline
collapsed into a single clause.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strain.backend.pipeline.diagnose import (
    _build_handoff_panel,
    _lawyer_questions_for_family,
)
from strain.backend.pipeline.segment import (
    detect_scope,
    detect_topics,
    is_compound,
    normalise,
    segment,
)

MANILA_STYLE = """HOUSE RENTAL CONTRACT

KNOWN ALL MEN BY THESE PRESENTS: This contract made on the 20th day of May 2007 at Manila by and between Antonio Ingles, of legal age, herein referred to as the Owner, and Geraldine Galinato, herein referred to as the Resident.

WITNESSETH: In consideration of the agreements, the Owner hereby rents the house at Lot 6, Las Pinas City for one year.

Resident hereby agrees to the following terms:

RENT: To pay SIX THOUSAND PESOS per month, due in advance on the 20th of every month.

FAILURE TO PAY ON TIME: Failure to pay will result in eviction. A three-day grace period will be allowed for late payment.

SECURITY DEPOSIT: Resident agrees to pay a deposit of SIX THOUSAND PESOS to secure full compliance. The deposit may not be used to pay rent.

METHOD OF PAYMENT: The initial payment must be PAID IN CASH at least 7 days before moving-in.
"""


class TestInlineHeaders:
    def test_narrative_doc_splits_into_many_clauses(self):
        clauses = segment(MANILA_STYLE, "doc-manila")
        assert len(clauses) >= 4, f"Expected >=4 clauses, got {len(clauses)}"

    def test_inline_headers_become_headings(self):
        clauses = segment(MANILA_STYLE, "doc-manila")
        headings = [c.heading for c in clauses]
        joined = " ".join(headings).lower()
        assert "rent" in joined
        assert "deposit" in joined

    def test_preamble_kept_separate(self):
        clauses = segment(MANILA_STYLE, "doc-manila")
        assert "preamble" in clauses[0].heading.lower()

    def test_numbered_docs_unaffected(self):
        text = "AGREEMENT\n\n1. RENT\nPay Rs. 10,000 monthly.\n\n2. DEPOSIT\nPay Rs. 20,000.\n\n3. NOTICE\n30 days notice.\n"
        clauses = segment(text, "doc-num")
        assert len(clauses) >= 3


class TestWrittenDates:
    def test_written_legal_date_normalised(self):
        result = normalise("made on the 20th day of May 2007 at Manila")
        assert "[DATE]" in result
        assert "2007" not in result

    def test_existing_date_formats_still_work(self):
        assert "[DATE]" in normalise("commences on 01/04/2024")
        assert "[DATE]" in normalise("dated 2024-04-01")


class TestRelativeDeadlines:
    def test_handoff_finds_absolute_and_relative(self):
        from strain.backend.pipeline.segment import ClauseRecord

        raw = [
            ClauseRecord("c1", "d1", 0, "Term",
                         "commencing on the 20th day of May, 2007",
                         "commencing on the [DATE]"),
            ClauseRecord("c2", "d1", 1, "Rent",
                         "A three-day grace period will be allowed.",
                         "A three-day grace period will be allowed."),
        ]
        top = [{
            "clause_id": "c1", "heading": "Term", "family_name": "Rent Payment",
            "virulence_score": 60.0, "text": raw[0].text,
        }]
        panel = _build_handoff_panel(top, raw)
        dates = panel["detected_deadlines"]
        kinds = {d["kind"] for d in dates}
        assert "absolute" in kinds, f"No absolute deadline found: {dates}"
        assert "relative" in kinds, f"No relative deadline found: {dates}"


class TestTopics:
    def test_single_topic_clause_not_compound(self):
        assert not is_compound("The monthly rent is Rs. 10,000 payable by the 5th.")
        topics = detect_topics("The monthly rent is payable monthly.")
        assert "rent" in topics
        assert not is_compound("The monthly rent is payable monthly.")

    def test_multi_topic_section_is_compound(self):
        text = ("Pay rent monthly. The deposit secures compliance and may not be "
                "used to pay rent. Initial payment must be paid in cash.")
        assert is_compound(text)
        assert len(detect_topics(text)) >= 3


class TestScope:
    def test_manila_doc_out_of_scope(self):
        scope = detect_scope(MANILA_STYLE)
        assert not scope["in_scope"]
        assert scope["markers"], "Expected scope markers"

    def test_indian_doc_in_scope(self):
        text = "Rent Rs. 15,000 per month in Mumbai. Stamp duty per the Indian Stamp Act, 1899."
        assert detect_scope(text)["in_scope"]


def _diagnose_manila(session):
    """Diagnose the Manila fixture through the real async pipeline."""
    import asyncio
    import tempfile
    from pathlib import Path as _Path

    from strain.backend.pipeline.diagnose import diagnose as _diagnose

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".txt", mode="w", encoding="utf-8"
    ) as tmp:
        tmp.write(MANILA_STYLE)
        tmp_path = tmp.name
    try:
        result = asyncio.run(_diagnose(tmp_path, "manila.txt", session))
    finally:
        _Path(tmp_path).unlink(missing_ok=True)
    # Tidy up: remove the fixture doc so repeated runs don't pollute the DB.
    from sqlmodel import select

    from strain.backend.store.store import Clause, Document

    doc_id = result["doc_id"]
    for clause in session.exec(
        select(Clause).where(Clause.doc_id == doc_id)
    ).all():
        session.delete(clause)
    doc = session.exec(
        select(Document).where(Document.doc_id == doc_id)
    ).first()
    if doc:
        session.delete(doc)
    session.commit()
    return result


class TestPreamble:
    def test_preamble_flagged_and_kept_out_of_handoff(self):
        from sqlmodel import Session

        from strain.backend.store.store import engine

        with Session(engine) as session:
            result = _diagnose_manila(session)
        assert result["clause_count"] >= 4
        by_id = {c["clause_id"]: c for c in result["clauses"]}
        preambles = [c for c in result["clauses"] if c.get("is_preamble")]
        assert len(preambles) == 1
        handoff_ids = {
            item["clause_id"]
            for item in result["handoff_panel"]["top_risk_clauses"]
        }
        assert not any(
            by_id[cid].get("is_preamble") for cid in handoff_ids
        ), "Preamble must not lead the handoff panel"


class TestRentQuestions:
    def test_rent_family_gets_specific_questions(self):
        qs = _lawyer_questions_for_family("Rent Payment", {})
        assert len(qs) == 3
        assert any("grace period" in q for q in qs)

    def test_penalty_family_gets_specific_questions(self):
        qs = _lawyer_questions_for_family("Penalty Clause", {})
        assert any("pre-estimate" in q or "proportion" in q for q in qs)
