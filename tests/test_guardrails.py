"""
Guardrail enforcement test.

Verifies that forbidden strings do not appear anywhere in the React
frontend source code (user-facing strings).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND_SRC = Path(__file__).resolve().parents[1] / "strain" / "frontend" / "src"

FORBIDDEN_PATTERNS = [
    # Exact strings that must not appear in user-facing text
    r"\byou should\b",
    r"\bwe recommend\b",
    r"\blegal advice\b",
]

# File extensions to check
EXTENSIONS = {".tsx", ".ts", ".jsx", ".js"}

# Allowlist: patterns that are allowed (e.g., in comments about what's forbidden)
ALLOWLIST = [
    # test files themselves are allowed to reference the forbidden terms in comments
]


def get_source_files() -> list[Path]:
    if not FRONTEND_SRC.exists():
        return []
    files = []
    for ext in EXTENSIONS:
        files.extend(FRONTEND_SRC.rglob(f"*{ext}"))
    return files


def scan_files(files: list[Path], patterns: list[str]) -> list[str]:
    """Return `file:line: 'snippet'` hits for user-facing (non-comment) lines."""
    violations = []
    for fpath in files:
        content = fpath.read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            violations.extend(
                f"{fpath.name}:{i}: '{line.strip()[:80]}'"
                for i, line in enumerate(content.split("\n"), 1)
                if not line.strip().startswith(("//", "*"))
                and re.search(pattern, line, re.IGNORECASE)
            )
    return violations


def test_no_legal_advice_strings():
    """The phrase 'legal advice' must not appear in frontend source."""
    files = get_source_files()
    if not files:
        pytest.skip("Frontend source not built yet")

    violations = scan_files(files, FORBIDDEN_PATTERNS)
    assert not violations, (
        "Forbidden strings found in frontend source:\n" + "\n".join(violations[:10])
    )


def test_no_you_should():
    """The phrase 'you should' must not appear in user-facing frontend text."""
    files = get_source_files()
    if not files:
        pytest.skip("Frontend source not built yet")

    violations = scan_files(files, [r"\byou should\b"])
    assert not violations, (
        "Found 'you should' in frontend source:\n" + "\n".join(violations[:10])
    )


def test_no_we_recommend():
    """The phrase 'we recommend' must not appear in user-facing frontend text."""
    files = get_source_files()
    if not files:
        pytest.skip("Frontend source not built yet")

    violations = scan_files(files, [r"\bwe recommend\b"])
    assert not violations, (
        "Found 'we recommend' in frontend source:\n" + "\n".join(violations[:10])
    )


def test_no_fabricated_citations():
    """Ensure no judge names or case citation patterns appear in frontend."""
    files = get_source_files()
    if not files:
        pytest.skip("Frontend source not built yet")

    # Pattern for things like "Justice Smith" or "AIR 2019 SC 123"
    citation_patterns = [
        r"\bJustice\s+[A-Z][a-z]+\b",
        r"\bAIR\s+\d{4}\s+(?:SC|HC|Del|Bom|Mad)\b",
        r"\bWrit\s+Petition\s+No\.",
    ]

    violations = []
    for fpath in files:
        content = fpath.read_text(encoding="utf-8", errors="replace")
        for pattern in citation_patterns:
            matches = re.findall(pattern, content)
            if matches:
                violations.append(f"{fpath.name}: {matches}")

    assert not violations, (
        "Potential fabricated citations found:\n" + "\n".join(violations[:5])
    )
