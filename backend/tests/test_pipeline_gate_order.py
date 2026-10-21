"""The free dry-run render gate runs before the paid voiceover judge.

Oct 1-19 2026: 3,393 of the 8,680 voiceover-judge LLM calls (39%, ~CA$15/mo)
were spent on code that then failed the ~0.2 s RenderTester dry run, because
the judge ran as stage 3 and the render test as stage 4. Every gate keeps its
verdict and the combined-feedback regeneration loop is untouched; only the
order changed, so a render failure must now skip the judge entirely and its
error must still reach the next attempt's feedback.

Drives the real generate_single_visualization with fakes (no LLM, no manim).
"""

import asyncio

from agents import pipeline
from agents.render_tester import RenderTestOutput
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

RENDER_ERROR = "unexpected keyword argument 'buff'"


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
        dependencies=["manim", "manim_voiceover"],
        voiceover_enabled=True,
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
        self.feedback_messages: list[str] = []

    async def run(self, **_kwargs):
        self.calls += 1
        return _code(f"attempt-{self.calls}")

    async def run_with_feedback(self, plan, previous_code, error_message, **_kwargs):
        self.calls += 1
        self.feedback_messages.append(error_message)
        return _code(f"attempt-{self.calls}")


class _Validator:
    """Fails the first N validations, passes afterwards."""

    def __init__(self, fail_first: int = 0):
        self.calls = 0
        self.fail_first = fail_first

    def validate(self, code):
        self.calls += 1
        if self.calls <= self.fail_first:
            return ValidatorOutput(
                is_valid=False, code=code, issues_found=["No Scene class found"], needs_regeneration=True
            )
        return ValidatorOutput(is_valid=True, code=code, issues_found=[], needs_regeneration=False)


class _PassingSpatial:
    def validate(self, code):
        return SpatialValidatorOutput(has_spatial_issues=False, needs_regeneration=False)


class _RenderGate:
    """Fails the first N dry runs with a real production error, passes afterwards."""

    def __init__(self, fail_first: int = 0):
        self.calls = 0
        self.fail_first = fail_first

    async def test_render(self, code, scene_class=None):
        self.calls += 1
        if self.calls <= self.fail_first:
            return RenderTestOutput(
                success=False,
                error_type="TypeError",
                error_message=RENDER_ERROR,
                fix_suggestion="`buff` is NOT a constructor argument.",
            )
        return RenderTestOutput(success=True)


class _Judge:
    """The paid gate: counts how often it is consulted."""

    def __init__(self, passes: bool = True):
        self.calls = 0
        self.passes = passes

    def validate(self, generated_code, plan, candidate):
        self.calls += 1
        return VoiceoverValidationOutput(
            is_valid=self.passes,
            issues_found=[] if self.passes else ["Narration 1 starts with animation command style wording."],
            score_alignment=0.9,
            score_educational=0.9,
            needs_regeneration=not self.passes,
        )


def _run(monkeypatch, *, generator, validator, render, judge):
    events: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(pipeline, "ENABLE_VOICEOVER", True)
    monkeypatch.setattr(pipeline, "metrics_hook", lambda gate, attempt, passed: events.append((gate, attempt, passed)))
    viz = asyncio.run(
        pipeline.generate_single_visualization(
            candidate=_candidate(),
            paper=_FakePaper(),
            planner=_FakePlanner(),
            generator=generator,
            validator=validator,
            spatial_validator=_PassingSpatial(),
            voiceover_script_validator=judge,
            render_tester=render,
        )
    )
    return viz, events


def test_render_gate_failure_skips_the_paid_judge(monkeypatch):
    generator, render, judge = _FakeGenerator(), _RenderGate(fail_first=1), _Judge()

    viz, events = _run(monkeypatch, generator=generator, validator=_Validator(), render=render, judge=judge)

    assert viz is not None
    # Attempt 0 died at the render gate without consulting the judge; attempt 1
    # reached it. One judge call for two attempts, not two.
    assert render.calls == 2
    assert judge.calls == 1
    assert events == [
        ("code_validator", 0, True),
        ("spatial_validator", 0, True),
        ("render_tester", 0, False),
        ("code_validator", 1, True),
        ("spatial_validator", 1, True),
        ("render_tester", 1, True),
        ("voiceover_script_validator", 1, True),
    ]


def test_render_error_still_drives_the_next_attempt(monkeypatch):
    generator, render = _FakeGenerator(), _RenderGate(fail_first=1)

    _run(monkeypatch, generator=generator, validator=_Validator(), render=render, judge=_Judge())

    # The regeneration prompt carries the dry-run error exactly as before the reorder.
    [feedback] = generator.feedback_messages
    assert "RUNTIME ERROR DETECTED" in feedback
    assert RENDER_ERROR in feedback


def test_judge_runs_last_when_every_gate_passes(monkeypatch):
    judge = _Judge()

    viz, events = _run(monkeypatch, generator=_FakeGenerator(), validator=_Validator(), render=_RenderGate(), judge=judge)

    assert viz is not None and judge.calls == 1
    assert [gate for gate, _attempt, _passed in events] == [
        "code_validator",
        "spatial_validator",
        "render_tester",
        "voiceover_script_validator",
    ]
