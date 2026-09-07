"""Admission control on POST /api/process (in-memory SQLite, no network).

Background: the code is public, so a crawler read the limiter and drove
~250 new papers/day through it — spoofing X-Forwarded-For to mint a fresh
per-IP bucket per request and pacing under the global cap. These tests pin
the layers that make that impossible regardless of what the client sends.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

import api.routes as routes_module
import api.throttle as throttle
import api.turnstile as turnstile
from api.routes import router
from db.connection import get_db
from db.models import Base


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    # Never run the real pipeline from a test.
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(routes_module, "process_paper_job", _noop)
    monkeypatch.delenv("USE_TEMPORAL", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    for lim in (throttle.per_ip_limiter, throttle.per_ip_daily_limiter, throttle.global_limiter):
        lim.reset()
    monkeypatch.setattr(throttle.per_ip_limiter, "max_events", 100)
    monkeypatch.setattr(throttle.per_ip_daily_limiter, "max_events", 100)
    monkeypatch.setattr(throttle.global_limiter, "max_events", 100)
    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "0")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _submit(client, arxiv_id, **headers):
    return client.post("/api/process", json={"arxiv_id": arxiv_id}, headers=headers)


# --- client_ip: the spoofable-header hole -----------------------------------

def _request_with_xff(value: str | None, peer="10.0.0.1") -> Request:
    headers = [(b"x-forwarded-for", value.encode())] if value is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


class TestClientIp:
    def test_uses_rightmost_forwarded_hop(self):
        # Ingress appends the true peer LAST; everything before it is attacker-controlled.
        assert throttle.client_ip(_request_with_xff("1.1.1.1, 2.2.2.2, 203.0.113.9")) == "203.0.113.9"

    def test_spoofed_prefix_does_not_change_identity(self):
        real = throttle.client_ip(_request_with_xff("203.0.113.9"))
        spoofed = throttle.client_ip(_request_with_xff("9.9.9.9, 203.0.113.9"))
        assert real == spoofed == "203.0.113.9"

    def test_falls_back_to_peer_without_header(self):
        assert throttle.client_ip(_request_with_xff(None, peer="10.1.2.3")) == "10.1.2.3"

    def test_fingerprint_is_short_and_non_reversible(self):
        tag = throttle.ip_fingerprint("203.0.113.9")
        assert len(tag) == 12 and "203" not in tag


# --- per-IP limits survive header games -------------------------------------

async def test_spoofed_forwarded_header_cannot_mint_new_buckets(client, monkeypatch):
    monkeypatch.setattr(throttle.per_ip_limiter, "max_events", 1)
    # Same real peer (rightmost), different fake prefixes each time.
    r1 = await _submit(client, "1706.03762", **{"X-Forwarded-For": "1.1.1.1, 203.0.113.9"})
    r2 = await _submit(client, "1810.04805", **{"X-Forwarded-For": "8.8.8.8, 203.0.113.9"})
    assert r1.status_code == 200
    assert r2.status_code == 429


async def test_per_ip_daily_quota(client, monkeypatch):
    monkeypatch.setattr(throttle.per_ip_daily_limiter, "max_events", 2)
    ids = ["1706.03762", "1810.04805", "1512.03385"]
    codes = [(await _submit(client, i)).status_code for i in ids]
    assert codes == [200, 200, 429]


# --- durable daily cap (the spend ceiling) ----------------------------------

async def test_daily_cap_is_enforced_from_the_jobs_table(client, monkeypatch):
    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "2")
    ids = ["1706.03762", "1810.04805", "1512.03385"]
    responses = [await _submit(client, i) for i in ids]
    assert [r.status_code for r in responses] == [200, 200, 429]
    assert "Retry-After" in responses[2].headers
    assert "tomorrow" in responses[2].json()["detail"]


async def test_daily_cap_does_not_block_dedupe_of_in_flight_paper(client, monkeypatch):
    # A resubmission of a paper already in flight is free and must stay so
    # even when the cap is exhausted (it starts no new work).
    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "1")
    first = await _submit(client, "1706.03762")
    assert first.status_code == 200
    again = await _submit(client, "1706.03762")
    assert again.status_code == 200
    assert again.json()["job_id"] == first.json()["job_id"]


async def test_daily_cap_zero_disables(client, monkeypatch):
    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "0")
    for i in ["1706.03762", "1810.04805", "1512.03385"]:
        assert (await _submit(client, i)).status_code == 200


# --- Turnstile: server-side, fail-closed ------------------------------------

async def test_turnstile_skipped_when_unconfigured(client):
    assert (await _submit(client, "1706.03762")).status_code == 200


async def test_turnstile_rejects_missing_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")
    resp = await _submit(client, "1706.03762")
    assert resp.status_code == 403


async def test_turnstile_accepts_verified_token(client, monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")

    async def fake_verify(token, remote_ip=None):
        return token == "good-token"

    monkeypatch.setattr(routes_module, "verify_turnstile", fake_verify)
    ok = await client.post("/api/process", json={"arxiv_id": "1706.03762", "turnstile_token": "good-token"})
    bad = await client.post("/api/process", json={"arxiv_id": "1810.04805", "turnstile_token": "forged"})
    assert ok.status_code == 200
    assert bad.status_code == 403


async def test_turnstile_verification_outage_fails_closed(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")

    class BoomClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise RuntimeError("cloudflare down")

    monkeypatch.setattr(turnstile.httpx, "AsyncClient", BoomClient)
    assert await turnstile.verify_turnstile("some-token", "203.0.113.9") is False


@pytest.mark.parametrize("token", [None, ""])
async def test_turnstile_empty_token_rejected_when_configured(monkeypatch, token):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")
    assert await turnstile.verify_turnstile(token, "203.0.113.9") is False
