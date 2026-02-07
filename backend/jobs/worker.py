"""
Background job processing for ArXiviz.

Processes papers asynchronously with progress tracking.
"""

import asyncio
import logging
from db.connection import async_session_maker
from db import queries
from db.models import Section
from rendering import process_visualization, get_video_path
from agents.pipeline import generate_visualizations
from models.paper import (
    ArxivPaperMeta,
    Equation,
    Figure,
    Section as PaperSection,
    StructuredPaper,
    Table,
)

logger = logging.getLogger(__name__)


async def process_paper_job(job_id: str, arxiv_id: str):
    """
    Main job processing function. Called as a background task.

    Pipeline:
    1. Ingest paper from arXiv (real fetch + parse)
    2. Store paper and sections in database
    3. Pick visualizations for sections
    4. Render all visualizations
    5. Update job status to completed
    """
    async with async_session_maker() as db:
        try:
            # Step 1: Ingest paper from arXiv
            await queries.update_job_status(
                db, job_id,
                status="processing",
                current_step="Fetching paper from arXiv",
                progress=0.05
            )

            paper_exists = await queries.paper_exists(db, arxiv_id)
            if not paper_exists:
                await _ingest_and_store_paper(db, job_id, arxiv_id)
            else:
                # Paper already exists, just link the job to it
                job = await queries.get_job(db, job_id)
                if job:
                    job.paper_id = arxiv_id
                    await db.commit()

            # Step 2: Generate visualizations from structured paper
            await queries.update_job_status(
                db, job_id,
                current_step="Generating visualizations",
                progress=0.3
            )

            db_paper = await queries.get_paper(db, arxiv_id)
            db_sections = sorted(db_paper.sections, key=lambda s: s.order_index)
            structured_paper = _build_structured_paper_from_db(db_paper, db_sections)
            generated_visualizations = await generate_visualizations(structured_paper)

            # Create visualization records
            viz_records = []
            job_suffix = job_id.replace("job_", "")[:8]
            for i, visualization in enumerate(generated_visualizations):
                viz_id = f"viz_{job_suffix}_{i+1}"
                await queries.create_visualization(
                    db,
                    viz_id=viz_id,
                    paper_id=arxiv_id,
                    section_id=visualization.section_id,
                    concept=visualization.concept,
                    storyboard={"raw": visualization.storyboard},
                    manim_code=visualization.manim_code,
                    status="pending",
                )
                viz_records.append({
                    "id": viz_id,
                    "manim_code": visualization.manim_code,
                })

            if not viz_records:
                await queries.update_job_status(
                    db, job_id,
                    status="completed",
                    current_step="No valid visualizations generated",
                    progress=1.0
                )
                return

            # Step 3: Render visualizations
            await queries.update_job_status(
                db, job_id,
                current_step="Rendering videos",
                progress=0.4,
                sections_total=len(viz_records),
                sections_completed=0
            )

            render_semaphore = asyncio.Semaphore(3)

            async def _render_one(viz: dict):
                async with render_semaphore:
                    try:
                        video_url = await process_visualization(
                            viz_id=viz["id"],
                            manim_code=viz["manim_code"],
                            quality="low_quality"
                        )
                        await queries.update_visualization_status(
                            db, viz["id"],
                            status="complete",
                            video_url=video_url
                        )
                    except Exception as e:
                        await queries.update_visualization_status(
                            db, viz["id"],
                            status="failed",
                            error=str(e)
                        )

            await asyncio.gather(*[
                _render_one(viz) for viz in viz_records
            ])

            await queries.update_job_status(
                db, job_id,
                progress=0.9,
                sections_completed=len(viz_records)
            )

            # Step 4: Complete
            await queries.update_job_status(
                db, job_id,
                status="completed",
                current_step="Complete",
                progress=1.0
            )

        except Exception as e:
            logger.exception(f"Job {job_id} failed for paper {arxiv_id}")
            try:
                await db.rollback()
                await queries.update_job_status(
                    db, job_id,
                    status="failed",
                    error=str(e)
                )
            except Exception:
                logger.exception("Failed to update job status after error")
            raise


async def _ingest_and_store_paper(db, job_id: str, arxiv_id: str):
    """
    Ingest a real paper from arXiv and store it in the database.
    """
    from ingestion import ingest_paper

    await queries.update_job_status(
        db, job_id,
        current_step="Fetching paper metadata from arXiv",
        progress=0.1
    )

    structured_paper = await ingest_paper(arxiv_id)
    meta = structured_paper.meta

    await queries.update_job_status(
        db, job_id,
        current_step=f"Parsed: {meta.title[:60]}",
        progress=0.2
    )

    # Store paper record
    await queries.create_paper(
        db,
        arxiv_id=meta.arxiv_id,
        title=meta.title,
        authors=meta.authors,
        abstract=meta.abstract,
        pdf_url=meta.pdf_url,
        html_url=meta.html_url,
    )

    # Now that the paper exists, link the job to it
    job = await queries.get_job(db, job_id)
    if job:
        job.paper_id = meta.arxiv_id
        await db.commit()

    # Store sections using savepoints so one failure doesn't roll back the paper
    stored_count = 0
    seen_ids = set()
    for i, section in enumerate(structured_paper.sections):
        # Ensure unique section IDs
        sid = section.id
        if sid in seen_ids:
            sid = f"{sid}-{i}"
        seen_ids.add(sid)

        try:
            async with db.begin_nested():
                equations_json = [eq.latex for eq in section.equations]
                figures_json = [fig.model_dump() for fig in section.figures]
                tables_json = [tbl.model_dump() for tbl in section.tables]

                section_obj = Section(
                    id=sid,
                    paper_id=meta.arxiv_id,
                    title=section.title,
                    content=section.content,
                    summary=section.summary or None,
                    level=section.level,
                    order_index=i,
                    equations=equations_json,
                    figures=figures_json,
                    tables=tables_json,
                )
                db.add(section_obj)
            stored_count += 1
        except Exception as e:
            logger.warning(f"Failed to store section '{section.title}': {e}")

    await db.commit()

    logger.info(f"Stored paper '{meta.title}' with {stored_count}/{len(structured_paper.sections)} sections")


def _build_structured_paper_from_db(db_paper, db_sections: list[Section]) -> StructuredPaper:
    """Reconstruct StructuredPaper from database rows for generator pipeline input."""
    meta = ArxivPaperMeta(
        arxiv_id=db_paper.id,
        title=db_paper.title,
        authors=db_paper.authors or [],
        abstract=db_paper.abstract or "",
        pdf_url=db_paper.pdf_url or f"https://arxiv.org/pdf/{db_paper.id}",
        html_url=db_paper.html_url,
    )

    sections: list[PaperSection] = []
    for db_section in db_sections:
        equations = [
            Equation(latex=eq if isinstance(eq, str) else str(eq), context="")
            for eq in (db_section.equations or [])
        ]
        figures = [
            Figure(
                id=fig.get("id", f"{db_section.id}-figure-{idx+1}"),
                caption=fig.get("caption", ""),
                page=fig.get("page"),
            )
            for idx, fig in enumerate(db_section.figures or [])
            if isinstance(fig, dict)
        ]
        tables = [
            Table(
                id=tbl.get("id", f"{db_section.id}-table-{idx+1}"),
                caption=tbl.get("caption", ""),
                headers=tbl.get("headers", []),
                rows=tbl.get("rows", []),
            )
            for idx, tbl in enumerate(db_section.tables or [])
            if isinstance(tbl, dict)
        ]

        sections.append(
            PaperSection(
                id=db_section.id,
                title=db_section.title,
                level=db_section.level,
                content=db_section.content or "",
                equations=equations,
                figures=figures,
                tables=tables,
            )
        )

    return StructuredPaper(meta=meta, sections=sections)
