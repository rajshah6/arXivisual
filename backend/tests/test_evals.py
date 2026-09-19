"""Unit tests for the generation-quality eval harness (backend/evals).

No network, no LLM calls: the pipeline is driven with fakes, and the
report-writing / regression-checking path runs on synthetic metrics.
"""

import asyncio
import contextvars
import json
import os
import sys
import types
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents import pipeline
from agents.base import LLMUsage
from evals import check_regression
from evals.metrics import GateMetrics, UsageMetrics, aggregate_summaries
from evals.run_evals import (
    build_report,
    eval_paper,
    experiment_config,
    load_golden_set,
    print_summary,
)
from models.generation import (
    GeneratedCode,
    Scene,
    ValidatorOutput,
    VisualizationCandidate,
    VisualizationPlan,
    VisualizationType,
)
from models.spatial import SpatialValidatorOutput
from models.voiceover import VoiceoverValidationOutput

BASELINES_PATH = BACKEND_ROOT / "evals" / "baselines.json"


# ---------------------------------------------------------------------------
# GateMetrics: hook counting math
# ---------------------------------------------------------------------------


def _events(trace):
    return [(e.gate, e.attempt, e.passed) for e in trace.events]


def test_hook_splits_traces_on_code_gate_attempt_zero():
    gm = GateMetrics()
    # viz A: clean first-attempt pass through two gates
    gm.hook("code_validator", 0, True)
    gm.hook("spatial_validator", 0, True)
    # viz B: passes only on attempt 2
    gm.hook("code_validator", 0, False)
    gm.hook("code_validator", 1, True)
    gm.hook("spatial_validator", 1, False)
    gm.hook("code_validator", 2, True)
    gm.hook("spatial_validator", 2, True)

    assert len(gm.traces) == 2
    a, b = gm.traces
    assert _events(a) == [("code_validator", 0, True), ("spatial_validator", 0, True)]
    assert a.succeeded and a.attempts_used == 1
    assert b.succeeded and b.attempts_used == 3

    summary = gm.summary()
    assert summary["candidates_run"] == 2
    assert summary["visualizations_validated"] == 2

    code = summary["gates"]["code_validator"]
    assert code == {
        "vizzes_evaluated": 2,
        "first_attempt_evals": 2,
        "first_attempt_passes": 1,
        "eventual_passes": 2,
        "total_evals": 4,
        "attempts_to_pass_total": 3,  # A passes attempt 1, B attempt 2
    }

    spatial = summary["gates"]["spatial_validator"]
    assert spatial == {
        "vizzes_evaluated": 2,
        "first_attempt_evals": 1,  # B never reached spatial on attempt 0
        "first_attempt_passes": 1,
        "eventual_passes": 2,
        "total_evals": 3,
        "attempts_to_pass_total": 4,  # A attempt 1, B attempt 3
    }


def test_exhausted_run_counts_as_not_validated():
    gm = GateMetrics()
    gm.hook("code_validator", 0, True)
    gm.hook("spatial_validator", 0, False)
    gm.hook("code_validator", 1, False)
    gm.hook("code_validator", 2, False)  # retry budget exhausted, last event fails

    [trace] = gm.traces
    assert not trace.succeeded
    summary = gm.summary()
    assert summary["candidates_run"] == 1
    assert summary["visualizations_validated"] == 0
    assert summary["gates"]["code_validator"]["eventual_passes"] == 1
    assert summary["gates"]["spatial_validator"]["eventual_passes"] == 0
    # A gate that never ran is absent from the summary.
    assert "voiceover_script_validator" not in summary["gates"]


def test_hook_separates_concurrent_tasks_via_contexts():
    """Interleaved events from two contexts (as asyncio.gather produces) must
    land in the right trace: each task context keeps its own current-trace
    pointer."""
    gm = GateMetrics()
    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()

    ctx_a.run(gm.hook, "code_validator", 0, True)
    ctx_b.run(gm.hook, "code_validator", 0, False)
    ctx_a.run(gm.hook, "spatial_validator", 0, False)
    ctx_b.run(gm.hook, "code_validator", 1, True)
    ctx_a.run(gm.hook, "code_validator", 1, True)
    ctx_b.run(gm.hook, "spatial_validator", 1, True)
    ctx_a.run(gm.hook, "spatial_validator", 1, True)

    assert len(gm.traces) == 2
    a, b = gm.traces
    assert _events(a) == [
        ("code_validator", 0, True),
        ("spatial_validator", 0, False),
        ("code_validator", 1, True),
        ("spatial_validator", 1, True),
    ]
    assert _events(b) == [
        ("code_validator", 0, False),
        ("code_validator", 1, True),
        ("spatial_validator", 1, True),
    ]
    assert a.succeeded and b.succeeded


def test_aggregate_summaries_math():
    gm = GateMetrics()
    gm.hook("code_validator", 0, True)
    gm.hook("spatial_validator", 0, True)
    gm.hook("code_validator", 0, False)
    gm.hook("code_validator", 1, True)
    gm.hook("spatial_validator", 1, False)
    gm.hook("code_validator", 2, True)
    gm.hook("spatial_validator", 2, True)

    agg = aggregate_summaries([gm.summary()])
    assert agg["papers_evaluated"] == 1
    assert agg["candidates_run"] == 2
    assert agg["visualizations_validated"] == 2
    assert agg["viz_yield_rate"] == 1.0

    code = agg["gates"]["code_validator"]
    assert code["first_attempt_rate"] == 0.5
    assert code["eventual_rate"] == 1.0
    assert code["avg_attempts"] == 1.5

    spatial = agg["gates"]["spatial_validator"]
    assert spatial["first_attempt_rate"] == 1.0
    assert spatial["avg_attempts"] == 2.0


def test_aggregate_summaries_handles_missing_gates_and_empty_input():
    paper_with_spatial = GateMetrics()
    paper_with_spatial.hook("code_validator", 0, True)
    paper_with_spatial.hook("spatial_validator", 0, True)

    paper_without_spatial = GateMetrics()
    paper_without_spatial.hook("code_validator", 0, False)
    paper_without_spatial.hook("code_validator", 1, False)
    paper_without_spatial.hook("code_validator", 2, False)

    agg = aggregate_summaries(
        [paper_with_spatial.summary(), paper_without_spatial.summary()]
    )
    assert agg["viz_yield_rate"] == 0.5
    assert agg["gates"]["spatial_validator"]["vizzes_evaluated"] == 1
    assert agg["gates"]["code_validator"]["first_attempt_rate"] == 0.5
    # code_validator never passed for paper 2 -> avg over the single pass
    assert agg["gates"]["code_validator"]["avg_attempts"] == 1.0

    empty = aggregate_summaries([])
    assert empty["papers_evaluated"] == 0
    assert empty["viz_yield_rate"] is None
    assert empty["gates"] == {}


# ---------------------------------------------------------------------------
# Pipeline seam: metrics_hook wiring (fakes, no LLM)
# ---------------------------------------------------------------------------


def _candidate() -> VisualizationCandidate:
    return VisualizationCandidate(
        section_id="section-1",
        concept_name="Scaled Dot-Product Attention",
        concept_description="Query-key similarity, softmax, value aggregation.",
        visualization_type=VisualizationType.DATA_FLOW,
        priority=5,
        context="Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V",
    )


def _plan() -> VisualizationPlan:
    return VisualizationPlan(
        concept_name="Scaled Dot-Product Attention",
        visualization_type=VisualizationType.DATA_FLOW,
        duration_seconds=30,
        scenes=[
            Scene(
                order=1,
                description="beat",
                duration_seconds=10,
                transitions="Write",
                elements=["Text"],
            )
        ],
        narration_points=[],
    )


def _code(tag: str) -> GeneratedCode:
    return GeneratedCode(
        code=f"# {tag}\nfrom manim import *\n",
        scene_class_name="Viz",
        dependencies=["manim"],
        voiceover_enabled=False,
        narration_lines=[],
        narration_beats=[],
    )


class _FakePaper:
    def get_section_by_id(self, _sid):
        return None

    def get_context(self):
        return "context"


class _FakePlanner:
    async def run(self, candidate, full_section_content, paper_context):
        return _plan()


class _FakeGenerator:
    def __init__(self):
        self.calls = 0

    async def run(self, **_kwargs):
        self.calls += 1
        return _code(f"attempt-{self.calls}")

    async def run_with_feedback(self, **_kwargs):
        self.calls += 1
        return _code(f"attempt-{self.calls}")


class _FlakyValidator:
    """Fails the first N validations, passes afterwards."""

    def __init__(self, fail_first: int = 0):
        self.calls = 0
        self.fail_first = fail_first

    def validate(self, code):
        self.calls += 1
        if self.calls <= self.fail_first:
            return ValidatorOutput(
                is_valid=False,
                code=code,
                issues_found=["SyntaxError: unexpected token"],
                needs_regeneration=True,
            )
        return ValidatorOutput(
            is_valid=True, code=code, issues_found=[], needs_regeneration=False
        )


class _PassingSpatial:
    def validate(self, code):
        return SpatialValidatorOutput(
            has_spatial_issues=False, needs_regeneration=False
        )


class _PassingVoice:
    def validate(self, generated_code, plan, candidate):
        return VoiceoverValidationOutput(
            is_valid=True,
            score_alignment=0.9,
            score_educational=0.9,
            needs_regeneration=False,
        )


def _run_single(monkeypatch, *, voiceover=False, validator=None, voice=None):
    monkeypatch.setattr(pipeline, "ENABLE_VOICEOVER", voiceover)
    return asyncio.run(
        pipeline.generate_single_visualization(
            candidate=_candidate(),
            paper=_FakePaper(),
            planner=_FakePlanner(),
            generator=_FakeGenerator(),
            validator=validator or _FlakyValidator(),
            spatial_validator=_PassingSpatial(),
            voiceover_script_validator=voice,
            render_tester=None,
        )
    )


def test_metrics_hook_defaults_to_none():
    assert pipeline.metrics_hook is None


def test_pipeline_reports_gate_events_through_hook(monkeypatch):
    gm = GateMetrics()
    monkeypatch.setattr(pipeline, "metrics_hook", gm.hook)

    viz = _run_single(monkeypatch, validator=_FlakyValidator(fail_first=1))

    assert viz is not None
    [trace] = gm.traces
    assert _events(trace) == [
        ("code_validator", 0, False),
        ("code_validator", 1, True),
        ("spatial_validator", 1, True),
    ]
    assert trace.succeeded


def test_pipeline_reports_voiceover_gate(monkeypatch):
    gm = GateMetrics()
    monkeypatch.setattr(pipeline, "metrics_hook", gm.hook)

    viz = _run_single(monkeypatch, voiceover=True, voice=_PassingVoice())

    assert viz is not None
    [trace] = gm.traces
    assert _events(trace) == [
        ("code_validator", 0, True),
        ("spatial_validator", 0, True),
        ("voiceover_script_validator", 0, True),
    ]


def test_raising_hook_never_breaks_generation(monkeypatch):
    def bad_hook(gate, attempt, passed):
        raise RuntimeError("metrics exploded")

    monkeypatch.setattr(pipeline, "metrics_hook", bad_hook)
    viz = _run_single(monkeypatch)
    assert viz is not None


# ---------------------------------------------------------------------------
# check_regression: pass/fail logic on synthetic reports
# ---------------------------------------------------------------------------


def _aggregate(**overrides):
    aggregate = {
        "papers_evaluated": 2,
        "candidates_run": 4,
        "visualizations_validated": 3,
        "viz_yield_rate": 0.75,
        "gates": {
            "code_validator": {
                "first_attempt_rate": 0.5,
                "eventual_rate": 1.0,
                "avg_attempts": 1.5,
            },
            "spatial_validator": {
                "first_attempt_rate": 0.75,
                "eventual_rate": 0.75,
                "avg_attempts": 1.2,
            },
            "voiceover_script_validator": {
                "first_attempt_rate": 0.5,
                "eventual_rate": 0.75,
                "avg_attempts": 1.8,
            },
        },
    }
    aggregate.update(overrides)
    return aggregate


def test_evaluate_thresholds_pass_fail_missing_and_max():
    thresholds = {
        "viz_yield_rate": {"min": 0.5},
        "gates.code_validator.eventual_rate": {"min": 0.7},
        "gates.code_validator.avg_attempts": {"max": 2.0},
        "gates.render_tester.eventual_rate": {"min": 0.7},  # gate disabled -> missing
    }
    rows = {
        r["metric"]: r
        for r in check_regression.evaluate_thresholds(_aggregate(), thresholds)
    }
    assert rows["viz_yield_rate"]["ok"]
    assert rows["gates.code_validator.eventual_rate"]["ok"]
    assert rows["gates.code_validator.avg_attempts"]["ok"]
    assert not rows["gates.render_tester.eventual_rate"]["ok"]
    assert "missing" in rows["gates.render_tester.eventual_rate"]["detail"]


def test_evaluate_thresholds_flags_regression_and_bare_numbers():
    rows = check_regression.evaluate_thresholds(
        _aggregate(viz_yield_rate=0.25),
        {"viz_yield_rate": 0.5},  # bare number == minimum
    )
    assert rows == [
        {
            "metric": "viz_yield_rate",
            "constraint": ">= 0.5",
            "actual": 0.25,
            "ok": False,
            "detail": "below minimum 0.5",
        }
    ]


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


def test_check_regression_main_exit_codes(tmp_path, capsys):
    baselines = {"metrics": {"viz_yield_rate": {"min": 0.5}}}
    good = _write(tmp_path, "good.json", {"aggregate": _aggregate()})
    bad = _write(
        tmp_path, "bad.json", {"aggregate": _aggregate(viz_yield_rate=0.1)}
    )
    baselines_path = _write(tmp_path, "baselines.json", baselines)

    assert check_regression.main([good, baselines_path]) == 0
    assert check_regression.main([bad, baselines_path]) == 1
    out = capsys.readouterr()
    assert "REGRESSION" in out.err


def test_check_regression_empty_baselines_fails(tmp_path):
    report = _write(tmp_path, "r.json", {"aggregate": _aggregate()})
    empty = _write(tmp_path, "b.json", {"metrics": {}})
    assert check_regression.main([report, empty]) == 1


# ---------------------------------------------------------------------------
# End to end (mocked metrics): report writing -> regression check
# ---------------------------------------------------------------------------


def _paper_result(arxiv_id: str, gm: GateMetrics, error=None) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "title": "t",
        "why": "w",
        "error": error,
        "wall_clock_seconds": 12.3,
        "visualizations_returned": len(gm.traces),
        **gm.summary(),
    }


def _usage_summary(cost_per_call_usd: float, calls: int = 4) -> dict:
    """A UsageMetrics summary costing exactly cost_per_call_usd per call."""
    um = UsageMetrics(prices={"m": {"input": 0.0, "cached_input": 0.0, "output": 1.0}})
    for _ in range(calls):
        um.hook(_usage("manim_generator", "m", 0, 0, int(cost_per_call_usd * 1_000_000), 0))
    return um.summary()


def test_report_writing_and_regression_check_end_to_end(tmp_path):
    """GateMetrics -> build_report -> report.json -> check_regression against
    the REAL baselines.json — the exact chain the CI workflow runs."""
    healthy = GateMetrics()
    for _ in range(2):  # two vizzes, all LLM gates pass first attempt
        healthy.hook("code_validator", 0, True)
        healthy.hook("spatial_validator", 0, True)
        healthy.hook("voiceover_script_validator", 0, True)

    errored = GateMetrics()  # ingestion failed: no events, error recorded

    # Measured 2026-09-07 on the golden set: $0.023 per validated viz at low
    # reasoning effort, $0.038 at medium.
    healthy_usage = _usage_summary(cost_per_call_usd=0.01)  # $0.04 / 2 viz = $0.02 each
    report = build_report(
        [
            {**_paper_result("1706.03762", healthy), "usage": healthy_usage},
            _paper_result("9999.99999", errored, error="ValueError: not found"),
        ],
        max_viz=2,
    )
    # Errored papers are excluded from the aggregate.
    assert report["aggregate"]["papers_evaluated"] == 1
    assert report["aggregate"]["viz_yield_rate"] == 1.0

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report, indent=2))

    assert check_regression.main([str(report_path), str(BASELINES_PATH)]) == 0

    # Now degrade code quality below the baseline floor and expect a failure.
    degraded = GateMetrics()
    degraded.hook("code_validator", 0, False)
    degraded.hook("code_validator", 1, False)
    degraded.hook("code_validator", 2, False)
    bad_report = build_report(
        [{**_paper_result("1706.03762", degraded), "usage": healthy_usage}], max_viz=2
    )
    bad_path = tmp_path / "bad_report.json"
    bad_path.write_text(json.dumps(bad_report))
    assert check_regression.main([str(bad_path), str(BASELINES_PATH)]) == 1

    # Same quality as the healthy run but 5x the cost per validated viz must
    # ALSO fail: a change that doubles tokens per paper is a regression.
    expensive = build_report(
        [{**_paper_result("1706.03762", healthy), "usage": _usage_summary(cost_per_call_usd=0.05)}],
        max_viz=2,
    )
    assert expensive["aggregate"]["cost_per_validated_viz_usd"] == 0.1
    expensive_path = tmp_path / "expensive_report.json"
    expensive_path.write_text(json.dumps(expensive))
    assert check_regression.main([str(expensive_path), str(BASELINES_PATH)]) == 1


def test_golden_set_shape_and_limit():
    entries = load_golden_set()
    assert len(entries) == 8
    for entry in entries:
        assert entry["arxiv_id"] and entry["why"]
    assert [e["arxiv_id"] for e in load_golden_set(3)] == [
        e["arxiv_id"] for e in entries[:3]
    ]


# ---------------------------------------------------------------------------
# UsageMetrics: tokens and dollars next to pass rates
# ---------------------------------------------------------------------------


def _usage(name, model, inp, cached, out, reasoning):
    return LLMUsage(
        name=name,
        model=model,
        input_tokens=inp,
        cached_tokens=cached,
        output_tokens=out,
        reasoning_tokens=reasoning,
    )


def test_usage_metrics_prices_disjoint_buckets_per_million():
    prices = {"gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.0}}
    um = UsageMetrics(prices=prices)
    um.hook(_usage("manim_generator", "gpt-5-mini", 1_000_000, 1_000_000, 500_000, 500_000))
    um.hook(_usage("section_analyzer", "gpt-5-mini", 0, 0, 0, 0))

    summary = um.summary()
    assert summary["llm_calls"] == 2
    assert summary["tokens"] == {
        "input": 1_000_000,
        "cached_input": 1_000_000,
        "output": 500_000,
        "reasoning": 500_000,
    }
    # 0.25 + 0.025 + (0.5M + 0.5M reasoning) * 2.0/M = 2.275
    assert summary["cost_usd"] == 2.275
    assert summary["unpriced_calls"] == 0
    assert summary["by_name"]["manim_generator"]["calls"] == 1
    assert summary["by_name"]["manim_generator"]["cost_usd"] == 2.275
    assert summary["by_name"]["section_analyzer"]["cost_usd"] == 0.0


def test_usage_metrics_counts_unpriced_models_instead_of_hiding_them():
    """An unknown model must be visible as unpriced, not silently cost $0 —
    that is exactly how gpt-5.6-sol went unbilled in Langfuse."""
    um = UsageMetrics(prices={"gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.0}})
    um.hook(_usage("visual_qa_judge", "gpt-5.6-sol-2026-07-09", 1000, 0, 100, 400))

    summary = um.summary()
    assert summary["unpriced_calls"] == 1
    assert summary["cost_usd"] == 0.0
    assert summary["by_name"]["visual_qa_judge"]["unpriced_calls"] == 1


def test_usage_metrics_default_prices_cover_production_models():
    um = UsageMetrics()
    um.hook(_usage("a", "gpt-5-mini", 1000, 1000, 100, 100))
    um.hook(_usage("b", "gpt-5-mini-2025-08-07", 1000, 1000, 100, 100))
    um.hook(_usage("c", "gpt-5.6-sol", 1000, 1000, 100, 100))
    um.hook(_usage("d", "gpt-5.6-sol-2026-07-09", 1000, 1000, 100, 100))
    assert um.summary()["unpriced_calls"] == 0


def test_aggregate_summaries_reports_cost_per_paper_and_per_validated_viz():
    gm = GateMetrics()
    gm.hook("code_validator", 0, True)
    gm.hook("spatial_validator", 0, True)
    gm.hook("code_validator", 0, True)
    gm.hook("spatial_validator", 0, False)
    gm.hook("code_validator", 1, False)
    gm.hook("code_validator", 2, False)  # second viz never validates
    um = UsageMetrics(prices={"m": {"input": 1.0, "cached_input": 0.1, "output": 10.0}})
    um.hook(_usage("manim_generator", "m", 1_000_000, 0, 100_000, 0))  # $2.00

    paper = {**gm.summary(), "usage": um.summary()}
    agg = aggregate_summaries([paper, paper])

    assert agg["visualizations_validated"] == 2
    assert agg["cost_usd"] == 4.0
    assert agg["cost_per_paper_usd"] == 2.0
    assert agg["cost_per_validated_viz_usd"] == 2.0
    assert agg["llm_calls"] == 2
    assert agg["tokens"]["input"] == 2_000_000
    assert agg["unpriced_calls"] == 0


def test_aggregate_summaries_without_usage_keeps_cost_fields_null():
    gm = GateMetrics()
    gm.hook("code_validator", 0, True)
    agg = aggregate_summaries([gm.summary()])
    assert agg["cost_usd"] is None
    assert agg["cost_per_paper_usd"] is None


def test_build_report_records_experiment_config():
    report = build_report([], max_viz=2, extra_config={"reasoning_effort": "low"})
    assert report["config"]["reasoning_effort"] == "low"
    assert report["config"]["max_visualizations"] == 2


def test_eval_paper_attaches_usage_hook_only_for_the_duration(monkeypatch):
    """eval_paper must capture LLM usage from the pipeline run into the paper
    result and leave base.usage_hook as it found it."""
    from agents import base

    async def fake_ingest(arxiv_id, force_refresh=False):
        return object()

    async def fake_generate(paper, max_visualizations):
        # the pipeline's LLM calls report through base.record_usage
        base.record_usage(
            _fake_openai_response(prompt=2000, completion=800, cached=1500, reasoning=300),
            name="manim_generator",
            model="gpt-5-mini",
        )
        return ["viz"]

    fake_pipeline = types.SimpleNamespace(
        metrics_hook=None, generate_visualizations=fake_generate
    )
    assert base.usage_hook is None
    result = asyncio.run(
        eval_paper({"arxiv_id": "1706.03762"}, 2, fake_pipeline, fake_ingest)
    )
    assert base.usage_hook is None
    assert result["visualizations_returned"] == 1
    assert result["usage"]["llm_calls"] == 1
    assert result["usage"]["tokens"] == {
        "input": 500,
        "cached_input": 1500,
        "output": 500,
        "reasoning": 300,
    }
    assert result["usage"]["cost_usd"] > 0


def test_experiment_config_applies_reasoning_effort_and_records_arm(monkeypatch):
    """The A/B arm must be both applied to the run and written into the report."""
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "medium")

    config = experiment_config(reasoning_effort="low", tag="e1-low")
    assert os.environ["AZURE_OPENAI_REASONING_EFFORT"] == "low"
    assert config == {"reasoning_effort": "low", "tag": "e1-low", "deployment": "gpt-5-mini"}

    # No override: record the effective value, do not touch the env.
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "high")
    config = experiment_config(reasoning_effort=None, tag=None)
    assert os.environ["AZURE_OPENAI_REASONING_EFFORT"] == "high"
    assert config["reasoning_effort"] == "high"
    assert config["tag"] is None


def test_print_summary_shows_cost_per_paper_and_unpriced_calls(capsys):
    gm = GateMetrics()
    gm.hook("code_validator", 0, True)
    um = UsageMetrics(prices={"m": {"input": 1.0, "cached_input": 0.1, "output": 10.0}})
    um.hook(_usage("manim_generator", "m", 1_000_000, 0, 0, 0))
    um.hook(_usage("visual_qa_judge", "unknown-model", 10, 0, 1, 0))
    paper = {**_paper_result("1706.03762", gm), "usage": um.summary()}

    print_summary(build_report([paper], max_viz=2))
    out = capsys.readouterr().out
    assert "cost_per_paper_usd=1.0" in out
    assert "unpriced_calls=1" in out


def test_eval_paper_records_tag_in_result(monkeypatch):
    async def fake_ingest(arxiv_id, force_refresh=False):
        return object()

    async def fake_generate(paper, max_visualizations):
        return []

    fake_pipeline = types.SimpleNamespace(metrics_hook=None, generate_visualizations=fake_generate)
    result = asyncio.run(
        eval_paper({"arxiv_id": "1706.03762"}, 2, fake_pipeline, fake_ingest, tag="e1-low")
    )
    assert result["tag"] == "e1-low"


def _fake_openai_response(prompt, completion, cached, reasoning):
    return types.SimpleNamespace(
        usage=types.SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            prompt_tokens_details=types.SimpleNamespace(cached_tokens=cached),
            completion_tokens_details=types.SimpleNamespace(reasoning_tokens=reasoning),
        ),
        choices=[],
    )
