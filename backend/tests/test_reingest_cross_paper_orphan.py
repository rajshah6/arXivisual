"""Re-ingesting a paper must survive a SIBLING paper's viz row pointing at its sections.

Legacy truncated viz ids (``viz_26082355_1``: eight characters of the arXiv id)
collided across sibling papers, and the upsert left rows whose ``paper_id`` is
one paper while ``section_id`` still references another's section.
``reset_paper_for_reingest`` unlinked viz rows ``WHERE paper_id = X`` and then
deleted X's sections — the sibling's row still referenced them, which Postgres
rejects (ForeignKeyViolation) on the first re-ingest of e.g. 2608.23552.

SQLite only enforces foreign keys with ``PRAGMA foreign_keys=ON``, so the
fixture turns it on; without it this test cannot fail.
"""

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import queries
from db.models import Base, Paper, Section, Visualization
from models.paper import ArxivPaperMeta

PAPER = "2608.23552"
SIBLING = "2608.23553"
LEGACY_VIZ = "viz_26082355_1"  # what both ids truncate to


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(db):
    for pid in (PAPER, SIBLING):
        db.add(Paper(id=pid, title=f"old {pid}", authors=["A"], abstract="abs"))
        db.add(Section(id=f"{pid}-section-0", paper_id=pid, title="Intro", content="text", order_index=0))
    await db.flush()
    # The paper's own row, and the cross-paper orphan: owned by the SIBLING,
    # still attached to one of THIS paper's sections.
    db.add(Visualization(id=f"viz_{PAPER.replace('.', '_')}_1", paper_id=PAPER,
                         section_id=f"{PAPER}-section-0", concept="own", status="complete"))
    db.add(Visualization(id=LEGACY_VIZ, paper_id=SIBLING,
                         section_id=f"{PAPER}-section-0", concept="orphan", status="complete"))
    # A healthy sibling row that must be left completely alone.
    db.add(Visualization(id=f"viz_{SIBLING.replace('.', '_')}_1", paper_id=SIBLING,
                         section_id=f"{SIBLING}-section-0", concept="sibling", status="complete"))
    await db.commit()


def _meta() -> ArxivPaperMeta:
    return ArxivPaperMeta(arxiv_id=PAPER, title="Real title", authors=["B"], abstract="real abstract",
                          pdf_url=f"https://arxiv.org/pdf/{PAPER}")


async def test_the_fixture_really_enforces_foreign_keys(db):
    # Guard the guard: if FK enforcement were off, the test below proves nothing.
    assert (await db.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    await _seed(db)
    with pytest.raises(IntegrityError):
        await db.execute(text("DELETE FROM sections WHERE paper_id = :pid"), {"pid": PAPER})
    await db.rollback()


async def test_reingest_unlinks_a_sibling_papers_row_from_the_deleted_sections(db):
    await _seed(db)

    await queries.reset_paper_for_reingest(db, _meta())  # raised IntegrityError before the fix

    assert (await db.execute(select(Section.id).where(Section.paper_id == PAPER))).all() == []
    rows = {v.id: v for v in (await db.execute(select(Visualization))).scalars()}
    # Every row survives (feedback references them); only the links to the
    # deleted sections are cut.
    assert len(rows) == 3
    assert rows[LEGACY_VIZ].section_id is None
    assert rows[LEGACY_VIZ].paper_id == SIBLING  # ownership is not rewritten
    assert rows[f"viz_{PAPER.replace('.', '_')}_1"].section_id is None
    # The sibling's healthy row and section are untouched.
    assert rows[f"viz_{SIBLING.replace('.', '_')}_1"].section_id == f"{SIBLING}-section-0"
    assert (await db.execute(select(Section.id).where(Section.paper_id == SIBLING))).all() != []
    assert (await db.get(Paper, PAPER)).title == "Real title"
