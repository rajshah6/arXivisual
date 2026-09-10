"""PostHog product events (backend/analytics.py) — hermetic.

The module must be a strict no-op without POSTHOG_API_KEY (local dev, CI),
must forward to the posthog client when a key is present, and must never raise
into a job. The client is always faked here: no network, no consumer thread.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import analytics
import api.routes as routes_module
import api.throttle as throttle
from api.routes import router
from db.connection import get_db
from db.models import Base


class FakePosthog:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.events: list[tuple[str, dict]] = []
        self.shutdown_calls = 0

    def capture(self, event, **kw):
        self.events.append((event, kw))

    def shutdown(self):
        self.shutdown_calls += 1


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch):
    """No singleton leaks between tests; no key unless a test sets one."""
    monkeypatch.setattr(analytics, "_client", None)
    monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
    monkeypatch.delenv("POSTHOG_HOST", raising=False)
    yield
    analytics._client = None


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setenv("POSTHOG_API_KEY", "phc_test")
    fake = FakePosthog()
    monkeypatch.setattr(analytics, "_client", fake)
    return fake


# --- off by default -----------------------------------------------------------

class TestDisabled:
    def test_enabled_false_without_key(self):
        assert analytics.enabled() is False

    def test_capture_is_a_noop_without_key(self, monkeypatch):
        def _boom():
            raise AssertionError("client must not be built when analytics is off")
        monkeypatch.setattr(analytics, "_get_client", _boom)
        analytics.capture("paper_accepted", "abc", {"arxiv_id": "1706.03762"})
        analytics.job_outcome(
            job_id="j", arxiv_id="1706.03762", status="completed",
            videos_complete=1, videos_total=1, created_at=None,
        )

    def test_shutdown_without_client_is_safe(self):
        analytics.shutdown()
        analytics.shutdown()


# --- forwarding ---------------------------------------------------------------

class TestCapture:
    def test_forwards_event_to_client(self, fake_client):
        assert analytics.enabled() is True
        analytics.capture("paper_accepted", "fp123", {"arxiv_id": "1706.03762", "path": "legacy"})
        assert fake_client.events == [
            ("paper_accepted", {"distinct_id": "fp123",
                                "properties": {"arxiv_id": "1706.03762", "path": "legacy"}}),
        ]

    def test_properties_default_to_empty_dict(self, fake_client):
        analytics.capture("paper_accepted", "fp123")
        assert fake_client.events[0][1]["properties"] == {}

    def test_client_errors_never_propagate(self, monkeypatch):
        monkeypatch.setenv("POSTHOG_API_KEY", "phc_test")

        class Broken:
            def capture(self, *a, **k):
                raise RuntimeError("queue full")
        monkeypatch.setattr(analytics, "_client", Broken())
        analytics.capture("paper_accepted", "fp123", {})

    def test_client_is_built_from_env(self, monkeypatch):
        monkeypatch.setenv("POSTHOG_API_KEY", "phc_test")
        monkeypatch.setenv("POSTHOG_HOST", "https://eu.i.posthog.com/")
        import posthog
        monkeypatch.setattr(posthog, "Posthog", FakePosthog)
        client = analytics._get_client()
        assert isinstance(client, FakePosthog)
        assert client.kwargs["project_api_key"] == "phc_test"
        assert client.kwargs["host"] == "https://eu.i.posthog.com"
        assert client.kwargs["enable_exception_autocapture"] is False
        assert analytics._get_client() is client  # singleton

    def test_default_host(self):
        assert analytics.host() == "https://us.i.posthog.com"

    def test_shutdown_flushes_and_releases(self, fake_client):
        analytics.shutdown()
        assert fake_client.shutdown_calls == 1
        assert analytics._client is None


# --- job outcomes -------------------------------------------------------------

class TestJobOutcome:
    def test_completed(self, fake_client):
        created = datetime.utcnow() - timedelta(seconds=90)  # naive UTC, like the DB
        analytics.job_outcome(
            job_id="job-1", arxiv_id="1706.03762", status="completed",
            videos_complete=3, videos_total=5, created_at=created, error=None,
        )
        event, kw = fake_client.events[0]
        assert event == "paper_completed"
        assert kw["distinct_id"] == "job-1"  # no client identity at finalize time
        props = kw["properties"]
        assert props["arxiv_id"] == "1706.03762"
        assert props["job_id"] == "job-1"
        assert props["videos_complete"] == 3 and props["videos_total"] == 5
        assert 89 <= props["duration_s"] <= 95
        assert "error" not in props

    def test_failed_carries_reason(self, fake_client):
        analytics.job_outcome(
            job_id="job-2", arxiv_id="1706.03762", status="failed",
            videos_complete=0, videos_total=4, created_at=None,
            error="  All 4 visualization(s) failed to render. ",
        )
        event, kw = fake_client.events[0]
        assert event == "paper_failed_server"
        assert kw["properties"]["error"] == "All 4 visualization(s) failed to render."
        assert kw["properties"]["duration_s"] is None

    def test_error_is_bounded(self, fake_client):
        analytics.job_outcome(
            job_id="j", arxiv_id="x", status="failed",
            videos_complete=None, videos_total=None, created_at=None, error="e" * 2000,
        )
        assert len(fake_client.events[0][1]["properties"]["error"]) == 500

    def test_duration_never_negative(self):
        assert analytics.duration_seconds(datetime.utcnow() + timedelta(hours=1)) == 0.0
        assert analytics.duration_seconds(None) is None


# --- wiring: POST /api/process emits paper_accepted ---------------------------

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

    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(routes_module, "process_paper_job", _noop)
    monkeypatch.delenv("USE_TEMPORAL", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    for lim in (throttle.per_ip_limiter, throttle.per_ip_daily_limiter):
        lim.reset()
    monkeypatch.setenv("RATE_LIMIT_PROCESS_GLOBAL", "100")
    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "0")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_process_emits_paper_accepted_with_fingerprint(client, fake_client, monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "k")
    resp = await client.post("/api/process", json={"arxiv_id": "2101.00001"},
                             headers={"x-forwarded-for": "203.0.113.9"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert fake_client.events == [
        ("paper_accepted", {
            "distinct_id": throttle.ip_fingerprint("203.0.113.9"),
            "properties": {"arxiv_id": "2101.00001", "job_id": job_id, "path": "legacy"},
        }),
    ]


async def test_duplicate_submission_does_not_emit(client, fake_client):
    first = await client.post("/api/process", json={"arxiv_id": "2101.00002"})
    assert first.status_code == 200
    again = await client.post("/api/process", json={"arxiv_id": "2101.00002"})
    assert again.status_code == 200
    assert again.json()["job_id"] == first.json()["job_id"]
    assert len(fake_client.events) == 1
