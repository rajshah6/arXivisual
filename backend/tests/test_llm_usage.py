"""Unit tests for the LLM usage seam in agents/base.py.

The eval harness needs tokens and cost per paper next to gate pass rates,
so every Azure call reports its usage through ``base.usage_hook`` (None in
production, exactly like ``pipeline.metrics_hook``). No network: the OpenAI
client is faked.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents import base
from agents.base import LLMUsage, record_usage


def _resp(prompt=100, completion=50, cached=None, reasoning=None, usage=True):
    """Shape of an OpenAI ChatCompletion as far as usage parsing cares."""
    if not usage:
        return SimpleNamespace(usage=None, choices=[])
    prompt_details = None if cached is None else SimpleNamespace(cached_tokens=cached)
    completion_details = (
        None if reasoning is None else SimpleNamespace(reasoning_tokens=reasoning)
    )
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            prompt_tokens_details=prompt_details,
            completion_tokens_details=completion_details,
        ),
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
    )


def test_usage_hook_defaults_to_none():
    assert base.usage_hook is None


def test_record_usage_splits_into_disjoint_buckets(monkeypatch):
    """prompt_tokens includes cached tokens and completion_tokens includes
    reasoning tokens (OpenAI semantics); we report the disjoint buckets that
    Langfuse and the Azure invoice use."""
    seen = []
    monkeypatch.setattr(base, "usage_hook", seen.append)

    usage = record_usage(
        _resp(prompt=100, completion=50, cached=60, reasoning=20),
        name="manim_generator",
        model="gpt-5-mini",
    )

    assert usage == LLMUsage(
        name="manim_generator",
        model="gpt-5-mini",
        input_tokens=40,
        cached_tokens=60,
        output_tokens=30,
        reasoning_tokens=20,
    )
    assert seen == [usage]


def test_record_usage_tolerates_missing_details_and_missing_usage(monkeypatch):
    monkeypatch.setattr(base, "usage_hook", None)

    usage = record_usage(_resp(prompt=10, completion=5), name="x", model="m")
    assert usage.cached_tokens == 0 and usage.reasoning_tokens == 0
    assert usage.input_tokens == 10 and usage.output_tokens == 5

    assert record_usage(_resp(usage=False), name="x", model="m") is None


def test_raising_usage_hook_never_breaks_the_call(monkeypatch):
    def bad_hook(_usage):
        raise RuntimeError("accounting exploded")

    monkeypatch.setattr(base, "usage_hook", bad_hook)
    usage = record_usage(_resp(), name="x", model="m")
    assert usage is not None  # the call's result is unaffected


class _FakeCompletions:
    def __init__(self, resp):
        self._resp = resp
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self._resp


def test_call_llm_reports_usage_for_azure_calls(monkeypatch):
    """The seam is wired into the one place all agent LLM calls go through."""
    completions = _FakeCompletions(_resp(prompt=1500, completion=700, cached=1024, reasoning=300))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(base, "get_provider", lambda: "azure")
    monkeypatch.setattr(base, "_get_azure_client", lambda: fake_client)
    monkeypatch.setattr(base, "_langfuse_enabled", lambda: False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")

    seen = []
    monkeypatch.setattr(base, "usage_hook", seen.append)

    text = asyncio.run(base.call_llm("hello", name="section_analyzer"))

    assert text == "ok"
    [usage] = seen
    assert usage.name == "section_analyzer"
    assert usage.model == "gpt-5-mini"
    assert (usage.input_tokens, usage.cached_tokens) == (476, 1024)
    assert (usage.output_tokens, usage.reasoning_tokens) == (400, 300)
