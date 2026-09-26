"""
Segmentation and normalisation pipeline.

Input:  raw document text (str) or file path (PDF/DOCX/TXT)
Output: list of ClauseRecord dicts

Normalisation replaces party names, amounts, dates, addresses with
placeholder tokens so two clauses differing only in rent amount are
recognised as the same clause family.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# ─── Placeholder tokens ───────────────────────────────────────────────────────

# Indian amount patterns: ₹1,00,000  or Rs. 25000  or INR 5000
_AMOUNT_PAT = re.compile(
    r"(?:₹|Rs\.?\s*|INR\s*)[\d,]+(?:\.\d+)?(?:\s*(?:per month|p\.?m\.?|lakh|lakhs))?",
    re.IGNORECASE,
)

# Dates: 01/04/2024, 1-Apr-2024, April 2024, 2024-04-01,
# "20th day of May, 2007" (written-legal format common in real agreements)
_DATE_PAT = re.compile(
    r"\b(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
    r"|\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{2,4}"
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2},?\s+\d{2,4}"
    r"|\d{1,2}(?:st|nd|rd|th)\s+day\s+of\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r",?\s+\d{2,4}"
    r"|\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)

# Relative deadlines: "3-day grace period", "within 15 days",
# "7 days before moving-in". Surfaced in the handoff panel alongside
# absolute dates.
_NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"

_RELATIVE_DEADLINE_PAT = re.compile(
    rf"\b{_NUM}\s*-\s*day grace period\b"
    rf"|\b{_NUM}\s+days?\s+grace period\b"
    rf"|\bwithin\s+{_NUM}\s+days?\b"
    rf"|\b{_NUM}\s+days?\s+before\b"
    r"|\bdue\s+[^.]{0,40}?\bevery\s+month\b",
    re.IGNORECASE,
)

# Common Indian cities
_CITY_PAT = re.compile(
    r"\b(?:Mumbai|Delhi|Bangalore|Bengaluru|Chennai|Hyderabad|Kolkata|Pune|Ahmedabad"
    r"|Jaipur|Lucknow|Surat|Kanpur|Nagpur|Indore|Bhopal|Patna|Vadodara|Ghaziabad"
    r"|Ludhiana|Agra|Nashik|Faridabad|Meerut|Rajkot|Varanasi|Srinagar|Aurangabad"
    r"|Dhanbad|Amritsar|Allahabad|Ranchi|Coimbatore|Jabalpur|Gwalior|Vijayawada"
    r"|Jodhpur|Madurai|Raipur|Kota|Guwahati|Chandigarh|Solapur|Hubli|Dharwad"
    r"|Tiruchirappalli|Bareilly|Mysore|Mysuru|Tiruppur|Moradabad|Jalandhar)\b",
    re.IGNORECASE,
)

# Party name patterns — detect "the Landlord" / "the Tenant" and specific named parties
# Named parties appear as patterns like "Mr./Ms. [Name]" or "M/s [Company]"
_NAMED_PARTY_A_PAT = re.compile(
    r"\b(?:M/s\.?\s+[A-Z][A-Za-z\s]+|Mr\.?\s+[A-Z][A-Za-z\s]+|Mrs\.?\s+[A-Z][A-Za-z\s]+"
    r"|Ms\.?\s+[A-Z][A-Za-z\s]+)(?=,|\s(?:hereinafter|and|the|of))",
    re.UNICODE,
)

# Normalise number-only references (notice period amounts like "30 days", "2 months")
# We keep these as they are mutation-relevant. We only strip monetary amounts.


# ─── Clause splitting ─────────────────────────────────────────────────────────

# Inline headers: an ALL-CAPS phrase ending in a colon mid-paragraph, e.g.
# "RENT:", "SECURITY DEPOSIT:", "METHOD OF PAYMENT:". Common in real-world
# agreements that use narrative flow instead of numbered lists.
_INLINE_HEADER_PAT = re.compile(
    r"\b([A-Z][A-Z0-9][A-Z0-9 /&\-']{1,38}):"
)

# Operative-terms cue: everything before this line is preamble (parties,
# recitals, consideration), not an operative clause.
_PREAMBLE_CUE_PAT = re.compile(
    r"hereby agrees? to the following terms|"
    r"the parties agree as follows|"
    r"NOW,?\s+THEREFORE",
    re.IGNORECASE,
)

# Broadened operative cues: alternative phrasings that end the preamble.
_OPERATIVE_CUE_PAT = re.compile(
    r"hereby agrees? to the following terms|"
    r"the parties agree as follows|"
    r"NOW,?\s+THEREFORE|"
    r"WITNESSETH\s+AS\s+FOLLOWS|"
    r"witnesseth\s*:|"
    r"agrees?\s+as\s+follows",
    re.IGNORECASE,
)

# Party-section signals: when no operative cue exists but the region before
# the first numbered clause carries these, it is preamble (parties,
# property, recitals) rather than an operative clause.
_PARTY_SIGNAL_PAT = re.compile(
    r"BY\s+AND\s+BETWEEN|hereinafter|\bS/O\b|\bD/O\b|\bW/O\b|residing at|"
    r"referred to as|made and executed on|entered into|aged \d+ years|"
    r"hereby (lets?|leases?|agrees? to let)",
    re.IGNORECASE,
)

# A signature/witness region starts a new segment so execution blocks are
# never merged into the final operative clause.
_SIGNATURE_START_PAT = re.compile(
    r"^(IN WITNESS WHEREOF|SIGNED AND DELIVERED|WITNESS\s*\d|WITNESSES?\s*:|"
    r"Signature of .{0,40}:|IN WITNESS THEREOF)",
    re.IGNORECASE,
)

# Numbered clause starters: "1.", "(1)", "1)", "a.", "(a)", "CLAUSE 1"
_CLAUSE_NUM_PAT = re.compile(
    r"^(?:CLAUSE\s+\d+[.:)]?"
    r"|\d+[.)]\s"
    r"|\(\d+\)\s"
    r"|[A-Z]\.\s"
    r"|\([a-z]\)\s"
    r"|[ivxlcdm]+[.)\s])",
    re.IGNORECASE | re.MULTILINE,
)

# Heading-like lines: ALL CAPS line or Title Case followed by newline
_HEADING_PAT = re.compile(r"^([A-Z][A-Z\s\-/]{3,}|(?:[A-Z][a-z]+\s?){2,})\s*$", re.MULTILINE)


@dataclass
class ClauseRecord:
    clause_id: str
    doc_id: str
    ordinal: int
    heading: str
    text: str
    normalised_text: str
    # Structured classification (rule-based, offline). `topic` is what the
    # clause is about (independent of strain family and risk). `kind` marks
    # non-operative document components (preamble/signature/...) that must
    # stay out of ordinary risk scoring. `source` is a best-effort locator
    # (line span) inside the extracted document text.
    topic: str = "other"
    kind: str = "operative"
    source: str = ""


def read_document(path: str | Path) -> str:
    """Extract raw text from PDF, DOCX, or TXT."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        import pdfplumber
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        return "\n\n".join(pages)

    elif suffix in (".docx", ".doc"):
        from docx import Document as DocxDocument
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table as DocxTable
        from docx.text.paragraph import Paragraph as DocxParagraph

        doc = DocxDocument(path)
        parts: list[str] = []
        seen: set[str] = set()

        def _emit(text: str) -> None:
            text = text.strip()
            if not text:
                return
            key = re.sub(r"\s+", " ", text).lower()
            if key in seen:
                return  # avoid duplicate extraction of the same content
            seen.add(key)
            parts.append(text)

        # Walk body elements in document order so table cells land where
        # the author placed them (python-docx `paragraphs` skips tables).
        for child in doc.element.body.iterchildren():
            if isinstance(child, CT_P):
                _emit(DocxParagraph(child, doc).text)
            elif isinstance(child, CT_Tbl):
                table = DocxTable(child, doc)
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    cells = [c for c in cells if c]
                    if cells:
                        _emit(" | ".join(cells))
        # Fallback: if ordered walk found nothing, use plain paragraphs.
        if not parts:
            for p in doc.paragraphs:
                _emit(p.text)
        return "\n".join(parts)

    else:
        return path.read_text(encoding="utf-8", errors="replace")


def normalise(text: str) -> str:
    """Replace identifying tokens with placeholders."""
    t = _AMOUNT_PAT.sub("[AMOUNT]", text)
    t = _DATE_PAT.sub("[DATE]", t)
    t = _CITY_PAT.sub("[CITY]", t)
    t = _NAMED_PARTY_A_PAT.sub("[NAMED_PARTY]", t)
    # Defined-term party roles → contract tokens (capitalised only, per
    # AGENTS.md algorithm contract; lowercase generic uses are preserved).
    t = re.sub(r"\b(Landlord|Lessor|Licensor|Owner|PARTY A)\b", "[PARTY_A]", t)
    t = re.sub(r"\b(Tenant|Lessee|Licensee|Occupant|Resident|PARTY B)\b", "[PARTY_B]", t)
    # Collapse runs of whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ─── Clause topic taxonomy ──────────────────────────────────────────────────
# Rule-based, offline. Topic answers "what is this clause about" and is
# deliberately independent of strain family (textual lineage) and risk
# score. Rules are ordered most-specific-first; the first match wins so a
# deposit clause mentioning rent is still a deposit clause.

#: Canonical topic ids. `other` = no rule fired (low topic confidence).
TOPIC_IDS = (
    "term_renewal",
    "rent_payment",
    "deposit_refund",
    "termination_notice",
    "eviction_possession",
    "late_penalty",
    "maintenance_repairs",
    "utilities",
    "landlord_access",
    "subletting",
    "permitted_use",
    "ownership_authority",
    "dispute_resolution",
    "property_schedule",
    "signature_witness",
    "other",
)

TOPIC_LABELS = {
    "term_renewal": "Tenancy Term and Renewal",
    "rent_payment": "Rent Amount and Payment",
    "deposit_refund": "Security Deposit and Refund",
    "termination_notice": "Termination and Notice",
    "eviction_possession": "Eviction and Possession",
    "late_penalty": "Late-Payment Penalties and Interest",
    "maintenance_repairs": "Maintenance and Repairs",
    "utilities": "Utilities and Service Charges",
    "landlord_access": "Landlord Access and Privacy",
    "subletting": "Subletting and Assignment",
    "permitted_use": "Permitted Use",
    "ownership_authority": "Ownership and Authority",
    "dispute_resolution": "Dispute Resolution and Jurisdiction",
    "property_schedule": "Property Schedule",
    "signature_witness": "Signature and Witness",
    "other": "Other / Unclassified",
}

_SIGNATURE_PAT = re.compile(
    r"in witness whereof|signed and delivered|set their hands|"
    r"signature of (the )?(landlord|tenant|lessor|lessee|licensor|licensee|owner)|"
    r"sign(ed)? (below|here)|witness\s*\d|witnesses:?|"
    r"name:\s*_+.*address:.*signature:",
    re.IGNORECASE,
)
_WITNESSETH_CLAUSE_PAT = re.compile(
    r"witnesseth\s+as\s+follows|witnesseth\s*:", re.IGNORECASE
)
_SCHEDULE_PAT = re.compile(
    r"\bschedule\b|annexure|property description|demise|hereby (lets|leases|demises)|"
    r"agreed to let out|flat no\.|plot no\.|survey no\.|measuring about",
    re.IGNORECASE,
)
_FOOTER_PAT = re.compile(
    r"synthetic document|for demonstration purposes|document id:|page \d+ of \d+",
    re.IGNORECASE,
)


def _has(pat: str, text: str) -> bool:
    return re.search(pat, text, re.IGNORECASE) is not None


def classify_topic(text: str, heading: str = "") -> tuple[str, str]:
    """Return (topic_id, confidence) for a clause.

    Confidence is "high" when a specific rule fired on the clause body,
    "medium" when only the heading matched, and "low" for the "other"
    fallback. Topic confidence is separate from strain similarity.
    """
    body = text or ""
    head = (heading or "").lower()

    def head_has(*kws: str) -> bool:
        return any(k in head for k in kws) if head else False

    # Signature / witness blocks are structural, not topical.
    if _SIGNATURE_PAT.search(body) or head_has("witness", "signature"):
        return "signature_witness", "high"
    # Ownership declarations must not be mistaken for rent clauses even
    # when they sit next to rental terms.
    if _has(r"absolute owner|ownership|free from (all )?encumbrances|"
            r"authority to (grant|create|execute)|title to (let|lease)|"
            r"marketable title|clear title|holds? .*title|competent to|"
            r"warrants? .*title|owner in possession|"
            r"represents and declares|it is hereby (declared|confirmed)", body):
        return "ownership_authority", "high"
    # Property grant / schedule descriptions.
    if _SCHEDULE_PAT.search(body) and not _has(r"pay|rent|deposit|notice", body):
        return "property_schedule", "medium"
    # Deposit beats rent: deposit clauses routinely mention rent amounts.
    if _has(r"deposit|security amount|caution amount|advance (payment|deposit)", body):
        return "deposit_refund", "high"
    # Penalties beat rent: late-fee clauses mention rent too.
    if _has(r"penalty|late fee|late payment|interest (at|on|per)|forfeit|"
            r"liquidated damages|penal interest", body):
        return "late_penalty", "high"
    # Eviction/possession is stronger than generic termination.
    if _has(r"evict|hand over (vacant |peaceful )?possession|deliver (up )?possession|"
            r"\bquit\b.*premises|re-enter|right of re-entry", body):
        return "eviction_possession", "high"
    # Term / renewal (incl. lock-in) before termination: duration language wins.
    if _has(r"remain in force|term of|duration|valid for|validity|renewal|renew\b|"
            r"lock[\s-]*in|commencement|minimum (occupancy|period)|tenure|expir(y|ation) of (this|the) (agreement|tenancy|lease)", body):
        return "term_renewal", "high"
    if _has(r"terminat|give .*notice|notice period|vacat|terminate", body):
        return "termination_notice", "high"
    if _has(r"\brent\b|licen[sc]e fee|monthly consideration|monthly rental|per month.*pay|pay.*per month", body):
        return "rent_payment", "high"
    if _has(r"repair|upkeep|\bmaintain\b|maintenance(?! charge)|structural|seepage|whitewash", body):
        return "maintenance_repairs", "high"
    if _has(r"electricity|water|gas|maintenance charges?|property tax|society charges|"
            r"utility|utilities|outgoings|service charges?|power backup", body):
        return "utilities", "high"
    if _has(r"\benter\b.*premises|inspect|visit.*premises|access.*premises|right of entry|"
            r"entry.*(notice|consent)|enter.{0,50}notice|notice.{0,50}\benter\b", body):
        return "landlord_access", "high"
    if _has(r"sublet|sub-let|assign|part with possession|share possession", body):
        return "subletting", "high"
    if _has(r"used? (only |exclusively |solely )?(for|as)|residential purposes?|"
            r"permitted use|no commercial|unlawful purpose|nuisance", body):
        return "permitted_use", "high"
    if _has(r"dispute|arbitrat|jurisdiction|court|mediation|consumer forum|rent authority", body):
        return "dispute_resolution", "high"
    # Heading-only fallback (medium confidence).
    if head_has("rent", "payment"):
        return "rent_payment", "medium"
    if head_has("deposit"):
        return "deposit_refund", "medium"
    if head_has("terminat", "notice", "evict", "vacat"):
        return "termination_notice", "medium"
    if head_has("repair", "maintenance"):
        return "maintenance_repairs", "medium"
    if head_has("utilit", "electricity", "water"):
        return "utilities", "medium"
    if head_has("entry", "access", "inspect"):
        return "landlord_access", "medium"
    if head_has("sublet"):
        return "subletting", "medium"
    if head_has("dispute", "arbitrat"):
        return "dispute_resolution", "medium"
    if head_has("term", "renewal", "duration", "lock"):
        return "term_renewal", "medium"
    return "other", "low"


#: Component kinds. Anything other than "operative" stays out of
#: ordinary legal-risk scoring and operative counts.
KIND_IDS = ("operative", "preamble", "schedule", "signature", "witness", "footer")


def classify_kind(text: str, heading: str = "") -> str:
    """Return the document-component kind for a clause segment."""
    body = text or ""
    head = heading or ""
    if _FOOTER_PAT.search(body):
        return "footer"
    if _WITNESSETH_CLAUSE_PAT.search(body):
        return "preamble"
    # "witness" needs a witness-block context; bare "witnesseth" is preamble
    # language, handled above.
    if re.search(r"witness\s*\d|witnesses\s*:|name:\s*_+.*signature:", body, re.IGNORECASE):
        return "witness"
    if _SIGNATURE_PAT.search(body) or "signature" in head.lower():
        return "signature"
    if _SCHEDULE_PAT.search(head) and len(body) < 600:
        return "schedule"
    return "operative"


# Words that only ever form a document title, never a clause topic. Title
# lines must not become running headings for unrelated clauses.
_DOC_TITLE_WORDS = frozenset({
    "rental", "agreement", "lease", "deed", "contract", "house",
    "format", "sample", "draft", "model", "residential",
})


def _is_doc_title(line: str) -> bool:
    words = re.findall(r"[a-z]+", line.lower())
    return bool(words) and len(line) < 60 and all(w in _DOC_TITLE_WORDS for w in words)


def _is_topic_heading(line: str) -> bool:
    """True when a heading line carries clause-topic information.

    Document titles ("RENTAL AGREEMENT") and preamble fragments
    ("BY AND BETWEEN") must not leak into topic labels or embeddings.
    """
    if not line or _is_doc_title(line):
        return False
    lowered = line.lower()
    return "by and between" not in lowered and "witnesseth" not in lowered


def _peel_preamble(text: str) -> tuple[tuple[str, str] | None, str]:
    """Split (preamble, operative_text).

    Returns ((heading, preamble_text), remaining) or (None, text) when no
    preamble boundary is found. The preamble is document context — parties,
    property, recitals — never an operative clause.
    """
    cue = _OPERATIVE_CUE_PAT.search(text)
    if cue:
        line_end = text.find("\n", cue.end())
        if line_end == -1:
            line_end = len(text)
        return (
            ("Preamble — Parties & Recitals", text[:line_end].strip()),
            text[line_end:].strip(),
        )
    # Fallback: party signals in the region before the first numbered clause.
    num = _CLAUSE_NUM_PAT.search(text)
    if num:
        region = text[: num.start()]
        if region.strip() and _PARTY_SIGNAL_PAT.search(region):
            return (
                ("Preamble — Parties & Recitals", region.strip()),
                text[num.start():].strip(),
            )
    return None, text


def segment(text: str, doc_id: str) -> list[ClauseRecord]:
    """
    Split document text into atomic clause records.

    Strategy (ordered by precedence):
    1. Peel the preamble (parties/recitals) — kept as context, never scored.
    2. If document has numbered clauses (e.g. "1.", "(a)"), split on those.
    3. Otherwise split on blank lines (paragraph mode).
    4. Sub-clauses within a numbered clause are kept together unless they
       themselves start a new numbered sequence.
    5. Signature/witness regions are split out and tagged, never merged
       into the final operative clause.
    """
    # Clean up
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Peel off the preamble (parties, recitals, consideration).
    preamble, text = _peel_preamble(text)

    # Check if document is list-structured
    numbered_lines = _CLAUSE_NUM_PAT.findall(text)
    if len(numbered_lines) >= 3:
        clauses = _split_numbered(text)
    else:
        clauses = _split_paragraphs(text)

    # Second pass: split bodies on inline ALL-CAPS headers ("RENT:", ...).
    # This rescues narrative-flow documents with no numbering at all.
    clauses = _split_inline_headers(clauses)

    if preamble and preamble[1]:
        clauses = [(preamble[0], preamble[1], "preamble"), *clauses]

    # Build ClauseRecord list
    records: list[ClauseRecord] = []
    for i, (heading, body, source) in enumerate(clauses):
        body = body.strip()
        if not body or len(body) < 20:
            continue
        heading = heading.strip()
        kind = classify_kind(body, heading)
        if kind == "preamble" or (preamble and i == 0):
            kind = "preamble"
            topic, _tconf = "other", "low"
        else:
            topic, _tconf = classify_topic(
                body, heading if _is_topic_heading(heading) else ""
            )
        clause_id = f"{doc_id}:c{i:03d}"
        records.append(
            ClauseRecord(
                clause_id=clause_id,
                doc_id=doc_id,
                ordinal=i,
                heading=heading,
                text=body,
                normalised_text=normalise(body),
                topic=topic,
                kind=kind,
                source=source or f"block {i}",
            )
        )
    return records


def _split_numbered(text: str) -> list[tuple[str, str, str]]:
    """Split on numbered clause markers, keeping sub-clauses grouped.

    Returns (heading, body, source) triples; source is the 1-based line span.
    A heading line applies to the next clause only (no carryover), document
    titles are skipped, and signature/witness regions start fresh segments.
    """
    lines = text.split("\n")
    clauses: list[tuple[str, str, str]] = []
    pending_heading = ""
    current_body: list[str] = []
    body_start = 0  # 0-based line index where current_body starts

    def _flush(end_line: int) -> None:
        nonlocal current_body, pending_heading, body_start
        if current_body:
            body = "\n".join(current_body)
            clauses.append((pending_heading, body, f"lines {body_start + 1}-{end_line}"))
            current_body = []
        pending_heading = ""

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if current_body:
                current_body.append("")
            continue

        # Document titles are layout, not clause topics — skip them so they
        # never become running headings or clause text.
        if _is_doc_title(stripped):
            continue

        # Signature / witness regions must not merge into operative clauses.
        if _SIGNATURE_START_PAT.match(stripped):
            _flush(idx)
            current_body = [stripped]
            body_start = idx
            continue

        # Check if this is a heading line (applies to the next clause only).
        if _HEADING_PAT.match(stripped) and len(stripped) < 80:
            if current_body:
                _flush(idx)
            pending_heading = stripped
            continue

        # Check if this starts a new top-level numbered clause
        m = re.match(
            r"^(\d+[.)]\s|CLAUSE\s+\d+[.:\s]|\([A-Z]\)\s)",
            stripped,
            re.IGNORECASE,
        )
        if m:
            if current_body:
                _flush(idx)
            rest = stripped[m.end():].strip()
            # A short, non-sentence remainder is the clause's own heading
            # ("1. RENT PAYMENT"); a full sentence is the clause body.
            # The marker line itself stays in the body so clause text (and
            # hence embeddings) is unchanged; the heading only adds structure.
            if (
                rest
                and len(rest) <= 60
                and not rest.endswith(".")
                and not re.search(r"\b(shall|must|will|agrees?)\b", rest, re.IGNORECASE)
            ):
                pending_heading = rest
            if not current_body:
                body_start = idx
            current_body.append(stripped)
        else:
            if not current_body:
                body_start = idx
            current_body.append(stripped)

    _flush(len(lines))

    return [(h, b, s) for h, b, s in clauses if b.strip()]


def _split_paragraphs(text: str) -> list[tuple[str, str, str]]:
    """Split on blank lines; heading lines extracted (next-clause only)."""
    blocks = re.split(r"\n{2,}", text)
    clauses: list[tuple[str, str, str]] = []
    pending_heading = ""
    line_no = 0

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        n_lines = block.count("\n") + 1
        lines = block.split("\n")
        # If first line looks like a heading (and is not a doc title)
        if (
            len(lines) > 1
            and _HEADING_PAT.match(lines[0].strip())
            and not _is_doc_title(lines[0].strip())
        ):
            pending_heading = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
        else:
            if _is_doc_title(block) and len(block) < 60:
                line_no += n_lines
                continue
            body = block

        if body:
            clauses.append((pending_heading, body, f"lines {line_no + 1}-{line_no + n_lines}"))
            pending_heading = ""
        line_no += n_lines

    return clauses


def _split_inline_headers(
    clauses: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Split clause bodies on inline ALL-CAPS headers ("RENT:", ...).

    The text before the first inline header keeps its original heading;
    each header becomes the heading of the text that follows it. Provenance
    is inherited from the parent block.
    """
    out: list[tuple[str, str, str]] = []
    for heading, body, source in clauses:
        parts = _INLINE_HEADER_PAT.split(body)
        if len(parts) <= 1:
            out.append((heading, body, source))
            continue
        # parts = [text_before, header1, text1, header2, text2, ...]
        first = parts[0].strip()
        if first:
            out.append((heading, first, source))
        for i in range(1, len(parts), 2):
            hdr = parts[i].strip().title()
            txt = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if txt:
                out.append((hdr, txt, source))
    return out


# ─── Topic / compound detection ─────────────────────────────────────────────

# Keyword sets for the clause topics the pipeline knows about. Used to flag
# compound sections (one segment covering 3+ topics) honestly in the UI
# instead of pretending they are a single clause.
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "rent": ["rent", "rental", "licence fee", "license fee", "per month"],
    "deposit": ["deposit", "advance payment"],
    "notice": ["notice"],
    "repairs": ["repair", "maintenance", "upkeep"],
    "entry": ["enter the premises", "entry", "inspect"],
    "subletting": ["sublet", "sub-let", "assign"],
    "termination": ["terminat", "evict", "vacat"],
    "dispute": ["dispute", "arbitrat", "jurisdiction"],
    "penalty": ["penalty", "forfeit", "liquidated", "interest per", "fine"],
    "utilities": ["utilit", "electricity", "water", "gas"],
    "payment": ["payment", "payable", "pay ", "paid ", "cash", "post dated", "post-dated", "cheque", "check"],
}

COMPOUND_TOPIC_THRESHOLD = 3


def detect_topics(text: str) -> list[str]:
    """Return the sorted list of known topics mentioned in the text."""
    lowered = text.lower()
    return sorted(
        topic
        for topic, keywords in _TOPIC_KEYWORDS.items()
        if any(kw in lowered for kw in keywords)
    )


def is_compound(text: str, threshold: int = COMPOUND_TOPIC_THRESHOLD) -> bool:
    """True when a single segment spans `threshold` or more known topics."""
    return len(detect_topics(text)) >= threshold


# ─── Geographic scope detection ──────────────────────────────────────────────

# v1 covers Indian residential rental agreements only. When a document carries
# markers from another jurisdiction, the pipeline still runs, but the UI must
# say the corpus framing may not apply.
_OUT_OF_SCOPE_PAT = re.compile(
    r"₱|\bPESOS?\b|\bPHP\b|\bDOLLARS?\b|\bUSD\b"
    r"|\bManila\b|\bCebu\b|\bDavao\b|\bQuezon City\b|\bMakati\b"
    r"|\bLondon\b|\bNew York\b|\bSingapore\b|\bDubai\b",
    re.IGNORECASE,
)
_IN_SCOPE_PAT = re.compile(
    r"₹|\bINR\b|\bRs\.?\b|Stamp Act|Registration Act|Rent Control"
    r"|Arbitration and Conciliation Act",
    re.IGNORECASE,
)


def detect_scope(text: str) -> dict:
    """Detect whether a document looks outside the v1 Indian scope.

    Returns {"in_scope": bool, "markers": [...]}. A document is flagged
    out-of-scope only when foreign markers are present *and* no Indian
    markers are found alongside them.
    """
    foreign = sorted(
        {m.group(0) for m in _OUT_OF_SCOPE_PAT.finditer(text)}
    )
    indian = bool(_IN_SCOPE_PAT.search(text))
    in_scope = not foreign or indian
    return {"in_scope": in_scope, "markers": foreign}


def segment_file(file_path: str | Path, doc_id: str) -> list[ClauseRecord]:
    """Convenience: read file then segment."""
    text = read_document(file_path)
    return segment(text, doc_id)
