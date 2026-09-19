"""Reasoning effort must be tunable per call type, not one global env var.

Production evidence: reasoning tokens are 36% of the generator's output, 53%
of the planner's, 60% of the analyzer's and 82% of the judge's (whose visible
answer is ~93 tokens). AZURE_OPENAI_REASONING_EFFORT applies to every agent
call at once, and the judge/repair calls in agents/visual_qa.py pass no
effort at all (API default). Experiments need to move them independently.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents import base, visual_qa


def test_request_kwargs_default_effort_comes_from_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "medium")
    kwargs = base._azure_request_kwargs("gpt-5-mini", "p", "", 100)
    assert kwargs["reasoning_effort"] == "medium"


def test_request_kwargs_explicit_effort_overrides_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "medium")
    kwargs = base._azure_request_kwargs("gpt-5-mini", "p", "", 100, reasoning_effort="low")
    assert kwargs["reasoning_effort"] == "low"


class _Completions:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=None
        )


def _fake_azure(monkeypatch, module):
    completions = _Completions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(module, "get_provider", lambda: "azure")
    monkeypatch.setattr(module, "_get_azure_client", lambda: client)
    return completions


def test_call_llm_passes_reasoning_effort_through(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "medium")
    monkeypatch.setattr(base, "_langfuse_enabled", lambda: False)
    completions = _fake_azure(monkeypatch, base)

    asyncio.run(base.call_llm("hello", reasoning_effort="minimal"))

    assert completions.kwargs["reasoning_effort"] == "minimal"


def test_judge_effort_is_env_tunable_and_absent_by_default(monkeypatch):
    """No env -> no reasoning_effort key (today's API-default behavior);
    VISUAL_QA_JUDGE_REASONING_EFFORT -> passed on the judge call only."""
    monkeypatch.setattr(visual_qa, "sample_frames", lambda video_bytes, count=3: [b"png"])
    monkeypatch.delenv("VISUAL_QA_JUDGE_REASONING_EFFORT", raising=False)
    completions = _fake_azure(monkeypatch, visual_qa)

    asyncio.run(visual_qa.judge_video(b"video"))
    assert "reasoning_effort" not in completions.kwargs

    monkeypatch.setenv("VISUAL_QA_JUDGE_REASONING_EFFORT", "low")
    asyncio.run(visual_qa.judge_video(b"video"))
    assert completions.kwargs["reasoning_effort"] == "low"


def test_repair_effort_is_env_tunable_independently_of_the_judge(monkeypatch):
    monkeypatch.setattr(visual_qa, "sample_frames", lambda video_bytes, count=3: [b"png"])
    monkeypatch.setenv("VISUAL_QA_JUDGE_REASONING_EFFORT", "low")
    monkeypatch.setenv("VISUAL_QA_REPAIR_REASONING_EFFORT", "high")
    completions = _fake_azure(monkeypatch, visual_qa)

    asyncio.run(visual_qa.repair_code_with_frames("code", ["overlap"], b"video"))

    assert completions.kwargs["reasoning_effort"] == "high"
