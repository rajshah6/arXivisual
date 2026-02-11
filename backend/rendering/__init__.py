"""
Rendering package for ArXiviz.

Supports both local (subprocess) and Modal.com (serverless) rendering.
Set RENDER_MODE environment variable to "local" or "modal".
"""

import os
from .local_runner import render_manim_local, extract_scene_name
from .storage import save_video, get_video_path, get_video_url, list_videos, get_backend

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
        from .modal_runner import render_manim_modal
        # Modal functions are sync, run in thread pool
        import asyncio
        return await asyncio.to_thread(
            render_manim_modal.remote, code, scene_name, quality
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
    # Extract scene name from code
    scene_name = extract_scene_name(manim_code)

    # Render the video using configured backend
    video_bytes = await render_manim(manim_code, scene_name, quality)

    # Save to storage
    video_url = await save_video(video_bytes, f"{viz_id}.mp4")

    return video_url
