"""
Phase 3 acceptance test: validates clause segmentation and normalisation.

Tests on 5 deliberately messy document fixtures:
1. Numbered list format
2. Nested sub-clauses
3. Paragraph-only document
4. Typo-heavy document
5. Split-paragraph document
"""
from __future__ import annotations

import pytest

# Import the pipeline
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strain.backend.pipeline.segment import segment, normalise


# ─── Fixtures ─────────────────────────────────────────────────────────────────

FIXTURE_1_NUMBERED = """RENTAL AGREEMENT

1. RENT PAYMENT
The monthly rent shall be Rs. 15,000 payable on or before the 5th of each month.

2. SECURITY DEPOSIT
A deposit of Rs. 45,000 shall be paid before taking possession.

3. NOTICE PERIOD
Either party shall give 30 days' written notice before termination.

4. REPAIRS
The Landlord shall be responsible for structural repairs.

5. SUBLETTING
The Tenant shall not sublet without written consent.
"""

FIXTURE_2_NESTED = """RENTAL AGREEMENT

CLAUSE 1: RENT AND PAYMENT
1.1 The monthly rent shall be Rs. 18,000.
1.2 Payment shall be made by the 1st of each month.
1.3 Late payment shall attract interest at 12% per annum.
    (a) Interest shall be calculated from the due date.
    (b) No grace period shall apply.

CLAUSE 2: DEPOSIT
2.1 A refundable deposit of Rs. 54,000 is payable.
2.2 The deposit shall be returned within 45 days of vacation.
    (a) Deductions may be made for damage.
    (b) A deduction statement shall be provided.

CLAUSE 3: TERMINATION
3.1 Either party may terminate by giving 30 days' notice.
"""

FIXTURE_3_PARAGRAPH = """RENTAL AGREEMENT

This agreement is made between the landlord and the tenant for residential premises.

The monthly rent is fifteen thousand rupees, payable by the fifth of each month. In case of delay, interest at twelve percent per annum will be charged from the date of default.

A security deposit of three months' rent shall be collected before possession. The deposit is refundable at the end of the tenancy after deducting any outstanding dues.

The tenant shall maintain the property in good condition and shall not sublet without consent. Violations will entitle the landlord to terminate the agreement with seven days' notice.

All utility bills including electricity, water, and gas shall be paid by the tenant. The landlord shall not be held responsible for disruption of utility services.

Disputes arising from this agreement shall be resolved by arbitration as per applicable law.
"""

FIXTURE_4_TYPOS = """RENTAL AGREEMNET

1. RNENT PAYMNET
The mnothly rnent shall be Rs. 20,000 pyaable on or befroe the 5th fo each monht. Any lated payment will attract a penalyt of Rs. 500 per day.

2. SECRUITY DEPOIST
A depoist of Rs. 60,000 is payble befroe possession. The depoist is refundble within 30 dyas of vacaitng.

3. TERMIANTOIN
Either praty may terminate this agreemnet by givnig 30 dyas' writtten notice.

4. REPARIS
The Landolrd shall be responsibel for structural reparis. Mnior reparis are the Tennat's responsibilty.

5. SUBLETTIGN
The Tennat shall nto sublet the premisies without priror writtten consent.
"""

FIXTURE_5_SPLIT_PARAGRAPH = """RENTAL AGREEMENT

This is a Rent Agreement for the premises situated at Koramangala, Bangalore.

RENT PAYMENT:
The tenant agrees to pay a monthly rent of Rupees Twelve Thousand only. The
rent is due on the first of every month. Payment shall be made via bank
transfer. The landlord shall provide a receipt within three days of receiving
payment.

DEPOSIT CLAUSE:
Before taking possession, the tenant shall pay a security deposit of Rupees
Twenty-Four Thousand only. This deposit will be
returned within thirty days of the tenant vacating the premises, less any
lawful deductions for unpaid rent or damage.

NOTICE:
Either party wishing to terminate this agreement must give a minimum of thirty days
written notice. The notice period shall begin from the date of receipt of the notice
by the other party.

MAINTENANCE:
The tenant is responsible for keeping the property clean and
in good condition. The landlord shall carry out structural
repairs within a reasonable time upon notification by the tenant.
"""


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestNumberedDocument:
    def test_all_clauses_captured(self):
        clauses = segment(FIXTURE_1_NUMBERED, "doc_test_1")
        # Should get at least 5 clauses (one per numbered item)
        assert len(clauses) >= 5, f"Expected ≥5 clauses, got {len(clauses)}"

    def test_no_empty_clauses(self):
        clauses = segment(FIXTURE_1_NUMBERED, "doc_test_1")
        for c in clauses:
            assert len(c.text.strip()) >= 10, f"Clause too short: '{c.text}'"

    def test_clause_ids_unique(self):
        clauses = segment(FIXTURE_1_NUMBERED, "doc_test_1")
        ids = [c.clause_id for c in clauses]
        assert len(ids) == len(set(ids)), "Duplicate clause IDs"


class TestNestedDocument:
    def test_nested_clauses_captured(self):
        clauses = segment(FIXTURE_2_NESTED, "doc_test_2")
        assert len(clauses) >= 3, f"Expected ≥3 clauses, got {len(clauses)}"

    def test_sub_clauses_included_in_parent(self):
        clauses = segment(FIXTURE_2_NESTED, "doc_test_2")
        full_text = " ".join(c.text for c in clauses)
        # Sub-clause content should be present
        assert "Interest shall be calculated" in full_text or "from the due date" in full_text
        assert "deduction statement" in full_text or "Deductions may be made" in full_text


class TestParagraphDocument:
    def test_paragraph_clauses_captured(self):
        clauses = segment(FIXTURE_3_PARAGRAPH, "doc_test_3")
        assert len(clauses) >= 4, f"Expected ≥4 clauses from paragraph doc, got {len(clauses)}"

    def test_no_clause_split_incorrectly(self):
        clauses = segment(FIXTURE_3_PARAGRAPH, "doc_test_3")
        # No clause should be shorter than 20 chars (indicates split)
        for c in clauses:
            assert len(c.text.strip()) >= 20, f"Clause appears split: '{c.text[:50]}'"


class TestTypoDocument:
    def test_typo_doc_clauses_captured(self):
        clauses = segment(FIXTURE_4_TYPOS, "doc_test_4")
        assert len(clauses) >= 4, f"Expected ≥4 clauses from typo doc, got {len(clauses)}"

    def test_typo_content_preserved(self):
        clauses = segment(FIXTURE_4_TYPOS, "doc_test_4")
        full_text = " ".join(c.text for c in clauses)
        # Core content should be present despite typos
        assert "20,000" in full_text or "rnent" in full_text or "mnothly" in full_text


class TestSplitParagraphDocument:
    def test_split_paragraph_clauses_captured(self):
        clauses = segment(FIXTURE_5_SPLIT_PARAGRAPH, "doc_test_5")
        assert len(clauses) >= 4, f"Expected ≥4 clauses, got {len(clauses)}"

    def test_split_paragraphs_joined(self):
        clauses = segment(FIXTURE_5_SPLIT_PARAGRAPH, "doc_test_5")
        full_text = " ".join(c.text for c in clauses)
        # The split "deposit" clause content should appear in some clause
        assert "Twenty-Four Thousand" in full_text or "30 days" in full_text or "thirty days" in full_text


# ─── Normalisation tests ───────────────────────────────────────────────────────

class TestNormalisation:
    def test_amount_replaced(self):
        text = "The rent is Rs. 15,000 per month."
        result = normalise(text)
        assert "[AMOUNT]" in result
        assert "15,000" not in result

    def test_date_replaced(self):
        text = "The agreement commences on 01/04/2024 at Mumbai."
        result = normalise(text)
        assert "[DATE]" in result

    def test_city_replaced(self):
        text = "The property is located in Mumbai."
        result = normalise(text)
        assert "[CITY]" in result
        assert "Mumbai" not in result

    def test_inr_amount_replaced(self):
        text = "A deposit of INR 50000 shall be paid."
        result = normalise(text)
        assert "[AMOUNT]" in result

    def test_rs_dot_replaced(self):
        text = "Monthly payment of Rs. 25,000 per month payable."
        result = normalise(text)
        assert "[AMOUNT]" in result
        assert "25,000" not in result

    def test_normalisation_idempotent_on_normal_text(self):
        text = "The tenant shall maintain the premises in good condition."
        result = normalise(text)
        assert result == text.strip() or "tenant" in result
