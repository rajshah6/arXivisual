"""Generation robustness: JSON repair/retry, candidate dedupe, per-viz
checkpoint callbacks, and the DB helpers behind resumable runs (no network).

Reviewer-confirmed defects pinned here: unparseable JSON silently dropped
concepts (~4% of papers lost a section's candidates, ~6% a planned viz);
the same concept was animated 2-3 times per paper; a worker restart lost
every finished visualization; rows stranded at 'pending' counted as visuals.
"""

import asyncio
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import agents.pipeline as pipeline
from agents.base import BaseAgent, repair_json_text
from db import queries
from db.models import Base, Paper, Visualization
from models.generation import Visualization as VizModel
from models.generation import VisualizationCandidate, VisualizationStatus, VisualizationType

# --- JSON repair -------------------------------------------------------------

class TestJsonRepair:
    def test_lone_backslashes_and_trailing_commas(self):
        raw = '{"concept": "uses \\alpha and \\mathcal{X}", "items": [1, 2,],}'
        agent = BaseAgent.__new__(BaseAgent)
        out = agent._parse_json_response(raw)
        assert out["concept"] == "uses \\alpha and \\mathcal{X}"
        assert out["items"] == [1, 2]

    def test_valid_escapes_untouched(self):
        assert repair_json_text('{"a": "line\\nbreak \\"q\\""}') == '{"a": "line\\nbreak \\"q\\""}'

    def test_fenced_json_still_parses(self):
        agent = BaseAgent.__new__(BaseAgent)
        assert agent._parse_json_response('```json\n{"x": 1}\n```') == {"x": 1}

    def test_call_llm_json_retries_once(self, monkeypatch):
        agent = BaseAgent.__new__(BaseAgent)
        agent._trace_name = "t"
        replies = iter(["not json at all", '{"ok": true}'])
        seen_prompts = []

        async def fake_call(prompt, json_mode=False, **kw):
            seen_prompts.append((prompt, json_mode))
            return next(replies)

        monkeypatch.setattr(agent, "_call_llm", fake_call)
        assert asyncio.run(agent._call_llm_json("do it")) == {"ok": True}
        assert len(seen_prompts) == 2 and all(j for _, j in seen_prompts)
        assert "not valid JSON" in seen_prompts[1][0]

    def test_call_llm_json_gives_up_after_retry(self, monkeypatch):
        agent = BaseAgent.__new__(BaseAgent)
        agent._trace_name = "t"

        async def fake_call(prompt, json_mode=False, **kw):
            return "still not json"

        monkeypatch.setattr(agent, "_call_llm", fake_call)
        with pytest.raises(ValueError):
            asyncio.run(agent._call_llm_json("do it"))


# --- candidate dedupe --------------------------------------------------------

def _cand(name, priority, section="s1"):
    return VisualizationCandidate(
        section_id=section, concept_name=name, concept_description="d", context="c",
        visualization_type=VisualizationType.DATA_FLOW, priority=priority,
    )


class TestDedupe:
    def test_near_duplicates_collapse_keeping_first(self):
        cands = [
            _cand("StreamHear pipeline (teacher -> pseudo-labels -> student)", 5),
            _cand("Teacher -> Pseudo-label -> Student Adaptation Pipeline", 4),
            _cand("Prior-regularized dynamic-programming realignment", 4),
            _cand("Prior-regularized Dynamic Programming Re-alignment", 3),
            _cand("Beam search decoding", 2),
        ]
        kept = pipeline._dedupe_candidates(cands)
        assert [c.priority for c in kept] == [5, 4, 2]

    def test_distinct_concepts_all_kept(self):
        cands = [_cand("Attention heads", 5), _cand("Positional encoding", 4), _cand("Beam search", 3)]
        assert len(pipeline._dedupe_candidates(cands)) == 3


# --- per-viz callbacks + skip ------------------------------------------------

class _Paper:
    class meta:
        title = "T"
    sections = []


async def test_callback_fires_per_visualization_and_skips_checkpointed(monkeypatch):
    for name in ("SectionAnalyzer", "VisualizationPlanner", "ManimGenerator", "CodeValidator",
                 "SpatialValidator", "VoiceoverScriptValidator", "RenderTester"):
        monkeypatch.setattr(pipeline, name, lambda *a, **k: object())

    async def fake_analyze(analyzer, paper):
        return [_cand("Alpha concept", 5), _cand("Beta concept", 4), _cand("Gamma concept", 3)]

    async def fake_generate(candidate, **kw):
        return VizModel(id="tmp", section_id="s1", concept=candidate.concept_name,
                        storyboard="{}", manim_code="from manim import *",
                        video_url=None, status=VisualizationStatus.PENDING)

    monkeypatch.setattr(pipeline, "_analyze_all_sections", fake_analyze)
    monkeypatch.setattr(pipeline, "generate_single_visualization", fake_generate)
    delivered = []

    async def on_viz(v):
        delivered.append(v.concept)

    out = await pipeline.generate_visualizations(
        _Paper(), on_visualization=on_viz, skip_concepts={"beta concept"}
    )
    assert sorted(delivered) == ["Alpha concept", "Gamma concept"]
    assert len(out) == 2


# --- DB helpers for resumable runs -------------------------------------------

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(db):
    db.add(Paper(id="1706.03762", title="A"))
    db.add(Visualization(id="viz_17060376_1", paper_id="1706.03762", section_id="s", concept="old",
                         status="complete", video_url="https://x/old.mp4", created_at=datetime(2026, 8, 24)))
    db.add(Visualization(id="viz_1706_03762_1", paper_id="1706.03762", section_id="s", concept="new",
                         status="pending", manim_code="code", created_at=datetime(2026, 9, 7)))
    db.add(Visualization(id="viz_1706_03762_2", paper_id="1706.03762", section_id="s", concept="new2",
                         status="complete", video_url="https://x/new.mp4", created_at=datetime(2026, 9, 7)))
    await db.commit()


async def test_delete_clears_stale_rows_for_a_run(db):
    await _seed(db)
    assert await queries.delete_visualizations_for_paper(db, "1706.03762") == 3
    assert await queries.get_visualizations_for_paper(db, "1706.03762") == []


async def test_fail_pending_marks_only_stranded_rows(db):
    await _seed(db)
    assert await queries.fail_pending_visualizations(db, "1706.03762", "died") == 1
    rows = {r.id: r for r in await queries.get_visualizations_for_paper(db, "1706.03762")}
    assert rows["viz_1706_03762_1"].status == "failed"
    assert rows["viz_1706_03762_2"].status == "complete"
    assert rows["viz_17060376_1"].status == "complete"
