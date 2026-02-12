"""
Local Manim rendering via subprocess.

Adapted from manim-mcp-server/src/manim_server.py
"""

import asyncio
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_manim_executable() -> str:
    """Get Manim executable path from environment or use default."""
    return os.getenv("MANIM_EXECUTABLE", "manim")


def extract_scene_name(code: str) -> str:
    """
    Extract the Scene class name from Manim code.

    Looks for patterns like: class MyScene(Scene), class TestScene(ThreeDScene), etc.
    """
    # Match class definitions that inherit from Scene or any *Scene class
    pattern = r'class\s+(\w+)\s*\(\s*\w*Scene\s*\)'
    match = re.search(pattern, code)
    if match:
        return match.group(1)
    return "MainScene"  # Fallback


def _render_manim_sync(
    code: str,
    scene_name: str,
    quality: str = "low_quality"
) -> bytes:
    """
    Synchronous Manim rendering.

    Args:
        code: Complete Manim Python code
        scene_name: Name of the Scene class to render
        quality: "low_quality", "medium_quality", or "high_quality"

    Returns:
        MP4 video file as bytes

    Raises:
        RuntimeError: If rendering fails
    """
    manim_executable = get_manim_executable()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Write code to file
        code_path = tmpdir_path / "scene.py"
        logger.info(f"  [Renderer] Writing Manim code to {code_path.name}")
        code_path.write_text(code)

        # Set up output directory
        output_dir = tmpdir_path / "media"
        logger.info(f"  [Renderer] Output directory: {output_dir}")

        # Map quality names to manim flags
        quality_flags = {
            "low_quality": "-ql",
            "medium_quality": "-qm",
            "high_quality": "-qh",
        }
        quality_flag = quality_flags.get(quality, "-ql")
        logger.info(f"  [Renderer] Rendering quality: {quality} ({quality_flag})")

        # Build manim command
        cmd = [
            manim_executable,
            "render",
            str(code_path),
            scene_name,
            quality_flag,
            "--format=mp4",
            f"--media_dir={output_dir}",
        ]

        logger.info(f"  [Renderer] Starting Manim render for scene: {scene_name}")
        logger.debug(f"  [Renderer] Command: {' '.join(cmd)}")

        # Run manim with real-time output logging
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                cwd=tmpdir,
            )

            # Log Manim output for debugging
            if result.stdout:
                logger.debug(f"  [Renderer] Manim stdout:\n{result.stdout}")
            if result.stderr:
                logger.debug(f"  [Renderer] Manim stderr:\n{result.stderr}")

        except subprocess.TimeoutExpired:
            logger.error(f"  [Renderer] Rendering timeout after 300 seconds for {scene_name}")
            raise RuntimeError(f"Manim render timed out after 300 seconds for scene {scene_name}")

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            logger.error(f"  [Renderer] Manim render failed with return code {result.returncode}")
            logger.error(f"  [Renderer] Error: {error_msg}")
            raise RuntimeError(f"Manim render failed: {error_msg}")

        logger.info(f"  [Renderer] Manim render completed successfully")

        # Find the output video file
        logger.info(f"  [Renderer] Looking for video file in {output_dir}")
        video_files = list(output_dir.rglob("*.mp4"))
        if not video_files:
            logger.error(f"  [Renderer] No MP4 files found in {output_dir}")
            raise RuntimeError(
                f"No video file produced. Manim output:\n{result.stdout}\n{result.stderr}"
            )

        video_file = video_files[0]
        file_size = video_file.stat().st_size
        logger.info(f"  [Renderer] Found video: {video_file.name} ({file_size:,} bytes)")

        # Return the video bytes
        video_bytes = video_file.read_bytes()
        logger.info(f"  [Renderer] Successfully read video file ({len(video_bytes):,} bytes)")
        return video_bytes


async def render_manim_local(
    code: str,
    scene_name: Optional[str] = None,
    quality: str = "low_quality"
) -> bytes:
    """
    Async wrapper for local Manim rendering.

    Runs the synchronous subprocess in a thread pool to avoid blocking.

    Args:
        code: Complete Manim Python code
        scene_name: Name of the Scene class to render (auto-detected if None)
        quality: "low_quality", "medium_quality", or "high_quality"

    Returns:
        MP4 video file as bytes
    """
    if scene_name is None:
        logger.info("  [Renderer] Extracting scene name from code")
        scene_name = extract_scene_name(code)
        logger.info(f"  [Renderer] Detected scene name: {scene_name}")

    logger.info(f"[Rendering] Starting async render for {scene_name}")

    # Run in thread pool to not block async event loop
    return await asyncio.to_thread(
        _render_manim_sync,
        code,
        scene_name,
        quality
    )


# Test code for manual verification
TEST_MANIM_CODE = '''
from manim import *

class TestScene(Scene):
    def construct(self):
        circle = Circle(color=BLUE)
        square = Square(color=RED).shift(RIGHT * 2)
        self.play(Create(circle))
        self.play(Transform(circle, square))
        self.wait()
'''

if __name__ == "__main__":
    # Quick test
    import sys

    print(f"Using Manim executable: {get_manim_executable()}")
    print(f"Extracted scene name: {extract_scene_name(TEST_MANIM_CODE)}")

    try:
        print("Rendering test scene...")
        video_bytes = _render_manim_sync(TEST_MANIM_CODE, "TestScene", "low_quality")

        # Save to file
        output_path = Path("test_output.mp4")
        output_path.write_bytes(video_bytes)
        print(f"Success! Video saved to {output_path} ({len(video_bytes)} bytes)")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
