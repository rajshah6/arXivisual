"""Temporal activities for the paper pipeline.

Each activity is a thin, self-contained wrapper over the same building blocks
the legacy BackgroundTasks path uses (`_ingest_and_store_paper`,
`generate_visualizations`, `process_visualization`, `queries`). Activities open
their own DB session (an AsyncSession is not safe to share across concurrent
tasks) and keep writing job/viz status to the DB exactly as the legacy path
does — the frontend's polling contract is unchanged.

Why these boundaries: each activity is a durable checkpoint. If the worker dies
mid-render (a redeploy — the exact failure that used to strand jobs at
"processing" forever), the workflow resumes AFTER the last completed activity:
the ~$0.07 LLM generation result is already checkpointed in workflow history,
so only the interrupted render re-runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from temporalio import activity

logger = logging.getLogger(__name__)


@dataclass
class PipelineInput:
    job_id: str
    arxiv_id: str


@dataclass
class RenderInput:
    job_id: str
    viz_id: str
    manim_code: str


@dataclass
class RenderResult:
    viz_id: str
    succeeded: bool


@dataclass
class ProgressUpdate:
    job_id: str
    completed: int
    total: int


@activity.defn
async def ingest_paper(params: PipelineInput) -> None:
    """Fetch + parse the paper into the DB (skips if already present)."""
    from db.connection import async_session_maker
    from db import queries
    from jobs.worker import _ingest_and_store_paper

    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            status="processing",
            current_step="Fetching paper from arXiv",
            progress=0.10,
        )
        if await queries.paper_exists(db, params.arxiv_id):
            job = await queries.get_job(db, params.job_id)
            if job:
                job.paper_id = params.arxiv_id
                await db.commit()
            await queries.update_job_status(
                db, params.job_id,
                current_step="Paper already processed",
                progress=0.30,
            )
            return
        await _ingest_and_store_paper(db, params.job_id, params.arxiv_id)


@activity.defn
async def generate_visualizations_for_paper(params: PipelineInput) -> list[RenderInput]:
    """Run the agent pipeline; upsert viz records; return render inputs.

    The returned list is checkpointed in workflow history (~8KB of Manim code
    per viz, well under Temporal's payload limits) — this is what makes
    resume-without-re-paying-generation possible.
    """
    from db.connection import async_session_maker
    from db import queries
    from agents.pipeline import generate_visualizations
    from jobs.worker import _build_structured_paper_from_db

    try:
        from langfuse import propagate_attributes
    except ImportError:  # pragma: no cover
        from contextlib import nullcontext

        def propagate_attributes(**_kw):  # type: ignore
            return nullcontext()

    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            current_step="Analyzing concepts for visualization",
            progress=0.50,
        )
        db_paper = await queries.get_paper(db, params.arxiv_id)
        db_sections = sorted(db_paper.sections, key=lambda s: s.order_index)
        structured_paper = _build_structured_paper_from_db(db_paper, db_sections)

    with propagate_attributes(
        session_id=params.job_id,
        trace_name="process-paper",
        tags=["pipeline", "temporal"],
        metadata={"arxiv_id": params.arxiv_id},
    ):
        generated = await generate_visualizations(structured_paper)

    render_inputs: list[RenderInput] = []
    paper_suffix = params.arxiv_id.replace(".", "")[:8]
    async with async_session_maker() as db:
        for i, viz in enumerate(generated):
            viz_id = f"viz_{paper_suffix}_{i + 1}"
            await queries.upsert_visualization(
                db,
                viz_id=viz_id,
                paper_id=params.arxiv_id,
                section_id=viz.section_id,
                concept=viz.concept,
                storyboard={"raw": viz.storyboard},
                manim_code=viz.manim_code,
                status="pending",
            )
            render_inputs.append(
                RenderInput(job_id=params.job_id, viz_id=viz_id, manim_code=viz.manim_code)
            )
        if render_inputs:
            await queries.update_job_status(
                db, params.job_id,
                current_step="Rendering videos",
                progress=0.75,
                sections_total=len(render_inputs),
                sections_completed=0,
            )
    return render_inputs


@activity.defn
async def render_visualization(params: RenderInput) -> RenderResult:
    """Render one video and record its status. Never raises for a render
    failure — the outcome travels back to the workflow, which owns aggregation.
    (Raising is reserved for infrastructure faults, which Temporal retries.)"""
    from db.connection import async_session_maker
    from db import queries
    from rendering import process_visualization

    succeeded = True
    video_url: str | None = None
    error: str | None = None
    try:
        video_url = await process_visualization(
            viz_id=params.viz_id,
            manim_code=params.manim_code,
            quality="low_quality",
        )
    except Exception as exc:
        succeeded = False
        error = str(exc)
        logger.error("Render failed for %s: %s", params.viz_id, error)

    async with async_session_maker() as db:
        await queries.update_visualization_status(
            db, params.viz_id,
            status="complete" if succeeded else "failed",
            video_url=video_url,
            error=error,
        )
    return RenderResult(viz_id=params.viz_id, succeeded=succeeded)


@activity.defn
async def update_render_progress(params: ProgressUpdate) -> None:
    """Progress writes are driven by the workflow (which owns the counters),
    so concurrent render activities never share mutable state."""
    from db.connection import async_session_maker
    from db import queries

    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            progress=0.75 + 0.20 * (params.completed / max(1, params.total)),
            sections_completed=params.completed,
        )


@activity.defn
async def finalize_job(params: ProgressUpdate) -> None:
    """Write the honest terminal status (completed/failed + failure counts)."""
    from db.connection import async_session_maker
    from db import queries
    from jobs.worker import resolve_terminal_job_status

    status, step, error = resolve_terminal_job_status(params.completed, params.total)
    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            status=status,
            current_step=step,
            progress=1.0,
            error=error,
        )


@activity.defn
async def mark_job_failed(params: PipelineInput) -> None:
    """Terminal failure marker for unrecoverable workflow errors."""
    from db.connection import async_session_maker
    from db import queries

    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            status="failed",
            error="Pipeline failed after retries. See worker logs for details.",
        )
