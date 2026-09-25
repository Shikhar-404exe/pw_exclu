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
import uuid
from dataclasses import dataclass, field
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
        doc = DocxDocument(path)
        return "\n".join(p.text for p in doc.paragraphs)

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


def segment(text: str, doc_id: str) -> list[ClauseRecord]:
    """
    Split document text into atomic clause records.

    Strategy (ordered by precedence):
    1. If document has numbered clauses (e.g. "1.", "(a)"), split on those.
    2. Otherwise split on blank lines (paragraph mode).
    3. Sub-clauses within a numbered clause are kept together unless they
       themselves start a new numbered sequence.
    """
    # Clean up
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Peel off the preamble (parties, recitals, consideration) if the
    # document uses an operative-terms cue ("hereby agrees to the following
    # terms", "NOW THEREFORE", ...). The preamble is kept as context, not
    # scored as an operative clause.
    preamble: tuple[str, str] | None = None
    cue = _PREAMBLE_CUE_PAT.search(text)
    if cue:
        line_end = text.find("\n", cue.end())
        if line_end == -1:
            line_end = len(text)
        preamble = ("Preamble — Parties & Recitals", text[:line_end].strip())
        text = text[line_end:].strip()

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
        clauses = [preamble] + clauses

    # Build ClauseRecord list
    records: list[ClauseRecord] = []
    current_heading = ""
    for i, (heading, body) in enumerate(clauses):
        if heading:
            current_heading = heading
        body = body.strip()
        if not body or len(body) < 20:
            continue
        clause_id = f"{doc_id}:c{i:03d}"
        records.append(
            ClauseRecord(
                clause_id=clause_id,
                doc_id=doc_id,
                ordinal=i,
                heading=current_heading,
                text=body,
                normalised_text=normalise(body),
            )
        )
    return records


def _split_numbered(text: str) -> list[tuple[str, str]]:
    """Split on numbered clause markers, keeping sub-clauses grouped."""
    # Find all top-level numbered lines
    lines = text.split("\n")
    clauses: list[tuple[str, str]] = []
    current_heading = ""
    current_body: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_body:
                current_body.append("")
            continue

        # Check if this is a heading line
        if _HEADING_PAT.match(stripped) and len(stripped) < 80:
            if current_body:
                clauses.append((current_heading, "\n".join(current_body)))
                current_body = []
            current_heading = stripped
            continue

        # Check if this starts a new top-level numbered clause
        m = re.match(
            r"^(\d+[.)]\s|CLAUSE\s+\d+[.:\s]|\([A-Z]\)\s)",
            stripped,
            re.IGNORECASE,
        )
        if m and current_body:
            clauses.append((current_heading, "\n".join(current_body)))
            current_body = [stripped]
        else:
            current_body.append(stripped)

    if current_body:
        clauses.append((current_heading, "\n".join(current_body)))

    return clauses


def _split_paragraphs(text: str) -> list[tuple[str, str]]:
    """Split on blank lines; heading lines extracted."""
    blocks = re.split(r"\n{2,}", text)
    clauses: list[tuple[str, str]] = []
    current_heading = ""

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        # If first line looks like a heading
        if len(lines) > 1 and _HEADING_PAT.match(lines[0].strip()):
            current_heading = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
        else:
            body = block

        if body:
            clauses.append((current_heading, body))

    return clauses


def _split_inline_headers(
    clauses: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Split clause bodies on inline ALL-CAPS headers ("RENT:", ...).

    The text before the first inline header keeps its original heading;
    each header becomes the heading of the text that follows it.
    """
    out: list[tuple[str, str]] = []
    for heading, body in clauses:
        parts = _INLINE_HEADER_PAT.split(body)
        if len(parts) <= 1:
            out.append((heading, body))
            continue
        # parts = [text_before, header1, text1, header2, text2, ...]
        first = parts[0].strip()
        if first:
            out.append((heading, first))
        for i in range(1, len(parts), 2):
            hdr = parts[i].strip().title()
            txt = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if txt:
                out.append((hdr, txt))
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
