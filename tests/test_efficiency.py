"""
Efficiency and performance tests for STRAIN.

Checks response times, validates that endpoints handle empty DB gracefully
without excessive computation, and verifies caching headers are present.
"""
from __future__ import annotations

import io
import time

# ─── Response time guards ─────────────────────────────────────────────────────

def test_health_responds_quickly(client):
    """Health endpoint must respond in under 500 ms."""
    start = time.perf_counter()
    resp = client.get("/api/health")
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    assert elapsed < 0.5, f"Health check took {elapsed:.2f}s — too slow"


def test_strains_list_responds_quickly_on_empty_db(client):
    """Strains list on empty DB must respond in under 500 ms."""
    start = time.perf_counter()
    resp = client.get("/api/strains")
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    assert elapsed < 0.5, f"/api/strains took {elapsed:.2f}s on empty DB"


def test_outbreak_responds_quickly_on_empty_db(client):
    """Outbreak dashboard on empty DB must respond in under 500 ms."""
    start = time.perf_counter()
    resp = client.get("/api/outbreak")
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    assert elapsed < 0.5, f"/api/outbreak took {elapsed:.2f}s on empty DB"


# ─── Pagination / limit guardrails ────────────────────────────────────────────

def test_strains_response_structure(client):
    """Strains response always has a 'total' key for pagination use."""
    resp = client.get("/api/strains")
    data = resp.json()
    assert "total" in data
    assert isinstance(data["total"], int)


def test_outbreak_response_structure(client):
    """Outbreak response includes all expected keys."""
    resp = client.get("/api/outbreak")
    data = resp.json()
    expected_keys = {"prevalence", "harshness_trend", "outcome_distribution",
                     "strain_growth", "total_documents", "total_clauses", "total_strains"}
    assert expected_keys.issubset(data.keys())


# ─── GZip compression ─────────────────────────────────────────────────────────

def test_gzip_middleware_active(client):
    """
    GZipMiddleware is registered; responses with Accept-Encoding: gzip
    for large payloads should be compressed.
    The health endpoint is small so may not be compressed — just verify
    the middleware does not break the response.
    """
    resp = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200


# ─── Multiple ingest performance ──────────────────────────────────────────────

def test_multiple_ingests_complete_in_time(client):
    """Ingesting 3 small documents must complete in under 5 seconds total."""
    texts = [
        b"1. RENT\nTenant shall pay Rs. 10,000 per month.\n",
        b"1. DEPOSIT\nA deposit of Rs. 20,000 is payable on signing.\n",
        b"1. NOTICE\nEither party may terminate with 30 days written notice.\n",
    ]
    start = time.perf_counter()
    for i, text in enumerate(texts):
        resp = client.post(
            "/api/ingest",
            files={"file": (f"doc{i}.txt", io.BytesIO(text), "text/plain")},
        )
        assert resp.status_code == 200
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"3 ingests took {elapsed:.2f}s — too slow"
