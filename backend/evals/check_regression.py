#!/usr/bin/env python3
"""Gate CI on generation-quality regressions.

Reads an eval report (run_evals.py output) and a baselines file, compares every
baseline threshold against the report's aggregate metrics, prints a verdict
table, and exits 1 if any metric regresses below its floor (or above its cap).

A metric that is missing from the report (e.g. a gate that never ran) counts as
a failure: silently losing a gate IS a regression.

Usage (from backend/):
    uv run python evals/check_regression.py report.json evals/baselines.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


def resolve_metric(aggregate: dict, dotted_path: str) -> Optional[Any]:
    """Look up a dotted path (e.g. 'gates.code_validator.eventual_rate')."""
    node: Any = aggregate
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def evaluate_thresholds(aggregate: dict, thresholds: dict) -> list[dict]:
    """Return one row per threshold: {metric, constraint, actual, ok, detail}."""
    rows = []
    for metric, spec in thresholds.items():
        actual = resolve_metric(aggregate, metric)
        minimum = spec.get("min") if isinstance(spec, dict) else spec
        maximum = spec.get("max") if isinstance(spec, dict) else None

        if actual is None:
            ok = False
            detail = "metric missing from report"
        elif not isinstance(actual, (int, float)):
            ok = False
            detail = f"metric is not numeric: {actual!r}"
        else:
            ok = True
            detail = ""
            if minimum is not None and actual < minimum:
                ok = False
                detail = f"below minimum {minimum}"
            if maximum is not None and actual > maximum:
                ok = False
                detail = f"above maximum {maximum}"

        constraint = []
        if minimum is not None:
            constraint.append(f">= {minimum}")
        if maximum is not None:
            constraint.append(f"<= {maximum}")

        rows.append(
            {
                "metric": metric,
                "constraint": " and ".join(constraint) or "-",
                "actual": actual,
                "ok": ok,
                "detail": detail,
            }
        )
    return rows


def print_table(rows: list[dict]) -> None:
    width = max([len(r["metric"]) for r in rows] + [len("metric")]) + 2
    print(f"{'metric':<{width}}{'required':>12}{'actual':>10}  status")
    print("-" * (width + 32))
    for r in rows:
        status = "OK" if r["ok"] else f"FAIL ({r['detail']})"
        actual = "-" if r["actual"] is None else r["actual"]
        print(f"{r['metric']:<{width}}{r['constraint']:>12}{str(actual):>10}  {status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail (exit 1) when eval aggregates regress below baselines."
    )
    parser.add_argument("report", help="report.json produced by run_evals.py")
    parser.add_argument("baselines", help="baselines.json with metric thresholds")
    args = parser.parse_args(argv)

    report = json.loads(Path(args.report).read_text())
    baselines = json.loads(Path(args.baselines).read_text())

    thresholds = {
        k: v
        for k, v in baselines.get("metrics", {}).items()
        if not k.startswith("_")
    }
    if not thresholds:
        print("No thresholds defined in baselines file.", file=sys.stderr)
        return 1

    aggregate = report.get("aggregate", {})
    rows = evaluate_thresholds(aggregate, thresholds)

    papers = aggregate.get("papers_evaluated")
    print(
        f"Regression check: {len(rows)} thresholds vs aggregate of "
        f"{papers if papers is not None else '?'} paper(s)\n"
    )
    print_table(rows)

    failures = [r for r in rows if not r["ok"]]
    if failures:
        print(
            f"\nREGRESSION: {len(failures)}/{len(rows)} metric(s) below baseline.",
            file=sys.stderr,
        )
        return 1
    print(f"\nAll {len(rows)} metrics within baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
