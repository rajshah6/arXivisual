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
        RepairInput,
        finalize_job,
        generate_visualizations_for_paper,
        ingest_paper,
        mark_job_failed,
        render_visualization,
        repair_visualization_code,
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
            results: list[RenderResult] = []
            for completed, task in enumerate(asyncio.as_completed(render_tasks), start=1):
                result: RenderResult = await task
                results.append(result)
                if result.succeeded:
                    succeeded += 1
                await workflow.execute_activity(
                    update_render_progress,
                    ProgressUpdate(job_id=params.job_id, completed=completed, total=total),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=_INFRA_RETRY,
                )

            # Repair pass (one round per viz, activity-gated via env): the
            # judge's specific findings drive a targeted layout fix, then a
            # re-render overwrites the video in place. A failed repair keeps
            # the original video — defective beats absent.
            code_by_viz = {ri.viz_id: ri.manim_code for ri in render_inputs}
            to_repair = [r for r in results if r.repair_recommended]
            if to_repair:
                workflow.logger.info(
                    "Repairing %d/%d defective visualization(s)", len(to_repair), total
                )
                repaired_ok = await asyncio.gather(
                    *[self._repair_one(params.job_id, r, code_by_viz[r.viz_id]) for r in to_repair]
                )
                workflow.logger.info(
                    "Repair pass: %d/%d now defect-free", sum(repaired_ok), len(to_repair)
                )

            await self._finalize(params.job_id, succeeded=succeeded, total=total)
            defective = sum(1 for r in results if r.severity == "major")
            return f"rendered {succeeded}/{total} ({defective} flagged, {len(to_repair)} repaired)"
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

    async def _repair_one(self, job_id: str, result: RenderResult, code: str) -> bool:
        """Repair one defective visualization; returns True if the re-render
        came back defect-free. Never raises — original video stays on failure."""
        try:
            fixed_code = await workflow.execute_activity(
                repair_visualization_code,
                RepairInput(
                    job_id=job_id,
                    viz_id=result.viz_id,
                    manim_code=code,
                    issues=result.issues,
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=_NO_RETRY,  # a repair is one LLM call — don't double-spend
            )
            rerender: RenderResult = await workflow.execute_activity(
                render_visualization,
                RenderInput(
                    job_id=job_id,
                    viz_id=result.viz_id,
                    manim_code=fixed_code,
                    is_repair=True,
                ),
                task_queue=RENDER_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=_NO_RETRY,  # original video already exists as fallback
            )
            return rerender.succeeded and rerender.severity != "major"
        except Exception as exc:
            workflow.logger.warning("Repair failed for %s: %s", result.viz_id, exc)
            return False

    async def _finalize(self, job_id: str, succeeded: int, total: int) -> None:
        await workflow.execute_activity(
            finalize_job,
            ProgressUpdate(job_id=job_id, completed=succeeded, total=total),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_INFRA_RETRY,
        )
