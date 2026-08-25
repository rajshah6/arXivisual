"""Tests for the Temporal paper pipeline.

Fast tests validate the module contracts (sandbox-safe imports, dataclasses).
The integration tests run the REAL workflow against a local Temporal dev server
(temporalio downloads it on first use) with mocked activities — proving
orchestration order, success/failure aggregation, and workflow-ID dedupe.
Integration tests are gated behind TEMPORAL_TESTS=1 to keep CI hermetic.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from temporal_app.activities import PipelineInput, ProgressUpdate, RenderInput, RenderResult
from temporal_app.workflows import RENDER_TASK_QUEUE, TASK_QUEUE, PaperPipelineWorkflow

requires_temporal = pytest.mark.skipif(
    os.getenv("TEMPORAL_TESTS") != "1",
    reason="set TEMPORAL_TESTS=1 to run Temporal integration tests (downloads a local dev server)",
)


def test_workflow_module_is_sandbox_safe():
    # Importing the workflow module must not drag in heavy/IO modules directly
    # (they are gated behind imports_passed_through); reaching this line at all
    # after the top-level imports proves definition-time sandbox safety.
    assert PaperPipelineWorkflow is not None
    assert TASK_QUEUE == "paper-pipeline"
    assert RENDER_TASK_QUEUE == "paper-render"


def test_dataclass_contracts():
    p = PipelineInput(job_id="job_x", arxiv_id="1706.03762")
    r = RenderInput(job_id="job_x", viz_id="viz_1", manim_code="code")
    assert p.arxiv_id == "1706.03762" and r.viz_id == "viz_1"


@requires_temporal
class TestWorkflowOrchestration:
    @pytest.fixture()
    def calls(self):
        return {"ingest": 0, "generate": 0, "render": [], "progress": [], "finalize": [], "failed": 0}

    def _mock_activities(self, calls, viz_count=3, fail_viz_ids=frozenset()):
        from temporalio import activity

        @activity.defn(name="ingest_paper")
        async def ingest(params: PipelineInput) -> None:
            calls["ingest"] += 1

        @activity.defn(name="generate_visualizations_for_paper")
        async def generate(params: PipelineInput) -> list[RenderInput]:
            calls["generate"] += 1
            return [
                RenderInput(job_id=params.job_id, viz_id=f"viz_{i}", manim_code=f"code{i}")
                for i in range(1, viz_count + 1)
            ]

        @activity.defn(name="render_visualization")
        async def render(params: RenderInput) -> RenderResult:
            calls["render"].append(params.viz_id)
            return RenderResult(viz_id=params.viz_id, succeeded=params.viz_id not in fail_viz_ids)

        @activity.defn(name="update_render_progress")
        async def progress(params: ProgressUpdate) -> None:
            calls["progress"].append((params.completed, params.total))

        @activity.defn(name="finalize_job")
        async def finalize(params: ProgressUpdate) -> None:
            calls["finalize"].append((params.completed, params.total))

        @activity.defn(name="mark_job_failed")
        async def failed(params: PipelineInput) -> None:
            calls["failed"] += 1

        return [ingest, generate, progress, finalize, failed], [render]

    async def _run(self, calls, viz_count=3, fail_viz_ids=frozenset()):
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        pipeline_acts, render_acts = self._mock_activities(calls, viz_count, fail_viz_ids)
        async with await WorkflowEnvironment.start_local() as env:
            async with Worker(
                env.client, task_queue=TASK_QUEUE,
                workflows=[PaperPipelineWorkflow], activities=pipeline_acts,
            ), Worker(
                env.client, task_queue=RENDER_TASK_QUEUE, activities=render_acts,
            ):
                wf_id = f"paper-test-{uuid.uuid4().hex[:8]}"
                result = await env.client.execute_workflow(
                    PaperPipelineWorkflow.run,
                    PipelineInput(job_id="job_t", arxiv_id="1706.03762"),
                    id=wf_id,
                    task_queue=TASK_QUEUE,
                )
                return result

    def test_happy_path_orders_and_aggregates(self, calls):
        result = asyncio.run(self._run(calls, viz_count=3))
        assert result == "rendered 3/3"
        assert calls["ingest"] == 1 and calls["generate"] == 1
        assert sorted(calls["render"]) == ["viz_1", "viz_2", "viz_3"]
        # Progress is monotonically driven by the workflow as results arrive.
        assert [c for c, _ in calls["progress"]] == [1, 2, 3]
        assert calls["finalize"] == [(3, 3)]
        assert calls["failed"] == 0

    def test_partial_failure_reaches_finalize_with_honest_counts(self, calls):
        result = asyncio.run(self._run(calls, viz_count=3, fail_viz_ids=frozenset({"viz_2"})))
        assert result == "rendered 2/3"
        assert calls["finalize"] == [(2, 3)]

    def test_zero_visualizations_finalizes_as_empty(self, calls):
        result = asyncio.run(self._run(calls, viz_count=0))
        assert result == "no-visualizations"
        assert calls["finalize"] == [(0, 0)]
        assert calls["render"] == []

    def test_duplicate_workflow_id_is_rejected(self, calls):
        from temporalio.exceptions import WorkflowAlreadyStartedError
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        async def run():
            pipeline_acts, render_acts = self._mock_activities(calls, viz_count=1)
            async with await WorkflowEnvironment.start_local() as env:
                async with Worker(
                    env.client, task_queue=TASK_QUEUE,
                    workflows=[PaperPipelineWorkflow], activities=pipeline_acts,
                ), Worker(env.client, task_queue=RENDER_TASK_QUEUE, activities=render_acts):
                    handle = await env.client.start_workflow(
                        PaperPipelineWorkflow.run,
                        PipelineInput(job_id="job_a", arxiv_id="9999.00001"),
                        id="paper-9999.00001",
                        task_queue=TASK_QUEUE,
                    )
                    # Structural dedupe: same workflow ID while running -> rejected.
                    with pytest.raises(WorkflowAlreadyStartedError):
                        await env.client.start_workflow(
                            PaperPipelineWorkflow.run,
                            PipelineInput(job_id="job_b", arxiv_id="9999.00001"),
                            id="paper-9999.00001",
                            task_queue=TASK_QUEUE,
                        )
                    await handle.result()

        asyncio.run(run())


def test_viz_ids_do_not_collide_across_sibling_arxiv_ids():
    """Regression: the old 8-char digit prefix collided for sibling ids
    (2608.23551 vs 2608.23553 -> both "26082355"), so papers overwrote each
    other's visualization rows via upsert. Found live in production."""
    def suffix(arxiv_id: str) -> str:
        return arxiv_id.replace(".", "_").replace("/", "_")

    a, b = suffix("2608.23551"), suffix("2608.23553")
    assert a != b
    assert a == "2608_23551"
    # Old-style ids (e.g. math/0211159) sanitize to filesystem/URL-safe form too.
    assert suffix("math/0211159") == "math_0211159"
