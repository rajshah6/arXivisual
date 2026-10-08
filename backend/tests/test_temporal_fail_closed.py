"""POST /api/process fails CLOSED when Temporal is down (fake client, no server).

The API used to fall back to running the paper in its own process when the
workflow start failed. That fallback peaked at 2.2 GiB / 2 vCPU (two
overlapping jobs, Sep 9 2026) and was the only reason the API needed 2 vCPU /
4 GiB. Now a failed start retires the job and answers 503 + Retry-After; the
in-process path is only for USE_TEMPORAL=0. These tests pin that contract.
"""

import logging
from datetime import datetime

import pytest_asyncio
from fastapi import BackgroundTasks, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

import analytics
import api.routes as routes_module
import api.temporal_client as temporal_client
import api.throttle as throttle
from api.routes import router
from db import queries
from db.connection import get_db
from db.models import Base, ProcessingJob

IP = "203.0.113.42"


class FakeTemporal:
    """Stands in for temporalio.client.Client: ``start_workflow`` raises
    ``error`` when one is set, otherwise records the workflow id."""

    def __init__(self, error: BaseException | None = None):
        self.error = error
        self.started: list[str] = []

    async def start_workflow(self, _run, _input, *, id, task_queue):
        if self.error is not None:
            raise self.error
        self.started.append(id)


def _outage() -> RPCError:
    # What the API logged on every Sep 9-15 fallback.
    return RPCError("tcp connect error", RPCStatusCode.UNAVAILABLE, b"")


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

    in_process_runs: list[tuple[str, str]] = []
    scheduled: list[str] = []
    events: list[str] = []

    async def _pipeline(job_id, arxiv_id):
        in_process_runs.append((job_id, arxiv_id))

    original_add_task = BackgroundTasks.add_task

    def _recording_add_task(self, func, *args, **kwargs):
        # Recorded at scheduling time: a raised HTTPException drops queued
        # background tasks, so checking the pipeline alone could miss one.
        scheduled.append(getattr(func, "__name__", repr(func)))
        return original_add_task(self, func, *args, **kwargs)

    monkeypatch.setattr(routes_module, "process_paper_job", _pipeline)
    monkeypatch.setattr(BackgroundTasks, "add_task", _recording_add_task)
    monkeypatch.setattr(analytics, "capture", lambda event, *a, **k: events.append(event))
    monkeypatch.setenv("USE_TEMPORAL", "1")
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PROCESS_GLOBAL", "100")
    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "0")
    for lim in (throttle.per_ip_limiter, throttle.per_ip_daily_limiter):
        lim.reset()
    monkeypatch.setattr(throttle.per_ip_limiter, "max_events", 100)
    monkeypatch.setattr(throttle.per_ip_daily_limiter, "max_events", 100)
    # The route reaches the client through the real get_temporal_client(),
    # which returns this cached instance instead of connecting.
    monkeypatch.setattr(temporal_client, "_client", None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "in_process_runs": in_process_runs,
            "scheduled": scheduled,
            "events": events,
        }


def _use(fake: FakeTemporal) -> FakeTemporal:
    temporal_client._client = fake
    return fake


def _submit(client, arxiv_id):
    return client.post(
        "/api/process", json={"arxiv_id": arxiv_id}, headers={"X-Forwarded-For": IP},
    )


async def _jobs(db) -> list[ProcessingJob]:
    db.expire_all()
    return list((await db.execute(select(ProcessingJob))).scalars().all())


def _per_ip_events() -> tuple[int, int]:
    return tuple(
        len(lim._events.get(IP, ()))
        for lim in (throttle.per_ip_limiter, throttle.per_ip_daily_limiter)
    )


# --- (a) Temporal down: 503, nothing runs here ------------------------------

async def test_failed_start_is_a_503_and_never_runs_in_process(harness, db, caplog):
    _use(FakeTemporal(error=_outage()))
    with caplog.at_level(logging.ERROR, logger="api.routes"):
        resp = await _submit(harness["client"], "2401.10001")

    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "60"
    assert "try again in a minute" in resp.json()["detail"]

    # No in-process run, not even a scheduled one.
    assert harness["scheduled"] == [] and harness["in_process_runs"] == []

    # The row exists for the record, retired with the never-started marker.
    [job] = await _jobs(db)
    assert job.status == "failed" and job.error == queries.JOB_NOT_STARTED_ERROR

    # Dedupe forgets it, so the user's retry starts a fresh job.
    assert throttle.recent_jobs.get("2401.10001") is None

    # The alert phrase survives; the old "falling back" wording does not.
    alert_lines = [r.getMessage() for r in caplog.records if "Temporal unavailable" in r.getMessage()]
    assert len(alert_lines) == 1 and "falling back" not in alert_lines[0]
    assert job.id in alert_lines[0]

    # Not a product "accepted" — nothing was.
    assert "paper_accepted" not in harness["events"]


async def test_refusal_gives_back_admission_slots(harness, db, monkeypatch):
    # Per-IP quota (3/day in prod) is released, and the retired row does not
    # count toward the durable daily cap / global window, so the retry after
    # Temporal recovers is admitted.
    monkeypatch.setenv("DAILY_NEW_PAPER_CAP", "1")
    monkeypatch.setenv("RATE_LIMIT_PROCESS_GLOBAL", "1")
    _use(FakeTemporal(error=_outage()))
    assert (await _submit(harness["client"], "2401.10002")).status_code == 503
    assert _per_ip_events() == (0, 0)
    assert await queries.count_jobs_created_since(db, datetime(2000, 1, 1)) == 0

    healthy = _use(FakeTemporal())
    retry = await _submit(harness["client"], "2401.10002")
    assert retry.status_code == 200
    assert healthy.started == ["paper-2401.10002"]
    assert _per_ip_events() == (1, 1)
    # The admitted retry counts again; the next new paper hits the cap.
    assert (await _submit(harness["client"], "2401.10003")).status_code == 429


async def test_failed_client_is_dropped_so_the_next_request_reconnects(harness):
    _use(FakeTemporal(error=_outage()))
    assert (await _submit(harness["client"], "2401.10004")).status_code == 503
    assert temporal_client._client is None


async def test_unexpected_errors_fail_closed_too(harness, db, caplog):
    # Not an RPCError (e.g. a bug in the start path): still 503, never the
    # in-process pipeline — and the traceback is kept for diagnosis.
    _use(FakeTemporal(error=TypeError("bad workflow input")))
    with caplog.at_level(logging.ERROR, logger="api.routes"):
        resp = await _submit(harness["client"], "2401.10005")
    assert resp.status_code == 503
    assert harness["scheduled"] == []
    [record] = [r for r in caplog.records if "Temporal unavailable" in r.getMessage()]
    assert record.exc_info is not None


async def test_rpc_outage_logs_one_line_without_traceback(harness, caplog):
    _use(FakeTemporal(error=_outage()))
    with caplog.at_level(logging.ERROR, logger="api.routes"):
        await _submit(harness["client"], "2401.10006")
    [record] = [r for r in caplog.records if "Temporal unavailable" in r.getMessage()]
    assert not record.exc_info
    assert "tcp connect error" in record.getMessage()


async def test_503_still_goes_out_when_the_job_row_cannot_be_retired(harness, monkeypatch):
    # The database may be what is down; the caller must still get the 503.
    async def _db_down(*a, **k):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(queries, "update_job_status", _db_down)
    _use(FakeTemporal(error=_outage()))
    resp = await _submit(harness["client"], "2401.10007")
    assert resp.status_code == 503
    assert harness["scheduled"] == []
    assert throttle.recent_jobs.get("2401.10007") is None


# --- (b) USE_TEMPORAL=0: the legacy in-process path is unchanged -------------

async def test_temporal_disabled_still_runs_the_legacy_background_task(harness, db, monkeypatch):
    monkeypatch.setenv("USE_TEMPORAL", "0")
    resp = await _submit(harness["client"], "2401.10008")
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert harness["scheduled"] == ["_pipeline"]
    assert harness["in_process_runs"] == [(job_id, "2401.10008")]
    assert harness["events"] == ["paper_accepted"]
    [job] = await _jobs(db)
    assert job.status == "queued"


# --- happy path and (c) duplicate start: unchanged ---------------------------

async def test_successful_start_runs_on_the_worker_only(harness):
    fake = _use(FakeTemporal())
    resp = await _submit(harness["client"], "2401.10009")
    assert resp.status_code == 200 and resp.json()["status"] == "queued"
    assert fake.started == ["paper-2401.10009"]
    assert harness["scheduled"] == []
    assert harness["events"] == ["paper_accepted"]


async def test_already_started_workflow_is_a_duplicate_not_an_outage(harness, db, caplog):
    fake = _use(FakeTemporal(error=WorkflowAlreadyStartedError("paper-2401.10010", "PaperPipelineWorkflow")))
    with caplog.at_level(logging.INFO, logger="api.routes"):
        resp = await _submit(harness["client"], "2401.10010")

    assert resp.status_code == 200
    assert "already being processed" in resp.json()["message"]
    [job] = await _jobs(db)
    assert job.status == "failed" and job.error.startswith("Duplicate submission")
    assert throttle.recent_jobs.get("2401.10010") is None
    assert harness["scheduled"] == []
    assert not [r for r in caplog.records if "Temporal unavailable" in r.getMessage()]
    # An answer from a live server, so the client is kept.
    assert temporal_client._client is fake
