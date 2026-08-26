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
    }
