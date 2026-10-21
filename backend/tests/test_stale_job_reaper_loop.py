"""The API reaps stale jobs on a timer, not only when someone submits."""

import asyncio
import contextlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import queries
from db.models import Base, ProcessingJob
from jobs import reaper


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


class FakeSessionMaker:
    def __init__(self) -> None:
        self.opened = 0

    def __call__(self):
        maker = self

        class _Session:
            async def __aenter__(self_inner):
                maker.opened += 1
                return "db"

            async def __aexit__(self_inner, *exc):
                return False

        return _Session()


async def _run_for(coro, seconds: float) -> None:
    task = asyncio.create_task(coro)
    await asyncio.sleep(seconds)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_reaps_every_interval_and_stops_cleanly_on_cancel():
    calls = []

    async def reap(db):
        calls.append(db)
        return 1

    maker = FakeSessionMaker()
    await _run_for(reaper.reap_forever(0.01, maker, reap), 0.06)
    assert len(calls) >= 3 and calls[0] == "db"
    assert maker.opened == len(calls)


async def test_a_failing_pass_does_not_kill_the_loop(caplog):
    calls = []

    async def reap(db):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database is away")
        return 0

    await _run_for(reaper.reap_forever(0.01, FakeSessionMaker(), reap), 0.06)
    assert len(calls) >= 3
    assert any("reaper pass failed" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 900.0), ("600", 600.0), ("0", 0.0), ("-5", 0.0), ("soon", 0.0)],
)
def test_interval_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("STALE_JOB_REAP_INTERVAL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("STALE_JOB_REAP_INTERVAL_SECONDS", raw)
    assert reaper.reap_interval_seconds() == expected


async def test_default_cutoff_outlasts_a_worst_case_paper(db):
    # A paper can legitimately run ~2.5 h (ingest 15 + generation 40 + two
    # render waves + repair); the old 2 h cutoff failed live jobs.
    now = datetime.utcnow()
    db.add(ProcessingJob(id="still_rendering", status="processing", created_at=now - timedelta(hours=2.5)))
    db.add(ProcessingJob(id="zombie", status="processing", created_at=now - timedelta(hours=3.5)))
    await db.commit()

    assert await queries.reap_stale_jobs(db) == 1
    assert (await queries.get_job(db, "still_rendering")).status == "processing"
    assert (await queries.get_job(db, "zombie")).status == "failed"
