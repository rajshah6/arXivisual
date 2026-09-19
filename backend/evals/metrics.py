"""Gate-level metrics collection for the generation-quality eval harness.

Consumes the ``(gate_name, attempt, passed)`` events emitted through
``agents.pipeline.metrics_hook`` and turns them into per-paper and aggregate
quality metrics. Stdlib-only on purpose: importable (and unit-testable)
without the ML dependency stack or any network access.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

#: Gates in pipeline order. Every generate_single_visualization run evaluates
#: ``code_validator`` first on attempt 0, exactly once — which is what lets the
#: collector split events into per-visualization traces without a viz id.
GATE_ORDER = (
    "code_validator",
    "spatial_validator",
    "voiceover_script_validator",
    "render_tester",
)
CODE_GATE = GATE_ORDER[0]


@dataclass
class GateEvent:
    gate: str
    attempt: int
    passed: bool


@dataclass
class VizTrace:
    """Ordered gate events for one generate_single_visualization run."""

    events: list[GateEvent] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """True when the final attempt cleared every enabled gate.

        The pipeline breaks out of its retry loop only when an attempt passes
        all gates, so the last recorded event of a successful run is a pass;
        an exhausted run always ends on the failing gate's event. (A "silent
        fallback" visualization returned by VOICE_FAIL_BEHAVIOR=return_silent
        therefore does NOT count as succeeded — this metric measures whether
        the LLM actually satisfied the gates.)
        """
        return bool(self.events) and self.events[-1].passed

    @property
    def attempts_used(self) -> int:
        """Number of generation attempts consumed (1-based)."""
        if not self.events:
            return 0
        return 1 + max(e.attempt for e in self.events)


class GateMetrics:
    """Collects pipeline gate events and summarizes them.

    Attribution of events to visualization runs works without a viz id:

    * every run emits ``(code_validator, attempt=0)`` exactly once, before any
      other event — so that event starts a new trace;
    * concurrent runs are separated by a ``ContextVar``: asyncio gives each
      gathered task its own Context copy, so the "current trace" pointer set
      inside one task is invisible to its siblings, while this collector's
      trace list (a shared object) sees every append.
    """

    def __init__(self) -> None:
        self.traces: list[VizTrace] = []
        self._current: contextvars.ContextVar[VizTrace | None] = contextvars.ContextVar(
            f"gate_metrics_current_{id(self)}", default=None
        )

    def hook(self, gate: str, attempt: int, passed: bool) -> None:
        """Signature-compatible with ``agents.pipeline.metrics_hook``."""
        trace = self._current.get()
        if trace is None or (gate == CODE_GATE and attempt == 0):
            trace = VizTrace()
            self.traces.append(trace)
            self._current.set(trace)
        trace.events.append(GateEvent(gate=gate, attempt=attempt, passed=passed))

    def summary(self) -> dict:
        """Per-paper summary: raw counts only, so summaries aggregate exactly."""
        gates: dict[str, dict] = {}
        for gate in GATE_ORDER:
            evaluated = [t for t in self.traces if any(e.gate == gate for e in t.events)]
            if not evaluated:
                continue  # gate disabled (or never reached) in this run

            first = [
                e
                for t in evaluated
                for e in t.events
                if e.gate == gate and e.attempt == 0
            ]

            eventual_passes = 0
            attempts_to_pass_total = 0
            for t in evaluated:
                pass_attempts = [e.attempt for e in t.events if e.gate == gate and e.passed]
                if pass_attempts:
                    eventual_passes += 1
                    attempts_to_pass_total += min(pass_attempts) + 1

            gates[gate] = {
                "vizzes_evaluated": len(evaluated),
                "first_attempt_evals": len(first),
                "first_attempt_passes": sum(1 for e in first if e.passed),
                "eventual_passes": eventual_passes,
                "total_evals": sum(
                    1 for t in evaluated for e in t.events if e.gate == gate
                ),
                "attempts_to_pass_total": attempts_to_pass_total,
            }

        return {
            "candidates_run": len(self.traces),
            "visualizations_validated": sum(1 for t in self.traces if t.succeeded),
            "gates": gates,
        }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


#: USD per 1M tokens, disjoint buckets (input = uncached prompt tokens;
#: reasoning is billed at the output rate). Azure OpenAI GlobalStandard list
#: prices (Azure Retail Prices API, eastus2, 2026-09) for the deployments
#: production runs; the September invoice meters match list, not the
#: announced 4/20 promo. Keys are matched by prefix so versioned Azure names
#: (``gpt-5-mini-2025-08-07``) price like the base model.
DEFAULT_PRICES_PER_M: dict[str, dict[str, float]] = {
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.0},
    "gpt-5.6-sol": {"input": 5.0, "cached_input": 0.50, "output": 30.0},
}

TOKEN_BUCKETS = ("input", "cached_input", "output", "reasoning")


def _price_for(model: str, prices: dict[str, dict[str, float]]) -> dict[str, float] | None:
    if model in prices:
        return prices[model]
    for known in sorted(prices, key=len, reverse=True):
        if model.startswith(known):
            return prices[known]
    return None


class UsageMetrics:
    """Accumulates ``agents.base.LLMUsage`` events (duck-typed: any object with
    name/model/input_tokens/cached_tokens/output_tokens/reasoning_tokens) and
    prices them, so an eval run reports dollars next to pass rates.

    A call whose model has no price is counted in ``unpriced_calls`` rather
    than costing $0 silently — an unpriced model is how a frontier-priced
    repair loop went unnoticed on the invoice.
    """

    def __init__(self, prices: dict[str, dict[str, float]] | None = None) -> None:
        self.prices = DEFAULT_PRICES_PER_M if prices is None else prices
        self.calls: list = []

    def hook(self, usage) -> None:
        """Signature-compatible with ``agents.base.usage_hook``."""
        self.calls.append(usage)

    def _cost(self, usage) -> float | None:
        price = _price_for(usage.model, self.prices)
        if price is None:
            return None
        return (
            usage.input_tokens * price["input"]
            + usage.cached_tokens * price["cached_input"]
            + (usage.output_tokens + usage.reasoning_tokens) * price["output"]
        ) / 1_000_000

    def summary(self) -> dict:
        by_name: dict[str, dict] = {}
        total = {"llm_calls": 0, "unpriced_calls": 0, "cost_usd": 0.0}
        tokens = dict.fromkeys(TOKEN_BUCKETS, 0)
        for u in self.calls:
            row = by_name.setdefault(
                u.name or "",
                {"calls": 0, "unpriced_calls": 0, "cost_usd": 0.0, "tokens": dict.fromkeys(TOKEN_BUCKETS, 0)},
            )
            cost = self._cost(u)
            buckets = (u.input_tokens, u.cached_tokens, u.output_tokens, u.reasoning_tokens)
            for scope in (row["tokens"], tokens):
                for key, n in zip(TOKEN_BUCKETS, buckets, strict=True):
                    scope[key] += n
            row["calls"] += 1
            total["llm_calls"] += 1
            if cost is None:
                row["unpriced_calls"] += 1
                total["unpriced_calls"] += 1
            else:
                row["cost_usd"] += cost
                total["cost_usd"] += cost
        for row in by_name.values():
            row["cost_usd"] = round(row["cost_usd"], 6)
        return {
            **total,
            "cost_usd": round(total["cost_usd"], 6),
            "tokens": tokens,
            "by_name": by_name,
        }


def _aggregate_usage(summaries: list[dict], validated: int) -> dict:
    usages = [s["usage"] for s in summaries if s.get("usage")]
    if not usages:
        return {
            "llm_calls": None,
            "unpriced_calls": None,
            "tokens": None,
            "cost_usd": None,
            "cost_per_paper_usd": None,
            "cost_per_validated_viz_usd": None,
        }
    cost = round(sum(u["cost_usd"] for u in usages), 6)
    return {
        "llm_calls": sum(u["llm_calls"] for u in usages),
        "unpriced_calls": sum(u["unpriced_calls"] for u in usages),
        "tokens": {k: sum(u["tokens"][k] for u in usages) for k in TOKEN_BUCKETS},
        "cost_usd": cost,
        "cost_per_paper_usd": round(cost / len(usages), 6),
        "cost_per_validated_viz_usd": round(cost / validated, 6) if validated else None,
    }


def aggregate_summaries(summaries: list[dict]) -> dict:
    """Combine per-paper summaries into the aggregate metrics that
    ``baselines.json`` thresholds are checked against (see check_regression.py).
    """
    candidates = sum(s["candidates_run"] for s in summaries)
    validated = sum(s["visualizations_validated"] for s in summaries)

    gates: dict[str, dict] = {}
    for gate in GATE_ORDER:
        rows = [s["gates"][gate] for s in summaries if gate in s.get("gates", {})]
        if not rows:
            continue
        first_evals = sum(r["first_attempt_evals"] for r in rows)
        first_passes = sum(r["first_attempt_passes"] for r in rows)
        evaluated = sum(r["vizzes_evaluated"] for r in rows)
        eventual = sum(r["eventual_passes"] for r in rows)
        attempts_total = sum(r["attempts_to_pass_total"] for r in rows)
        gates[gate] = {
            "vizzes_evaluated": evaluated,
            "first_attempt_rate": _rate(first_passes, first_evals),
            "eventual_rate": _rate(eventual, evaluated),
            "avg_attempts": _rate(attempts_total, eventual),
        }

    return {
        "papers_evaluated": len(summaries),
        "candidates_run": candidates,
        "visualizations_validated": validated,
        "viz_yield_rate": _rate(validated, candidates),
        "gates": gates,
        **_aggregate_usage(summaries, validated),
    }
