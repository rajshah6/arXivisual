"""Unit tests for the Azure OpenAI TTS wiring in the voiceover pipeline.

These cover the prompt-grounding snippets the generator injects into scenes and
the render-subprocess env that routes manim-voiceover's OpenAIService at Azure.
No network calls — pure config logic.
"""

import importlib

import pytest

from agents.manim_generator import ManimGenerator


@pytest.fixture
def generator():
    return ManimGenerator()


def test_openai_snippet_uses_configured_voice_and_model(generator):
    snippet = generator._get_tts_setup_snippet("openai", "shimmer")
    assert "OpenAIService(" in snippet
    assert 'voice="shimmer"' in snippet
    assert 'model="gpt-4o-mini-tts"' in snippet
    # Bookmark transcription must stay off — it would pull in whisper at render.
    assert "transcription_model=None" in snippet
    # Persistent audio cache — without it, retries re-synthesize (and re-bill)
    # identical narration because the default cache dies with the render tmpdir.
    assert 'cache_dir="/tmp/arxivisual-tts-cache"' in snippet


def test_gtts_snippet_also_uses_persistent_cache(generator):
    assert 'cache_dir="/tmp/arxivisual-tts-cache"' in generator._get_tts_setup_snippet("gtts", "")


def test_openai_snippet_defaults_voice_when_blank(generator):
    snippet = generator._get_tts_setup_snippet("openai", "")
    assert 'voice="nova"' in snippet


def test_gtts_snippet_is_the_free_fallback(generator):
    snippet = generator._get_tts_setup_snippet("gtts", "")
    assert "GTTSService(" in snippet
    assert "OpenAIService" not in snippet


def test_unknown_service_falls_back_to_gtts(generator):
    assert "GTTSService(" in generator._get_tts_setup_snippet("banana", "")


def test_import_line_matches_service(generator):
    assert generator._get_tts_import("openai") == (
        "from manim_voiceover.services.openai import OpenAIService"
    )
    assert generator._get_tts_import("gtts") == (
        "from manim_voiceover.services.gtts import GTTSService"
    )


def test_render_env_routes_openai_to_azure(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    from rendering import local_runner
    importlib.reload(local_runner)
    env = local_runner._tts_subprocess_env()

    assert env["OPENAI_API_KEY"] == "azure-secret"
    assert env["OPENAI_BASE_URL"] == "https://example.openai.azure.com/openai/v1/"
    # Disambiguates the module-level client so it doesn't refuse Azure+OpenAI env.
    assert env["OPENAI_API_TYPE"] == "openai"


def test_render_env_respects_existing_openai_key(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "real-openai-key")

    from rendering import local_runner
    importlib.reload(local_runner)
    env = local_runner._tts_subprocess_env()

    # A real OpenAI key wins — we don't clobber it with the Azure endpoint.
    assert env["OPENAI_API_KEY"] == "real-openai-key"
    assert "OPENAI_BASE_URL" not in env or env["OPENAI_BASE_URL"] != (
        "https://example.openai.azure.com/openai/v1/"
    )
