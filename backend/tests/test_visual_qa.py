"""Unit tests for the visual QA judge (no network, no ffmpeg)."""

import asyncio

from agents import visual_qa
from agents.visual_qa import VisualQAResult, _parse_verdict


def test_parse_clean_json():
    v = _parse_verdict(
        '{"overlap": true, "cutoff": false, "collisions": true, '
        '"severity": "major", "issues": ["labels overlap arrows"]}'
    )
    assert v.overlap is True
    assert v.cutoff is False
    assert v.collisions is True
    assert v.severity == "major"
    assert v.has_defects
    assert v.issues == ["labels overlap arrows"]


def test_parse_fenced_json():
    v = _parse_verdict(
        'Here is my assessment:\n```json\n{"overlap": false, "cutoff": false, '
        '"collisions": false, "severity": "none", "issues": []}\n```'
    )
    assert v.severity == "none"
    assert not v.has_defects


def test_parse_json_embedded_in_prose():
    v = _parse_verdict(
        'The frame looks mostly fine. {"overlap": false, "cutoff": true, '
        '"collisions": false, "severity": "minor", "issues": ["left box clipped"]}'
    )
    assert v.cutoff is True
    assert v.severity == "minor"


def test_parse_garbage_degrades_to_clean_verdict():
    # Unparseable judge output must not raise and must not block anything.
    v = _parse_verdict("I could not analyse the image, sorry!")
    assert isinstance(v, VisualQAResult)
    assert v.severity == "none"
    assert not v.has_defects


def test_contradictory_none_severity_is_upgraded_to_minor():
    # Judge sets defect flags but claims severity "none" — trust the flags so
    # the defect isn't scored as clean (CodeRabbit regression, PR #28).
    v = _parse_verdict(
        '{"overlap": true, "cutoff": false, "collisions": false, '
        '"severity": "none", "issues": ["title overlaps box"]}'
    )
    assert v.severity == "minor"
    assert v.has_defects


def test_parse_invalid_severity_is_derived_from_flags():
    v = _parse_verdict(
        '{"overlap": true, "cutoff": false, "collisions": false, '
        '"severity": "catastrophic", "issues": ["x"]}'
    )
    assert v.severity == "minor"  # derived: defect flags set, unknown severity


def test_issue_list_is_capped():
    issues = [f"issue {i}" for i in range(25)]
    v = _parse_verdict(
        '{"overlap": true, "cutoff": false, "collisions": false, '
        f'"severity": "major", "issues": {issues!r}}}'.replace("'", '"')
    )
    assert len(v.issues) == 10


def test_judge_video_skips_non_azure_provider(monkeypatch):
    monkeypatch.setattr(visual_qa, "get_provider", lambda: "dedalus")
    result = asyncio.run(visual_qa.judge_video(b"not-a-video"))
    assert result is None


def test_judge_video_survives_ffmpeg_failure(monkeypatch):
    # Azure provider but frame sampling explodes -> None, never raises.
    monkeypatch.setattr(visual_qa, "get_provider", lambda: "azure")

    def boom(video_bytes, count=3):
        raise RuntimeError("ffprobe failed")

    monkeypatch.setattr(visual_qa, "sample_frames", boom)
    result = asyncio.run(visual_qa.judge_video(b"not-a-video"))
    assert result is None


def _fake_client(content: str, prompt=1000, completion=500, cached=0, reasoning=400):
    """Azure client fake: records the create() kwargs, returns a response with usage."""
    from types import SimpleNamespace

    class _Completions:
        def __init__(self):
            self.kwargs = None

        async def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=SimpleNamespace(
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
                ),
            )

    completions = _Completions()
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def test_judge_reports_usage_through_the_shared_seam(monkeypatch):
    """Judge calls bypass call_llm, so they must report usage themselves or
    the eval harness cannot cost the QA loop."""
    from agents import base

    monkeypatch.setattr(visual_qa, "get_provider", lambda: "azure")
    monkeypatch.setattr(visual_qa, "sample_frames", lambda video_bytes, count=3: [b"png"])
    monkeypatch.setattr(visual_qa, "VISUAL_QA_MODEL", "gpt-5-mini")
    client, _ = _fake_client('{"overlap": true, "severity": "major", "issues": ["x"]}')
    monkeypatch.setattr(visual_qa, "_get_azure_client", lambda: client)
    seen = []
    monkeypatch.setattr(base, "usage_hook", seen.append)

    verdict = asyncio.run(visual_qa.judge_video(b"video", viz_id="viz_1"))

    assert verdict is not None and verdict.severity == "major"
    [usage] = seen
    assert usage.name == "visual_qa_judge"
    assert usage.model == "gpt-5-mini"
    assert (usage.output_tokens, usage.reasoning_tokens) == (100, 400)


def test_repair_reports_usage_through_the_shared_seam(monkeypatch):
    from agents import base

    monkeypatch.setattr(visual_qa, "get_provider", lambda: "azure")
    monkeypatch.setattr(visual_qa, "sample_frames", lambda video_bytes, count=3: [b"png"])
    monkeypatch.setattr(visual_qa, "VISUAL_QA_REPAIR_MODEL", "gpt-5-mini")
    client, _ = _fake_client("from manim import *", prompt=6000, completion=5000, reasoning=2000)
    monkeypatch.setattr(visual_qa, "_get_azure_client", lambda: client)
    seen = []
    monkeypatch.setattr(base, "usage_hook", seen.append)

    out = asyncio.run(visual_qa.repair_code_with_frames("code", ["overlap"], b"video"))

    assert out == "from manim import *"
    [usage] = seen
    assert usage.name == "visual_qa_repair_vision"
    assert (usage.input_tokens, usage.output_tokens, usage.reasoning_tokens) == (6000, 3000, 2000)


class TestVisionGroundedRepair:
    """v2 repair: the model sees the defect frames; text-only is the fallback."""

    def test_non_azure_provider_returns_none(self, monkeypatch):
        monkeypatch.setattr(visual_qa, "get_provider", lambda: "dedalus")
        out = asyncio.run(
            visual_qa.repair_code_with_frames("code", ["overlap"], b"video")
        )
        assert out is None

    def test_frame_sampling_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(visual_qa, "get_provider", lambda: "azure")

        def boom(video_bytes, count=3):
            raise RuntimeError("ffprobe failed")

        monkeypatch.setattr(visual_qa, "sample_frames", boom)
        out = asyncio.run(
            visual_qa.repair_code_with_frames("code", ["overlap"], b"video")
        )
        assert out is None

    def test_prompt_includes_issues_code_and_contract(self):
        text = visual_qa.REPAIR_VISION_PROMPT.format(
            issues="- labels overlap arrows",
            code="from manim import *",
            contract=visual_qa.REPAIR_OUTPUT_CONTRACT,
        )
        assert "labels overlap arrows" in text
        assert "from manim import *" in text
        # The prompt must tell the model to trust the pixels over the list.
        assert "trust the pixels" in text
        # The shared output contract (one place to edit) must arrive intact.
        assert "PRESERVE the narration text" in text
        assert text.rstrip().endswith("No markdown, no prose.")
