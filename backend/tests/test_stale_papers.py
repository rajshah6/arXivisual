"""Stale (pre-fix abstract-only) papers and legacy viz-row hygiene (in-memory SQLite, no network).

~31% of the corpus was ingested from the arXiv abstract page before the
LaTeXML fix. Those rows are not papers: the gallery hides them, the reader
reports them as not visualized, and a new request re-ingests instead of
skipping. Staleness needs provenance, not just length — stored content is
the ~35% summary, so a short real paper ingested after the fix must never
loop through re-ingestion. Older still are viz rows named with the
truncated id (``viz_17060376_1``) that show up as a second generation of
videos.
"""

from datetime import timedelta

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

REAL_TEXT = "word " * 1600  # 8000 chars: a real paper's summary
ABSTRACT_TEXT = "an abstract inflated to three hundred words by the old floor " * 40  # ~2500 chars
PRE_FIX = queries.ABSTRACT_INGEST_FIXED_AT - timedelta(days=3)
POST_FIX = queries.ABSTRACT_INGEST_FIXED_AT + timedelta(hours=1)


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


async def _paper(db, pid, *, text, ingested_at=PRE_FIX, title="T", video=False):
    db.add(Paper(id=pid, title=title, authors=["A"], abstract="abs", created_at=ingested_at, updated_at=ingested_at))
    db.add(Section(id=f"{pid}-section-0", paper_id=pid, title="Intro", content=text, order_index=0))
    if video:
        db.add(Visualization(id=f"viz_{pid}_1", paper_id=pid, section_id=f"{pid}-section-0", concept="c",
                             status="complete", video_url="https://x/v.mp4"))
    await db.commit()


class TestStaleRule:
    def test_pre_fix_abstract_sized_text_is_stale(self):
        assert queries.is_stale(PRE_FIX, 2500)

    def test_pre_fix_real_summary_is_not(self):
        assert not queries.is_stale(PRE_FIX, 8000)

    def test_post_fix_ingest_is_trusted_whatever_its_length(self):
        # The summarizer already refused abstracts; a short real paper stays a paper.
        assert not queries.is_stale(POST_FIX, 900)

    def test_unknown_ingest_time_falls_back_to_length(self):
        assert queries.is_stale(None, 2500) and not queries.is_stale(None, 8000)

    async def test_paper_is_stale_reads_the_row(self, db):
        await _paper(db, "2301.00001", text=ABSTRACT_TEXT)
        await _paper(db, "2301.00002", text=REAL_TEXT)
        await _paper(db, "2301.00003", text=ABSTRACT_TEXT, ingested_at=POST_FIX)
        assert await queries.paper_is_stale(db, "2301.00001")
        assert not await queries.paper_is_stale(db, "2301.00002")
        assert not await queries.paper_is_stale(db, "2301.00003")
        assert not await queries.paper_is_stale(db, "missing")


class TestGalleryAndReader:
    async def test_stale_status_even_with_videos(self, client, db):
        # The videos exist but were made from the abstract; not worth a card.
        await _paper(db, "2301.00001", text=ABSTRACT_TEXT, video=True)
        await _paper(db, "2301.00002", text=REAL_TEXT, video=True)
        await _paper(db, "2301.00003", text=ABSTRACT_TEXT, ingested_at=POST_FIX, video=True)
        by_id = {p["paper_id"]: p["status"] for p in (await client.get("/api/papers")).json()["papers"]}
        assert by_id == {"2301.00001": "stale", "2301.00002": "ready", "2301.00003": "ready"}

    async def test_stale_paper_being_regenerated_shows_processing(self, client, db):
        await _paper(db, "2301.00001", text=ABSTRACT_TEXT)
        db.add(ProcessingJob(id="job_1", paper_id="2301.00001", status="processing"))
        await db.commit()
        [p] = (await client.get("/api/papers")).json()["papers"]
        assert p["status"] == "processing"

    async def test_ready_paper_being_rerun_keeps_its_count(self, client, db):
        # Unchanged behaviour for healthy papers: videos win over an in-flight job.
        await _paper(db, "2301.00002", text=REAL_TEXT, video=True)
        db.add(ProcessingJob(id="job_1", paper_id="2301.00002", status="processing"))
        await db.commit()
        [p] = (await client.get("/api/papers")).json()["papers"]
        assert p["status"] == "ready" and p["visualization_count"] == 1

    async def test_reader_404s_stale_paper(self, client, db):
        await _paper(db, "2301.00001", text=ABSTRACT_TEXT, video=True)
        r = await client.get("/api/paper/2301.00001")
        assert r.status_code == 404 and "process it again" in r.json()["detail"]

    async def test_reader_serves_real_and_post_fix_papers(self, client, db):
        await _paper(db, "2301.00002", text=REAL_TEXT, video=True)
        await _paper(db, "2301.00003", text=ABSTRACT_TEXT, ingested_at=POST_FIX)
        assert (await client.get("/api/paper/2301.00002")).status_code == 200
        assert (await client.get("/api/paper/2301.00003")).status_code == 200


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
        assert paper.updated_at >= queries.ABSTRACT_INGEST_FIXED_AT  # trusted from now on
        assert not await queries.paper_is_stale(db, "2301.00001")
        # The old video row survives (feedback may reference it) but no longer points at a section.
        [old] = await queries.get_visualizations_for_paper(db, "2301.00001", include_superseded=True)
        assert old.id == "viz_2301.00001_1" and old.section_id is None
        assert (await queries.get_job(db, "job_1")).paper_id == "2301.00001"

    async def test_reingested_short_paper_is_not_reingested_again(self, db, monkeypatch):
        # A genuinely short paper: its real summary is still under the threshold.
        import ingestion
        from jobs.worker import _ingest_and_store_paper

        await _paper(db, "2301.00001", text=ABSTRACT_TEXT)
        db.add(ProcessingJob(id="job_1", status="processing"))
        await db.commit()
        short = _structured("2301.00001")
        for s in short.sections:
            s.content = "short " * 100

        async def fake_ingest(arxiv_id, force_refresh=False, prefer_pdf=False):
            return short

        monkeypatch.setattr(ingestion, "ingest_paper", fake_ingest)
        await _ingest_and_store_paper(db, "job_1", "2301.00001", replace=True)
        assert not await queries.paper_is_stale(db, "2301.00001")

    async def test_finalize_supersedes_the_unlinked_rows_once_the_new_run_has_videos(self, db):
        await _paper(db, "2301.00001", text=REAL_TEXT, video=True)
        await db.execute(
            queries.update(Visualization).where(Visualization.id == "viz_2301.00001_1").values(section_id=None)
        )
        await db.commit()
        run_started = queries._utcnow_naive() + timedelta(seconds=1)
        await queries.supersede_visualizations_before(db, "2301.00001", run_started)
        [old] = await queries.get_visualizations_for_paper(db, "2301.00001", include_superseded=True)
        assert old.status == "superseded"

    async def test_activity_reingests_stale_and_skips_healthy(self, db, monkeypatch):
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

    def test_legacy_id_shape(self):
        m = queries._LEGACY_VIZ_ID_RE.match
        assert m("viz_17060376_1") and m("viz_math/061_2") and m("viz_08053898_1")
        assert not m("viz_1706.03762_1") and not m("viz_0805.3898_1") and not m("viz_math/0612817_1")

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
