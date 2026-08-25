"""Tests for zombie-job handling in dedupe (in-memory SQLite, no network).

Found in production: a job stranded at "processing" for 6 days (worker killed
by a redeploy) satisfied the dedupe check, permanently blocking re-processing
of its paper. Active-job lookup must ignore stale jobs, and submission reaps
them so the jobs table tells the truth.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import queries
from db.models import Base, ProcessingJob


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _add_job(db, job_id: str, paper_id: str, status: str, age_hours: float):
    job = ProcessingJob(
        id=job_id,
        paper_id=paper_id,
        status=status,
        progress=0.5,
        created_at=datetime.utcnow() - timedelta(hours=age_hours),
    )
    db.add(job)
    await db.commit()
    return job


async def test_fresh_processing_job_is_active(db):
    await _add_job(db, "job_fresh", "1706.03762", "processing", age_hours=0.1)
    found = await queries.get_active_job_for_paper(db, "1706.03762")
    assert found is not None and found.id == "job_fresh"


async def test_zombie_job_is_not_treated_as_active(db):
    # The production case: 6-day-old job stuck at "processing".
    await _add_job(db, "job_zombie", "1706.03762", "processing", age_hours=144)
    found = await queries.get_active_job_for_paper(db, "1706.03762")
    assert found is None


async def test_completed_jobs_are_never_active(db):
    await _add_job(db, "job_done", "1706.03762", "completed", age_hours=0.1)
    assert await queries.get_active_job_for_paper(db, "1706.03762") is None


async def test_reap_marks_stale_jobs_failed_with_actionable_error(db):
    await _add_job(db, "job_zombie", "1706.03762", "processing", age_hours=144)
    await _add_job(db, "job_fresh", "2608.23554", "processing", age_hours=0.1)

    reaped = await queries.reap_stale_jobs(db)
    assert reaped == 1

    zombie = await queries.get_job(db, "job_zombie")
    assert zombie.status == "failed"
    assert "interrupted" in zombie.error
    fresh = await queries.get_job(db, "job_fresh")
    assert fresh.status == "processing"  # untouched


async def test_reap_noop_when_nothing_stale(db):
    await _add_job(db, "job_fresh", "1706.03762", "processing", age_hours=0.1)
    assert await queries.reap_stale_jobs(db) == 0
