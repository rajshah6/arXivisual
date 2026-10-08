"""Smoke-test one Azure OpenAI deployment with every call shape production sends.

Before pointing production at another model (gpt-5-mini -> gpt-6-luna), send
each request shape the pipeline really uses to that deployment, check the
answers are usable, and get a first read on token volume: reasoning tokens
dominate output cost, and the luna saving disappears above ~4.3x gpt-5-mini's
output tokens (cost review, 2026-10-08). The kwargs come from the production
builders (agents.base._azure_request_kwargs, agents.visual_qa.judge_request /
repair_request) and the production client factories, so they cannot drift:

  pipeline_text     async client; system + user message, max_completion_tokens,
                    reasoning_effort (call_llm: generator, section formatter,
                    text-only repair)
  pipeline_json     + response_format json_object (call_llm_json: planner,
                    section organizer); the reply must parse as JSON
  pipeline_sync     the sync client, same kwargs (call_llm_sync: section
                    analyzer, voiceover validator)
  visual_qa_judge   one user message: judge prompt + VISUAL_QA_FRAMES (3) PNG
                    data-URI image_urls, 4,096-token cap; the verdict must parse
  visual_qa_repair  repair prompt + code + the same frames, 16,000-token cap;
                    must return code

A reply cut off at max_completion_tokens (finish_reason "length") is a FAIL:
an empty judge reply passes a defective video (visual_qa fails open).

The token columns are a rough model-to-model RATIO, not production volume. The
pipeline prompts are a few sentences, and real output and reasoning volume
depends on the paper (run-to-run variance at one setting was ~10%). The
visual-QA frames are production-sized (854x480, the -ql render size, as many
as VISUAL_QA_FRAMES) because image tokenization differs per model, but they are
synthetic. The cost gate for a model swap is the Langfuse canary on real
papers; this tool proves the call shapes work.

Usage, from backend/ (reads AZURE_OPENAI_* from the env or backend/.env, like
agents/base.py):

    uv run python -m tools.model_smoke --deployment gpt-5-mini --effort medium
    uv run python -m tools.model_smoke --deployment gpt-6-luna --effort medium

--effort (low | medium | high, the values both models accept) applies to every
shape; without it each shape uses its production setting
(AZURE_OPENAI_REASONING_EFFORT, VISUAL_QA_REASONING_EFFORT). Langfuse tracing is
off for these calls. Exit status: 0 all shapes ok, 1 any FAIL, 2 Azure OpenAI
not configured. A run costs well under one cent on gpt-5-mini.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import base, visual_qa

# The frame size of a low_quality (-ql) render, which is what production
# renders (temporal_app/activities.py) and visual_qa.sample_frames extracts.
FRAME_SIZE = (854, 480)

# 1x1 PNG, used only when Pillow is missing (it ships with manim).
_FALLBACK_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhg"
    "GAWjR9awAAAABJRU5ErkJggg=="
)

_REPAIR_CODE = '''from manim import *


class SmokeScene(Scene):
    def construct(self):
        box = Rectangle(width=4, height=2)
        title = Text("A title that is far too long for its box").move_to(box)
        self.play(Create(box), Write(title))
'''


@dataclass
class Result:
    shape: str
    ok: bool = False
    effort: str = "-"
    latency_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    served_model: str = "-"
    error: str = ""


def sample_frames(count: int = visual_qa.VISUAL_QA_FRAMES) -> list[bytes]:
    """``count`` in-memory PNGs the size of a production frame, each with a
    real layout defect (a title spilling out of its box), so the judge has
    something to find and the request carries production's image tokens."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:  # pragma: no cover - Pillow comes with manim
        return [base64.b64decode(_FALLBACK_PNG)] * count
    try:
        font = ImageFont.load_default(size=40)
    except (TypeError, OSError):  # pragma: no cover - Pillow < 10.1 / no FreeType
        font = ImageFont.load_default()
    frames = []
    for i in range(count):
        img = Image.new("RGB", FRAME_SIZE, "black")
        draw = ImageDraw.Draw(img)
        draw.rectangle((277, 190, 577, 290), outline="white", width=3)
        draw.text((150 + 20 * i, 215), "A title far too long for its box", fill="yellow", font=font)
        draw.line((427, 290, 427, 420), fill="white", width=3)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        frames.append(buf.getvalue())
    return frames


def describe_error(exc: BaseException) -> str:
    """One line, no secrets: HTTP status + Azure error code + message."""
    import openai

    if isinstance(exc, openai.APIStatusError):
        message = exc.body.get("message") if isinstance(exc.body, dict) else None
        code = f" {exc.code}" if exc.code else ""
        text = f"HTTP {exc.status_code}{code}: {message or exc.message}"
    elif isinstance(exc, openai.APIConnectionError):
        text = f"connection error: {exc.message}"
    else:
        text = f"{type(exc).__name__}: {exc}"
    return " ".join(text.split())


def _check_text(content: str) -> str:
    return "" if content.strip() else "empty reply"


def _check_json(content: str) -> str:
    try:
        parsed = base.parse_json_response(content)
    except ValueError:
        return "reply is not parseable JSON"
    return "" if isinstance(parsed, dict) else "reply is JSON but not an object"


def _check_verdict(content: str) -> str:
    if not content.strip():
        return "empty judge reply (production would pass the video unjudged)"
    verdict = visual_qa._parse_verdict(content)
    return "judge verdict unparseable" if "judge output unparseable" in verdict.issues else ""


# A class declaration at the start of a line (fenced or not), not prose that
# happens to contain "class " ("I cannot repair this class without ...").
_CLASS_DECL = re.compile(r"^\s*class\s+\w+\s*(\([^)]*\))?\s*:", re.MULTILINE)


def _check_code(content: str) -> str:
    if not content.strip():
        return "empty repair reply"
    return "" if _CLASS_DECL.search(content) else "repair reply contains no class definition"


Request = tuple[str, dict, bool, Callable[[str], str]]


def build_requests(deployment: str, effort: str | None) -> list[Request]:
    """(shape, kwargs, use_sync_client, check) for every production call shape."""
    model = base._azure_model(deployment)
    frames = sample_frames()
    text = base._azure_request_kwargs(
        model,
        "In two sentences, explain what a Fourier transform does.",
        "You are a concise technical writer.",
        256,
    )
    as_json = base._azure_request_kwargs(
        model,
        'From "attention weighs each token by its relevance to the others", list two '
        'concepts worth animating. Return {"concepts": ["...", "..."]}.',
        "You plan educational animations. Reply with a JSON object only.",
        256,
        json_mode=True,
    )
    sync = base._azure_request_kwargs(
        model,
        "Name the one equation most worth animating in a paper about gradient descent.",
        "You are a concise technical writer.",
        256,
    )
    if effort:
        # Override the key base set from AZURE_OPENAI_REASONING_EFFORT, rather
        # than setting that env var: a run must leave the process as it was.
        for kwargs in (text, as_json, sync):
            kwargs["reasoning_effort"] = effort
    judge = visual_qa.judge_request(frames, model=model, effort=effort)
    repair = visual_qa.repair_request(
        _REPAIR_CODE, ["Title text overflows the rectangle"], frames, model=model, effort=effort,
    )
    return [
        ("pipeline_text", text, False, _check_text),
        ("pipeline_json", as_json, False, _check_json),
        ("pipeline_sync", sync, True, _check_text),
        ("visual_qa_judge", judge, False, _check_verdict),
        ("visual_qa_repair", repair, False, _check_code),
    ]


async def run(
    deployment: str, effort: str | None, *, async_client=None, sync_client=None,
) -> list[Result]:
    async_client = async_client or base._get_azure_client()
    sync_client = sync_client or base._get_azure_sync_client()
    results = []
    for shape, kwargs, use_sync, check in build_requests(deployment, effort):
        result = Result(shape=shape, effort=kwargs.get("reasoning_effort", "-"))
        t0 = time.monotonic()
        try:
            if use_sync:
                resp = await asyncio.to_thread(sync_client.chat.completions.create, **kwargs)
            else:
                resp = await async_client.chat.completions.create(**kwargs)
        except Exception as exc:
            result.latency_s = time.monotonic() - t0
            result.error = describe_error(exc)
            results.append(result)
            continue
        result.latency_s = time.monotonic() - t0
        result.served_model = getattr(resp, "model", None) or "-"
        usage = getattr(resp, "usage", None)
        if usage is not None:
            result.prompt_tokens = usage.prompt_tokens
            result.completion_tokens = usage.completion_tokens
            details = getattr(usage, "completion_tokens_details", None)
            result.reasoning_tokens = getattr(details, "reasoning_tokens", None)
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            result.error = (
                f"truncated at max_completion_tokens={kwargs['max_completion_tokens']} "
                "(finish_reason=length)"
            )
        elif choice.finish_reason != "stop":
            # content_filter (and anything else) means Azure omitted output,
            # even when some partial text came back: never count it as usable.
            result.error = f"finish_reason={choice.finish_reason} (output omitted or incomplete)"
        else:
            result.error = check(choice.message.content or "")
        result.ok = not result.error
        results.append(result)
    return results


def format_table(results: list[Result]) -> str:
    def num(value) -> str:
        return "-" if value is None else str(value)

    header = (
        "shape", "result", "effort", "latency", "prompt", "completion", "reasoning",
        "served model", "error",
    )
    rows = [
        (
            r.shape,
            "ok" if r.ok else "FAIL",
            r.effort,
            "-" if r.latency_s is None else f"{r.latency_s:.1f}s",
            num(r.prompt_tokens),
            num(r.completion_tokens),
            num(r.reasoning_tokens),
            r.served_model,
            r.error[:110],
        )
        for r in results
    ]
    widths = [max(len(str(c)) for c in col) for col in zip(header, *rows, strict=True)]
    lines = [" | ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=True)).rstrip()
             for row in (header, *rows)]
    lines.insert(1, "-+-".join("-" * w for w in widths))
    totals = [sum(getattr(r, f) or 0 for r in results)
              for f in ("prompt_tokens", "completion_tokens", "reasoning_tokens")]
    lines.append(f"totals: prompt {totals[0]}, completion {totals[1]} (reasoning {totals[2]})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send every production LLM call shape to one Azure OpenAI deployment.",
    )
    parser.add_argument(
        "--deployment", required=True, help="Azure deployment name, e.g. gpt-6-luna",
    )
    parser.add_argument(
        "--effort", choices=base.PORTABLE_REASONING_EFFORTS,
        help="reasoning_effort for every shape (default: each shape's production setting)",
    )
    args = parser.parse_args(argv)

    # Before the first call creates the (Langfuse-wrapped) OpenAI client: a
    # smoke run must not land in the production traces or cost dashboards.
    # Here, not at import, so importing this module changes nothing.
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

    try:
        base._require_azure_env()
    except RuntimeError as exc:
        print(f"Azure OpenAI is not configured: {exc}", file=sys.stderr)
        return 2

    # The Langfuse client wrapper re-logs every API error as a warning; the
    # table already reports it, once and without the raw response body.
    logging.getLogger("langfuse").setLevel(logging.ERROR)
    print(f"deployment {args.deployment}, effort {args.effort or 'production settings'}\n")
    results = asyncio.run(run(args.deployment, args.effort))
    print(format_table(results))
    failed = [r.shape for r in results if not r.ok]
    summary = f"\n{len(results) - len(failed)}/{len(results)} shapes ok"
    print(summary + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
