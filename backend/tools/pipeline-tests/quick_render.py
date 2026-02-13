#!/usr/bin/env python3
"""
Quick render utility - test Manim code snippets directly.

This is the fastest way to test video rendering with custom code.

Usage:
    # Render a Manim code file
    python quick_render.py examples/voiceover_equation.py

    # Render with high quality
    python quick_render.py examples/voiceover_equation.py --quality high_quality

    # Render with verbose output
    python quick_render.py examples/voiceover_equation.py -v

    # Use a specific scene name
    python quick_render.py examples/voiceover_equation.py --scene MyScene
"""

import asyncio
import argparse
import logging
import sys
import uuid
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


async def main():
    """Quick render main function."""
    parser = argparse.ArgumentParser(
        description="Quickly render a Manim code file to video",
        usage="python quick_render.py <code_file> [options]"
    )

    parser.add_argument(
        "code_file",
        help="Path to Python file with Manim scene code"
    )
    parser.add_argument(
        "-q", "--quality",
        default="low_quality",
        choices=["low_quality", "medium_quality", "high_quality"],
        help="Render quality (default: low_quality for speed)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "-s", "--scene",
        type=str,
        help="Specific scene name to render (auto-detected if not provided)"
    )
    parser.add_argument(
        "--viz-id",
        type=str,
        help="Custom visualization ID (auto-generated if not provided)"
    )

    args = parser.parse_args()

    # Set verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("rendering").setLevel(logging.DEBUG)

    # Validate file
    code_path = Path(args.code_file)
    if not code_path.exists():
        logger.error(f"File not found: {code_path}")
        return False

    # Read code
    with open(code_path) as f:
        manim_code = f.read()

    logger.info("=" * 70)
    logger.info(f"Quick Render - {code_path.name}")
    logger.info("=" * 70)
    logger.info(f"Quality: {args.quality}")

    try:
        from rendering import process_visualization, extract_scene_name

        # Detect or use provided scene name
        if args.scene:
            scene_name = args.scene
            logger.info(f"Using specified scene: {scene_name}")
        else:
            scene_name = extract_scene_name(manim_code)
            logger.info(f"Detected scene: {scene_name}")

        # Generate or use provided viz_id
        viz_id = args.viz_id or f"quick_{uuid.uuid4().hex[:8]}"
        logger.info(f"Visualization ID: {viz_id}")
        logger.info("-" * 70)

        # Render
        video_url = await process_visualization(
            viz_id=viz_id,
            manim_code=manim_code,
            quality=args.quality
        )

        logger.info("-" * 70)
        logger.info("✓ Render completed successfully!")
        logger.info(f"Video URL: {video_url}")
        logger.info("=" * 70)

        return True

    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure you're in the backend directory with dependencies installed")
        return False
    except RuntimeError as e:
        logger.error(f"Render failed: {e}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
