#!/usr/bin/env python3
"""
Standalone video generation test script.

This script allows you to test video rendering separately from the full pipeline.
It extracts the video generation step from the main worker pipeline.

Usage:
    # Test with a sample Manim code snippet
    python test_video_generation.py --code-file examples/voiceover_equation.py

    # Test with code directly
    python test_video_generation.py --code "class TestScene(MovingCameraScene): ..."

    # Test with quality setting
    python test_video_generation.py --code-file examples/voiceover_equation.py --quality low_quality

    # Render and keep the generated files
    python test_video_generation.py --code-file examples/voiceover_equation.py --keep-temp
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
logging.getLogger("rendering").setLevel(logging.INFO)


async def main():
    """Main test function."""
    parser = argparse.ArgumentParser(
        description="Test video generation independently from the pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with a file
  python test_video_generation.py --code-file examples/voiceover_equation.py

  # Test with inline code
  python test_video_generation.py --code "class TestScene(Scene): ..."

  # Test with different quality
  python test_video_generation.py --code-file examples/voiceover_equation.py --quality low_quality

  # Keep temporary files for inspection
  python test_video_generation.py --code-file examples/voiceover_equation.py --keep-temp
        """
    )

    parser.add_argument(
        "--code-file",
        type=str,
        help="Path to file containing Manim code"
    )
    parser.add_argument(
        "--code",
        type=str,
        help="Manim code as string (use if not providing --code-file)"
    )
    parser.add_argument(
        "--quality",
        type=str,
        default="low_quality",
        choices=["low_quality", "medium_quality", "high_quality"],
        help="Quality preset for rendering (default: low_quality)"
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary render files for inspection"
    )
    parser.add_argument(
        "--viz-id",
        type=str,
        default="test_viz",
        help="Video ID prefix (default: test_viz)"
    )

    args = parser.parse_args()

    # Get Manim code
    manim_code = None
    if args.code_file:
        code_path = Path(args.code_file)
        if not code_path.exists():
            logger.error(f"Code file not found: {code_path}")
            return False
        with open(code_path) as f:
            manim_code = f.read()
        logger.info(f"Loaded code from: {code_path}")
    elif args.code:
        manim_code = args.code
        logger.info("Using provided Manim code")
    else:
        logger.error("Either --code-file or --code must be provided")
        parser.print_help()
        return False

    # Import rendering function
    try:
        from rendering import process_visualization, extract_scene_name
    except ImportError as e:
        logger.error(f"Failed to import rendering module: {e}")
        logger.error("Make sure you're running this from the backend directory")
        return False

    # Extract scene name for logging
    scene_name = extract_scene_name(manim_code)
    logger.info(f"Scene name detected: {scene_name}")

    # Run rendering
    logger.info("=" * 60)
    logger.info("Starting video rendering...")
    logger.info("=" * 60)

    try:
        video_url = await process_visualization(
            viz_id=args.viz_id,
            manim_code=manim_code,
            quality=args.quality
        )

        logger.info("=" * 60)
        logger.info("✓ Video rendering completed successfully!")
        logger.info("=" * 60)
        logger.info(f"Video ID: {args.viz_id}")
        logger.info(f"Scene: {scene_name}")
        logger.info(f"Quality: {args.quality}")
        logger.info(f"Video URL: {video_url}")

        return True

    except RuntimeError as e:
        logger.error(f"✗ Rendering failed: {e}")
        return False
    except Exception as e:
        logger.exception(f"✗ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
