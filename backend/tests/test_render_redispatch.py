"""Renders whose task was lost before it started are re-dispatched.

Production (Oct 20 - Nov 2): 13-29 renders a day failed with "Activity task
timed out" without ever logging "[Processing Visualization]". The Temporal
server marked the task started (matching logged "Activity task already
started" next to Postgres "context deadline exceeded"), the worker never ran
the body, and both attempts died on the 2-minute heartbeat timeout. A render
that never started cost nothing, so the workflow sends it again — but only
when no attempt ever heartbeated, so a render that ran and died is never
repeated past its retry policy.

The predicate tests are hermetic; the end-to-end ones need TEMPORAL_TESTS=1.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    RetryState,
    TimeoutError,
    TimeoutType,
)

from temporal_app import workflows
from temporal_app.activities import PipelineInput, ProgressUpdate, RenderInput, RenderResult
from temporal_app.workflows import RENDER_TASK_QUEUE, TASK_QUEUE, PaperPipelineWorkflow

requires_temporal = pytest.mark.skipif(
    os.getenv("TEMPORAL_TESTS") != "1",
    reason="set TEMPORAL_TESTS=1 to run Temporal integration tests (downloads a local dev server)",
)


def _activity_error(cause: BaseException) -> ActivityError:
    err = ActivityError(
        "Activity task timed out",
        scheduled_event_id=18, started_event_id=19, identity="worker",
        activity_type="render_visualization", activity_id="7",
        retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
    )
    err.__cause__ = cause
    return err


def test_heartbeat_timeout_without_a_beat_means_never_started():
    exc = _activity_error(TimeoutError("timed out", type=TimeoutType.HEARTBEAT, last_heartbeat_details=[]))
    assert workflows._never_started(exc)


def test_a_render_that_beat_is_not_treated_as_lost():
    # Heartbeat details survive across attempts: any beat means some attempt ran.
    exc = _activity_error(TimeoutError(
        "timed out", type=TimeoutType.HEARTBEAT, last_heartbeat_details=["rendering viz_1"],
    ))
    assert not workflows._never_started(exc)


@pytest.mark.parametrize("cause", [
    TimeoutError("timed out", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]),
    ApplicationError("render crashed"),
])
def test_other_failures_are_not_treated_as_lost(cause):
    assert not workflows._never_started(_activity_error(cause))


def test_non_activity_errors_are_not_treated_as_lost():
    assert not workflows._never_started(RuntimeError("Activity task timed out"))


def test_redispatch_budget_is_bounded():
    # Each dispatch can cost a full retry round of heartbeat timeouts.
    assert 1 <= workflows._LOST_DISPATCH_REDISPATCHES <= 3


@requires_temporal
class TestLostRenderDispatch:
    """The mock render stands in for the server losing the task: it never
    heartbeats, which is all the workflow can observe of a lost dispatch."""

    def _acts(self, calls, lost_viz: str, lost_dispatches: int, beat_before_hanging: bool):
        from temporalio import activity

        @activity.defn(name="ingest_paper")
        async def ingest(params: PipelineInput) -> None: ...

        @activity.defn(name="generate_visualizations_for_paper")
        async def generate(params: PipelineInput) -> list[RenderInput]:
            return [
                RenderInput(job_id=params.job_id, viz_id=f"viz_{i}", manim_code=f"code{i}")
                for i in (1, 2, 3)
            ]

        @activity.defn(name="render_visualization")
        async def render(params: RenderInput) -> RenderResult:
            calls["renders"].append(params.viz_id)
            if params.viz_id == lost_viz and calls["renders"].count(lost_viz) <= lost_dispatches:
                if beat_before_hanging:
                    activity.heartbeat(f"rendering {params.viz_id}")
                await asyncio.sleep(3600)
            return RenderResult(viz_id=params.viz_id, succeeded=True)

        @activity.defn(name="record_render_failure")
        async def record_failure(params: RenderInput) -> None:
            calls["recorded_failures"].append(params.viz_id)

        @activity.defn(name="update_render_progress")
        async def progress(params: ProgressUpdate) -> None: ...

        @activity.defn(name="finalize_job")
        async def finalize(params: ProgressUpdate) -> None:
            calls["finalize"].append((params.completed, params.total))

        @activity.defn(name="mark_job_failed")
        async def failed(params: PipelineInput) -> None: ...

        return [ingest, generate, record_failure, progress, finalize, failed], [render]

    def _run(self, monkeypatch, calls, **kw):
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import UnsandboxedWorkflowRunner, Worker

        # Unsandboxed so the shortened heartbeat timeout reaches the workflow.
        monkeypatch.setattr(workflows, "_RENDER_HEARTBEAT", timedelta(seconds=1))

        async def go():
            pipeline_acts, render_acts = self._acts(calls, **kw)
            async with await WorkflowEnvironment.start_local() as env, Worker(
                env.client, task_queue=TASK_QUEUE,
                workflows=[PaperPipelineWorkflow], activities=pipeline_acts,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ), Worker(
                env.client, task_queue=RENDER_TASK_QUEUE, activities=render_acts,
                max_concurrent_activities=20,
            ):
                return await env.client.execute_workflow(
                    PaperPipelineWorkflow.run,
                    PipelineInput(job_id="job_l", arxiv_id="2608.00938"),
                    id=f"paper-lost-{uuid.uuid4().hex[:8]}",
                    task_queue=TASK_QUEUE,
                )
        return asyncio.run(go())

    def test_render_lost_for_a_whole_retry_round_is_redispatched(self, monkeypatch):
        calls = {"renders": [], "recorded_failures": [], "finalize": []}
        # Both attempts of the first dispatch are lost — the 2608.00938 case.
        result = self._run(monkeypatch, calls, lost_viz="viz_1", lost_dispatches=2, beat_before_hanging=False)
        assert result == "rendered 3/3 (0 flagged, 0 repaired)"
        assert calls["renders"].count("viz_1") == 3
        assert calls["recorded_failures"] == []

    def test_redispatches_stop_at_the_budget(self, monkeypatch):
        calls = {"renders": [], "recorded_failures": [], "finalize": []}
        result = self._run(monkeypatch, calls, lost_viz="viz_1", lost_dispatches=99, beat_before_hanging=False)
        assert result.startswith("rendered 2/3")
        attempts = workflows._INFRA_RETRY.maximum_attempts
        assert calls["renders"].count("viz_1") == attempts * (1 + workflows._LOST_DISPATCH_REDISPATCHES)
        assert calls["recorded_failures"] == ["viz_1"]

    def test_a_render_that_started_is_not_redispatched(self, monkeypatch):
        calls = {"renders": [], "recorded_failures": [], "finalize": []}
        result = self._run(monkeypatch, calls, lost_viz="viz_1", lost_dispatches=99, beat_before_hanging=True)
        assert result.startswith("rendered 2/3")
        assert calls["renders"].count("viz_1") == workflows._INFRA_RETRY.maximum_attempts
        assert calls["recorded_failures"] == ["viz_1"]
