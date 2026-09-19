"""Temporal activities must attribute their LLM calls to the paper's job.

Production evidence: 2,553 judge traces and 741 repair traces in one week
were orphan roots with no session or paper id, because only the generation
activity wrapped its work in ``propagate_attributes``. Every activity that
can call a model must propagate ``session_id=job_id`` so per-paper cost is a
single session filter in Langfuse.
"""

import contextlib
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import langfuse

from temporal_app import activities
from temporal_app.activities import RenderInput, RepairInput


def _recording_propagate(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_propagate_attributes(**kwargs):
        calls.append(kwargs)
        return contextlib.nullcontext()

    monkeypatch.setattr(langfuse, "propagate_attributes", fake_propagate_attributes)
    return calls


def test_render_scope_links_the_render_to_the_job_session(monkeypatch):
    calls = _recording_propagate(monkeypatch)
    params = RenderInput(job_id="job-1", viz_id="viz_2306_14048_2", manim_code="", is_repair=False)

    with activities.render_scope(params):
        pass

    [attrs] = calls
    assert attrs["session_id"] == "job-1"
    assert attrs["trace_name"] == "render-visualization"
    assert "temporal" in attrs["tags"] and "repair" not in attrs["tags"]
    assert attrs["metadata"] == {"viz_id": "viz_2306_14048_2", "is_repair": "0"}


def test_repair_rerender_is_tagged_as_repair(monkeypatch):
    calls = _recording_propagate(monkeypatch)
    params = RenderInput(job_id="job-1", viz_id="viz_1", manim_code="", is_repair=True)

    with activities.render_scope(params):
        pass

    [attrs] = calls
    assert "repair" in attrs["tags"]
    assert attrs["metadata"]["is_repair"] == "1"


def test_repair_scope_links_the_repair_llm_call_to_the_job_session(monkeypatch):
    calls = _recording_propagate(monkeypatch)
    params = RepairInput(job_id="job-9", viz_id="viz_1", manim_code="", issues=["x"])

    with activities.repair_scope(params):
        pass

    [attrs] = calls
    assert attrs["session_id"] == "job-9"
    assert attrs["trace_name"] == "repair-visualization"
    assert "repair" in attrs["tags"]
    assert attrs["metadata"] == {"viz_id": "viz_1"}


def test_scopes_are_noops_without_langfuse(monkeypatch):
    monkeypatch.delattr(langfuse, "propagate_attributes", raising=True)
    params = RenderInput(job_id="job-1", viz_id="viz_1", manim_code="")
    with activities.render_scope(params):
        pass  # must not raise
