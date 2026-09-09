"""Sections expose every complete video; stale URLs never survive a
pending/failed status (in-memory SQLite, no network).

Audit numbers behind this: 614 of 2,767 rendered videos (22%) were never
displayable because a section carried one video_url; re-runs left the
previous run's URL on rows that were now pending/failed.
"""

from datetime import datetime

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes import router
from db import queries
from db.connection import get_db
from db.models import Base, Paper, Section, Visualization


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


async def _seed(db):
    db.add(Paper(id="2608.13717", title="StreamHear", authors=["A"]))
    sec = "2608.13717-section-2"
    db.add(Section(id=sec, paper_id="2608.13717", title="Pipeline", content="word " * 500, order_index=0))
    db.add(Visualization(id="viz_2608_13717_3", paper_id="2608.13717", section_id=sec,
                         concept="Teacher -> Student", status="complete",
                         video_url="https://x/3.mp4", created_at=datetime(2026, 9, 7, 10)))
    db.add(Visualization(id="viz_2608_13717_4", paper_id="2608.13717", section_id=sec,
                         concept="DP realignment", status="complete",
                         video_url="https://x/4.mp4", created_at=datetime(2026, 9, 7, 11)))
    db.add(Visualization(id="viz_2608_13717_5", paper_id="2608.13717", section_id=sec,
                         concept="stale", status="failed", video_url="https://x/old.mp4",
                         created_at=datetime(2026, 9, 7, 12)))
    db.add(Visualization(id="viz_2608_13717_6", paper_id="2608.13717", section_id=sec,
                         concept="not yet", status="pending", created_at=datetime(2026, 9, 7, 13)))
    await db.commit()


async def test_section_lists_all_complete_videos_newest_first(client, db):
    await _seed(db)
    sec = (await client.get("/api/paper/2608.13717")).json()["sections"][0]
    assert [v["viz_id"] for v in sec["videos"]] == ["viz_2608_13717_4", "viz_2608_13717_3"]
    assert sec["videos"][0]["concept"] == "DP realignment"
    # legacy single field = the newest complete video, never the failed one
    assert sec["video_url"] == "https://x/4.mp4"


async def test_upsert_to_pending_clears_previous_run_url_and_sets_paper(db):
    await _seed(db)
    await queries.upsert_visualization(
        db, viz_id="viz_2608_13717_3", paper_id="2608.13717", section_id="2608.13717-section-2",
        concept="Teacher -> Student", status="pending",
    )
    row = await queries.get_visualization(db, "viz_2608_13717_3")
    assert row.status == "pending" and row.video_url is None and row.paper_id == "2608.13717"


async def test_failed_status_drops_stale_url(db):
    await _seed(db)
    await queries.update_visualization_status(db, "viz_2608_13717_4", status="failed", error="boom")
    row = await queries.get_visualization(db, "viz_2608_13717_4")
    assert row.status == "failed" and row.video_url is None and row.error == "boom"


async def test_superseded_rows_never_reach_the_api(client, db):
    # Reviewer: this exact filter broke once during the stack merge.
    db.add(Paper(id="1706.03762", title="A"))
    db.add(Section(id="s1", paper_id="1706.03762", title="S", content="word " * 500, order_index=0))
    db.add(Visualization(id="viz_1706_03762_1", paper_id="1706.03762", section_id="s1", concept="old",
                         status="superseded", video_url="https://x/old.mp4", created_at=datetime(2026, 9, 9)))
    db.add(Visualization(id="viz_1706_03762_2", paper_id="1706.03762", section_id="s1", concept="new",
                         status="complete", video_url="https://x/new.mp4", created_at=datetime(2026, 9, 8)))
    db.add(Visualization(id="viz_1706_03762_3", paper_id="1706.03762", section_id=None, concept="orphan",
                         status="complete", video_url="https://x/orphan.mp4", created_at=datetime(2026, 9, 8)))
    await db.commit()
    resp = await client.get("/api/paper/1706.03762")
    assert resp.status_code == 200  # a NULL section_id row used to 500 the endpoint
    body = resp.json()
    sec = body["sections"][0]
    assert [v["viz_id"] for v in sec["videos"]] == ["viz_1706_03762_2"]
    assert sec["video_url"] == "https://x/new.mp4"
    assert "viz_1706_03762_1" not in {v["id"] for v in body["visualizations"]}
