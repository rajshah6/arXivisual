"""The static Manim reference must not be sent twice.

``get_manim_docs`` returns the static ``manim_reference.md`` when every live
source fails; the generator then appended it to a system prompt that already
IS that file. In production 12/12 sampled generator system prompts were
reference + header + reference: ~4.4k extra tokens on every call.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents import manim_generator
from agents.manim_generator import ManimGenerator
from models.generation import VisualizationType

STATIC_REFERENCE = "# Manim reference\n" + "x" * 500


def _generator() -> ManimGenerator:
    g = ManimGenerator.__new__(ManimGenerator)
    g.system_prompt = STATIC_REFERENCE
    return g


def _plan():
    return SimpleNamespace(visualization_type=VisualizationType.DATA_FLOW, concept_name="attention")


def _patch_docs(monkeypatch, text):
    async def fake_get_manim_docs(topic, max_tokens=5000, use_dedalus=True):
        return text

    monkeypatch.setattr(manim_generator, "get_manim_docs", fake_get_manim_docs)


def test_static_fallback_is_not_appended_to_the_system_prompt(monkeypatch):
    _patch_docs(monkeypatch, STATIC_REFERENCE)
    enriched = asyncio.run(_generator()._enrich_system_prompt_with_live_docs(_plan()))
    assert enriched == STATIC_REFERENCE


def test_genuinely_live_docs_are_still_appended(monkeypatch):
    _patch_docs(monkeypatch, "## Axes\nAxes(x_length=..., y_length=...) " + "y" * 200)
    enriched = asyncio.run(_generator()._enrich_system_prompt_with_live_docs(_plan()))
    assert enriched.startswith(STATIC_REFERENCE)
    assert "x_length" in enriched
