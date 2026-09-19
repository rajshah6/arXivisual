"""
Rendering package for ArXiviz.

Supports both local (subprocess) and Modal.com (serverless) rendering.
Set RENDER_MODE environment variable to "local" or "modal".
"""

import contextlib
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
    is_repair: bool = False,
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
        is_repair: This render is the re-render after a layout repair; the
            re-judge then also scores whether the repair fixed the defect.

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
        verdict = await _judge_and_score(viz_id, video_bytes, is_repair=is_repair)
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


@contextlib.contextmanager
def _qa_observation(viz_id: str, is_repair: bool):
    """Run the judge inside a Langfuse span.

    Without an enclosing observation the judge's generation is an orphan root
    and ``score_current_trace`` has nothing to attach to — which is how 97%
    of production verdicts went unscored. Telemetry failure never blocks QA.
    """
    span = None
    try:
        from langfuse import get_client

        span = get_client().start_as_current_observation(
            as_type="span",
            name="visual-qa",
            metadata={"viz_id": viz_id, "is_repair": "1" if is_repair else "0"},
        )
        span.__enter__()
    except Exception as exc:
        logger.debug("[VisualQA] Langfuse span unavailable for %s: %s", viz_id, exc)
        span = None
    try:
        yield
    finally:
        if span is not None:
            try:
                span.__exit__(None, None, None)
            except Exception as exc:
                logger.debug("[VisualQA] Langfuse span close failed for %s: %s", viz_id, exc)


def _score_verdict(viz_id: str, verdict, is_repair: bool) -> None:
    """Score the QA trace: defect (bool), severity (categorical) and, on a
    post-repair re-judge, whether the repair fixed it — 'fixed' is the
    workflow's own definition (no longer ``major``)."""
    try:
        from langfuse import get_client

        client = get_client()
        comment = f"{viz_id}: {verdict.severity}; " + "; ".join(verdict.issues[:3])
        client.score_current_trace(
            name="visual_qa_defect",
            value=1.0 if verdict.has_defects else 0.0,
            data_type="BOOLEAN",
            comment=comment,
        )
        client.score_current_trace(
            name="visual_qa_severity",
            value=verdict.severity,
            data_type="CATEGORICAL",
            comment=viz_id,
        )
        if is_repair:
            client.score_current_trace(
                name="visual_qa_repair_fixed",
                value=1.0 if verdict.severity != "major" else 0.0,
                data_type="BOOLEAN",
                comment=comment,
            )
    except Exception as exc:
        # Distinguish broken telemetry from intentional unconfiguration.
        logger.warning("[VisualQA] Langfuse scoring failed for %s: %s", viz_id, exc)


async def _judge_and_score(viz_id: str, video_bytes: bytes, is_repair: bool = False):
    """Run the vision layout judge; log + Langfuse-score; return the verdict.

    Never raises — a QA failure returns None so callers can proceed.
    """
    try:
        from agents.visual_qa import judge_video

        with _qa_observation(viz_id, is_repair):
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
            _score_verdict(viz_id, verdict, is_repair)
        return verdict
    except Exception as exc:
        logger.warning("[VisualQA] QA failed for %s: %s", viz_id, exc)
        return None


async def _observe_visual_qa(viz_id: str, video_bytes: bytes) -> None:
    """Background observe-mode wrapper around the judge."""
    await _judge_and_score(viz_id, video_bytes)
