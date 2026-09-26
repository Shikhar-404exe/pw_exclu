"""
Security-focused tests for STRAIN.

Verifies: input validation, path traversal blocking, error sanitisation,
security headers, file upload guards, and that error responses never leak
stack traces.
"""
from __future__ import annotations

import io
import re

# ─── Security headers ─────────────────────────────────────────────────────────


def test_security_headers_present(client):
    """Every response must carry baseline security headers."""
    resp = client.get("/api/health")
    headers = {k.lower(): v for k, v in resp.headers.items()}
    assert "x-content-type-options" in headers, "Missing X-Content-Type-Options"
    assert headers["x-content-type-options"] == "nosniff"
    assert "x-frame-options" in headers, "Missing X-Frame-Options"
    assert headers["x-frame-options"] == "DENY"
    assert "referrer-policy" in headers, "Missing Referrer-Policy"


def test_content_security_policy_present(client):
    """CSP header must be present on API responses."""
    resp = client.get("/api/health")
    headers = {k.lower(): v for k, v in resp.headers.items()}
    assert "content-security-policy" in headers, "Missing Content-Security-Policy"
    csp = headers["content-security-policy"]
    assert "default-src" in csp
    assert "object-src 'none'" in csp


# ─── File upload validation ────────────────────────────────────────────────────


def test_upload_blocks_html_extension(client):
    resp = client.post(
        "/api/ingest",
        files={"file": ("xss.html", io.BytesIO(b"<script>alert(1)</script>"), "text/html")},
    )
    assert resp.status_code == 400


def test_upload_blocks_js_extension(client):
    resp = client.post(
        "/api/ingest",
        files={"file": ("evil.js", io.BytesIO(b"require('child_process')"), "text/javascript")},
    )
    assert resp.status_code == 400


def test_upload_blocks_svg_extension(client):
    resp = client.post(
        "/api/ingest",
        files={"file": ("x.svg", io.BytesIO(b"<svg><script>alert(1)</script></svg>"), "image/svg+xml")},
    )
    assert resp.status_code == 400


def test_upload_allows_txt(client):
    text = b"1. RENT\nPay Rs. 10,000 per month.\n"
    resp = client.post(
        "/api/ingest",
        files={"file": ("lease.txt", io.BytesIO(text), "text/plain")},
    )
    assert resp.status_code == 200


# ─── Path traversal ───────────────────────────────────────────────────────────


def test_sample_dotfile_blocked(client):
    """Sample filenames starting with '.' must return 404."""
    resp = client.get("/api/samples/.bashrc")
    assert resp.status_code == 404


def test_sample_double_dot_name_blocked(client):
    """A filename that is '..something' must return 404."""
    resp = client.get("/api/samples/..secret")
    assert resp.status_code == 404


def test_sample_path_traversal_slash(client):
    """
    URL-path traversal: /api/samples/../requirements.txt

    FastAPI/Starlette normalises double-dot segments *before* routing,
    so the request arrives at a different route (not get_sample). Either
    the different route returns 404/422, or Starlette itself rejects it.
    In all cases the requirements.txt content must NOT be returned.
    """
    resp = client.get("/api/samples/../requirements.txt")
    # Must never return the file contents as a 200 JSON
    if resp.status_code == 200:
        # If somehow 200, confirm it's NOT requirements.txt content
        body = resp.text
        assert "fastapi" not in body.lower() and "uvicorn" not in body.lower(), \
            "Path traversal leaked requirements.txt content!"


def test_sample_path_traversal_dotdot(client):
    """URL-encoded dot-dot traversal must not expose arbitrary files."""
    resp = client.get("/api/samples/..%2Frequirements.txt")
    if resp.status_code == 200:
        body = resp.text
        assert "fastapi" not in body.lower() and "uvicorn" not in body.lower(), \
            "URL-encoded traversal leaked requirements.txt!"


# ─── Error response sanitisation ──────────────────────────────────────────────


_STACK_TRACE_PAT = re.compile(r"Traceback \(most recent call last\)|File \".*\.py\"")


def test_404_error_does_not_leak_stack_trace(client):
    """A 404 response body must not contain a Python stack trace."""
    resp = client.get("/api/strain/does-not-exist-xyz")
    assert resp.status_code == 404
    body = resp.text
    assert not _STACK_TRACE_PAT.search(body), f"Stack trace leaked in 404: {body[:200]}"


def test_400_error_does_not_leak_stack_trace(client):
    """A 400 response body must not contain a Python stack trace."""
    resp = client.post("/api/ingest", files={"file": ("bad.exe", io.BytesIO(b"MZ"), "application/octet-stream")})
    assert resp.status_code == 400
    body = resp.text
    assert not _STACK_TRACE_PAT.search(body), f"Stack trace leaked in 400: {body[:200]}"


# ─── CORS ─────────────────────────────────────────────────────────────────────


def test_cors_allows_localhost_dev(client):
    """OPTIONS preflight from localhost:5173 (dev) must be allowed."""
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code in {200, 204}


def test_cors_blocks_arbitrary_origin(client):
    """Arbitrary origin must not appear in CORS allowed-origins header."""
    resp = client.get("/api/health", headers={"Origin": "https://evil.example.com"})
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao != "*", "CORS wildcard must not be present"
    assert "evil.example.com" not in acao, f"Unexpected CORS allow for evil.example.com: {acao}"
