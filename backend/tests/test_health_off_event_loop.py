"""GET /api/health keeps its blocking probes off the event loop.

``manim --version`` (~1.5 CPU-s, ~175 MiB) and the boto3 R2 check used to run
synchronously inside the async handler, stalling every request on the API's
single event loop — and the API is being cut from 2 vCPU to 0.5. These tests
pin that both run in a worker thread, that only one manim probe runs at a time,
and that a success is reused instead of re-spawning the interpreter.
"""

import asyncio
import subprocess
import threading
import time

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import api.routes as routes_module
import rendering
import rendering.storage as storage
from api.routes import router
from db.connection import get_db
from db.models import Base


class FakeManim:
    """Stands in for subprocess.run: records the calling thread and how many
    probes overlap; ``fail_first`` makes the first call FileNotFoundError."""

    def __init__(self, *, delay: float = 0.0, fail_first: bool = False):
        self.delay = delay
        self.fail_first = fail_first
        self.threads: list[int] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def __call__(self, args, **kwargs):
        with self._lock:
            self.threads.append(threading.get_ident())
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            first = len(self.threads) == 1
        try:
            time.sleep(self.delay)
            if self.fail_first and first:
                raise FileNotFoundError(args[0])
            return subprocess.CompletedProcess(args, 0, stdout="Manim Community v0.19.2\n", stderr="")
        finally:
            with self._lock:
                self.in_flight -= 1


class FakeR2:
    def __init__(self):
        self.threads: list[int] = []

    def check_connectivity(self) -> bool:
        self.threads.append(threading.get_ident())
        return True


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with maker() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(routes_module, "_manim_available", None)
    monkeypatch.setattr(routes_module, "_manim_probe_lock", asyncio.Lock())
    # Offline and deterministic whatever a developer's .env says (it may set
    # STORAGE_MODE=r2, which would reach the real bucket).
    monkeypatch.setattr(storage, "STORAGE_MODE", "local")
    monkeypatch.setattr(rendering, "RENDER_MODE", "local")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_manim_and_r2_probes_run_off_the_event_loop(client, monkeypatch):
    manim = FakeManim()
    r2 = FakeR2()
    monkeypatch.setattr(subprocess, "run", manim)
    monkeypatch.setattr(storage, "STORAGE_MODE", "r2")
    monkeypatch.setattr(storage, "get_backend", lambda: r2)
    loop_thread = threading.get_ident()

    resp = await client.get("/api/health")

    assert resp.status_code == 200
    services = resp.json()["services"]
    assert "available (Manim Community v0.19.2)" in services["manim"]
    assert services["storage"] == "r2: connected"
    assert manim.threads and loop_thread not in manim.threads
    assert r2.threads and loop_thread not in r2.threads


async def test_the_loop_keeps_serving_while_manim_is_probed(client, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeManim(delay=0.3))
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        assert (await client.get("/api/health")).status_code == 200
    finally:
        task.cancel()
    # A blocking probe would allow ~0 ticks during the 0.3 s it sleeps.
    assert ticks >= 10


async def test_concurrent_calls_share_one_probe_and_a_success_is_kept(client, monkeypatch):
    manim = FakeManim(delay=0.05)
    monkeypatch.setattr(subprocess, "run", manim)

    responses = await asyncio.gather(*(client.get("/api/health") for _ in range(5)))
    assert all(r.json()["status"] == "healthy" for r in responses)
    assert manim.max_in_flight == 1 and len(manim.threads) == 1

    # Later calls reuse the success: no new interpreter per health check.
    await client.get("/api/health")
    assert len(manim.threads) == 1


async def test_a_failed_probe_is_retried_not_cached(client, monkeypatch):
    manim = FakeManim(fail_first=True)
    monkeypatch.setattr(subprocess, "run", manim)

    first = await client.get("/api/health")
    assert first.json()["services"]["manim"] == "not installed"
    assert first.json()["status"] == "degraded"

    second = await client.get("/api/health")
    assert "available" in second.json()["services"]["manim"]
    assert len(manim.threads) == 2
