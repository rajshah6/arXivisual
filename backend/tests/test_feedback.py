"""Feedback endpoint + storage tests (in-memory SQLite, no network).

Video feedback is labeled ground truth for the visual-QA loop, so the tests
pin the invariants that keep the data trustworthy: votes attach only to real
visualizations, the paper id is denormalized from the viz (never trusted from
the client), and junk requests are rejected before they reach the table.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes import router
from api.throttle import feedback_limiter
from db import queries
from db.connection import get_db
from db.models import Base, Feedback, Paper, Visualization


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
    feedback_limiter._events.clear()  # isolate rate-limit state between tests
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_viz(db, viz_id="viz_1706_03762_1", paper_id="1706.03762"):
    db.add(Paper(id=paper_id, title="Attention Is All You Need"))
    db.add(Visualization(id=viz_id, paper_id=paper_id, concept="attention"))
    await db.commit()


async def test_video_feedback_is_stored_with_denormalized_paper(client, db):
    await _seed_viz(db)
    resp = await client.post("/api/feedback", json={
        "kind": "video", "viz_id": "viz_1706_03762_1",
        "vote": "down", "reason": "overlapping text",
    })
    assert resp.status_code == 200
    rows = (await db.execute(select(Feedback))).scalars().all()
    assert len(rows) == 1
    fb = rows[0]
    assert fb.vote == "down" and fb.reason == "overlapping text"
    # paper_id comes from the viz row, not the client
    assert fb.paper_id == "1706.03762"
    assert fb.created_at.tzinfo is None  # naive-UTC convention (CLAUDE.md #6)


async def test_video_feedback_rejects_unknown_viz(client):
    resp = await client.post("/api/feedback", json={
        "kind": "video", "viz_id": "viz_does_not_exist", "vote": "up",
    })
    assert resp.status_code == 404


async def test_video_feedback_requires_vote(client, db):
    await _seed_viz(db)
    resp = await client.post("/api/feedback", json={
        "kind": "video", "viz_id": "viz_1706_03762_1",
    })
    assert resp.status_code == 422


async def test_site_feedback_requires_comment(client):
    assert (await client.post("/api/feedback", json={"kind": "site"})).status_code == 422
    assert (await client.post("/api/feedback", json={
        "kind": "site", "comment": "   ",
    })).status_code == 422
    resp = await client.post("/api/feedback", json={
        "kind": "site", "comment": "please add voice selection",
    })
    assert resp.status_code == 200


async def test_site_feedback_never_stores_viz_or_vote(client, db):
    await client.post("/api/feedback", json={
        "kind": "site", "comment": "great tool",
        "viz_id": "viz_smuggled", "vote": "up",
    })
    fb = (await db.execute(select(Feedback))).scalars().one()
    assert fb.viz_id is None and fb.vote is None


async def test_oversized_comment_is_rejected(client):
    resp = await client.post("/api/feedback", json={
        "kind": "site", "comment": "x" * 2001,
    })
    assert resp.status_code == 422


async def test_rate_limit_kicks_in(client, db, monkeypatch):
    await _seed_viz(db)
    monkeypatch.setattr(feedback_limiter, "max_events", 2)
    body = {"kind": "video", "viz_id": "viz_1706_03762_1", "vote": "up"}
    assert (await client.post("/api/feedback", json=body)).status_code == 200
    assert (await client.post("/api/feedback", json=body)).status_code == 200
    resp = await client.post("/api/feedback", json=body)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_create_feedback_query_defaults(db):
    fb = await queries.create_feedback(db, kind="site", comment="hi")
    assert fb.id.startswith("fb_")
    assert fb.viz_id is None and fb.vote is None
