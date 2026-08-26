"""
Rendering package for ArXiviz.

Supports both local (subprocess) and Modal.com (serverless) rendering.
Set RENDER_MODE environment variable to "local" or "modal".
"""

import logging
import os

from .local_runner import extract_scene_name, render_manim_local
from .storage import get_backend, get_video_path, get_video_url, list_videos, save_video

logger = logging.getLogger(__name__)

# Render mode: "local" or "modal"
RENDER_MODE = os.getenv("RENDER_MODE", "local")

__all__ = [
    "RENDER_MODE",
    "extract_scene_name",
    "get_backend",
    "get_video_path",
    "get_video_url",
    "list_videos",
    "process_visualization",
    "render_manim",
    "render_manim_local",
    "save_video",
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


async def process_visualization(
    viz_id: str,
    manim_code: str,
    quality: str = "low_quality",
    collect_qa: bool = False,
):
    """
    Process a visualization: render Manim code and save the video.

    Args:
        viz_id: Unique identifier for this visualization
        manim_code: Complete Manim Python code
        quality: Rendering quality ("low_quality", "medium_quality", "high_quality")
        collect_qa: When True, run the visual QA judge INLINE and return
            ``(video_url, verdict)`` so the caller (the Temporal render
            activity) can drive a repair pass. When False (legacy path),
            returns just the URL and QA runs as background observe-mode.

    Returns:
        URL path to the rendered video, or ``(url, VisualQAResult | None)``
        when ``collect_qa`` is True.

    Raises:
        RuntimeError: If rendering fails
    """
    logger.info(f"[Processing Visualization] {viz_id}")
    logger.info(f"[Processing Visualization] Quality setting: {quality}")

    # Extract scene name from code
    scene_name = extract_scene_name(manim_code)
    logger.info(f"[Processing Visualization] Scene name: {scene_name}")

    # Render the video using configured backend
    logger.info("[Processing Visualization] Starting rendering phase...")
    video_bytes = await render_manim(manim_code, scene_name, quality)
    logger.info(f"[Processing Visualization] Rendering complete ({len(video_bytes):,} bytes)")

    # Save to storage FIRST — visual QA must never delay video delivery.
    logger.info("[Processing Visualization] Saving to storage...")
    video_url = await save_video(video_bytes, f"{viz_id}.mp4")
    logger.info("[Processing Visualization] Video saved successfully")
    logger.info(f"[Processing Visualization] Video URL: {video_url}")

    if collect_qa:
        # Inline judging for the repair loop: the activity needs the verdict.
        verdict = await _judge_and_score(viz_id, video_bytes)
        return video_url, verdict

    # Visual QA (observe mode): judge sampled frames for overlap/cutoff defects.
    # Dispatched as supervised background work — logs + Langfuse score only,
    # never blocks the render path or fails the visualization.
    _dispatch_visual_qa(viz_id, video_bytes)

    return video_url


# Keep strong references so background QA tasks aren't garbage-collected early.
_visual_qa_tasks: set = set()


def _dispatch_visual_qa(viz_id: str, video_bytes: bytes) -> None:
    """Fire-and-supervise the observe-mode visual QA task."""
    if os.getenv("ENABLE_VISUAL_QA", "0") != "1":
        return
    import asyncio

    task = asyncio.get_running_loop().create_task(_observe_visual_qa(viz_id, video_bytes))
    _visual_qa_tasks.add(task)

    def _done(t: "asyncio.Task") -> None:
        _visual_qa_tasks.discard(t)
        exc = t.exception() if not t.cancelled() else None
        if exc is not None:
            logger.warning("[VisualQA] Background QA task failed for %s: %s", viz_id, exc)

    task.add_done_callback(_done)


async def _judge_and_score(viz_id: str, video_bytes: bytes):
    """Run the vision layout judge; log + Langfuse-score; return the verdict.

    Never raises — a QA failure returns None so callers can proceed.
    """
    try:
        from agents.visual_qa import judge_video

        verdict = await judge_video(video_bytes, viz_id=viz_id)
        if verdict is None:
            return None
        if verdict.has_defects:
            logger.warning(
                "[VisualQA] %s severity=%s overlap=%s cutoff=%s collisions=%s issues=%s",
                viz_id, verdict.severity, verdict.overlap, verdict.cutoff,
                verdict.collisions, "; ".join(verdict.issues[:5]),
            )
        else:
            logger.info("[VisualQA] %s clean (%s frames)", viz_id, verdict.frames_checked)
        # Score the current Langfuse trace so defect rates become dashboardable.
        try:
            from langfuse import get_client

            get_client().score_current_trace(
                name="visual_qa_defect",
                value=1.0 if verdict.has_defects else 0.0,
                comment=f"{viz_id}: {verdict.severity}; " + "; ".join(verdict.issues[:3]),
            )
        except Exception as exc:
            # Distinguish broken telemetry from intentional unconfiguration.
            logger.warning("[VisualQA] Langfuse scoring failed for %s: %s", viz_id, exc)
        return verdict
    except Exception as exc:
        logger.warning("[VisualQA] QA failed for %s: %s", viz_id, exc)
        return None


async def _observe_visual_qa(viz_id: str, video_bytes: bytes) -> None:
    """Background observe-mode wrapper around the judge."""
    await _judge_and_score(viz_id, video_bytes)
