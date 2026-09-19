#!/usr/bin/env python3
"""Golden-set eval runner for the arXivisual generation pipeline.

For each golden-set paper this runner does a REAL arXiv fetch + ingestion and
runs the REAL multi-agent LLM pipeline (agents.pipeline.generate_visualizations)
with the GateMetrics hook attached — but with local render testing disabled
(RENDER_MODE=modal), so the run measures the LLM quality gates (CodeValidator,
SpatialValidator, VoiceoverScriptValidator), not ffmpeg/cairo.

Requires the LLM provider env (AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT /
AZURE_OPENAI_DEPLOYMENT): this makes real, billable LLM calls. Cost control:
--papers limits golden-set coverage, --max-viz caps visualizations per paper.

Usage (from backend/):
    uv run python evals/run_evals.py --papers 3 --max-viz 2 --output report.json
    uv run python evals/check_regression.py report.json evals/baselines.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evals.metrics import GateMetrics, UsageMetrics, aggregate_summaries  # noqa: E402

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.json"


def _load_pipeline():
    """Import the pipeline with local render testing disabled.

    ENABLE_RENDER_TESTING is derived from RENDER_MODE at agents.pipeline import
    time, so the env var must be set BEFORE the import. Deferred into a helper
    (rather than module top-level) so `--help` and the unit tests can import
    this module without env side effects or the ML dependency stack.
    """
    os.environ["RENDER_MODE"] = "modal"
    from agents import pipeline
    from ingestion import ingest_paper

    if pipeline.ENABLE_RENDER_TESTING:
        raise RuntimeError(
            "agents.pipeline was imported before run_evals could set "
            "RENDER_MODE=modal; render testing would skew the eval."
        )
    return pipeline, ingest_paper


def load_golden_set(limit: int | None = None) -> list[dict]:
    entries = json.loads(GOLDEN_SET_PATH.read_text())["papers"]
    if limit is not None:
        entries = entries[: max(limit, 0)]
    return entries


def experiment_config(reasoning_effort: str | None, tag: str | None) -> dict:
    """Apply the experiment arm to this process and return it for the report.

    ``reasoning_effort`` overrides AZURE_OPENAI_REASONING_EFFORT for the run
    (agents/base.py reads it per call); None records the effective value.
    """
    from agents import base  # importing base loads backend/.env, like the pipeline does

    if reasoning_effort:
        os.environ["AZURE_OPENAI_REASONING_EFFORT"] = reasoning_effort
    return {
        "reasoning_effort": os.environ.get("AZURE_OPENAI_REASONING_EFFORT", "low"),
        "tag": tag,
        "deployment": base._azure_deployment(),
    }


def _trace_context(tag: str | None, arxiv_id: str):
    """Langfuse attribution for eval traces (session = tag, so an A/B arm is
    one filter in the UI). A no-op when the tag is unset or Langfuse is absent.
    """
    if not tag:
        return contextlib.nullcontext()
    try:
        from langfuse import propagate_attributes
    except ImportError:
        return contextlib.nullcontext()
    return propagate_attributes(
        session_id=tag,
        trace_name="eval-paper",
        tags=["eval", tag],
        metadata={"arxiv_id": arxiv_id, "eval_tag": tag},
    )


async def eval_paper(
    entry: dict, max_viz: int, pipeline, ingest_paper, tag: str | None = None
) -> dict:
    """Ingest one paper and run generation with the metrics hook attached."""
    result: dict = {
        "arxiv_id": entry["arxiv_id"],
        "title": entry.get("title", ""),
        "why": entry.get("why", ""),
        "tag": tag,
        "error": None,
    }
    from agents import base

    metrics = GateMetrics()
    usage = UsageMetrics()
    pipeline.metrics_hook = metrics.hook
    previous_usage_hook = base.usage_hook
    base.usage_hook = usage.hook
    started = time.monotonic()
    vizzes: list = []
    try:
        paper = await ingest_paper(entry["arxiv_id"], force_refresh=True)
        with _trace_context(tag, entry["arxiv_id"]):
            vizzes = await pipeline.generate_visualizations(
                paper, max_visualizations=max_viz
            )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        pipeline.metrics_hook = None
        base.usage_hook = previous_usage_hook

    result["wall_clock_seconds"] = round(time.monotonic() - started, 1)
    result["visualizations_returned"] = len(vizzes)
    result.update(metrics.summary())
    result["usage"] = usage.summary()
    return result


async def run_all(entries: list[dict], max_viz: int, tag: str | None = None) -> list[dict]:
    """Evaluate papers sequentially inside ONE event loop.

    Sequential keeps LLM concurrency bounded (each paper already fans out its
    own visualization tasks); one loop keeps base.py's cached AsyncOpenAI
    client bound to a live loop across papers.
    """
    pipeline, ingest_paper = _load_pipeline()
    results = []
    for i, entry in enumerate(entries, 1):
        print(f"\n[{i}/{len(entries)}] {entry['arxiv_id']} — {entry.get('title', '')}")
        result = await eval_paper(entry, max_viz, pipeline, ingest_paper, tag=tag)
        status = result["error"] or (
            f"{result['visualizations_validated']}/{result['candidates_run']} validated "
            f"in {result['wall_clock_seconds']}s, ${result['usage']['cost_usd']:.4f}"
        )
        print(f"    -> {status}")
        results.append(result)
    return results


def build_report(
    paper_results: list[dict], max_viz: int, extra_config: dict | None = None
) -> dict:
    ok = [p for p in paper_results if p.get("error") is None]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {
            "max_visualizations": max_viz,
            "render_testing_enabled": False,
            "papers_requested": len(paper_results),
            **(extra_config or {}),
        },
        "papers": paper_results,
        "aggregate": aggregate_summaries(ok),
    }


def print_summary(report: dict) -> None:
    print("\n" + "=" * 72)
    print("Per-paper results")
    print("-" * 72)
    print(f"{'paper':<14}{'cand':>6}{'valid':>7}{'returned':>10}{'wall(s)':>10}  error")
    for p in report["papers"]:
        print(
            f"{p['arxiv_id']:<14}{p['candidates_run']:>6}"
            f"{p['visualizations_validated']:>7}{p['visualizations_returned']:>10}"
            f"{p['wall_clock_seconds']:>10}  {p['error'] or '-'}"
        )

    agg = report["aggregate"]
    print("-" * 72)
    print(
        f"Aggregate: {agg['papers_evaluated']} papers, "
        f"{agg['visualizations_validated']}/{agg['candidates_run']} visualizations "
        f"validated (viz_yield_rate={agg['viz_yield_rate']})"
    )
    print(f"\n{'gate':<28}{'first-attempt':>14}{'eventual':>10}{'avg attempts':>14}")
    for gate, row in agg["gates"].items():
        print(
            f"{gate:<28}{row['first_attempt_rate']!s:>14}"
            f"{row['eventual_rate']!s:>10}{row['avg_attempts']!s:>14}"
        )
    print(
        f"\nCost: cost_usd={agg['cost_usd']} cost_per_paper_usd={agg['cost_per_paper_usd']} "
        f"cost_per_validated_viz_usd={agg['cost_per_validated_viz_usd']} "
        f"llm_calls={agg['llm_calls']} unpriced_calls={agg['unpriced_calls']}"
    )
    if agg["tokens"]:
        t = agg["tokens"]
        print(
            f"Tokens: input={t['input']} cached_input={t['cached_input']} "
            f"output={t['output']} reasoning={t['reasoning']}"
        )
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run generation-quality evals over the golden paper set."
    )
    parser.add_argument(
        "--papers",
        type=int,
        default=None,
        metavar="N",
        help="evaluate only the first N golden-set papers (default: all)",
    )
    parser.add_argument(
        "--max-viz",
        type=int,
        default=2,
        metavar="M",
        help="cap visualizations generated per paper (cost control, default: 2)",
    )
    parser.add_argument(
        "--output",
        default="report.json",
        help="path for the JSON report (default: report.json)",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high"),
        default=None,
        help="override AZURE_OPENAI_REASONING_EFFORT for this run (experiment arm)",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="experiment label; becomes the Langfuse session id and is written to the report",
    )
    args = parser.parse_args(argv)

    entries = load_golden_set(args.papers)
    if not entries:
        print("No golden-set papers selected.", file=sys.stderr)
        return 1

    config = experiment_config(args.reasoning_effort, args.tag)
    print(
        f"Evaluating {len(entries)} golden-set paper(s), "
        f"max {args.max_viz} visualization(s) each (render testing disabled); "
        f"reasoning_effort={config['reasoning_effort']} tag={config['tag']}"
    )
    results = asyncio.run(run_all(entries, args.max_viz, tag=args.tag))

    report = build_report(results, args.max_viz, extra_config=config)
    output = Path(args.output)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print_summary(report)
    print(f"\nReport written to {output}")

    if all(p["error"] for p in results):
        print("ERROR: every paper failed to evaluate.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
