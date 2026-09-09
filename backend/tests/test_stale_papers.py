"""Abstract-only ("stale") papers and legacy viz-row hygiene (in-memory SQLite, no network).

~31% of the corpus was ingested from the arXiv abstract page before the
LaTeXML fix. Those rows are not papers: the gallery hides them, the reader
reports them as not visualized, and a new request re-ingests instead of
skipping. Older still are viz rows named with the truncated id
(``viz_17060376_1``) that show up as a second generation of videos.
"""

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes import router
from db import queries
from db.connection import get_db
from db.models import Base, Paper, ProcessingJob, Section, Visualization
from models.paper import ArxivPaperMeta, StructuredPaper
from models.paper import Section as PaperSection

REAL_TEXT = "word " * 800  # 4000 chars, comfortably above STALE_TEXT_CHARS
ABSTRACT_TEXT = "an abstract inflated to a few sentences " * 8  # ~320 chars


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


async def _paper(db, pid, *, text, title="T", video=False):
    db.add(Paper(id=pid, title=title, authors=["A"], abstract="abs"))
    db.add(Section(id=f"{pid}-section-0", paper_id=pid, title="Intro", content=text, order_index=0))
    if video:
        db.add(Visualization(id=f"viz_{pid}_1", paper_id=pid, section_id=f"{pid}-section-0", concept="c",
                             status="complete", video_url="https://x/v.mp4"))
    await db.commit()


class TestDegradedDetection:
    async def test_abstract_only_is_degraded(self, db):
        await _paper(db, "2301.00001", text=ABSTRACT_TEXT)
        assert await queries.paper_is_degraded(db, "2301.00001")

    async def test_real_paper_is_not(self, db):
        await _paper(db, "2301.00002", text=REAL_TEXT)
        assert not await queries.paper_is_degraded(db, "2301.00002")

    async def test_no_sections_is_degraded(self, db):
        db.add(Paper(id="2301.00003", title="T", authors=[]))
        await db.commit()
        assert await queries.paper_is_degraded(db, "2301.00003")


class TestGalleryAndReader:
    async def test_stale_status_even_with_videos(self, client, db):
        # The videos exist but were made from the abstract; not worth a card.
        await _paper(db, "2301.00001", text=ABSTRACT_TEXT, video=True)
        await _paper(db, "2301.00002", text=REAL_TEXT, video=True)
        by_id = {p["paper_id"]: p["status"] for p in (await client.get("/api/papers")).json()["papers"]}
        assert by_id == {"2301.00001": "stale", "2301.00002": "ready"}

    async def test_processing_wins_over_stale(self, client, db):
        await _paper(db, "2301.00001", text=ABSTRACT_TEXT)
        db.add(ProcessingJob(id="job_1", paper_id="2301.00001", status="processing"))
        await db.commit()
        [p] = (await client.get("/api/papers")).json()["papers"]
        assert p["status"] == "processing"

    async def test_reader_404s_degraded_paper(self, client, db):
        await _paper(db, "2301.00001", text=ABSTRACT_TEXT, video=True)
        r = await client.get("/api/paper/2301.00001")
        assert r.status_code == 404 and "abstract-only" in r.json()["detail"]

    async def test_reader_serves_real_paper(self, client, db):
        await _paper(db, "2301.00002", text=REAL_TEXT, video=True)
        assert (await client.get("/api/paper/2301.00002")).status_code == 200


def _structured(arxiv_id: str, title: str = "Real title") -> StructuredPaper:
    meta = ArxivPaperMeta(arxiv_id=arxiv_id, title=title, authors=["B"], abstract="real abstract",
                          pdf_url=f"https://arxiv.org/pdf/{arxiv_id}", html_url=f"https://arxiv.org/html/{arxiv_id}")
    sections = [PaperSection(id=f"{arxiv_id}-section-{i}", title=f"S{i}", content=REAL_TEXT, summary="sum")
                for i in range(3)]
    return StructuredPaper(meta=meta, sections=sections)


class TestReingest:
    async def test_replace_updates_paper_and_swaps_sections_keeping_viz_rows(self, db, monkeypatch):
        import ingestion
        from jobs.worker import _ingest_and_store_paper

        await _paper(db, "2301.00001", text=ABSTRACT_TEXT, title="Abstract-page title", video=True)
        db.add(ProcessingJob(id="job_1", status="processing"))
        await db.commit()
        # Worst case for the identity map: the paper and its sections are loaded first.
        loaded = await queries.get_paper(db, "2301.00001")
        assert len(loaded.sections) == 1

        calls = {}

        async def fake_ingest(arxiv_id, force_refresh=False, prefer_pdf=False):
            calls["force_refresh"] = force_refresh
            return _structured(arxiv_id)

        monkeypatch.setattr(ingestion, "ingest_paper", fake_ingest)
        await _ingest_and_store_paper(db, "job_1", "2301.00001", replace=True)

        assert calls["force_refresh"] is True  # the in-memory ingest cache must not serve the abstract again
        paper = await queries.get_paper(db, "2301.00001")
        assert paper.title == "Real title" and paper.abstract == "real abstract"
        assert sorted(s.id for s in paper.sections) == [f"2301.00001-section-{i}" for i in range(3)]
        assert not await queries.paper_is_degraded(db, "2301.00001")
        # The old video row survives (feedback may reference it) but no longer points at a section.
        [old] = await queries.get_visualizations_for_paper(db, "2301.00001", include_superseded=True)
        assert old.id == "viz_2301.00001_1" and old.section_id is None
        job = await queries.get_job(db, "job_1")
        assert job.paper_id == "2301.00001"

    async def test_activity_reingests_degraded_and_skips_healthy(self, db, monkeypatch):
        import contextlib

        import db.connection as connection
        import jobs.worker as worker
        from temporal_app.activities import PipelineInput, ingest_paper

        @contextlib.asynccontextmanager
        async def session():
            yield db

        monkeypatch.setattr(connection, "async_session_maker", session)
        seen = []

        async def fake_store(db_, job_id, arxiv_id, replace=False):
            seen.append((arxiv_id, replace))

        monkeypatch.setattr(worker, "_ingest_and_store_paper", fake_store)

        await _paper(db, "2301.00001", text=ABSTRACT_TEXT)
        await _paper(db, "2301.00002", text=REAL_TEXT)
        db.add(ProcessingJob(id="job_a", status="queued"))
        db.add(ProcessingJob(id="job_b", status="queued"))
        await db.commit()

        await ingest_paper(PipelineInput(job_id="job_a", arxiv_id="2301.00001"))
        await ingest_paper(PipelineInput(job_id="job_b", arxiv_id="2301.00002"))

        assert seen == [("2301.00001", True)]
        assert (await queries.get_job(db, "job_b")).current_step == "Paper already processed"


class TestLegacyTruncatedRows:
    async def _viz(self, db, vid, pid, status="complete", url="https://x/v.mp4"):
        db.add(Visualization(id=vid, paper_id=pid, concept="c", status=status, video_url=url))

    async def test_legacy_rows_superseded_only_where_full_id_video_exists(self, db):
        db.add(Paper(id="1706.03762", title="A", authors=[]))
        db.add(Paper(id="1706.03763", title="B", authors=[]))
        await db.commit()
        await self._viz(db, "viz_17060376_1", "1706.03762")
        await self._viz(db, "viz_17060376_2", "1706.03762", status="failed", url=None)
        await self._viz(db, "viz_1706.03762_1", "1706.03762")
        await self._viz(db, "viz_17060376_3", "1706.03763")  # only legacy videos: keep
        await db.commit()

        assert await queries.supersede_legacy_truncated_rows(db) == 2
        status = {v.id: v.status for v in await queries.get_visualizations_for_paper(
            db, "1706.03762", include_superseded=True)}
        assert status == {"viz_17060376_1": "superseded", "viz_17060376_2": "superseded",
                          "viz_1706.03762_1": "complete"}
        [kept] = await queries.get_visualizations_for_paper(db, "1706.03763")
        assert kept.status == "complete"
        # Idempotent: the API runs this at every startup.
        assert await queries.supersede_legacy_truncated_rows(db) == 0
