"""The paper pipeline as a durable Temporal workflow.

Why each Temporal feature is here (they all map to failures this project has
actually had, not to technology enthusiasm):

- Durable execution: a worker killed mid-run (redeploys did this twice) no
  longer strands the job at "processing" forever — the workflow resumes after
  the last completed activity, and the checkpointed generation result means the
  LLM spend is never paid twice.
- Workflow ID = ``paper-{arxiv_id}``: duplicate submissions become structurally
  impossible at the orchestrator (the API's in-memory/DB dedupe remains as a
  cheap first line, but this is the guarantee).
- Per-activity retry policies: transient render failures (LaTeX/CPU
  contention) retry once automatically; generation never auto-retries, because
  a retry doubles real LLM spend and deserves a deliberate decision.
- Orchestration state (completion counters) lives in the workflow, not in
  shared mutable state between concurrent tasks — progress writes are issued
  by the workflow as render results arrive.

This module must stay sandbox-clean: no I/O, no heavy imports — activities
carry all side effects.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporal_app.activities import (
        PipelineInput,
        ProgressUpdate,
        RenderInput,
        RenderResult,
        finalize_job,
        generate_visualizations_for_paper,
        ingest_paper,
        mark_job_failed,
        render_visualization,
        update_render_progress,
    )

TASK_QUEUE = "paper-pipeline"
RENDER_TASK_QUEUE = "paper-render"

# Transient infra faults (network, DB hiccup) get one automatic retry.
_INFRA_RETRY = RetryPolicy(maximum_attempts=2)
# Generation is real money (~$0.07/paper of LLM spend) — never auto-retry.
_NO_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class PaperPipelineWorkflow:
    """ingest → generate → parallel renders → honest finalize."""

    @workflow.run
    async def run(self, params: PipelineInput) -> str:
        try:
            await workflow.execute_activity(
                ingest_paper,
                params,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_INFRA_RETRY,
            )

            # 40 min: measured generation is ~2-8 min alone, but under
            # multi-paper load it queues behind renders on the shared CPUs —
            # 25 min timed out in production the first night. (Queue WAIT
            # doesn't count here; start_to_close covers execution only.)
            render_inputs: list[RenderInput] = await workflow.execute_activity(
                generate_visualizations_for_paper,
                params,
                start_to_close_timeout=timedelta(minutes=40),
                retry_policy=_NO_RETRY,
            )

            total = len(render_inputs)
            if total == 0:
                await self._finalize(params.job_id, succeeded=0, total=0)
                return "no-visualizations"

            # Start all renders; the render worker's concurrency cap does the
            # throttling (Temporal queues the surplus — no semaphore needed).
            render_tasks = [
                workflow.execute_activity(
                    render_visualization,
                    ri,
                    task_queue=RENDER_TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=_INFRA_RETRY,
                )
                for ri in render_inputs
            ]

            succeeded = 0
            completed = 0
            for task in asyncio.as_completed(render_tasks):
                result: RenderResult = await task
                completed += 1
                if result.succeeded:
                    succeeded += 1
                await workflow.execute_activity(
                    update_render_progress,
                    ProgressUpdate(job_id=params.job_id, completed=completed, total=total),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_INFRA_RETRY,
                )

            await self._finalize(params.job_id, succeeded=succeeded, total=total)
            return f"rendered {succeeded}/{total}"
        except Exception:
            # Mark the job failed so pollers see the truth, then let Temporal
            # record the workflow failure with full history for debugging.
            await workflow.execute_activity(
                mark_job_failed,
                params,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_INFRA_RETRY,
            )
            raise

    async def _finalize(self, job_id: str, succeeded: int, total: int) -> None:
        await workflow.execute_activity(
            finalize_job,
            ProgressUpdate(job_id=job_id, completed=succeeded, total=total),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_INFRA_RETRY,
        )
