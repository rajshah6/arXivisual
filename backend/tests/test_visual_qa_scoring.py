"""Visual QA verdicts must land in Langfuse as scores on a trace that exists.

Production evidence: 106 ``visual_qa_defect`` scores for ~4,400 judge calls in
one week, because ``score_current_trace`` was called with no current
observation inside the Temporal render activity. The judge must run inside a
Langfuse span, and a post-repair re-judge must record whether the repair fixed
the defect, or the repair loop's value cannot be measured.

No network: Langfuse's client and the judge are faked.
"""

import asyncio
import contextlib
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import langfuse

import rendering
from agents import visual_qa
from agents.visual_qa import VisualQAResult


class _FakeLangfuse:
    """Records spans and scores the way rendering._judge_and_score uses them."""

    def __init__(self, fail: bool = False):
        self.spans: list[dict] = []
        self.scores: list[dict] = []
        self.fail = fail

    @contextlib.contextmanager
    def start_as_current_observation(self, **kwargs):
        if self.fail:
            raise RuntimeError("langfuse down")
        self.spans.append(kwargs)
        yield object()

    def score_current_trace(self, **kwargs):
        if self.fail:
            raise RuntimeError("langfuse down")
        self.scores.append(kwargs)

    def score_current_span(self, **kwargs):
        self.score_current_trace(**kwargs)


def _verdict(severity: str) -> VisualQAResult:
    return VisualQAResult(
        overlap=severity != "none",
        severity=severity,
        issues=["title overlaps axis"] if severity != "none" else [],
        judge_model="gpt-5-mini",
        frames_checked=3,
    )


def _wire(monkeypatch, severity: str, fake: _FakeLangfuse):
    async def fake_judge(video_bytes, viz_id=""):
        return _verdict(severity)

    monkeypatch.setattr(visual_qa, "judge_video", fake_judge)
    monkeypatch.setattr(langfuse, "get_client", lambda: fake)


def _scores_by_name(fake: _FakeLangfuse) -> dict:
    return {s["name"]: s for s in fake.scores}


def test_judge_runs_inside_a_langfuse_span_and_scores_the_verdict(monkeypatch):
    fake = _FakeLangfuse()
    _wire(monkeypatch, "major", fake)

    verdict = asyncio.run(rendering._judge_and_score("viz_2306_14048_2", b"mp4"))

    assert verdict is not None and verdict.severity == "major"
    [span] = fake.spans
    assert span["as_type"] == "span" and span["name"] == "visual-qa"
    assert span["metadata"]["viz_id"] == "viz_2306_14048_2"

    scores = _scores_by_name(fake)
    assert scores["visual_qa_defect"]["value"] == 1
    assert scores["visual_qa_defect"]["data_type"] == "BOOLEAN"
    assert "title overlaps axis" in scores["visual_qa_defect"]["comment"]
    assert scores["visual_qa_severity"]["value"] == "major"
    assert scores["visual_qa_severity"]["data_type"] == "CATEGORICAL"
    assert "visual_qa_repair_fixed" not in scores


def test_clean_verdict_scores_zero_defect(monkeypatch):
    fake = _FakeLangfuse()
    _wire(monkeypatch, "none", fake)

    asyncio.run(rendering._judge_and_score("viz_1", b"mp4"))

    scores = _scores_by_name(fake)
    assert scores["visual_qa_defect"]["value"] == 0
    assert scores["visual_qa_severity"]["value"] == "none"


def test_rejudge_after_repair_records_whether_the_repair_fixed_it(monkeypatch):
    """Fixed means the workflow's own definition: no longer 'major'."""
    fixed = _FakeLangfuse()
    _wire(monkeypatch, "minor", fixed)
    asyncio.run(rendering._judge_and_score("viz_1", b"mp4", is_repair=True))
    assert _scores_by_name(fixed)["visual_qa_repair_fixed"]["value"] == 1
    assert fixed.spans[0]["metadata"]["is_repair"] == "1"

    still_broken = _FakeLangfuse()
    _wire(monkeypatch, "major", still_broken)
    asyncio.run(rendering._judge_and_score("viz_1", b"mp4", is_repair=True))
    assert _scores_by_name(still_broken)["visual_qa_repair_fixed"]["value"] == 0


def test_langfuse_failure_never_hides_the_verdict(monkeypatch):
    _wire(monkeypatch, "major", _FakeLangfuse(fail=True))
    verdict = asyncio.run(rendering._judge_and_score("viz_1", b"mp4"))
    assert verdict is not None and verdict.severity == "major"
