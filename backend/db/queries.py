"""
Database queries for ArXiviz.

CRUD operations for papers, sections, visualizations, and processing jobs.
"""

import uuid
from datetime import datetime
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


async def create_standalone_visualization(
    db: AsyncSession,
    viz_id: str,
    concept: str,
    manim_code: str,
    video_url: str,
    status: str = "complete",
) -> Visualization:
    """
    Create a standalone visualization without a paper_id.
    
    Used for direct Manim file uploads that aren't associated with a paper.
    """
    viz = Visualization(
        id=viz_id,
        paper_id=None,  # Standalone, not associated with a paper
        section_id=None,
        concept=concept,
        manim_code=manim_code,
        video_url=video_url,
        status=status,
    )
    db.add(viz)
    await db.commit()
    await db.refresh(viz)
    return viz


async def list_all_visualizations(db: AsyncSession) -> list[Visualization]:
    """
    List all visualizations in the database.
    
    Returns all visualizations ordered by creation date (newest first).
    """
    result = await db.execute(
        select(Visualization).order_by(Visualization.created_at.desc())
    )
    return list(result.scalars().all())


async def get_visualization(db: AsyncSession, viz_id: str) -> Optional[Visualization]:
    """Get a visualization by its ID."""
    result = await db.execute(
        select(Visualization).where(Visualization.id == viz_id)
    )
    return result.scalar_one_or_none()


# === Seeding ===

async def seed_mock_paper(db: AsyncSession):
    """
    Seed the database with "Attention Is All You Need" paper for testing.

    Only seeds if the paper doesn't already exist.
    """
    arxiv_id = "1706.03762"

    # Check if already exists
    if await paper_exists(db, arxiv_id):
        return

    # Create paper
    paper = await create_paper(
        db=db,
        arxiv_id=arxiv_id,
        title="Attention Is All You Need",
        authors=[
            "Ashish Vaswani",
            "Noam Shazeer",
            "Niki Parmar",
            "Jakob Uszkoreit",
            "Llion Jones",
            "Aidan N. Gomez",
            "Lukasz Kaiser",
            "Illia Polosukhin",
        ],
        abstract="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks show these models to be superior in quality while being more parallelizable and requiring significantly less time to train.",
        pdf_url="https://arxiv.org/pdf/1706.03762",
        html_url="https://ar5iv.org/abs/1706.03762",
    )

    # Create sections
    sections_data = [
        {
            "id": "section-1",
            "title": "Introduction",
            "content": "Recurrent neural networks, long short-term memory and gated recurrent neural networks in particular, have been firmly established as state of the art approaches in sequence modeling and transduction problems such as language modeling and machine translation. Numerous efforts have since continued to push the boundaries of recurrent language models and encoder-decoder architectures.",
            "level": 1,
            "order_index": 0,
            "equations": [],
        },
        {
            "id": "section-3",
            "title": "Model Architecture",
            "content": "Most competitive neural sequence transduction models have an encoder-decoder structure. Here, the encoder maps an input sequence of symbol representations to a sequence of continuous representations. Given z, the decoder then generates an output sequence of symbols one element at a time.",
            "level": 1,
            "order_index": 1,
            "equations": [r"\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V"],
        },
        {
            "id": "section-3-2",
            "title": "Scaled Dot-Product Attention",
            "content": "We call our particular attention 'Scaled Dot-Product Attention'. The input consists of queries and keys of dimension dk, and values of dimension dv. We compute the dot products of the query with all keys, divide each by √dk, and apply a softmax function to obtain the weights on the values.",
            "level": 2,
            "order_index": 2,
            "equations": [r"\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V"],
        },
        {
            "id": "section-3-3",
            "title": "Multi-Head Attention",
            "content": "Instead of performing a single attention function with dmodel-dimensional keys, values and queries, we found it beneficial to linearly project the queries, keys and values h times with different, learned linear projections to dk, dk and dv dimensions, respectively.",
            "level": 2,
            "order_index": 3,
            "equations": [
                r"\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, ..., \text{head}_h)W^O",
                r"\text{head}_i = \text{Attention}(QW_i^Q, KW_i^K, VW_i^V)",
            ],
        },
        {
            "id": "section-7",
            "title": "Conclusion",
            "content": "In this work, we presented the Transformer, the first sequence transduction model based entirely on attention, replacing the recurrent layers most commonly used in encoder-decoder architectures with multi-headed self-attention.",
            "level": 1,
            "order_index": 4,
            "equations": [],
        },
    ]

    for s in sections_data:
        await create_section(
            db=db,
            section_id=s["id"],
            paper_id=arxiv_id,
            title=s["title"],
            content=s["content"],
            level=s["level"],
            order_index=s["order_index"],
            equations=s["equations"],
        )

    # Create visualizations
    visualizations_data = [
        {
            "id": "viz_001",
            "section_id": "section-3-2",
            "concept": "Scaled Dot-Product Attention",
            "status": "complete",
            "video_url": "https://placeholder.arxiviz.org/videos/viz_001.mp4",
        },
        {
            "id": "viz_002",
            "section_id": "section-3-3",
            "concept": "Multi-Head Attention",
            "status": "complete",
            "video_url": "https://placeholder.arxiviz.org/videos/viz_002.mp4",
        },
    ]

    for v in visualizations_data:
        await create_visualization(
            db=db,
            viz_id=v["id"],
            paper_id=arxiv_id,
            section_id=v["section_id"],
            concept=v["concept"],
            status=v["status"],
            video_url=v["video_url"],
        )

    print(f"✓ Seeded mock paper: {arxiv_id}")
