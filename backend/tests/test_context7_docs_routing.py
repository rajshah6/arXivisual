"""Regression tests for provider routing in get_manim_docs.

The Dedalus doc path must be selected only when explicitly requested AND the
resolved LLM provider is Dedalus. The direct Context7 REST path (and the static
fallback) must keep working even when no provider is configured — resolving the
provider eagerly there previously raised RuntimeError and broke the independent
docs path (CodeRabbit finding on PR #15).
"""

import asyncio

import pytest

from agents import context7_docs


@pytest.fixture(autouse=True)
def _no_provider(monkeypatch):
    # No LLM provider configured -> base.get_provider() would raise RuntimeError.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("DEDALUS_API_KEY", raising=False)


def _stub_docs(monkeypatch):
    calls = {"direct": 0, "dedalus": 0}

    async def fake_direct(topic, max_tokens):
        calls["direct"] += 1
        return "DIRECT DOCS"

    async def fake_dedalus(topic, max_tokens):
        calls["dedalus"] += 1
        return "DEDALUS DOCS"

    monkeypatch.setattr(context7_docs, "fetch_manim_docs_direct", fake_direct)
    monkeypatch.setattr(context7_docs, "fetch_manim_docs_via_dedalus", fake_dedalus)
    context7_docs._docs_cache.clear()
    return calls


def test_direct_path_works_without_provider(monkeypatch):
    calls = _stub_docs(monkeypatch)
    docs = asyncio.run(context7_docs.get_manim_docs(topic="direct-no-provider", use_dedalus=False))
    assert docs == "DIRECT DOCS"
    assert calls["dedalus"] == 0  # provider never consulted / dedalus never called


def test_use_dedalus_true_without_provider_falls_back(monkeypatch):
    calls = _stub_docs(monkeypatch)
    # use_dedalus=True but no provider configured: get_provider() raises, is caught,
    # and we fall through to the direct path instead of blowing up.
    docs = asyncio.run(context7_docs.get_manim_docs(topic="dedalus-no-provider", use_dedalus=True))
    assert docs == "DIRECT DOCS"
    assert calls["dedalus"] == 0


def test_static_fallback_used_when_live_sources_empty(monkeypatch):
    calls = _stub_docs(monkeypatch)

    async def empty_direct(topic, max_tokens):
        calls["direct"] += 1
        return ""

    monkeypatch.setattr(context7_docs, "fetch_manim_docs_direct", empty_direct)
    # Static read is exercised off the event loop via asyncio.to_thread; stub it
    # so the test doesn't depend on the on-disk reference file.
    monkeypatch.setattr(context7_docs, "_read_static_docs", lambda path: "STATIC DOCS")

    docs = asyncio.run(context7_docs.get_manim_docs(topic="static-fallback", use_dedalus=False))
    assert docs == "STATIC DOCS"
    assert calls["direct"] == 1
