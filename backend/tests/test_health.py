"""GET /api/health: commit + dialect, no blocking work on the event loop, no leaks.

The old handler ran ``manim --version`` with a blocking subprocess.run inside
an ``async def`` on EVERY request (1-2 s of frozen event loop each time the
deploy poller or an uptime monitor asked), called boto3 synchronously, and
echoed raw exception text — connection errors name hosts and users — to any
caller.
"""

import subprocess
import threading

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import health
from api.routes import router
from db.connection import get_db


class _CountingManim:
    """Stand-in for subprocess.run that records how and where it was called."""

    def __init__(self, returncode=0, stdout="Manim Community v0.19.2\n", stderr="", raises=None):
        self.calls = 0
        self.threads = []
        self.returncode, self.stdout, self.stderr, self.raises = returncode, stdout, stderr, raises

    def __call__(self, cmd, **kwargs):
        self.calls += 1
        self.threads.append(threading.current_thread())
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr=self.stderr)


@pytest.fixture(autouse=True)
def _fresh_health_state(monkeypatch):
    health.reset_cache()
    monkeypatch.delenv("APP_COMMIT_SHA", raising=False)
    yield
    health.reset_cache()


@pytest.fixture()
def manim(monkeypatch):
    fake = _CountingManim()
    monkeypatch.setattr(health.subprocess, "run", fake)
    return fake


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _client(session) -> AsyncClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestPayload:
    async def test_commit_comes_from_app_commit_sha_at_the_top_level(self, db, manim, monkeypatch):
        # The deploy workflow polls for `.commit == <sha>`: exact key, top level.
        monkeypatch.setenv("APP_COMMIT_SHA", "21baa13deadbeef")
        async with _client(db) as client:
            body = (await client.get("/api/health")).json()
        assert body["commit"] == "21baa13deadbeef"

    async def test_commit_defaults_to_unknown(self, db, manim):
        async with _client(db) as client:
            assert (await client.get("/api/health")).json()["commit"] == "unknown"

    async def test_reports_the_database_dialect(self, db, manim):
        async with _client(db) as client:
            assert (await client.get("/api/health")).json()["database_dialect"] == "sqlite"

    async def test_existing_fields_are_unchanged(self, db, manim):
        # frontend/lib/api.ts and docs/DEPLOY.md consume these: only ADD fields.
        async with _client(db) as client:
            body = (await client.get("/api/health")).json()
        assert body["status"] == "healthy"
        assert body["version"] == "0.1.0"
        assert body["services"] == {
            "database": "connected",
            "manim": "available (Manim Community v0.19.2)",
            "storage": "local",
            "redis": "not configured",
            "modal": "not configured",
        }


class TestNoBlockingWorkPerRequest:
    async def test_manim_version_is_resolved_once_and_off_the_event_loop(self, db, manim):
        async with _client(db) as client:
            for _ in range(4):
                assert (await client.get("/api/health")).status_code == 200
        assert manim.calls == 1
        assert manim.threads[0] is not threading.main_thread()

    async def test_a_failed_manim_probe_is_retried_after_the_ttl_not_cached_forever(self, db, monkeypatch):
        # A probe that timed out under CPU load must not pin "degraded" until restart.
        failing = _CountingManim(raises=subprocess.TimeoutExpired(cmd="manim", timeout=5))
        monkeypatch.setattr(health.subprocess, "run", failing)
        async with _client(db) as client:
            first = (await client.get("/api/health")).json()
            assert first["services"]["manim"] == "error" and first["status"] == "degraded"
            await client.get("/api/health")
            assert failing.calls == 1  # inside the TTL: cached

            health.expire_cache()
            monkeypatch.setattr(health.subprocess, "run", _CountingManim())
            assert (await client.get("/api/health")).json()["status"] == "healthy"

    async def test_database_check_is_cached_for_the_ttl(self, manim):
        class _Session:
            executed = 0

            def get_bind(self):
                raise RuntimeError("no bind on a fake")

            async def execute(self, _stmt):
                _Session.executed += 1

        async with _client(_Session()) as client:
            for _ in range(3):
                assert (await client.get("/api/health")).json()["services"]["database"] == "connected"
            assert _Session.executed == 1

            health.expire_cache()
            await client.get("/api/health")
            assert _Session.executed == 2

    async def test_r2_check_runs_in_a_worker_thread_and_is_cached(self, db, manim, monkeypatch):
        import rendering.storage as storage

        class _R2:
            calls = 0
            threads = []

            def check_connectivity(self):
                _R2.calls += 1
                _R2.threads.append(threading.current_thread())
                return True

        monkeypatch.setattr(storage, "STORAGE_MODE", "r2")
        monkeypatch.setattr(storage, "get_backend", _R2)
        async with _client(db) as client:
            for _ in range(3):
                assert (await client.get("/api/health")).json()["services"]["storage"] == "r2: connected"
        assert _R2.calls == 1
        assert _R2.threads[0] is not threading.main_thread()


class TestNoLeaks:
    async def test_database_errors_are_generic_to_the_caller_and_detailed_in_the_log(self, manim, caplog):
        class _Broken:
            def get_bind(self):
                raise RuntimeError("no bind")

            async def execute(self, _stmt):
                raise ConnectionError("could not connect to db.internal:5432 as user dbadmin_example password=hunter2")

        with caplog.at_level("WARNING"):
            async with _client(_Broken()) as client:
                response = await client.get("/api/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["services"]["database"] == "error"
        assert body["database_dialect"] == "unknown"
        for secret in ("hunter2", "db.internal", "dbadmin_example"):
            assert secret not in response.text
        assert "db.internal" in caplog.text  # operators still get the detail

    async def test_manim_and_storage_errors_are_generic_too(self, db, monkeypatch):
        import rendering.storage as storage

        class _R2:
            def check_connectivity(self):
                raise RuntimeError("AccessDenied for key AKIAEXAMPLE at https://acct.r2.cloudflarestorage.com")

        monkeypatch.setattr(storage, "STORAGE_MODE", "r2")
        monkeypatch.setattr(storage, "get_backend", _R2)
        monkeypatch.setattr(health.subprocess, "run", _CountingManim(
            returncode=1, stdout="", stderr="Traceback ...\nOSError: /app/.venv/secret/path missing"))
        async with _client(db) as client:
            response = await client.get("/api/health")

        services = response.json()["services"]
        assert services["manim"] == "error"
        assert services["storage"] == "r2: error"
        assert "AKIAEXAMPLE" not in response.text and "/app/.venv" not in response.text

    async def test_missing_manim_is_reported_as_not_installed(self, db, monkeypatch):
        monkeypatch.setattr(health.subprocess, "run", _CountingManim(raises=FileNotFoundError("manim")))
        async with _client(db) as client:
            body = (await client.get("/api/health")).json()
        assert body["services"]["manim"] == "not installed"
        assert body["status"] == "degraded"
