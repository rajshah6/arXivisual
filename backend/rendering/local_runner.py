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

logger = logging.getLogger(__name__)


# Import-time chatter manim/manim-voiceover print to stderr before any real
# error. Matched per line when no traceback is found.
_WARNING_NOISE = ("UserWarning", "SyntaxWarning", "DeprecationWarning", "warnings.warn")

# The DB error column and log pipelines surface the head of this string, so
# keep it short enough to read but long enough to hold a full traceback box.
_ERROR_MSG_LIMIT = 4000


def _extract_render_error(stderr: str, stdout: str) -> str:
    """Distill a failed render's output into the part that names the error.

    Manim prints deprecation/syntax warnings at import time, BEFORE any
    traceback — a raw ``stderr`` head is all warning and no error (a real
    production failure was stored as just the pkg_resources deprecation
    notice, hiding the actual ValueError). Prefer everything from the last
    traceback onward; otherwise drop known warning lines; otherwise keep the
    tail, where Python puts the exception.
    """
    text = (stderr or stdout or "").strip()
    if not text:
        return "Unknown error"
    idx = text.rfind("Traceback (most recent call last)")
    if idx != -1:
        return text[idx:][:_ERROR_MSG_LIMIT]
    lines = [
        line for line in text.splitlines()
        if not any(marker in line for marker in _WARNING_NOISE)
    ]
    cleaned = "\n".join(lines).strip() or text
    return cleaned[-_ERROR_MSG_LIMIT:]


def _tts_subprocess_env() -> dict[str, str]:
    """Environment for the render subprocess.

    manim-voiceover's OpenAIService talks to the module-level OpenAI client,
    which reads ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL``. When those aren't
    already set but Azure OpenAI is configured, point them at Azure's
    OpenAI-compatible endpoint so voiceover audio bills against Azure credits.
    A pre-existing ``OPENAI_API_KEY`` (e.g. a real OpenAI key) is respected.
    """
    env = dict(os.environ)
    if not env.get("OPENAI_API_KEY"):
        endpoint = env.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        key = env.get("AZURE_OPENAI_API_KEY", "")
        if endpoint and key:
            env["OPENAI_API_KEY"] = key
            env["OPENAI_BASE_URL"] = f"{endpoint}/openai/v1/"
            # Both OPENAI_* and AZURE_OPENAI_* are now present; the module-level
            # OpenAI client refuses to guess between them. Pin it to the plain
            # OpenAI code path — our base_url already targets the Azure endpoint.
            env["OPENAI_API_TYPE"] = "openai"
    return env


def get_manim_executable() -> str:
    """Get Manim executable path from environment or venv, with system fallback."""
    env_val = os.getenv("MANIM_EXECUTABLE")
    if env_val:
        return env_val
    # Prefer the manim binary from the same venv as the running Python
    import sys
    venv_manim = Path(sys.executable).parent / "manim"
    if venv_manim.exists():
        return str(venv_manim)
    return "manim"


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


def _link_persistent_voiceover_cache(media_dir: Path, scene_name: str) -> None:
    """Persist manim-voiceover's narration cache across renders.

    The library's default cache is ``Path(media_dir) / "voiceovers"`` — inside
    the render's TemporaryDirectory, so identical narration was re-synthesized
    (and re-billed per character) on every retry/re-render. Symlinking that
    location to a stable per-scene path keeps the library on its default
    Path-typed codepath (an explicit ``cache_dir=str`` crashes its cache
    lookup) and gives each scene its own cache index, so concurrent renders
    never share — or race on — the same cache.json.

    Best effort: any failure just means the render uses the throwaway default.
    """
    try:
        cache_root = Path(os.getenv("VOICEOVER_CACHE_DIR", "/tmp/arxivisual-tts-cache"))
        safe_scene = re.sub(r"[^A-Za-z0-9_-]", "_", scene_name) or "scene"
        target = cache_root / safe_scene
        target.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / "voiceovers").symlink_to(target, target_is_directory=True)
    except Exception as exc:
        logger.warning("[Renderer] Voiceover cache link failed (%s) — using throwaway cache", exc)


def _run_manim_subprocess(
    code: str,
    scene_name: str,
    quality: str,
    label: str = "",
) -> bytes:
    """Run a single Manim render subprocess and return video bytes."""
    manim_executable = get_manim_executable()
    tag = f"  [Renderer{label}]"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        code_path = tmpdir_path / "scene.py"
        logger.info(f"{tag} Writing Manim code to {code_path.name}")
        code_path.write_text(code)

        output_dir = tmpdir_path / "media"
        _link_persistent_voiceover_cache(output_dir, scene_name)
        quality_flags = {
            "low_quality": "-ql",
            "medium_quality": "-qm",
            "high_quality": "-qh",
        }
        quality_flag = quality_flags.get(quality, "-ql")
        logger.info(f"{tag} Rendering quality: {quality} ({quality_flag})")

        cmd = [
            manim_executable,
            "render",
            str(code_path),
            scene_name,
            quality_flag,
            "--format=mp4",
            f"--media_dir={output_dir}",
        ]

        logger.info(f"{tag} Starting Manim render for scene: {scene_name}")
        logger.debug(f"{tag} Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=tmpdir,
                env=_tts_subprocess_env(),
                stdin=subprocess.DEVNULL,
            )
            if result.stdout:
                logger.debug(f"{tag} Manim stdout:\n{result.stdout}")
            if result.stderr:
                logger.debug(f"{tag} Manim stderr:\n{result.stderr}")
        except subprocess.TimeoutExpired:
            logger.error(f"{tag} Rendering timeout after 300 seconds for {scene_name}")
            raise RuntimeError(
                f"Manim render timed out after 300 seconds for scene {scene_name}"
            ) from None

        if result.returncode != 0:
            error_msg = _extract_render_error(result.stderr, result.stdout)
            logger.error(f"{tag} Manim render failed with return code {result.returncode}")
            logger.error(f"{tag} Error: {error_msg}")
            raise RuntimeError(f"Manim render failed: {error_msg}")

        logger.info(f"{tag} Manim render completed successfully")

        video_files = list(output_dir.rglob("*.mp4"))
        if not video_files:
            logger.error(f"{tag} No MP4 files found in {output_dir}")
            raise RuntimeError(
                f"No video file produced. Manim output:\n{result.stdout}\n{result.stderr}"
            )

        video_file = video_files[0]
        file_size = video_file.stat().st_size
        logger.info(f"{tag} Found video: {video_file.name} ({file_size:,} bytes)")
        video_bytes = video_file.read_bytes()
        logger.info(f"{tag} Successfully read video file ({len(video_bytes):,} bytes)")
        return video_bytes


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
    return _run_manim_subprocess(code, scene_name, quality)


async def render_manim_local(
    code: str,
    scene_name: str | None = None,
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
