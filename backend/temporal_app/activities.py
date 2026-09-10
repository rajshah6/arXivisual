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

import contextlib
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
class FailInput:
    job_id: str
    arxiv_id: str
    # The workflow's exception text: the job row used to carry only a generic
    # "failed after retries", which hid the real cause from the site and logs.
    reason: str = ""


@dataclass
class ProgressUpdate:
    job_id: str
    completed: int
    total: int


@activity.defn
async def ingest_paper(params: PipelineInput) -> None:
    """Fetch + parse the paper into the DB (skips if already present)."""
    from db import queries
    from db.connection import async_session_maker
    from jobs.worker import _ingest_and_store_paper

    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            status="processing",
            current_step="Fetching paper from arXiv",
            progress=0.10,
        )
        replace = False
        if await queries.paper_exists(db, params.arxiv_id):
            if await queries.paper_is_stale(db, params.arxiv_id):
                # Stored from the abstract page before the LaTeXML fix: the
                # request is the signal to ingest the real paper this time.
                logger.info("Paper %s is a pre-fix abstract-only ingest; re-ingesting", params.arxiv_id)
                replace = True
            else:
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
        try:
            await _ingest_and_store_paper(db, params.job_id, params.arxiv_id, replace=replace)
        except Exception as exc:
            # Deterministic ingestion failures (abstract-only source, formatting
            # failed after its own attempts) must reach the job row verbatim and
            # must NOT be multiplied by the activity retry policy.
            from temporalio.exceptions import ApplicationError

            from ingestion.section_formatter import SourceTooShortError

            deterministic = isinstance(exc, SourceTooShortError) or "Section formatting failed" in str(exc)
            if deterministic:
                await queries.update_job_status(db, params.job_id, status="failed", error=str(exc))
                raise ApplicationError(str(exc), non_retryable=True) from exc
            raise


@activity.defn
async def generate_visualizations_for_paper(params: PipelineInput) -> list[RenderInput]:
    """Run the agent pipeline; upsert viz rows; return render inputs.

    Checkpointed per visualization: each finished viz is upserted (and the
    activity heartbeats) the moment it is ready. Before this, rows were
    written only after ALL candidates finished, so a worker restart
    mid-generation lost every finished visualization and left '0 visuals'.
    On a retry attempt the already-checkpointed concepts are skipped, so a
    restart costs the unfinished work only — never a second full generation.

    The returned list is checkpointed in workflow history (~8KB of Manim code
    per viz, well under Temporal's payload limits).
    """
    import asyncio

    from agents.pipeline import MAX_VISUALIZATIONS, generate_visualizations
    from db import queries
    from db.connection import async_session_maker
    from jobs.worker import _build_structured_paper_from_db

    try:
        from langfuse import propagate_attributes
    except ImportError:  # pragma: no cover
        from contextlib import nullcontext

        def propagate_attributes(**_kw):  # type: ignore
            return nullcontext()

    # Full sanitized arXiv id — a truncated prefix collided across sibling
    # ids (e.g. 2608.23551 vs 2608.23553 both mapped to "26082355"), making
    # papers overwrite each other's visualization rows via upsert.
    paper_suffix = params.arxiv_id.replace(".", "_").replace("/", "_")
    attempt = activity.info().attempt

    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            current_step="Analyzing concepts for visualization",
            progress=0.50,
        )
        job = await queries.get_job(db, params.job_id)
        run_started = job.created_at if job else None
        # This run's checkpoints only (rows created since the job began): a
        # retried attempt resumes from them. Previous runs' rows stay visible
        # to readers until finalize_job supersedes them — a re-run no longer
        # blanks an already-visualized paper for 10-25 minutes.
        existing = [
            r for r in await queries.get_visualizations_for_paper(db, params.arxiv_id, since=run_started)
            if r.manim_code
        ]
        db_paper = await queries.get_paper(db, params.arxiv_id)
        if db_paper is None:
            from temporalio.exceptions import ApplicationError

            # Used to surface as "'NoneType' object has no attribute 'sections'".
            raise ApplicationError(
                f"Paper {params.arxiv_id} is not stored — ingestion did not complete for this id",
                non_retryable=True,
            )
        db_sections = sorted(db_paper.sections, key=lambda s: s.order_index)
        structured_paper = _build_structured_paper_from_db(db_paper, db_sections)

    render_inputs: list[RenderInput] = [
        RenderInput(job_id=params.job_id, viz_id=r.id, manim_code=r.manim_code) for r in existing
    ]
    if existing:
        logger.info("Attempt %d: resuming with %d checkpointed visualization(s)", attempt, len(existing))
    remaining = max(0, MAX_VISUALIZATIONS - len(existing))

    async def checkpoint(viz) -> None:
        # The id is minted from the table at write time and INSERTed (never
        # upserted): if a second attempt ever overlaps the first — the 40-min
        # start-to-close timeout can fire while attempt 1 is still running —
        # neither can overwrite the other's row.
        viz_id = await queries.insert_visualization_with_next_index(
            paper_suffix=paper_suffix,
            paper_id=params.arxiv_id,
            section_id=viz.section_id,
            concept=viz.concept,
            storyboard={"raw": viz.storyboard},
            manim_code=viz.manim_code,
            session_maker=async_session_maker,
        )
        render_inputs.append(RenderInput(job_id=params.job_id, viz_id=viz_id, manim_code=viz.manim_code))
        activity.heartbeat(f"{len(render_inputs)} visualization(s) checkpointed")

    async def heartbeat_loop() -> None:
        # A heartbeat only on checkpoints let a live-but-slow worker exceed the
        # heartbeat timeout before its first viz finished, spawning a second
        # attempt that double-spent and collided on ids. Beat on a timer.
        while True:
            await asyncio.sleep(30)
            activity.heartbeat(f"{len(render_inputs)} visualization(s) checkpointed")

    if remaining == 0:
        logger.info("All %d visualization slots already checkpointed; skipping generation", len(existing))
    else:
        beat = asyncio.create_task(heartbeat_loop())
        try:
            with propagate_attributes(
                session_id=params.job_id,
                trace_name="process-paper",
                tags=["pipeline", "temporal"],
                metadata={"arxiv_id": params.arxiv_id},
            ):
                await generate_visualizations(
                    structured_paper,
                    max_visualizations=remaining,
                    on_visualization=checkpoint,
                    skip_concepts={r.concept for r in existing},
                )
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    if render_inputs:
        async with async_session_maker() as db:
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

    from db import queries
    from db.connection import async_session_maker
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
[-6, 6], y in [-3.5, 3.5].

{contract}"""


async def _fetch_rendered_video(viz_id: str) -> bytes | None:
    """Authoritative read of the just-rendered video for vision-grounded repair.

    Reads through the storage backend (S3 GetObject / local file), NEVER the
    public URL: the CDN caches the stable per-viz key for up to a year, so a
    re-run could otherwise repair against the previous run's frames. Any
    failure returns None — the caller falls back to text-only repair.
    """
    try:
        from rendering import get_backend

        return await get_backend().load_video(viz_id)
    except Exception as exc:
        logger.warning("Could not fetch video for repair of %s: %s", viz_id, exc)
        return None


@activity.defn
async def repair_visualization_code(params: RepairInput) -> str:
    """Targeted layout repair: judge findings -> focused LLM fix -> validated code.

    v2 is vision-grounded: the rendered video is fetched back, defect frames are
    sampled, and the repair model SEES the actual defects (two experiments proved
    text-only feedback insufficient — the model fixes what it's told about while
    the judge finds what the text never captured). Falls back to text-only repair
    when the video can't be retrieved, and raises on unusable output so the
    workflow keeps the original video — a defective video beats no video.
    """
    from agents.base import call_llm
    from agents.code_validator import CodeValidator
    from agents.visual_qa import format_issue_list, repair_code_with_frames

    def _extract_and_validate(raw: str):
        """Fence-strip + gate. Returns validated code or None."""
        import re

        fence = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL)
        candidate = (fence.group(1) if fence else raw).strip()
        validation = CodeValidator().validate(candidate)
        return validation.code if validation.is_valid else None

    # Attempt 1: vision-grounded. EVERY vision failure mode — video fetch, frame
    # sampling, model call, empty output, or invalid code — falls through to the
    # text-only attempt (consistent contract: garbage is treated like absence).
    code = None
    video_bytes = await _fetch_rendered_video(params.viz_id)
    if video_bytes:
        raw = await repair_code_with_frames(
            params.manim_code, params.issues, video_bytes, viz_id=params.viz_id
        )
        if raw:
            code = _extract_and_validate(raw)
            if code:
                logger.info("Vision-grounded repair produced code for %s", params.viz_id)
            else:
                logger.warning(
                    "Vision repair output failed validation for %s; trying text-only",
                    params.viz_id,
                )

    if code is None:
        logger.info("Text-only repair for %s", params.viz_id)
        from agents.visual_qa import REPAIR_OUTPUT_CONTRACT

        prompt = REPAIR_PROMPT.format(
            issues=format_issue_list(params.issues),
            code=params.manim_code,
            contract=REPAIR_OUTPUT_CONTRACT,
        )
        raw = await call_llm(prompt, max_tokens=10000, name="visual_qa_repair")
        code = _extract_and_validate(raw)

    if code is None:
        raise RuntimeError(f"Repair produced invalid code for {params.viz_id}")
    logger.info("Repair code ready for %s (%d chars)", params.viz_id, len(code))
    return code


@activity.defn
async def update_render_progress(params: ProgressUpdate) -> None:
    """Progress writes are driven by the workflow (which owns the counters),
    so concurrent render activities never share mutable state."""
    from db import queries
    from db.connection import async_session_maker

    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            progress=0.75 + 0.20 * (params.completed / max(1, params.total)),
            sections_completed=params.completed,
        )


@activity.defn
async def finalize_job(params: ProgressUpdate) -> None:
    """Write the honest terminal status (completed/failed + failure counts)."""
    import analytics
    from db import queries
    from db.connection import async_session_maker
    from jobs.worker import resolve_terminal_job_status

    status, step, error = resolve_terminal_job_status(params.completed, params.total)
    job = None
    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            status=status,
            current_step=step,
            progress=1.0,
            error=error,
        )
        # Only a run that actually produced videos retires the previous run's
        # rows; a failed re-run leaves the old videos serving.
        job = await queries.get_job(db, params.job_id)
        if job and job.paper_id and job.created_at:
            # Every render input has written a terminal status by now; a row
            # still pending is one whose failure recorder itself failed.
            leftover = await queries.fail_pending_visualizations(
                db, job.paper_id,
                error="Render did not complete before the job finished.",
                since=job.created_at,
            )
            if leftover:
                logger.warning("Failed %d leftover pending visualization(s) for %s", leftover, job.paper_id)
            if params.completed > 0:
                retired = await queries.supersede_visualizations_before(db, job.paper_id, job.created_at)
                if retired:
                    logger.info("Superseded %d previous-run visualization(s) for %s", retired, job.paper_id)

    # Product event, after every DB write and outside the session: analytics
    # can never fail (or retry) a finalize. distinct_id is the job id — no
    # client identity reaches the worker (see analytics.job_outcome).
    analytics.job_outcome(
        job_id=params.job_id,
        arxiv_id=job.paper_id if job else None,
        status=status,
        videos_complete=params.completed,
        videos_total=params.total,
        created_at=job.created_at if job else None,
        error=error,
    )


@activity.defn
async def record_render_failure(params: RenderInput) -> None:
    """A render activity that failed at the Temporal level (timeout, worker
    death after retries) never ran the status write inside
    render_visualization — record it so the row doesn't strand at pending."""
    from db import queries
    from db.connection import async_session_maker

    async with async_session_maker() as db:
        await queries.update_visualization_status(
            db, params.viz_id, status="failed",
            error="Render did not complete (worker interrupted or timed out).",
        )


@activity.defn
async def mark_job_failed(params: FailInput) -> None:
    """Terminal failure marker for unrecoverable workflow errors."""
    import analytics
    from db import queries
    from db.connection import async_session_maker

    reason = (params.reason or "").strip()[:500]
    job = None
    async with async_session_maker() as db:
        await queries.update_job_status(
            db, params.job_id,
            status="failed",
            error=f"Pipeline failed: {reason}" if reason else
                  "Pipeline failed after retries. See worker logs for details.",
        )
        # Rows the dead run never got to render would otherwise sit at
        # 'pending' forever and count as visuals in the gallery.
        job = await queries.get_job(db, params.job_id)
        stranded = await queries.fail_pending_visualizations(
            db, params.arxiv_id,
            error="Pipeline failed before this visualization rendered.",
            since=job.created_at if job else None,
        )
        if stranded:
            logger.info("Marked %d stranded visualization(s) failed for %s", stranded, params.arxiv_id)

    # Product event (distinct_id = job id; no client identity here). The job
    # row's counters are the best available render tally for a dead run.
    analytics.job_outcome(
        job_id=params.job_id,
        arxiv_id=params.arxiv_id,
        status="failed",
        videos_complete=job.sections_completed if job else None,
        videos_total=job.sections_total if job else None,
        created_at=job.created_at if job else None,
        error=reason or "Pipeline failed after retries",
    )
