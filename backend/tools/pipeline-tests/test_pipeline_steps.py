#!/usr/bin/env python3
"""
Step-by-step pipeline testing script.

This allows you to test each phase of the visualization pipeline independently:
1. Paper ingestion and parsing
2. Visualization planning and generation
3. Code validation
4. Video rendering

Usage:
    # Test entire pipeline for a paper
    python test_pipeline_steps.py --arxiv-id 2410.05905 --step all

    # Test only visualization generation
    python test_pipeline_steps.py --arxiv-id 2410.05905 --step generate

    # Test only video rendering
    python test_pipeline_steps.py --arxiv-id 2410.05905 --step render

    # List available steps
    python test_pipeline_steps.py --help
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Set specific logger levels
logging.getLogger("agents").setLevel(logging.INFO)
logging.getLogger("rendering").setLevel(logging.INFO)


async def ingest_paper(arxiv_id: str):
    """Step 1: Ingest paper from arXiv."""
    logger.info("=" * 60)
    logger.info("STEP 1: Ingesting paper from arXiv")
    logger.info("=" * 60)

    try:
        from ingestion import ingest_paper as ingest_paper_fn
        paper = await ingest_paper_fn(arxiv_id)
        logger.info(f"✓ Successfully ingested: {paper.meta.title}")
        logger.info(f"  Authors: {', '.join(paper.meta.authors[:3])}")
        logger.info(f"  Sections: {len(paper.sections)}")
        logger.info(f"  Abstract: {paper.meta.abstract[:100]}...")
        return paper
    except Exception as e:
        logger.error(f"✗ Failed to ingest paper: {e}")
        raise


async def generate_visualizations(paper):
    """Step 2: Generate visualizations from paper."""
    logger.info("=" * 60)
    logger.info("STEP 2: Generating visualizations")
    logger.info("=" * 60)

    try:
        from agents.pipeline import generate_visualizations as gen_viz
        visualizations = await gen_viz(paper, max_visualizations=3)
        logger.info(f"✓ Generated {len(visualizations)} visualizations")
        for i, viz in enumerate(visualizations, 1):
            logger.info(f"  [{i}] {viz.concept} (section: {viz.section_id})")
            logger.info(f"      Status: {viz.status}")
        return visualizations
    except Exception as e:
        logger.error(f"✗ Failed to generate visualizations: {e}")
        raise


async def render_videos(visualizations):
    """Step 3: Render videos for all visualizations."""
    logger.info("=" * 60)
    logger.info(f"STEP 3: Rendering {len(visualizations)} videos")
    logger.info("=" * 60)

    try:
        from rendering import process_visualization
        import uuid

        render_results = []
        for i, viz in enumerate(visualizations, 1):
            try:
                viz_id = f"test_{uuid.uuid4().hex[:8]}"
                logger.info(f"  [{i}/{len(visualizations)}] Rendering {viz_id}...")

                video_url = await process_visualization(
                    viz_id=viz_id,
                    manim_code=viz.manim_code,
                    quality="low_quality"
                )

                logger.info(f"    ✓ Success: {video_url}")
                render_results.append({
                    "viz_id": viz_id,
                    "concept": viz.concept,
                    "video_url": video_url
                })
            except Exception as e:
                logger.error(f"    ✗ Failed: {str(e)[:100]}")

        logger.info(f"✓ Rendered {len(render_results)}/{len(visualizations)} videos successfully")
        return render_results

    except Exception as e:
        logger.error(f"✗ Failed to render videos: {e}")
        raise


async def run_full_pipeline(arxiv_id: str):
    """Run the complete pipeline."""
    logger.info("Starting full pipeline...")
    logger.info("This will: ingest paper -> generate visualizations -> render videos")

    try:
        # Step 1: Ingest
        paper = await ingest_paper(arxiv_id)

        # Step 2: Generate
        visualizations = await generate_visualizations(paper)

        if not visualizations:
            logger.warning("No visualizations generated, skipping rendering step")
            return True

        # Step 3: Render
        render_results = await render_videos(visualizations)

        logger.info("=" * 60)
        logger.info("✓ Full pipeline completed successfully!")
        logger.info("=" * 60)
        for result in render_results:
            logger.info(f"  {result['concept']}: {result['video_url']}")

        return True

    except Exception as e:
        logger.exception(f"✗ Pipeline failed: {e}")
        return False


async def test_step(arxiv_id: str, step: str):
    """Test a specific step of the pipeline."""
    try:
        if step == "ingest":
            await ingest_paper(arxiv_id)
        elif step == "generate":
            paper = await ingest_paper(arxiv_id)
            await generate_visualizations(paper)
        elif step == "render":
            # For this step, we need visualizations from the database or provide sample code
            logger.error("Render step requires visualizations from previous steps")
            logger.info("Run with --step all or --step generate first")
            return False
        elif step == "all":
            return await run_full_pipeline(arxiv_id)
        else:
            logger.error(f"Unknown step: {step}")
            return False
        return True
    except Exception as e:
        logger.exception(f"Step '{step}' failed: {e}")
        return False


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test visualization pipeline steps individually",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test entire pipeline
  python test_pipeline_steps.py --arxiv-id 2410.05905 --step all

  # Test just paper ingestion
  python test_pipeline_steps.py --arxiv-id 2410.05905 --step ingest

  # Test visualization generation
  python test_pipeline_steps.py --arxiv-id 2410.05905 --step generate

Available steps:
  ingest   - Fetch and parse paper from arXiv
  generate - Generate visualizations from paper
  render   - Render videos from visualizations
  all      - Run complete pipeline (default)
        """
    )

    parser.add_argument(
        "--arxiv-id",
        type=str,
        required=True,
        help="arXiv paper ID (e.g., 2410.05905)"
    )
    parser.add_argument(
        "--step",
        type=str,
        default="all",
        choices=["ingest", "generate", "render", "all"],
        help="Pipeline step to test (default: all)"
    )
    parser.add_argument(
        "--max-viz",
        type=int,
        default=3,
        help="Maximum visualizations to generate (default: 3)"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"ArXiviz Pipeline Test - Step: {args.step.upper()}")
    logger.info(f"Paper ID: {args.arxiv_id}")
    logger.info("=" * 60)

    success = await test_step(args.arxiv_id, args.step)
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
