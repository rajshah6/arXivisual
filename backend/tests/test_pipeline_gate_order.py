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
    VisualizationStatus,
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


ALWAYS = range(1, 1000)


class _RenderGate:
    """Fails the dry runs numbered in ``fail_on`` (1-based) with a real production error."""

    def __init__(self, fail_on=()):
        self.calls = 0
        self.fail_on = set(fail_on)

    async def test_render(self, code, scene_class=None):
        self.calls += 1
        if self.calls in self.fail_on:
            return RenderTestOutput(
                success=False,
                error_type="TypeError",
                error_message=RENDER_ERROR,
                fix_suggestion="`buff` is NOT a constructor argument.",
            )
        return RenderTestOutput(success=True)


class _Judge:
    """The paid gate: counts how often it is consulted; fails the calls in ``fail_on``."""

    def __init__(self, fail_on=()):
        self.calls = 0
        self.fail_on = set(fail_on)

    def validate(self, generated_code, plan, candidate):
        self.calls += 1
        passes = self.calls not in self.fail_on
        return VoiceoverValidationOutput(
            is_valid=passes,
            issues_found=[] if passes else ["Narration 1 starts with animation command style wording."],
            score_alignment=0.9,
            score_educational=0.9,
            needs_regeneration=not passes,
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
    generator, render, judge = _FakeGenerator(), _RenderGate(fail_on={1}), _Judge()

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
    generator, render = _FakeGenerator(), _RenderGate(fail_on={1})

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


# ---------------------------------------------------------------------------
# VOICE_FAIL_BEHAVIOR=return_silent after every attempt failed
# ---------------------------------------------------------------------------
# The fallback exists for narration the judge never accepted. It used to ship
# the last attempt's code whatever gate it failed, so code that had just failed
# the structural check or the dry run went to the renderer anyway: TTS billed
# for the beats before the crash, a render slot held, a failed row written —
# 562 times Oct 1-19 2026. Only the LAST attempt's gate decides.

MAX_ATTEMPTS = pipeline.MAX_RETRIES + pipeline.VOICE_QUALITY_RETRIES


def test_code_that_failed_the_render_gate_on_every_attempt_is_dropped(monkeypatch):
    monkeypatch.setattr(pipeline, "VOICE_FAIL_BEHAVIOR", "return_silent")
    generator, judge = _FakeGenerator(), _Judge()

    viz, _events = _run(monkeypatch, generator=generator, validator=_Validator(), render=_RenderGate(fail_on=ALWAYS), judge=judge)

    assert viz is None
    assert generator.calls == MAX_ATTEMPTS  # the retry budget is unchanged
    assert judge.calls == 0  # and none of it paid for a judge verdict


def test_code_that_failed_the_structural_gate_on_every_attempt_is_dropped(monkeypatch):
    monkeypatch.setattr(pipeline, "VOICE_FAIL_BEHAVIOR", "return_silent")

    viz, _events = _run(
        monkeypatch, generator=_FakeGenerator(), validator=_Validator(fail_first=MAX_ATTEMPTS), render=_RenderGate(), judge=_Judge()
    )

    assert viz is None


def test_narration_only_failure_still_ships_the_silent_visualization(monkeypatch):
    monkeypatch.setattr(pipeline, "VOICE_FAIL_BEHAVIOR", "return_silent")
    generator, render = _FakeGenerator(), _RenderGate()

    viz, _events = _run(monkeypatch, generator=generator, validator=_Validator(), render=render, judge=_Judge(fail_on=ALWAYS))

    # Renderable code whose narration the judge never accepted: the existing
    # policy, unchanged — the last attempt ships and renders silent.
    assert viz is not None
    assert viz.status == VisualizationStatus.PENDING
    assert f"# attempt-{MAX_ATTEMPTS}" in viz.manim_code
    assert render.calls == generator.calls == MAX_ATTEMPTS


def test_only_the_last_attempt_decides(monkeypatch):
    monkeypatch.setattr(pipeline, "VOICE_FAIL_BEHAVIOR", "return_silent")

    # Judge rejected attempts 1-4, then attempt 5 crashed in the dry run: dropped.
    viz, _events = _run(
        monkeypatch, generator=_FakeGenerator(), validator=_Validator(), render=_RenderGate(fail_on={MAX_ATTEMPTS}), judge=_Judge(fail_on=ALWAYS)
    )
    assert viz is None

    # Attempt 1 crashed in the dry run, attempts 2-5 rendered but the judge
    # rejected their narration: the last attempt is renderable, so it ships.
    viz, _events = _run(
        monkeypatch, generator=_FakeGenerator(), validator=_Validator(), render=_RenderGate(fail_on={1}), judge=_Judge(fail_on=ALWAYS)
    )
    assert viz is not None
