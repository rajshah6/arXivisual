"""Paper routing + Explore summaries (in-memory SQLite, no network).

Reviewer-confirmed defects pinned here: old-style arXiv ids with a slash
404'd (single-segment path param), the version strip mangled category
prefixes, and the gallery counted viz rows of any status.
"""

from datetime import datetime, timedelta

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes import router
from db.connection import get_db
from db.models import Base, Paper, ProcessingJob, Section, Visualization


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
async def client(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _paper(db, pid, title="T", with_section=True):
    db.add(Paper(id=pid, title=title, authors=["A"]))
    if with_section:
        db.add(Section(id=f"{pid}-section-1", paper_id=pid, title="Intro", content="x", order_index=0))
    await db.commit()


class TestOldStyleIds:
    async def test_slash_id_routes(self, client, db):
        await _paper(db, "math/0612817", title="Old style")
        r = await client.get("/api/paper/math/0612817")
        assert r.status_code == 200 and r.json()["title"] == "Old style"

    async def test_percent_encoded_slash_routes(self, client, db):
        await _paper(db, "hep-th/9711200")
        assert (await client.get("/api/paper/hep-th%2F9711200")).status_code == 200

    async def test_version_suffix_stripped_only_at_end(self, client, db):
        await _paper(db, "1706.03762")
        await _paper(db, "adap-org/9707006")  # contains a 'v' in the category
        assert (await client.get("/api/paper/1706.03762v2")).status_code == 200
        assert (await client.get("/api/paper/adap-org/9707006")).status_code == 200


class TestExploreSummaries:
    async def test_count_is_playable_sections_not_rows(self, client, db):
        await _paper(db, "1706.03762")
        sec = "1706.03762-section-1"
        db.add(Visualization(id="v1", paper_id="1706.03762", section_id=sec, concept="a",
                             status="complete", video_url="https://x/v1.mp4"))
        db.add(Visualization(id="v2", paper_id="1706.03762", section_id=sec, concept="b",
                             status="complete", video_url="https://x/v2.mp4"))
        db.add(Visualization(id="v3", paper_id="1706.03762", section_id=sec, concept="c",
                             status="failed"))
        db.add(Visualization(id="v4", paper_id="1706.03762", section_id=sec, concept="d",
                             status="pending"))
        await db.commit()
        p = (await client.get("/api/papers")).json()["papers"][0]
        assert p["visualization_count"] == 1 and p["status"] == "ready"

    async def test_in_flight_paper_is_processing_not_empty(self, client, db):
        await _paper(db, "2509.23444")
        db.add(ProcessingJob(id="job_x", paper_id="2509.23444", status="processing",
                             progress=0.5, created_at=datetime.utcnow()))
        await _paper(db, "1801.00369")  # nothing at all
        db.add(ProcessingJob(id="job_old", paper_id="1801.00369", status="processing",
                             progress=0.5, created_at=datetime.utcnow() - timedelta(hours=9)))
        await db.commit()
        by_id = {p["paper_id"]: p for p in (await client.get("/api/papers")).json()["papers"]}
        assert by_id["2509.23444"]["status"] == "processing"
        assert by_id["1801.00369"]["status"] == "empty"  # stale job doesn't count

    async def test_processed_at_carries_utc_offset(self, client, db):
        await _paper(db, "1706.03762")
        p = (await client.get("/api/papers")).json()["papers"][0]
        assert p["processed_at"].endswith("+00:00")
