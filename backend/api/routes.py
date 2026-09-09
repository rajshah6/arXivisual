"""
FastAPI routes for the ArXiviz API.

Now using SQLite database and local Manim rendering.
"""

import hmac
import logging
import os
import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import queries
from db.connection import get_db
from db.queries import _utcnow_naive
from ingestion.text_normalize import normalize_display_text, tex_to_text
from jobs import process_paper_job
from rendering import extract_scene_name, get_video_path, get_video_url, process_visualization

from .schemas import (
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    JobStatus,
    PaperListResponse,
    PaperResponse,
    PaperSummary,
    ProcessRequest,
    ProcessResponse,
    RenderRequest,
    RenderResponse,
    SectionResponse,
    SectionVideo,
    StatusResponse,
    StepInfo,
    VisualizationResponse,
    VisualizationStatus,
)
from .throttle import (
    client_ip,
    daily_cap_verdict,
    enforce,
    enforce_all,
    feedback_limiter,
    global_limiter,
    ip_fingerprint,
    per_ip_daily_limiter,
    per_ip_limiter,
    recent_jobs,
    request_context,
)
from .turnstile import verify_turnstile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# DB datetimes are naive UTC (backend convention #6); a naive floor for sorting.
_NAIVE_EPOCH = datetime(1970, 1, 1)  # noqa: DTZ001


def _first_video_url(videos: list[SectionVideo] | None) -> str | None:
    """Legacy single-video field: the newest complete video, if any."""
    return videos[0].video_url if videos else None


def _viz_order(v) -> tuple:
    """Newest first; equal timestamps break on the numeric id suffix (a
    string tiebreak ordered viz_x_9 before viz_x_10)."""
    m = re.search(r"_(\d+)$", v.id)
    return (v.created_at or _NAIVE_EPOCH, int(m.group(1)) if m else 0, v.id)


def _authorize_render(secret: str | None) -> None:
    """Guard the raw-code render endpoint.

    ``POST /api/render`` executes caller-supplied Python via Manim, so it must
    never be openly reachable in production. Outside production it stays open for
    local development; in production it is disabled entirely unless RENDER_API_SECRET
    is configured AND the caller presents it. We return 404 (not 403) so the
    endpoint's existence isn't advertised.
    """
    if os.getenv("ENVIRONMENT", "development").lower() != "production":
        return
    expected = os.getenv("RENDER_API_SECRET")
    # Timing-safe comparison; the explicit None guard keeps compare_digest from
    # being handed a non-str. No configured secret in prod = fully disabled.
    if expected and secret is not None and hmac.compare_digest(secret, expected):
        return
    raise HTTPException(status_code=404, detail="Not found")


# === Endpoints ===

@router.post("/process", response_model=ProcessResponse)
async def start_processing(
    request: ProcessRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Start processing an arXiv paper.

    Returns immediately with a job_id. Poll /api/status/{job_id} for progress.
    Duplicate submissions for a paper already in flight return the existing
    job instead of starting (and paying for) a second pipeline.
    """
    arxiv_id = request.arxiv_id

    # Opportunistic hygiene: jobs stranded at queued/processing by an
    # interrupted worker would otherwise satisfy the dedupe check forever and
    # block re-processing. Reap them before looking for an active job.
    try:
        reaped = await queries.reap_stale_jobs(db)
        if reaped:
            logger.info("Reaped %d stale job(s) before submission", reaped)
    except Exception:
        logger.exception("Stale-job reaping failed; continuing with submission")

    # Dedupe: an in-flight job for this paper is returned as-is. The in-memory
    # map covers the seconds before the worker links job.paper_id; the DB query
    # covers everything after (including submissions from other clients).
    existing_id = recent_jobs.get(arxiv_id)
    if existing_id is None:
        existing = await queries.get_active_job_for_paper(db, arxiv_id)
        existing_id = existing.id if existing else None
    if existing_id is not None:
        job = await queries.get_job(db, existing_id)
        if job and job.status in ("queued", "processing"):
            return ProcessResponse(
                job_id=existing_id,
                arxiv_id=arxiv_id,
                status=JobStatus(job.status),
                message="This paper is already being processed. Poll /api/status/{job_id} for updates.",
            )
        recent_jobs.clear(arxiv_id)

    # Admission control — every accepted job spends real LLM + render money,
    # and this endpoint is public on an open-source codebase, so each layer
    # below assumes the previous one is being gamed:
    #   1. durable daily cap (Postgres-backed: the hard spend ceiling) — checked
    #      first so a capped day doesn't burn a human's single-use Turnstile token
    #   2. proof-of-humanity (server-verified; direct API scripts never pass)
    #   3. per-IP hourly + daily, then global sliding windows (in-memory),
    #      peeked together and recorded only once every layer passes
    ip = client_ip(http_request)
    # Fingerprint first (the log queries extract it), then request forensics.
    client_tag = f"{ip_fingerprint(ip)} {request_context(http_request)}"

    now = _utcnow_naive()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    started_today = await queries.count_jobs_created_since(db, day_start)
    exhausted, retry_after = daily_cap_verdict(started_today, now)
    if exhausted:
        logger.warning(
            "Daily new-paper cap reached (%d) — rejecting %s from client %s",
            started_today, arxiv_id, client_tag,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                "Daily capacity for new papers is used up. Already-visualized "
                "papers are still available in Explore; new ones resume tomorrow."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    if not await verify_turnstile(request.turnstile_token, ip):
        logger.info("Turnstile check failed (client %s)", client_tag)
        raise HTTPException(
            status_code=403,
            detail="Human verification failed. Reload the page and try again.",
        )

    enforce_all(
        [
            (per_ip_limiter, ip, "Rate limit reached for starting new papers. Try again later."),
            (per_ip_daily_limiter, ip,
             "You've started today's share of new papers from this address. Try again tomorrow."),
            (global_limiter, "global",
             "The service is at capacity for new papers right now. Try again later."),
        ],
        client_tag=client_tag,
    )

    # Create job in database
    job_id = await queries.create_job(db, arxiv_id)
    recent_jobs.put(arxiv_id, job_id)
    logger.info("Accepted new paper %s (job %s) from client %s", arxiv_id, job_id, client_tag)

    # Durable path (USE_TEMPORAL=1): start a Temporal workflow. Execution
    # happens on the worker app and survives restarts/redeploys; the workflow
    # ID makes duplicate submissions structurally impossible at the
    # orchestrator. Fail-open: any Temporal error falls back to the legacy
    # in-process BackgroundTasks path so paper processing never breaks on
    # orchestrator trouble.
    started_durably = False
    from .temporal_client import temporal_enabled

    if temporal_enabled():
        try:
            from temporalio.exceptions import WorkflowAlreadyStartedError

            from temporal_app.activities import PipelineInput
            from temporal_app.workflows import TASK_QUEUE, PaperPipelineWorkflow

            from .temporal_client import get_temporal_client

            temporal = await get_temporal_client()
            try:
                await temporal.start_workflow(
                    PaperPipelineWorkflow.run,
                    PipelineInput(job_id=job_id, arxiv_id=arxiv_id),
                    id=f"paper-{arxiv_id}",
                    task_queue=TASK_QUEUE,
                )
                started_durably = True
            except WorkflowAlreadyStartedError:
                # A workflow for this paper is already running (race past the
                # cheap dedupe). Retire the row we just created and point the
                # caller at the active job.
                await queries.update_job_status(
                    db, job_id, status="failed",
                    error="Duplicate submission; another run was already in flight.",
                )
                recent_jobs.clear(arxiv_id)
                active = await queries.get_active_job_for_paper(db, arxiv_id)
                return ProcessResponse(
                    job_id=active.id if active else job_id,
                    arxiv_id=arxiv_id,
                    status=JobStatus(active.status) if active else JobStatus.queued,
                    message="This paper is already being processed. Poll /api/status/{job_id} for updates.",
                )
        except Exception:
            logger.exception(
                "Temporal unavailable — falling back to in-process pipeline"
            )

    if not started_durably:
        # Legacy path: in-process background task (does not survive restarts).
        background_tasks.add_task(process_paper_job, job_id, arxiv_id)

    return ProcessResponse(
        job_id=job_id,
        arxiv_id=arxiv_id,
        status=JobStatus.queued,
        message="Processing started. Poll /api/status/{job_id} for updates."
    )


@router.get("/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get the processing status of a job.

    Team 4 polls this endpoint to track progress.
    """
    job = await queries.get_job(db, job_id)

    if job:
        # Build steps_completed from job progress
        progress = job.progress or 0.0
        steps = [
            StepInfo(
                name="fetch_paper",
                status="complete" if progress > 0.1 else ("in_progress" if progress > 0.0 else "pending"),
            ),
            StepInfo(
                name="parse_sections",
                status="complete" if progress > 0.25 else ("in_progress" if progress > 0.1 else "pending"),
            ),
            StepInfo(
                name="generate_visualizations",
                status="complete" if progress > 0.4 else ("in_progress" if progress > 0.25 else "pending"),
            ),
            StepInfo(
                name="render_videos",
                status="complete" if progress >= 1.0 else ("in_progress" if progress > 0.4 else "pending"),
            ),
        ]

        return StatusResponse(
            job_id=job.id,
            arxiv_id=job.paper_id or "unknown",
            status=JobStatus(job.status),
            progress=progress,
            current_step=job.current_step,
            sections_completed=job.sections_completed or 0,
            sections_total=job.sections_total or 0,
            steps_completed=steps,
            error=job.error,
            created_at=job.created_at,
            estimated_completion=job.created_at + timedelta(minutes=5) if job.status != "completed" else None
        )

    # Job not found - return 404
    raise HTTPException(
        status_code=404,
        detail=f"Job '{job_id}' not found"
    )


@router.get("/paper/{arxiv_id:path}", response_model=PaperResponse)
async def get_paper(arxiv_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get a processed paper with all sections and visualizations.

    Returns 404 if the paper hasn't been processed yet. ``:path`` so old-style
    ids with a category prefix (``math/0612817``, ``hep-th/9711200``) route —
    a plain segment param 404'd ten library papers.
    """
    # Version suffix only ("1706.03762v1" -> "1706.03762"); splitting on any
    # 'v' mangled category prefixes like adap-org/… and quant-ph/….
    base_id = re.sub(r"v\d+$", "", arxiv_id)

    paper = await queries.get_paper(db, base_id)

    if paper and await queries.paper_is_stale(db, base_id):
        # Pre-fix ingest of the abstract page, not the paper. Reported as not
        # visualized so the reader offers "Start Processing", which re-ingests.
        raise HTTPException(
            status_code=404,
            detail=f"Paper '{arxiv_id}' has no usable stored text; process it again to regenerate it.",
        )

    if paper:
        # Convert database models to response schemas
        sections = sorted(paper.sections, key=lambda s: s.order_index)

        # Previous runs' rows are kept for feedback integrity but never shown.
        visible_viz = [v for v in paper.visualizations if v.status != "superseded"]
        # Every COMPLETE video per section, newest first. The old picker kept
        # one row per section and could prefer a stale previous-run row (the
        # relationship loads in heap order); pending/failed rows with a
        # leftover video_url were also mapped.
        section_videos: dict[str, list[SectionVideo]] = {}
        ordered = sorted(visible_viz, key=_viz_order, reverse=True)
        for v in ordered:
            if v.status == "complete" and v.video_url and v.section_id:
                section_videos.setdefault(v.section_id, []).append(
                    SectionVideo(viz_id=v.id, video_url=v.video_url, concept=v.concept or "")
                )

        return PaperResponse(
            paper_id=paper.id,
            title=tex_to_text(paper.title),
            authors=paper.authors or [],
            abstract=normalize_display_text(paper.abstract, from_organizer=False),
            pdf_url=paper.pdf_url or f"https://arxiv.org/pdf/{paper.id}",
            html_url=paper.html_url,
            sections=[
                SectionResponse(
                    id=s.id,
                    title=tex_to_text(s.title),
                    # Normalized on the way out so the ~940 papers stored
                    # before the ingest-time rules render cleanly too.
                    content=normalize_display_text(s.content),
                    summary=normalize_display_text(s.summary) if s.summary else None,
                    level=s.level,
                    order_index=s.order_index,
                    equations=s.equations or [],
                    video_url=_first_video_url(section_videos.get(s.id)),
                    videos=section_videos.get(s.id, []),
                )
                for s in sections
            ],
            visualizations=[
                VisualizationResponse(
                    id=v.id,
                    section_id=v.section_id,
                    concept=v.concept,
                    video_url=v.video_url,
                    status=VisualizationStatus(v.status),
                )
                for v in visible_viz
            ],
            processed_at=paper.updated_at or paper.created_at or _utcnow_naive(),
        )

    raise HTTPException(
        status_code=404,
        detail=f"Paper '{arxiv_id}' not found. Try processing it first with POST /api/process"
    )


@router.get("/papers", response_model=PaperListResponse)
async def list_papers(db: AsyncSession = Depends(get_db)):
    """
    List all processed papers for the Explore gallery.

    ``visualization_count`` is the number of sections with a playable video
    (rows of any status used to be counted, so 84% of cards disagreed with
    what the page could show); ``status`` lets the gallery label in-flight
    papers and hide empty ones.
    """
    rows = await queries.list_paper_summaries(db)

    def _status(row: dict) -> str:
        # Pre-fix abstract-only ingests: not a paper, whatever videos were
        # made from it. Hidden until a request re-ingests it.
        if queries.is_stale(row["updated_at"] or row["created_at"], row["text_chars"]):
            return "processing" if row["processing"] else "stale"
        if row["playable_sections"] > 0:
            return "ready"
        return "processing" if row["processing"] else "empty"

    return PaperListResponse(
        papers=[
            PaperSummary(
                paper_id=row["paper_id"],
                title=tex_to_text(row["title"]),
                authors=row["authors"],
                visualization_count=row["playable_sections"],
                status=_status(row),
                processed_at=row["updated_at"] or row["created_at"] or _utcnow_naive(),
            )
            for row in rows
        ],
        total=len(rows),
    )


@router.get("/video/{video_id}")
async def get_video(video_id: str):
    """
    Get a rendered visualization video.

    Returns the actual video file if it exists locally,
    or redirects to the cloud URL (R2) if available.
    """
    # Try local file first
    video_path = get_video_path(video_id)
    if video_path and video_path.exists():
        return FileResponse(
            path=str(video_path),
            media_type="video/mp4",
            filename=f"{video_id}.mp4"
        )

    # Try cloud URL (R2 mode)
    cloud_url = get_video_url(video_id)
    if cloud_url and cloud_url.startswith("http"):
        return RedirectResponse(url=cloud_url, status_code=302)

    raise HTTPException(
        status_code=404,
        detail=f"Video '{video_id}' not found"
    )


@router.post("/render", response_model=RenderResponse)
async def render_manim(
    request: RenderRequest,
    x_render_secret: str | None = Header(default=None),
):
    """
    Test endpoint to render Manim code directly.

    This is for testing/development purposes only — it executes caller-supplied
    Python. It is disabled in production unless RENDER_API_SECRET is set and the
    caller presents it via the X-Render-Secret header. In production, rendering
    happens as part of the paper processing pipeline.
    """
    _authorize_render(x_render_secret)
    try:
        # Generate a unique video ID
        video_id = f"test_{uuid.uuid4().hex[:8]}"

        # Extract scene name for response
        scene_name = extract_scene_name(request.code)

        # Render the visualization
        video_url = await process_visualization(
            viz_id=video_id,
            manim_code=request.code,
            quality=request.quality
        )

        return RenderResponse(
            video_id=video_id,
            video_url=video_url,
            scene_name=scene_name,
            message=f"Successfully rendered {scene_name}"
        )

    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Rendering failed: {e!s}"
        ) from e
    except Exception:
        logger.exception("Unexpected error while rendering Manim code")
        raise HTTPException(
            status_code=500,
            detail="Internal error while rendering. See server logs.",
        ) from None


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Store viewer feedback.

    kind=video: a verdict on one rendered visualization — this is labeled
    ground truth the visual-QA judge can be calibrated against, so the viz
    must exist and carry a vote. kind=site: a free-text suggestion.
    """
    ip = client_ip(http_request)
    enforce(feedback_limiter, ip, "Too much feedback from this address. Try again later.",
            client_tag=ip_fingerprint(ip))

    paper_id = None
    if request.kind == "video":
        if not request.viz_id or not request.vote:
            raise HTTPException(
                status_code=422,
                detail="Video feedback requires viz_id and vote.",
            )
        viz = await queries.get_visualization(db, request.viz_id)
        if viz is None:
            raise HTTPException(status_code=404, detail="Visualization not found")
        paper_id = viz.paper_id
    elif not (request.comment and request.comment.strip()):
        raise HTTPException(
            status_code=422,
            detail="Site feedback requires a comment.",
        )

    await queries.create_feedback(
        db,
        kind=request.kind,
        viz_id=request.viz_id if request.kind == "video" else None,
        paper_id=paper_id,
        vote=request.vote if request.kind == "video" else None,
        # reason is the downvote category — meaningless on site rows.
        reason=request.reason if request.kind == "video" else None,
        comment=request.comment,
    )
    logger.info(
        "Feedback stored: kind=%s viz=%s vote=%s",
        request.kind, request.viz_id, request.vote,
    )
    return FeedbackResponse()


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint.

    Returns status of the API and dependent services.
    """
    import os
    import subprocess

    # Test database connection
    db_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e!s}"

    # Test Manim availability
    manim_status = "not found"
    try:
        manim_exe = os.getenv("MANIM_EXECUTABLE", "manim")
        result = subprocess.run(
            [manim_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip().split("\n")[0]
            manim_status = f"available ({version})"
        else:
            detail = (result.stderr.strip() or result.stdout.strip()).splitlines()
            manim_status = f"error: {detail[-1][:200] if detail else 'command failed'}"
    except FileNotFoundError:
        manim_status = "not installed"
    except Exception as e:
        manim_status = f"error: {e!s}"

    # Test storage connectivity
    from rendering.storage import STORAGE_MODE, get_backend
    storage_status = "local"
    if STORAGE_MODE == "r2":
        backend = get_backend()
        if hasattr(backend, "check_connectivity"):
            try:
                storage_status = "r2: connected" if backend.check_connectivity() else "r2: unreachable"
            except Exception as e:
                storage_status = f"r2: error ({e})"
        else:
            storage_status = "r2: configured"

    # Check Modal configuration
    from rendering import RENDER_MODE
    modal_status = "not configured"
    if RENDER_MODE == "modal":
        modal_token = os.getenv("MODAL_TOKEN_ID")
        modal_status = "configured" if modal_token else "missing MODAL_TOKEN_ID"

    # When using Modal, manim doesn't need to be local
    if RENDER_MODE == "modal":
        all_healthy = db_status == "connected"
    else:
        all_healthy = db_status == "connected" and "available" in manim_status

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        version="0.1.0",
        services={
            "database": db_status,
            "manim": manim_status if RENDER_MODE != "modal" else f"offloaded to modal ({manim_status})",
            "storage": storage_status,
            "redis": "not configured",
            "modal": modal_status
        }
    )
