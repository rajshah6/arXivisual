"""Render and repair activities heartbeat on a timer and stop cleanly."""

import asyncio
import inspect

import pytest

from temporal_app import activities, workflows


async def test_heartbeats_on_the_timer_and_stops_with_the_body(monkeypatch):
    beats = []
    monkeypatch.setattr(activities.activity, "heartbeat", beats.append)
    async with activities._heartbeating("rendering viz_x", every=0.01):
        await asyncio.sleep(0.06)
    seen = len(beats)
    assert seen >= 3 and beats[0] == "rendering viz_x"
    await asyncio.sleep(0.05)
    assert len(beats) == seen, "the beat task must be cancelled when the body ends"


async def test_body_exception_still_stops_the_beat(monkeypatch):
    beats = []
    monkeypatch.setattr(activities.activity, "heartbeat", beats.append)
    with pytest.raises(RuntimeError):
        async with activities._heartbeating("repairing viz_x", every=0.01):
            await asyncio.sleep(0.03)
            raise RuntimeError("boom")
    seen = len(beats)
    await asyncio.sleep(0.05)
    assert len(beats) == seen


def test_render_and_repair_activities_are_wrapped():
    # The wrapper is what makes the workflow's heartbeat_timeout safe: an
    # activity with a heartbeat_timeout and no heartbeat would always fail.
    for fn in (activities.render_visualization, activities.repair_visualization_code):
        assert "_heartbeating(" in inspect.getsource(fn), fn.__name__


def test_workflow_sets_a_heartbeat_timeout_on_every_render_and_repair_call():
    src = inspect.getsource(workflows.PaperPipelineWorkflow)
    calls = [c for c in src.split("workflow.execute_activity(") if c.lstrip().startswith(("render_visualization", "repair_visualization_code"))]
    assert len(calls) == 3
    assert all("heartbeat_timeout=_RENDER_HEARTBEAT" in c for c in calls)
    assert workflows._RENDER_HEARTBEAT.total_seconds() >= 4 * 30, "allow four missed 30 s beats"
