# Generation-quality evals

A golden-set eval harness for the multi-agent Manim generation pipeline
(`agents/pipeline.py`). It measures per-gate LLM generation quality on a fixed
set of real arXiv papers and **fails CI when any aggregate metric regresses
below baseline** — see `.github/workflows/evals.yml` (nightly at 06:00 UTC,
plus manual `workflow_dispatch`).

## What it measures

Each golden-set paper (`golden_set.json`, 8 papers spanning core ML,
theory/optimization, and applied CV) is fetched and ingested for real, then run
through the real pipeline with the metrics hook attached
(`agents.pipeline.metrics_hook` → `evals/metrics.py:GateMetrics`). Local render
testing is disabled (`RENDER_MODE=modal`), so the run measures the **LLM
quality gates**, not ffmpeg/cairo:

| Gate | What it checks |
|---|---|
| `code_validator` | AST syntax + structure (deterministic) |
| `spatial_validator` | positioning / bounds / overlaps (deterministic) |
| `voiceover_script_validator` | narration quality (heuristics + LLM judge) |
| `render_tester` | *disabled in evals* (import/execution test) |

Reported per gate (aggregate and per paper): **first-attempt pass rate**,
**eventual pass rate** (within the retry budget), and **average attempts to
pass**. Per paper: candidates run, visualizations validated vs returned, and
wall-clock time. The headline `viz_yield_rate` counts only visualizations that
actually cleared every enabled gate — silent fallbacks
(`VOICE_FAIL_BEHAVIOR=return_silent`) do not inflate it.

## Running locally

Real LLM calls and real arXiv fetches — you need the provider env
(`backend/.env` works, `agents/base.py` loads it):

```bash
export AZURE_OPENAI_API_KEY=... AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_DEPLOYMENT=...
export AZURE_OPENAI_REASONING_EFFORT=low   # cost control

cd backend
uv run python evals/run_evals.py --papers 2 --max-viz 2 --output report.json
uv run python evals/check_regression.py report.json evals/baselines.json
```

- `--papers N` — first N papers of `golden_set.json` (default: all 8; order is
  cheapest/most load-bearing first)
- `--max-viz M` — cap visualizations per paper (default 2)
- `check_regression.py` exits 1 with a verdict table on any regression.

**Cost:** roughly **$0.05–0.15 per paper** at 2 visualizations and low
reasoning effort (no rendering). Nightly CI runs 5 papers; manual dispatch
defaults to 3.

## Baselines and tightening procedure

`baselines.json` holds minimum thresholds against `report["aggregate"]`
(dotted-path keys, `{"min": x}` / `{"max": x}`). The initial values carry
**generous slack** — they catch collapses, not drift:

- `viz_yield_rate >= 0.5`
- `code_validator` first-attempt `>= 0.4`, eventual `>= 0.7`
- `spatial_validator` / `voiceover_script_validator` eventual `>= 0.7`

**Tighten once 3+ real nightly runs establish variance.** Procedure:

1. Download the `eval-report` artifacts from the last 3+ green nightly runs.
2. For each baselined metric, take the minimum observed value across runs.
3. Set the threshold to that floor minus a small variance margin (~0.05–0.10
   for rates), and consider adding `{"max": ...}` caps on `avg_attempts`.
4. Land the `baselines.json` change with the run links in the PR description.

A metric *missing* from a report (a gate that never ran) fails the check on
purpose — silently losing a gate is a regression.

## Layout

```
evals/
├── golden_set.json      # 8 fixed papers + why each is in the set
├── metrics.py           # GateMetrics collector + aggregate_summaries (stdlib-only)
├── run_evals.py         # CLI runner: ingest → generate → report.json
├── baselines.json       # regression thresholds (see tightening procedure)
└── check_regression.py  # report vs baselines → exit 1 on regression
```

The pipeline seam is a single optional module-level callback
(`agents.pipeline.metrics_hook`) invoked after each gate with
`(gate_name, attempt, passed)`; it is `None` in production and never affects
generation behavior. Unit tests: `tests/test_evals.py` (no network).
