"""Generation robustness: JSON repair/retry, candidate dedupe, per-viz
checkpoint callbacks, and the DB helpers behind resumable runs (no network).

Reviewer-confirmed defects pinned here: unparseable JSON silently dropped
concepts (~4% of papers lost a section's candidates, ~6% a planned viz);
the same concept was animated 2-3 times per paper; a worker restart lost
every finished visualization; rows stranded at 'pending' counted as visuals.
"""

import asyncio
import json
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import agents.base as base
import agents.pipeline as pipeline
from agents.base import BaseAgent, call_llm_json, parse_json_response, repair_json_text
from db import queries
from db.models import Base, Feedback, Paper, Visualization
from models.generation import Visualization as VizModel
from models.generation import VisualizationCandidate, VisualizationStatus, VisualizationType

# --- JSON repair -------------------------------------------------------------

class TestJsonRepair:
    def test_lone_backslashes_and_trailing_commas(self):
        raw = '{"concept": "uses \\alpha and \\mathcal{X}", "items": [1, 2,],}'
        out = parse_json_response(raw)
        assert out["concept"] == "uses \\alpha and \\mathcal{X}"
        assert out["items"] == [1, 2]

    def test_escaped_pairs_survive_repair(self):
        # Reviewer repro: a correctly escaped \\alpha plus a trailing comma was
        # turned into \\\\alpha (invalid) by the old lookahead-only regex.
        raw = '{"c": "\\\\alpha", "items": [1,],}'
        assert parse_json_response(raw) == {"c": "\\alpha", "items": [1]}

    def test_repair_is_idempotent_on_valid_json(self):
        valid = '{"c": "\\\\alpha \\u00e9 \\n"}'
        assert repair_json_text(valid) == valid
        assert json.loads(repair_json_text(valid)) == json.loads(valid)

    def test_bogus_unicode_escape_is_repaired(self):
        # \u not followed by 4 hex digits is a lone backslash, not an escape.
        assert json.loads(repair_json_text('{"c": "\\underline"}')) == {"c": "\\underline"}

    def test_valid_escapes_untouched(self):
        assert repair_json_text('{"a": "line\\nbreak \\"q\\""}') == '{"a": "line\\nbreak \\"q\\""}'

    def test_fenced_json_still_parses(self):
        assert parse_json_response('```json\n{"x": 1}\n```') == {"x": 1}

    def test_call_llm_json_retries_once(self, monkeypatch):
        replies = iter(["not json at all", '{"ok": true}'])
        seen = []

        async def fake_call(prompt, **kw):
            seen.append((prompt, kw.get("json_mode")))
            return next(replies)

        monkeypatch.setattr(base, "call_llm", fake_call)
        assert asyncio.run(call_llm_json("do it", name="t")) == {"ok": True}
        assert len(seen) == 2 and all(j for _, j in seen)
        assert "not valid JSON" in seen[1][0] and "double quote" in seen[1][0]

    def test_call_llm_json_gives_up_after_retry(self, monkeypatch):
        async def fake_call(prompt, **kw):
            return "still not json"

        monkeypatch.setattr(base, "call_llm", fake_call)
        with pytest.raises(ValueError):
            asyncio.run(call_llm_json("do it", name="t"))

    def test_agent_wrapper_delegates_to_shared_caller(self, monkeypatch):
        agent = BaseAgent.__new__(BaseAgent)
        agent._trace_name, agent.model, agent.max_tokens, agent.system_prompt = "t", "m", 10, "sys"
        captured = {}

        async def fake(prompt, **kw):
            captured.update(kw)
            return {"ok": 1}

        monkeypatch.setattr(base, "call_llm_json", fake)
        assert asyncio.run(agent._call_llm_json("p")) == {"ok": 1}
        assert captured["system_prompt"] == "sys" and captured["name"] == "t"


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

    # skip_concepts takes RAW names (normalized inside) — a checkpointed
    # 'Beta Concepts' must skip the analyzer's 'Beta concept'.
    out = await pipeline.generate_visualizations(
        _Paper(), on_visualization=on_viz, skip_concepts={"Beta Concepts"}
    )
    assert sorted(delivered) == ["Alpha concept", "Gamma concept"]
    assert len(out) == 2


async def test_failing_checkpoint_surfaces_instead_of_dropping_paid_work(monkeypatch):
    for name in ("SectionAnalyzer", "VisualizationPlanner", "ManimGenerator", "CodeValidator",
                 "SpatialValidator", "VoiceoverScriptValidator", "RenderTester"):
        monkeypatch.setattr(pipeline, name, lambda *a, **k: object())

    async def fake_analyze(analyzer, paper):
        return [_cand("Alpha concept", 5)]

    async def fake_generate(candidate, **kw):
        return VizModel(id="tmp", section_id="s1", concept=candidate.concept_name,
                        storyboard="{}", manim_code="from manim import *",
                        video_url=None, status=VisualizationStatus.PENDING)

    async def broken_checkpoint(v):
        raise RuntimeError("db down")

    monkeypatch.setattr(pipeline, "_analyze_all_sections", fake_analyze)
    monkeypatch.setattr(pipeline, "generate_single_visualization", fake_generate)
    with pytest.raises(pipeline.CheckpointError):
        await pipeline.generate_visualizations(_Paper(), on_visualization=broken_checkpoint)


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


async def test_supersede_hides_previous_runs_but_keeps_rows_and_feedback(db):
    await _seed(db)
    db.add(Feedback(id="fb_1", kind="video", viz_id="viz_17060376_1", paper_id="1706.03762", vote="down"))
    await db.commit()
    # The 2026-09-07 run succeeded: everything created before it is retired.
    assert await queries.supersede_visualizations_before(db, "1706.03762", datetime(2026, 9, 7)) == 1
    visible = {r.id for r in await queries.get_visualizations_for_paper(db, "1706.03762")}
    assert visible == {"viz_1706_03762_1", "viz_1706_03762_2"}
    everything = await queries.get_visualizations_for_paper(db, "1706.03762", include_superseded=True)
    assert {r.id: r.status for r in everything}["viz_17060376_1"] == "superseded"
    # The vote still points at the row it was cast on (no FK violation, no data loss).
    fb = (await db.execute(select(Feedback))).scalars().one()
    assert fb.viz_id == "viz_17060376_1"


async def test_run_scoped_checkpoints_and_next_index(db):
    await _seed(db)
    this_run = await queries.get_visualizations_for_paper(db, "1706.03762", since=datetime(2026, 9, 7))
    assert {r.id for r in this_run} == {"viz_1706_03762_1", "viz_1706_03762_2"}
    everything = await queries.get_visualizations_for_paper(db, "1706.03762", include_superseded=True)
    # Ids are never reused: the next new row is _3 even though _1 belongs to an old run.
    assert queries.next_viz_index(everything) == 3


async def test_fail_pending_marks_only_stranded_rows(db):
    await _seed(db)
    assert await queries.fail_pending_visualizations(db, "1706.03762", "died", since=datetime(2026, 9, 7)) == 1
    rows = {r.id: r for r in await queries.get_visualizations_for_paper(db, "1706.03762")}
    assert rows["viz_1706_03762_1"].status == "failed"
    assert rows["viz_1706_03762_2"].status == "complete"
    assert rows["viz_17060376_1"].status == "complete"


# --- every activity the workflow calls must be registered on a worker ---------

def test_every_workflow_activity_is_registered_on_a_worker():
    import inspect

    from temporal_app import activities, worker, workflows

    registered = {fn.__name__ for fn in worker.PIPELINE_ACTIVITIES + worker.RENDER_ACTIVITIES}
    source = inspect.getsource(workflows)
    referenced = {
        name for name, obj in vars(activities).items()
        if callable(obj) and hasattr(obj, "__temporal_activity_definition") and name in source
    }
    assert referenced, "no activities detected in workflows.py — test is broken"
    missing = referenced - registered
    assert not missing, f"activities invoked by the workflow but not registered: {missing}"
