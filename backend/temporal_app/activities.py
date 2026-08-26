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
    # Set on repair re-renders so the activity doesn't recommend repairing the
    # repair (one round max, decided by the workflow).
    is_repair: bool = False


@dataclass
class RenderResult:
    viz_id: str
    succeeded: bool
    # Visual QA verdict for the rendered video (empty/none when QA is off,
    # failed, or unavailable). The workflow uses repair_recommended — computed
    # HERE from env + severity so the workflow itself stays deterministic.
    severity: str = "none"
    issues: list[str] = None  # type: ignore[assignment]
    repair_recommended: bool = False

    def __post_init__(self) -> None:
        if self.issues is None:
            self.issues = []


@dataclass
class RepairInput:
    job_id: str
    viz_id: str
    manim_code: str
    issues: list[str]


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
    # Full sanitized arXiv id — a truncated prefix collided across sibling
    # ids (e.g. 2608.23551 vs 2608.23553 both mapped to "26082355"), making
    # papers overwrite each other's visualization rows via upsert.
    paper_suffix = params.arxiv_id.replace(".", "_").replace("/", "_")
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
    """Render one video, judge it (when visual QA is on), record status.

    Never raises for a render failure — the outcome travels back to the
    workflow, which owns aggregation. (Raising is reserved for infrastructure
    faults, which Temporal retries.) The repair recommendation is computed
    here from env so the workflow stays deterministic on replay.
    """
    import os

    from db.connection import async_session_maker
    from db import queries
    from rendering import process_visualization

    qa_enabled = os.getenv("ENABLE_VISUAL_QA", "0") == "1"
    repair_enabled = os.getenv("VISUAL_QA_REPAIR", "0") == "1"

    succeeded = True
    video_url: str | None = None
    error: str | None = None
    severity = "none"
    issues: list[str] = []
    try:
        if qa_enabled:
            video_url, verdict = await process_visualization(
                viz_id=params.viz_id,
                manim_code=params.manim_code,
                quality="low_quality",
                collect_qa=True,
            )
            if verdict is not None:
                severity = verdict.severity
                issues = list(verdict.issues)
        else:
            video_url = await process_visualization(
                viz_id=params.viz_id,
                manim_code=params.manim_code,
                quality="low_quality",
            )
    except Exception as exc:
        succeeded = False
        error = str(exc)
        logger.error("Render failed for %s: %s", params.viz_id, error)

    if params.is_repair and not succeeded:
        # A failed repair re-render must not clobber the original video's
        # record — the pre-repair video is still stored and serving.
        logger.warning("Repair re-render failed for %s; keeping original video", params.viz_id)
    else:
        async with async_session_maker() as db:
            await queries.update_visualization_status(
                db, params.viz_id,
                status="complete" if succeeded else "failed",
                video_url=video_url,
                error=error,
            )
    return RenderResult(
        viz_id=params.viz_id,
        succeeded=succeeded,
        severity=severity,
        issues=issues,
        repair_recommended=(
            repair_enabled
            and succeeded
            and severity == "major"
            and not params.is_repair
        ),
    )


REPAIR_PROMPT = """You are fixing LAYOUT DEFECTS in a working Manim animation.
A vision model inspected the rendered video frames and found these problems:

{issues}

Here is the current code (it renders successfully — do NOT restructure it):

```python
{code}
```

Fix ONLY the layout problems listed above: reposition or scale elements, add
FadeOut between beats, move labels off arrows, keep everything inside x in
[-6, 6], y in [-3.5, 3.5]. PRESERVE the narration text, voiceover structure,
scene class name, beat comments, and overall animation flow exactly.

Return ONLY the complete corrected Python code. No markdown, no prose."""


@activity.defn
async def repair_visualization_code(params: RepairInput) -> str:
    """Targeted layout repair: judge findings -> focused LLM fix -> validated code.

    Raises on failure (unusable output) so the workflow keeps the original
    video — a defective video beats no video.
    """
    from agents.base import call_llm
    from agents.code_validator import CodeValidator

    prompt = REPAIR_PROMPT.format(
        issues="\n".join(f"- {i}" for i in params.issues[:8]),
        code=params.manim_code,
    )
    raw = await call_llm(prompt, max_tokens=10000, name="visual_qa_repair")

    # Strip a markdown fence if the model added one despite instructions.
    import re

    fence = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL)
    code = (fence.group(1) if fence else raw).strip()

    validation = CodeValidator().validate(code)
    if not validation.is_valid:
        raise RuntimeError(
            f"Repair produced invalid code for {params.viz_id}: "
            + "; ".join(validation.issues_found[:3])
        )
    logger.info("Repair code ready for %s (%d chars)", params.viz_id, len(validation.code))
    return validation.code


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
