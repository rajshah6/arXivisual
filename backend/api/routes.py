"""
FastAPI routes for the ArXiviz API.

Now using SQLite database and local Manim rendering.
"""

import uuid
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from .schemas import (
    ProcessRequest,
    ProcessResponse,
    StatusResponse,
    StepInfo,
    PaperResponse,
    PaperListResponse,
    PaperSummary,
    SectionResponse,
    VisualizationResponse,
    VideoResponse,
    HealthResponse,
    JobStatus,
    VisualizationStatus,
    RenderRequest,
    RenderResponse,
)
from db.connection import get_db
from db import queries
from rendering import process_visualization, get_video_path, extract_scene_name
from jobs import process_paper_job

router = APIRouter(prefix="/api")


# === Endpoints ===

@router.post("/process", response_model=ProcessResponse)
async def start_processing(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Start processing an arXiv paper.

    Returns immediately with a job_id. Poll /api/status/{job_id} for progress.
    """
    # Create job in database
    job_id = await queries.create_job(db, request.arxiv_id)

    # Start background processing
    background_tasks.add_task(process_paper_job, job_id, request.arxiv_id)

    return ProcessResponse(
        job_id=job_id,
        arxiv_id=request.arxiv_id,
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


@router.get("/paper/{arxiv_id}", response_model=PaperResponse)
async def get_paper(arxiv_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get a processed paper with all sections and visualizations.

    Returns 404 if the paper hasn't been processed yet.
    """
    # Handle version suffix (e.g., "1706.03762v1" -> "1706.03762")
    base_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id

    paper = await queries.get_paper(db, base_id)

    if paper:
        # Convert database models to response schemas
        sections = sorted(paper.sections, key=lambda s: s.order_index)

        # Build section_id -> video_url lookup from visualizations
        section_video_map = {}
        for v in paper.visualizations:
            if v.video_url and v.section_id:
                section_video_map[v.section_id] = v.video_url

        return PaperResponse(
            paper_id=paper.id,
            title=paper.title,
            authors=paper.authors or [],
            abstract=paper.abstract or "",
            pdf_url=paper.pdf_url or f"https://arxiv.org/pdf/{paper.id}",
            html_url=paper.html_url,
            sections=[
                SectionResponse(
                    id=s.id,
                    title=s.title,
                    content=s.content or "",
                    summary=s.summary or None,
                    level=s.level,
                    order_index=s.order_index,
                    equations=s.equations or [],
                    video_url=section_video_map.get(s.id),
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
                for v in paper.visualizations
            ],
            processed_at=paper.updated_at or paper.created_at or datetime.utcnow(),
        )

    raise HTTPException(
        status_code=404,
        detail=f"Paper '{arxiv_id}' not found. Try processing it first with POST /api/process"
    )


@router.get("/papers", response_model=PaperListResponse)
async def list_papers(db: AsyncSession = Depends(get_db)):
    """
    List all processed papers.

    Returns a summary of each paper with visualization counts.
    """
    papers = await queries.list_papers(db)

    return PaperListResponse(
        papers=[
            PaperSummary(
                paper_id=p.id,
                title=p.title,
                authors=p.authors or [],
                visualization_count=len(p.visualizations) if p.visualizations else 0,
                processed_at=p.updated_at or p.created_at or datetime.utcnow(),
            )
            for p in papers
        ],
        total=len(papers),
    )


@router.get("/video/{video_id}")
async def get_video(video_id: str):
    """
    Get a rendered visualization video.

    Returns the actual video file if it exists locally,
    or video metadata if it's a placeholder.
    """
    # Check if video exists in local storage
    video_path = get_video_path(video_id)

    if video_path and video_path.exists():
        # Serve the actual video file
        return FileResponse(
            path=str(video_path),
            media_type="video/mp4",
            filename=f"{video_id}.mp4"
        )

    # Return 404 if video doesn't exist
    raise HTTPException(
        status_code=404,
        detail=f"Video '{video_id}' not found"
    )


@router.post("/render", response_model=RenderResponse)
async def render_manim(request: RenderRequest):
    """
    Test endpoint to render Manim code directly.

    This is for testing/development purposes.
    In production, rendering happens as part of the paper processing pipeline.
    """
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
            detail=f"Rendering failed: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint.

    Returns status of the API and dependent services.
    """
    import subprocess
    import os

    # Test database connection
    db_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"

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
            manim_status = "error: command failed"
    except FileNotFoundError:
        manim_status = "not installed"
    except Exception as e:
        manim_status = f"error: {str(e)}"

    all_healthy = db_status == "connected" and "available" in manim_status

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        version="0.1.0",
        services={
            "database": db_status,
            "manim": manim_status,
            "redis": "not configured",
            "modal": "not configured"
        }
    )
