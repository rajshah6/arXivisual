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

    def test_fingerprint_is_keyed(self, monkeypatch):
        # HMAC under a server secret: same input, different key -> different tag,
        # so logs can't be reversed offline by hashing the IPv4 space.
        monkeypatch.setenv("IP_HASH_SECRET", "key-a")
        a = throttle.ip_fingerprint("203.0.113.9")
        monkeypatch.setenv("IP_HASH_SECRET", "key-b")
        b = throttle.ip_fingerprint("203.0.113.9")
        assert len(a) == 12 and a != b
        monkeypatch.setenv("IP_HASH_SECRET", "key-a")
        assert throttle.ip_fingerprint("203.0.113.9") == a


# --- per-IP limits survive header games -------------------------------------

async def test_spoofed_forwarded_header_cannot_mint_new_buckets(client, monkeypatch):
    monkeypatch.setattr(throttle.per_ip_limiter, "max_events", 1)
    # Same real peer (rightmost), different fake prefixes each time.
    r1 = await _submit(client, "1706.03762", **{"X-Forwarded-For": "1.1.1.1, 203.0.113.9"})
    r2 = await _submit(client, "1810.04805", **{"X-Forwarded-For": "8.8.8.8, 203.0.113.9"})
    assert r1.status_code == 200
    assert r2.status_code == 429


async def test_global_denial_does_not_consume_per_ip_budget(client, monkeypatch):
    # Reviewer-reproduced lockout: chained record-and-check let three "at
    # capacity" answers exhaust a real user's 3/day quota with zero papers started.
    monkeypatch.setattr(throttle.global_limiter, "max_events", 1)
    monkeypatch.setattr(throttle.per_ip_daily_limiter, "max_events", 3)
    xff = {"X-Forwarded-For": "203.0.113.77"}
    assert (await _submit(client, "1706.03762", **xff)).status_code == 200
    for paper in ("1810.04805", "1512.03385", "2010.11929"):
        hit = await _submit(client, paper, **xff)
        assert hit.status_code == 429 and "capacity" in hit.json()["detail"]
    # Three global denials must not have touched this client's daily budget.
    assert len(throttle.per_ip_daily_limiter._events["203.0.113.77"]) == 1
    throttle.global_limiter.reset()
    assert (await _submit(client, "1810.04805", **xff)).status_code == 200


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


async def test_daily_cap_counts_only_today_utc(client, db, monkeypatch):
    # A job created one second before UTC midnight belongs to yesterday.
    from datetime import datetime, timedelta

    from db.models import ProcessingJob

    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "1")
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    db.add(ProcessingJob(id="job_yesterday", status="completed", progress=1.0,
                         created_at=day_start - timedelta(seconds=1)))
    await db.commit()
    assert (await _submit(client, "1706.03762")).status_code == 200


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

    async def fake_verify(token, remote_ip=None, *, expected_cdata=None):
        assert expected_cdata in ("1706_03762", "1810_04805")  # token bound to the paper
        return turnstile.TurnstileVerdict(token == "good-token", None, 12.0)

    monkeypatch.setattr(routes_module, "verify_turnstile_detailed", fake_verify)
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


async def test_turnstile_rejects_token_for_foreign_hostname(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")

    class Resp:
        def json(self): return {"success": True, "hostname": "evil.example"}

    class OkClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return Resp()

    monkeypatch.setattr(turnstile.httpx, "AsyncClient", OkClient)
    assert await turnstile.verify_turnstile("tok", "203.0.113.9") is False
    monkeypatch.setenv("TURNSTILE_ALLOWED_HOSTNAMES", "evil.example")
    assert await turnstile.verify_turnstile("tok", "203.0.113.9") is True


@pytest.mark.parametrize("token", [None, ""])
async def test_turnstile_empty_token_rejected_when_configured(monkeypatch, token):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")
    assert await turnstile.verify_turnstile(token, "203.0.113.9") is False


# --- id validation is enforced before any budget is spent ------------------

async def test_non_arxiv_id_is_rejected_before_creating_a_job(client, db, monkeypatch):
    from sqlalchemy import func, select

    from db.models import ProcessingJob

    resp = await client.post("/api/process", json={"arxiv_id": "10.64898/2026.06.29.26356713v1.full.pdf"})
    assert resp.status_code == 422
    assert (await db.execute(select(func.count()).select_from(ProcessingJob))).scalar_one() == 0


async def test_versioned_id_is_normalized_on_the_job(client, db):
    resp = await client.post("/api/process", json={"arxiv_id": "0805.3898v2"})
    assert resp.status_code == 200
    assert resp.json()["arxiv_id"] == "0805.3898"



def test_request_context_is_compact_and_never_the_ip():
    from starlette.requests import Request

    from api.throttle import request_context

    scope = {
        "type": "http", "method": "POST", "path": "/api/process", "query_string": b"",
        "client": ("203.0.113.9", 1234),
        "headers": [
            (b"user-agent", b'Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/128 "quoted"'),
            (b"accept-language", b"en-US,en;q=0.9"),
            (b"referer", b"https://www.arxivisual.org/abs/2301.00001"),
            (b"origin", b"https://www.arxivisual.org"),
            (b"x-forwarded-for", b"203.0.113.9"),
        ],
    }
    ctx = request_context(Request(scope))
    assert ctx.startswith('ua="Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/128 \'quoted\'"')
    assert 'lang="en-US,en;q=0.9"' in ctx and "ref=www.arxivisual.org" in ctx
    assert "origin=https://www.arxivisual.org" in ctx and "203.0.113.9" not in ctx



# --- token binding: one solved challenge starts one paper --------------------

def test_cdata_encoding_is_deterministic_and_in_alphabet():
    assert turnstile.turnstile_cdata("1706.03762") == "1706_03762"
    assert turnstile.turnstile_cdata("math.GT/0309136") == "math_GT-0309136"
    assert turnstile.turnstile_cdata("adap-org/9707006") == "adap-org-9707006"
    assert turnstile.turnstile_cdata("1706.03762v2") == "1706_03762v2"


def _client_returning(body):
    class Resp:
        def json(self): return body

    class Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return Resp()
    return Client


async def test_token_bound_to_action_and_paper(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")
    from datetime import UTC, datetime, timedelta

    minted = (datetime.now(UTC) - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    good = {"success": True, "hostname": "arxivisual.org", "action": "start-paper",
            "cdata": "1706_03762v2", "challenge_ts": minted}
    monkeypatch.setattr(turnstile.httpx, "AsyncClient", _client_returning(good))
    v = await turnstile.verify_turnstile_detailed("tok", "203.0.113.9", expected_cdata="1706_03762")
    assert v.ok and 25 <= v.token_age_s <= 40  # version suffix ignored, age from challenge_ts

    monkeypatch.setattr(turnstile.httpx, "AsyncClient", _client_returning({**good, "cdata": "1810_04805"}))
    v = await turnstile.verify_turnstile_detailed("tok", "203.0.113.9", expected_cdata="1706_03762")
    assert not v.ok and v.reason.startswith("cdata")

    monkeypatch.setattr(turnstile.httpx, "AsyncClient", _client_returning({**good, "action": "login"}))
    v = await turnstile.verify_turnstile_detailed("tok", "203.0.113.9", expected_cdata="1706_03762")
    assert not v.ok and v.reason.startswith("action")

    # Binding is only enforced when the caller asks for it (older callers/tests).
    monkeypatch.setattr(turnstile.httpx, "AsyncClient", _client_returning({"success": True, "hostname": "arxivisual.org"}))
    assert await turnstile.verify_turnstile("tok", "203.0.113.9") is True
