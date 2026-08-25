"""Visual QA judge — catches layout defects the static validators can't see.

The spatial validator regex-parses explicit ``move_to``/``shift`` coordinates,
but generated scenes mostly use relative layout (``next_to``/``arrange`` — which
the prompt itself encourages), so real overlaps are invisible to it. This module
judges the *rendered pixels* instead: sample a few frames from the finished
video and ask a vision model whether elements overlap, collide, or fall off
frame.

Ships in OBSERVE mode: enable with ``ENABLE_VISUAL_QA=1`` and results are
logged (and scored to Langfuse when configured) without changing pipeline
behavior. Once thresholds are trusted, the verdict can gate a targeted repair.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

# Handle imports for both package and direct execution
try:
    from .base import _get_azure_client, _azure_model, get_provider
except ImportError:  # pragma: no cover - direct execution path
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.base import _get_azure_client, _azure_model, get_provider

logger = logging.getLogger(__name__)

# Observe-mode switch and judge model (gpt-5-mini and gpt-5.6-sol both verified
# to catch real overlap/cutoff/collision defects on production frames).
VISUAL_QA_ENABLED = os.getenv("ENABLE_VISUAL_QA", "0") == "1"
VISUAL_QA_MODEL = os.getenv("VISUAL_QA_MODEL", "gpt-5-mini")
VISUAL_QA_FRAMES = max(1, int(os.getenv("VISUAL_QA_FRAMES", "3")))

JUDGE_PROMPT = """You are a visual QA judge for auto-generated Manim educational videos.
Inspect these frames (sampled from one video) for LAYOUT DEFECTS only, not content quality:
1. overlapping elements (text/shapes drawn on top of each other illegibly)
2. elements cut off by the frame edges
3. text colliding with arrows/shapes

Return ONLY JSON:
{"overlap": bool, "cutoff": bool, "collisions": bool, "severity": "none"|"minor"|"major", "issues": ["short specific descriptions"]}"""


class VisualQAResult(BaseModel):
    """Structured verdict from the vision judge."""

    overlap: bool = False
    cutoff: bool = False
    collisions: bool = False
    severity: str = Field("none", description='none | minor | major')
    issues: list[str] = Field(default_factory=list)
    judge_model: str = ""
    frames_checked: int = 0

    @property
    def has_defects(self) -> bool:
        return self.severity in ("minor", "major")


def sample_frames(video_bytes: bytes, count: int = VISUAL_QA_FRAMES) -> list[bytes]:
    """Extract ``count`` evenly spaced PNG frames from an MP4 via ffmpeg.

    Runs in a temp dir; returns raw PNG bytes. Raises RuntimeError on ffmpeg
    failure so callers can decide whether QA failure should be fatal (in
    observe mode it never is).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / "video.mp4"
        video_path.write_bytes(video_bytes)

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {probe.stderr.strip()[:200]}")
        duration = float(probe.stdout.strip())

        frames: list[bytes] = []
        for i in range(1, count + 1):
            # Sample the middle of the video's i-th segment; skip t=0 (usually
            # an empty first frame) and the very end.
            ts = duration * i / (count + 1)
            out_path = Path(tmpdir) / f"frame_{i}.png"
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ts:.3f}",
                 "-i", str(video_path), "-frames:v", "1", str(out_path)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0 or not out_path.exists():
                raise RuntimeError(f"ffmpeg frame extract failed: {result.stderr.strip()[:200]}")
            frames.append(out_path.read_bytes())
        return frames


def _parse_verdict(text: str) -> VisualQAResult:
    """Parse the judge's JSON, tolerating markdown fences and prose padding."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if brace:
            cleaned = brace.group(0)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        logger.warning("[VisualQA] Unparseable judge output: %r", text[:200])
        return VisualQAResult(severity="none", issues=["judge output unparseable"])
    if data.get("severity") not in ("none", "minor", "major"):
        data["severity"] = "minor" if any(
            data.get(k) for k in ("overlap", "cutoff", "collisions")
        ) else "none"
    return VisualQAResult(
        overlap=bool(data.get("overlap", False)),
        cutoff=bool(data.get("cutoff", False)),
        collisions=bool(data.get("collisions", False)),
        severity=data["severity"],
        issues=[str(i) for i in data.get("issues", [])][:10],
    )


async def judge_video(video_bytes: bytes, viz_id: str = "") -> Optional[VisualQAResult]:
    """Judge a rendered video's frames for layout defects.

    Returns None when QA can't run (non-Azure provider, ffmpeg failure, API
    error) — observe mode never breaks the pipeline.
    """
    if get_provider() != "azure":
        logger.info("[VisualQA] Skipped (non-Azure provider has no vision path)")
        return None
    try:
        frames = sample_frames(video_bytes)
    except Exception as exc:
        logger.warning("[VisualQA] Frame sampling failed for %s: %s", viz_id, exc)
        return None

    content: list[dict] = [{"type": "text", "text": JUDGE_PROMPT}]
    for frame in frames:
        b64 = base64.b64encode(frame).decode()
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        )

    try:
        client = _get_azure_client()
        resp = await client.chat.completions.create(
            model=_azure_model(VISUAL_QA_MODEL),
            messages=[{"role": "user", "content": content}],
            max_completion_tokens=4096,
        )
        verdict = _parse_verdict(resp.choices[0].message.content or "")
        verdict.judge_model = VISUAL_QA_MODEL
        verdict.frames_checked = len(frames)
        return verdict
    except Exception as exc:
        logger.warning("[VisualQA] Judge call failed for %s: %s", viz_id, exc)
        return None
