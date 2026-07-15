"""
Per-society rate limiting on the endpoints that spend Claude calls.

Tests exercise the bucket directly plus the HTTP surface. The HTTP case is made
cheap by pointing the limit at a tiny capacity and asserting the 429 arrives
before any agent runs (the limiter is a dependency, so it short-circuits first —
no Claude call, no DB write).

    python -m pytest backend/tests/test_ratelimit.py -v
"""

import pytest
from fastapi.testclient import TestClient

from backend import ratelimit
from backend.main import app
from backend.ratelimit import TokenBucket
from backend.security import create_access_token

client = TestClient(app)

SOC_A = "00000000-0000-0000-0000-0000000000a1"
SOC_B = "00000000-0000-0000-0000-0000000000b2"


@pytest.fixture(autouse=True)
def _clean_buckets():
    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


def _hdr(society, role="guard"):
    token = create_access_token(
        user_id="00000000-0000-0000-0000-000000000000", society_id=society, role=role)
    return {"Authorization": f"Bearer {token}"}


# --- the bucket itself -----------------------------------------------------

def test_bucket_allows_burst_then_blocks():
    b = TokenBucket(capacity=3, window_seconds=60)
    assert [b.take("s")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = b.take("s")
    assert allowed is False
    assert retry_after >= 1  # tells the caller when to come back


def test_bucket_is_keyed_per_society():
    b = TokenBucket(capacity=1, window_seconds=60)
    assert b.take(SOC_A)[0] is True
    assert b.take(SOC_A)[0] is False   # A is exhausted...
    assert b.take(SOC_B)[0] is True    # ...but B is unaffected


def test_bucket_refills_over_time(monkeypatch):
    b = TokenBucket(capacity=60, window_seconds=60)  # 1 token/second
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])

    for _ in range(60):
        assert b.take("s")[0] is True
    assert b.take("s")[0] is False     # drained

    now[0] += 2.0                      # two seconds -> ~2 tokens back
    assert b.take("s")[0] is True
    assert b.take("s")[0] is True
    assert b.take("s")[0] is False


def test_bucket_never_exceeds_capacity(monkeypatch):
    b = TokenBucket(capacity=5, window_seconds=5)
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    b.take("s")
    now[0] += 10_000                   # idle a long time
    assert [b.take("s")[0] for _ in range(5)] == [True] * 5
    assert b.take("s")[0] is False     # capped at capacity, no infinite credit


# --- the HTTP surface ------------------------------------------------------

def test_sessions_endpoint_429s_with_uniform_error_and_retry_after(monkeypatch):
    """The 2nd entry is refused before the pipeline runs; another society is unaffected."""
    from backend import main as mn

    # Stub the pipeline: this test is about the limiter, and a real call would
    # hit Claude and the DB. The limiter is a dependency, so an allowed request
    # still proves it ran and passed.
    monkeypatch.setattr(mn, "handle_visitor_entry", lambda *a, **k: object())
    monkeypatch.setattr(mn, "serialize", lambda row: {"session_id": "stub", "flat_number": "A-101"})

    # Shrink the live bucket the dependency already closed over.
    bucket = ratelimit._session_bucket
    monkeypatch.setattr(bucket, "capacity", 1.0)
    monkeypatch.setattr(bucket, "refill_per_second", 1.0 / 60)
    bucket.reset()

    body = {"visitor_name": "Rajesh", "flat_number": "A-101",
            "purpose": "guest", "purpose_detail": "Visit"}

    r1 = client.post("/sessions", headers=_hdr(SOC_A), json=body)
    assert r1.status_code == 201, r1.text          # first one is allowed

    r2 = client.post("/sessions", headers=_hdr(SOC_A), json=body)
    assert r2.status_code == 429, r2.text          # second is refused
    assert r2.headers.get("Retry-After")           # tells the client when to retry
    assert r2.json()["error"]["code"] == "rate_limited"  # uniform error shape

    # One society exhausting its budget must not starve another.
    r3 = client.post("/sessions", headers=_hdr(SOC_B), json=body)
    assert r3.status_code == 201, r3.text


def test_rate_limit_requires_auth_first():
    # Unauthenticated callers get 401, not a rate-limit key of "anonymous".
    r = client.post("/sessions", json={})
    assert r.status_code == 401
