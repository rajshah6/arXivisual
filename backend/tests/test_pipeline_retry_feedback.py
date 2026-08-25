"""Regression test for stale retry feedback in generate_single_visualization.

Bug: per-stage results (validation / spatial / voice / render) were initialized
once before the retry loop and never reset per attempt. If a later attempt failed
at an early gate, the regeneration prompt for the *next* attempt still carried a
gate result from an earlier attempt — feeding the model issues that no longer
applied. The fix resets all four each attempt after feedback is built.

This test drives the real generate_single_visualization with fakes so that:
  attempt 0: stage 1 passes, stage 2 (spatial) FAILS  -> spatial issue recorded
  attempt 1: feedback carries the spatial issue; stage 1 FAILS (syntax)
  attempt 2: feedback must carry ONLY the syntax issue, NOT the stale spatial one
"""

import asyncio

from agents import pipeline
from models.generation import (
    GeneratedCode,
    Scene,
    ValidatorOutput,
    VisualizationCandidate,
    VisualizationPlan,
    VisualizationType,
)
from models.spatial import SpatialValidatorOutput

SPATIAL_MARKER = "SPATIAL ISSUES DETECTED"
SYNTAX_MARKER = "SyntaxError: unexpected token"


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
        scenes=[Scene(order=1, description="beat", duration_seconds=10, transitions="Write", elements=["Text"])],
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
        self.feedback_messages: list[str] = []

    async def run(self, **_kwargs):
        return _code("attempt-0")

    async def run_with_feedback(self, plan, previous_code, error_message, **_kwargs):
        self.feedback_messages.append(error_message)
        return _code(f"attempt-{len(self.feedback_messages)}")


class _FakeValidator:
    """attempt 0 valid, attempt 1 invalid (syntax), rest valid."""

    def __init__(self):
        self.calls = 0

    def validate(self, code):
        self.calls += 1
        if self.calls == 2:
            return ValidatorOutput(
                is_valid=False,
                code=code,
                issues_found=[SYNTAX_MARKER],
                needs_regeneration=True,
            )
        return ValidatorOutput(is_valid=True, code=code, issues_found=[], needs_regeneration=False)


class _FakeSpatial:
    """Always reports a spatial failure when reached (only attempt 0 reaches it)."""

    def validate(self, code):
        return SpatialValidatorOutput(
            has_spatial_issues=True,
            needs_regeneration=True,
            suggestions=["Element off-screen at x=9"],
        )


def test_retry_feedback_drops_stale_gate_results(monkeypatch):
    # Keep the loop in a simple 2-gate configuration: no voiceover, no render test.
    monkeypatch.setattr(pipeline, "ENABLE_VOICEOVER", False)
    monkeypatch.setattr(pipeline, "ENABLE_SPATIAL_VALIDATION", True)

    generator = _FakeGenerator()

    asyncio.run(
        pipeline.generate_single_visualization(
            candidate=_candidate(),
            paper=_FakePaper(),
            planner=_FakePlanner(),
            generator=generator,
            validator=_FakeValidator(),
            spatial_validator=_FakeSpatial(),
            voiceover_script_validator=None,
            render_tester=None,
        )
    )

    # feedback_messages[0] -> attempt 1 (built from attempt 0: spatial failure)
    assert SPATIAL_MARKER in generator.feedback_messages[0]

    # feedback_messages[1] -> attempt 2 (built from attempt 1: syntax failure only).
    # The stale spatial result from attempt 0 must NOT leak in.
    assert SYNTAX_MARKER in generator.feedback_messages[1]
    assert SPATIAL_MARKER not in generator.feedback_messages[1]
