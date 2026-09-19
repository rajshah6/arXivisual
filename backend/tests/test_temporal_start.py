"""API -> Temporal start: reconnect once before falling back (fake client, no server).

36 jobs in 10 days silently ran on the in-process pipeline because the API's
CACHED Temporal client kept raising "tcp connect error" from start_workflow —
the cache never dropped the dead client, so every later submission failed the
same way until the API restarted. The start now resets the cache, reconnects
and retries ONCE; the fail-open fallback stays, behind one loud log line an
alert can key on.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

import api.routes as routes_module
import api.temporal_client as temporal_client
import api.throttle as throttle
from api.routes import router
from db.connection import get_db
from db.models import Base

ALERT_PHRASE = "Temporal unavailable"


def _tcp_connect_error() -> RPCError:
    return RPCError("tcp connect error", RPCStatusCode.UNAVAILABLE, b"")


class _FakeTemporal:
    """One connected client; ``outcomes`` are raised/returned per start call."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.started = []

    async def start_workflow(self, _run, params, *, id, task_queue):
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome
        self.started.append((id, params.job_id, task_queue))


class _Connector:
    """Stand-in for temporalio's Client.connect: hands out clients in order."""

    def __init__(self, *clients):
        self.clients = list(clients)
        self.calls = 0

    async def __call__(self, *_args, **_kwargs):
        self.calls += 1
        nxt = self.clients.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


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
async def harness(db, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db

    legacy_runs = []

    async def _legacy(job_id, arxiv_id):
        legacy_runs.append(arxiv_id)

    monkeypatch.setattr(routes_module, "process_paper_job", _legacy)
    monkeypatch.setenv("USE_TEMPORAL", "1")
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    for lim in (throttle.per_ip_limiter, throttle.per_ip_daily_limiter):
        lim.reset()
    monkeypatch.setenv("RATE_LIMIT_PROCESS_GLOBAL", "100")
    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "0")
    temporal_client.reset_temporal_client()

    def connect_with(*clients) -> _Connector:
        connector = _Connector(*clients)
        monkeypatch.setattr(temporal_client.Client, "connect", connector)
        return connector

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, connect_with, legacy_runs
    temporal_client.reset_temporal_client()


def _alert_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if ALERT_PHRASE in r.getMessage()]


async def test_healthy_start_uses_the_cached_client(harness, caplog):
    client, connect_with, legacy_runs = harness
    temporal = _FakeTemporal()
    connector = connect_with(temporal)

    for arxiv_id in ("2401.00001", "2401.00002"):
        assert (await client.post("/api/process", json={"arxiv_id": arxiv_id})).status_code == 200

    assert connector.calls == 1  # connected once, reused
    assert [s[0] for s in temporal.started] == ["paper-2401.00001", "paper-2401.00002"]
    assert legacy_runs == [] and _alert_lines(caplog) == []


async def test_dead_cached_client_is_replaced_and_the_start_retried_once(harness, caplog):
    client, connect_with, legacy_runs = harness
    dead, fresh = _FakeTemporal(_tcp_connect_error()), _FakeTemporal()
    connector = connect_with(dead, fresh)

    response = await client.post("/api/process", json={"arxiv_id": "2401.00003"})

    assert response.status_code == 200
    assert connector.calls == 2  # reset + reconnect
    assert [s[0] for s in fresh.started] == ["paper-2401.00003"]
    assert legacy_runs == []  # ran durably, not in-process
    assert _alert_lines(caplog) == []  # a recovered start is not an outage

    # The fresh client is the cached one now.
    await client.post("/api/process", json={"arxiv_id": "2401.00004"})
    assert connector.calls == 2 and len(fresh.started) == 2


async def test_connect_failure_is_retried_once_too(harness):
    client, connect_with, legacy_runs = harness
    fresh = _FakeTemporal()
    connector = connect_with(RuntimeError("Failed client connect: tcp connect error"), fresh)

    assert (await client.post("/api/process", json={"arxiv_id": "2401.00005"})).status_code == 200
    assert connector.calls == 2 and len(fresh.started) == 1 and legacy_runs == []


async def test_two_failures_fall_back_with_one_greppable_line(harness, caplog):
    client, connect_with, legacy_runs = harness
    connector = connect_with(_FakeTemporal(_tcp_connect_error()), _FakeTemporal(_tcp_connect_error()))

    with caplog.at_level("INFO"):
        response = await client.post("/api/process", json={"arxiv_id": "2401.00006"})

    assert response.status_code == 200  # fail-open: the paper still gets processed
    assert legacy_runs == ["2401.00006"]
    assert connector.calls == 2  # exactly one retry, not a loop
    lines = _alert_lines(caplog)
    assert len(lines) == 1, lines
    assert "\n" not in lines[0]  # a single line: log pipelines split on newlines
    assert "2401.00006" in lines[0] and "tcp connect error" in lines[0]
    [record] = [r for r in caplog.records if ALERT_PHRASE in r.getMessage()]
    assert record.levelname == "ERROR" and record.exc_info is None


async def test_a_failed_client_is_never_left_in_the_cache(harness):
    client, connect_with, legacy_runs = harness
    recovered = _FakeTemporal()
    connector = connect_with(
        _FakeTemporal(_tcp_connect_error()), _FakeTemporal(_tcp_connect_error()), recovered,
    )

    await client.post("/api/process", json={"arxiv_id": "2401.00007"})  # falls back
    await client.post("/api/process", json={"arxiv_id": "2401.00008"})  # next request reconnects

    assert connector.calls == 3
    assert [s[0] for s in recovered.started] == ["paper-2401.00008"]
    assert legacy_runs == ["2401.00007"]


async def test_duplicate_workflow_is_not_treated_as_an_outage(harness, caplog):
    client, connect_with, legacy_runs = harness
    temporal = _FakeTemporal(WorkflowAlreadyStartedError("paper-2401.00009", "PaperPipelineWorkflow"))
    connector = connect_with(temporal)

    response = await client.post("/api/process", json={"arxiv_id": "2401.00009"})

    assert response.status_code == 200
    assert "already being processed" in response.json()["message"]
    assert connector.calls == 1  # no reconnect, no retry
    assert legacy_runs == [] and _alert_lines(caplog) == []


async def test_non_rpc_errors_are_not_retried_but_still_fail_open(harness, caplog):
    client, connect_with, legacy_runs = harness
    connector = connect_with(_FakeTemporal(ValueError("payload not serializable")))

    assert (await client.post("/api/process", json={"arxiv_id": "2401.00010"})).status_code == 200
    assert connector.calls == 1
    assert legacy_runs == ["2401.00010"]
    assert len(_alert_lines(caplog)) == 1


@pytest.mark.parametrize("flag, expected", [("1", True), ("0", False), (None, False)])
def test_temporal_enabled_flag(monkeypatch, flag, expected):
    if flag is None:
        monkeypatch.delenv("USE_TEMPORAL", raising=False)
    else:
        monkeypatch.setenv("USE_TEMPORAL", flag)
    assert temporal_client.temporal_enabled() is expected
