"""
API route tests: verify all endpoints respond correctly using the
in-memory database fixture (no seeded corpus required).
"""
from __future__ import annotations

import io


# ─── Health ───────────────────────────────────────────────────────────────────


def test_health_returns_ok(client):
    """GET /api/health must return 200 with service name."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "STRAIN"


# ─── Strains ──────────────────────────────────────────────────────────────────


def test_list_strains_empty_db(client):
    """GET /api/strains on empty DB returns empty list, not 500."""
    resp = client.get("/api/strains")
    assert resp.status_code == 200
    data = resp.json()
    assert "strains" in data
    assert isinstance(data["strains"], list)
    assert data["total"] == 0


def test_get_strain_not_found(client):
    """GET /api/strain/<id> for unknown id returns 404."""
    resp = client.get("/api/strain/nonexistent-strain-id")
    assert resp.status_code == 404


# ─── Outbreak ─────────────────────────────────────────────────────────────────


def test_outbreak_empty_db(client):
    """GET /api/outbreak on empty DB returns valid structure."""
    resp = client.get("/api/outbreak")
    assert resp.status_code == 200
    data = resp.json()
    assert "prevalence" in data
    assert "harshness_trend" in data
    assert "outcome_distribution" in data
    assert "strain_growth" in data
    assert data["total_documents"] == 0
    assert data["total_clauses"] == 0


# ─── Samples ──────────────────────────────────────────────────────────────────


def test_list_samples_returns_list(client):
    """GET /api/samples returns a list (may be empty if data/samples missing)."""
    resp = client.get("/api/samples")
    assert resp.status_code == 200
    data = resp.json()
    assert "samples" in data
    assert isinstance(data["samples"], list)


def test_get_sample_traversal_blocked(client):
    """Path traversal in sample filename must be blocked.

    FastAPI normalises paths before routing: /api/samples/../x is
    normalised to /api/x and never reaches get_sample. The real attack
    vector is a dot-encoded or dot-only name passed as the {filename}
    segment; those are tested here.
    """
    # Dot-only names: should be blocked by the startswith('.') check
    for bad in [".hidden", "..secret"]:
        resp = client.get(f"/api/samples/{bad}")
        assert resp.status_code == 404, f"Expected 404 for {bad!r}, got {resp.status_code}"


# ─── Ingest ───────────────────────────────────────────────────────────────────


def test_ingest_txt_document(client):
    """POST /api/ingest with a TXT file returns doc_id and status ingested."""
    text = b"1. RENT\nTenant shall pay Rs. 10,000 per month by the 5th.\n\n2. DEPOSIT\nA deposit of Rs. 20,000 is payable.\n"
    resp = client.post(
        "/api/ingest",
        files={"file": ("test_agreement.txt", io.BytesIO(text), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "doc_id" in data
    assert data["status"] == "ingested"


def test_ingest_rejects_unsupported_type(client):
    """POST /api/ingest with a .exe file must return 400."""
    resp = client.post(
        "/api/ingest",
        files={"file": ("malware.exe", io.BytesIO(b"MZ\x00"), "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_ingest_rejects_oversized_file(client):
    """POST /api/ingest with a file > 10 MB must return 413."""
    big = b"A" * (11 * 1024 * 1024)
    resp = client.post(
        "/api/ingest",
        files={"file": ("big.txt", io.BytesIO(big), "text/plain")},
    )
    assert resp.status_code == 413


def test_ingest_path_traversal_in_filename(client):
    """Filename with path separators must be sanitised, not cause a server error."""
    text = b"1. RENT\nPay rent monthly.\n"
    resp = client.post(
        "/api/ingest",
        files={"file": ("../../../etc/passwd", io.BytesIO(text), "text/plain")},
    )
    # Should either succeed (name sanitised) or 400 — never 500
    assert resp.status_code in {200, 400}


def test_diagnose_requires_file_or_doc_id(client):
    """POST /api/diagnose with neither file nor doc_id returns 400."""
    resp = client.post("/api/diagnose")
    assert resp.status_code == 400
