"""
Database queries for ArXiviz.

CRUD operations for papers, sections, visualizations, and processing jobs.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Paper, Section, Visualization, ProcessingJob


# === Processing Jobs ===

async def create_job(db: AsyncSession, arxiv_id: str) -> str:
    """Create a new processing job and return the job_id."""
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job = ProcessingJob(
        id=job_id,
        paper_id=None,  # Set after paper record is created to avoid FK violation
        status="queued",
        progress=0.0,
        current_step="Queued for processing",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    await db.commit()
    return job_id


async def get_job(db: AsyncSession, job_id: str) -> Optional[ProcessingJob]:
    """Get a processing job by ID."""
    result = await db.execute(
        select(ProcessingJob).where(ProcessingJob.id == job_id)
    )
    return result.scalar_one_or_none()


async def get_active_job_for_paper(
    db: AsyncSession, arxiv_id: str, max_age_hours: float = 2.0
) -> Optional[ProcessingJob]:
    """Find a genuinely in-flight job for a paper, newest first.

    Jobs older than ``max_age_hours`` are ignored: a worker interrupted mid-run
    (e.g. by a redeploy) strands its job at "processing" forever, and treating
    such a zombie as active would block the paper from ever being re-processed
    via dedupe. No real pipeline run approaches this age (p95 is ~7 minutes).

    Note: jobs are created with paper_id=None (FK) and linked by the worker a
    few seconds in, so this misses just-created jobs — callers pair it with the
    in-memory recent-jobs map in api.throttle for the immediate-duplicate window.
    """
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    result = await db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.paper_id == arxiv_id,
            ProcessingJob.status.in_(("queued", "processing")),
            ProcessingJob.created_at >= cutoff,
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def reap_stale_jobs(db: AsyncSession, max_age_hours: float = 2.0) -> int:
    """Mark long-stranded queued/processing jobs as failed.

    A worker killed mid-run (redeploy, crash, OOM) never updates its job row,
    leaving it at "processing" forever — misleading pollers and, before the
    dedupe staleness cutoff, blocking re-processing. Called opportunistically
    on job submission; returns the number of jobs reaped.
    """
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.status.in_(("queued", "processing")),
            ProcessingJob.created_at < cutoff,
        )
    )
    stale = list(result.scalars().all())
    for job in stale:
        job.status = "failed"
        job.error = (
            "Job was interrupted (worker restarted mid-run) and never resumed. "
            "Submit the paper again to re-process it."
        )
    if stale:
        await db.commit()
    return len(stale)


async def update_job_status(
    db: AsyncSession,
    job_id: str,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    current_step: Optional[str] = None,
    sections_completed: Optional[int] = None,
    sections_total: Optional[int] = None,
    error: Optional[str] = None,
):
    """Update a processing job's status."""
    job = await get_job(db, job_id)
    if not job:
        return None

    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if current_step is not None:
        job.current_step = current_step
    if sections_completed is not None:
        job.sections_completed = sections_completed
    if sections_total is not None:
        job.sections_total = sections_total
    if error is not None:
        job.error = error
    if status == "completed":
        job.completed_at = datetime.utcnow()

    await db.commit()
    return job


# === Papers ===

async def get_paper(db: AsyncSession, arxiv_id: str) -> Optional[Paper]:
    """Get a paper by arXiv ID with all related sections and visualizations."""
    result = await db.execute(
        select(Paper)
        .where(Paper.id == arxiv_id)
        .options(
            selectinload(Paper.sections),
            selectinload(Paper.visualizations),
        )
    )
    return result.scalar_one_or_none()


async def create_paper(
    db: AsyncSession,
    arxiv_id: str,
    title: str,
    authors: list[str],
    abstract: str,
    pdf_url: str,
    html_url: Optional[str] = None,
) -> Paper:
    """Create a new paper."""
    paper = Paper(
        id=arxiv_id,
        title=title,
        authors=authors,
        abstract=abstract,
        pdf_url=pdf_url,
        html_url=html_url,
    )
    db.add(paper)
    await db.commit()
    await db.refresh(paper)
    return paper


async def list_papers(db: AsyncSession) -> list[Paper]:
    """List all papers with their sections and visualizations."""
    result = await db.execute(
        select(Paper)
        .options(
            selectinload(Paper.sections),
            selectinload(Paper.visualizations),
        )
        .order_by(Paper.created_at.desc())
    )
    return list(result.scalars().all())


async def paper_exists(db: AsyncSession, arxiv_id: str) -> bool:
    """Check if a paper exists in the database."""
    result = await db.execute(
        select(Paper.id).where(Paper.id == arxiv_id)
    )
    return result.scalar_one_or_none() is not None


# === Sections ===

async def create_section(
    db: AsyncSession,
    section_id: str,
    paper_id: str,
    title: str,
    content: str,
    level: int = 1,
    order_index: int = 0,
    equations: Optional[list] = None,
    figures: Optional[list] = None,
    tables: Optional[list] = None,
) -> Section:
    """Create a new section."""
    section = Section(
        id=section_id,
        paper_id=paper_id,
        title=title,
        content=content,
        level=level,
        order_index=order_index,
        equations=equations or [],
        figures=figures or [],
        tables=tables or [],
    )
    db.add(section)
    await db.commit()
    return section


# === Visualizations ===

async def create_visualization(
    db: AsyncSession,
    viz_id: str,
    paper_id: str,
    section_id: str,
    concept: str,
    status: str = "pending",
    video_url: Optional[str] = None,
    storyboard: Optional[dict] = None,
    manim_code: Optional[str] = None,
) -> Visualization:
    """Create a new visualization."""
    viz = Visualization(
        id=viz_id,
        paper_id=paper_id,
        section_id=section_id,
        concept=concept,
        storyboard=storyboard,
        manim_code=manim_code,
        status=status,
        video_url=video_url,
    )
    db.add(viz)
    await db.commit()
    return viz


async def update_visualization_status(
    db: AsyncSession,
    viz_id: str,
    status: str,
    video_url: Optional[str] = None,
    error: Optional[str] = None,
):
    """Update a visualization's status."""
    result = await db.execute(
        select(Visualization).where(Visualization.id == viz_id)
    )
    viz = result.scalar_one_or_none()
    if not viz:
        return None

    viz.status = status
    if video_url:
        viz.video_url = video_url
    if error:
        viz.error = error

    await db.commit()
    return viz


async def upsert_visualization(
    db: AsyncSession,
    viz_id: str,
    paper_id: str,
    section_id: str,
    concept: str,
    status: str = "pending",
    video_url: Optional[str] = None,
    storyboard: Optional[dict] = None,
    manim_code: Optional[str] = None,
) -> Visualization:
    """Create or update a visualization."""
    result = await db.execute(
        select(Visualization).where(Visualization.id == viz_id)
    )
    viz = result.scalar_one_or_none()

    if viz:
        # Update existing visualization
        viz.section_id = section_id
        viz.concept = concept
        viz.status = status
        if video_url:
            viz.video_url = video_url
        if storyboard:
            viz.storyboard = storyboard
        if manim_code:
            viz.manim_code = manim_code
    else:
        # Create new visualization
        viz = Visualization(
            id=viz_id,
            paper_id=paper_id,
            section_id=section_id,
            concept=concept,
            storyboard=storyboard,
            manim_code=manim_code,
            status=status,
            video_url=video_url,
        )
        db.add(viz)

    await db.commit()
    return viz
