"""
Rendering package for ArXiviz.

Supports both local (subprocess) and Modal.com (serverless) rendering.
Set RENDER_MODE environment variable to "local" or "modal".
"""

import logging
import os
from .local_runner import render_manim_local, extract_scene_name
from .storage import save_video, get_video_path, get_video_url, list_videos, get_backend

logger = logging.getLogger(__name__)

# Render mode: "local" or "modal"
RENDER_MODE = os.getenv("RENDER_MODE", "local")

__all__ = [
    "render_manim_local",
    "extract_scene_name",
    "save_video",
    "get_video_path",
    "get_video_url",
    "list_videos",
    "process_visualization",
    "render_manim",
    "get_backend",
    "RENDER_MODE",
]


async def render_manim(code: str, scene_name: str, quality: str = "low_quality") -> bytes:
    """
    Render Manim code using configured backend (local or Modal).

    Args:
        code: Complete Manim Python code
        scene_name: Name of the Scene class to render
        quality: Rendering quality ("low_quality", "medium_quality", "high_quality")

    Returns:
        MP4 video file as bytes
    """
    if RENDER_MODE == "modal":
        import asyncio
        import modal
        # Look up the deployed function by app + function name.
        # This works from any external Python process (Render, scripts, etc.)
        # unlike direct import which only works inside `modal run`.
        render_fn = modal.Function.from_name("arxiviz-manim", "render_manim_modal")
        return await asyncio.to_thread(
            render_fn.remote, code, scene_name, quality
        )
    else:
        return await render_manim_local(code, scene_name, quality)


async def process_visualization(viz_id: str, manim_code: str, quality: str = "low_quality") -> str:
    """
    Process a visualization: render Manim code and save the video.

    Args:
        viz_id: Unique identifier for this visualization
        manim_code: Complete Manim Python code
        quality: Rendering quality ("low_quality", "medium_quality", "high_quality")

    Returns:
        URL path to the rendered video (e.g., "/api/video/viz_001")

    Raises:
        RuntimeError: If rendering fails
    """
    logger.info(f"[Processing Visualization] {viz_id}")
    logger.info(f"[Processing Visualization] Quality setting: {quality}")

    # Extract scene name from code
    scene_name = extract_scene_name(manim_code)
    logger.info(f"[Processing Visualization] Scene name: {scene_name}")

    # Render the video using configured backend
    logger.info(f"[Processing Visualization] Starting rendering phase...")
    video_bytes = await render_manim(manim_code, scene_name, quality)
    logger.info(f"[Processing Visualization] Rendering complete ({len(video_bytes):,} bytes)")

    # Visual QA (observe mode): judge sampled frames for overlap/cutoff defects.
    # Logs + Langfuse score only — never blocks the pipeline or fails the render.
    await _observe_visual_qa(viz_id, video_bytes)

    # Save to storage
    logger.info(f"[Processing Visualization] Saving to storage...")
    video_url = await save_video(video_bytes, f"{viz_id}.mp4")
    logger.info(f"[Processing Visualization] Video saved successfully")
    logger.info(f"[Processing Visualization] Video URL: {video_url}")

    return video_url


async def _observe_visual_qa(viz_id: str, video_bytes: bytes) -> None:
    """Run the vision layout judge when ENABLE_VISUAL_QA=1; log-only."""
    if os.getenv("ENABLE_VISUAL_QA", "0") != "1":
        return
    try:
        from agents.visual_qa import judge_video

        verdict = await judge_video(video_bytes, viz_id=viz_id)
        if verdict is None:
            return
        if verdict.has_defects:
            logger.warning(
                "[VisualQA] %s severity=%s overlap=%s cutoff=%s collisions=%s issues=%s",
                viz_id, verdict.severity, verdict.overlap, verdict.cutoff,
                verdict.collisions, "; ".join(verdict.issues[:5]),
            )
        else:
            logger.info("[VisualQA] %s clean (%s frames)", viz_id, verdict.frames_checked)
        # Score the current Langfuse span so defect rates become dashboardable.
        try:
            from langfuse import get_client

            get_client().score_current_trace(
                name="visual_qa_defect",
                value=1.0 if verdict.has_defects else 0.0,
                comment=f"{viz_id}: {verdict.severity}; " + "; ".join(verdict.issues[:3]),
            )
        except Exception:
            pass  # Langfuse unavailable/unconfigured — logging above suffices
    except Exception as exc:
        logger.warning("[VisualQA] Observe-mode QA failed for %s: %s", viz_id, exc)
