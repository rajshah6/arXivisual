# arXivisual Backend — Agent Context

FastAPI service that turns an arXiv ID into narrated Manim explainer videos, live on Azure Container Apps
(arxivisual.org). Deep dive: `../docs/ARCHITECTURE.md`. Infra (Terraform, production): `../infra/README.md`.

## Architecture

```
POST /api/process  (api/routes.py: rate-limit + dedupe [api/throttle.py] + stale-job reap [db/queries.py])
        │
        ├─ USE_TEMPORAL=1 → Temporal workflow  paper-{arxiv_id}   (temporal_app/workflows.py, durable)
        └─ off / Temporal error → FastAPI BackgroundTasks legacy path (jobs/worker.py) — fail-open
        │
  ingest (ingestion/) → agent pipeline (agents/pipeline.py) → parallel renders
  (rendering/local_runner.py: manim subprocess + TTS) → Cloudflare R2 upload (rendering/storage.py)
  → visual QA (agents/visual_qa.py) → repair pass (temporal_app/activities.py) → honest finalize
        │
  Postgres via async SQLAlchemy (db/) ← frontend polls GET /api/status/{job_id}
```

- **LLM**: Azure OpenAI GPT-5 family, provider-switchable via `agents/base.py` (Dedalus = legacy fallback).
- **TTS**: Azure OpenAI `gpt-4o-mini-tts` as manim-voiceover `OpenAIService`; env routed to Azure's
  OpenAI-compatible endpoint at render time by `rendering/local_runner.py:_tts_subprocess_env`.
- **Rendering**: local subprocess (`RENDER_MODE=local`, the default and what prod runs). Modal exists
  (`rendering/modal_runner.py`) only as an unused optional mode. **There is no Redis anywhere.**
- **DB**: Postgres (asyncpg) when `DATABASE_URL` set, SQLite `./arxiviz.db` locally. No alembic — schema is
  `Base.metadata.create_all` in `db/connection.py:init_db()` at startup.
- **Observability**: Langfuse v3 (OTel-based) — `langfuse.openai` drop-in client wraps every LLM call, plus
  `@observe` spans; active iff both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set.

## Pipeline stages (agents/pipeline.py)

| # | Stage | File | Kind |
|---|-------|------|------|
| 1 | SectionAnalyzer | `agents/section_analyzer.py` | LLM: pick concepts worth animating |
| 2 | VisualizationPlanner | `agents/visualization_planner.py` | LLM: scene-by-scene storyboard |
| 3 | ManimGenerator (voice-aware) | `agents/manim_generator.py` | LLM: full `VoiceoverScene` code, few-shot by viz type |
| 4 | CodeValidator | `agents/code_validator.py` | gate: AST/structure/auto-fixes, no LLM |
| 5 | SpatialValidator | `agents/spatial_validator.py` | gate: bounds/overlap regex, no LLM |
| 6 | VoiceoverScriptValidator | `agents/voiceover_script_validator.py` | gate: narration quality, heuristics + LLM judge |
| 7 | RenderTester | `agents/render_tester.py` | gate: compile + import test (auto-skipped when `RENDER_MODE=modal`) |

Gate failure → regenerate with combined feedback (`MAX_RETRIES=3` + `VOICE_QUALITY_RETRIES=2` attempts); all
attempts failing → `VOICE_FAIL_BEHAVIOR="return_silent"`. Gates report to the eval harness through the
`agents.pipeline.metrics_hook` seam (None in production). After rendering, a vision judge samples frames for
layout defects (`agents/visual_qa.py`); on the Temporal path a `severity=major` verdict can drive one
closed-loop layout repair + re-render (`temporal_app/activities.py:repair_visualization_code`).

## Commands (from `backend/`)

```bash
uv sync --extra dev                          # install (dev extra = pytest)
uv run pytest tests/                         # unit suite (~89 tests, hermetic; CI hard gate on py3.11+3.13)
TEMPORAL_TESTS=1 uv run pytest tests/test_temporal_pipeline.py   # integration (downloads Temporal dev server)
uvx ruff check .                             # lint — HARD CI gate; the tree is ruff-clean (policy in pyproject)
uv run uvicorn main:app --reload             # API on :8000, docs at /docs
uv run python -m temporal_app.worker         # Temporal worker (paper-pipeline + paper-render queues)
uv run python evals/run_evals.py --papers 2 --max-viz 2 --output report.json   # real LLM spend (~$0.05–0.15/paper)
uv run python evals/check_regression.py report.json evals/baselines.json
```

CI (`.github/workflows/`): `ci.yml` — backend pytest, frontend tsc + build, docker image build (hard gates;
backend ruff and frontend eslint are both HARD gates). `security.yml` — gitleaks secret scan (blocking) + npm/pip audit
(advisory). `evals.yml` — nightly 06:00 UTC golden-set evals, fails on baseline regression. `deploy-backend.yml`
— Azure OIDC login, ACR build, Container App roll, health verify.

## Env vars (\* = secret; template: `.env.example`)

- `AZURE_OPENAI_API_KEY`\*, `AZURE_OPENAI_ENDPOINT` — primary provider (auto-detected; `LLM_PROVIDER=azure|dedalus` forces).
- `AZURE_OPENAI_DEPLOYMENT` (default `gpt-5`), `AZURE_OPENAI_REASONING_EFFORT` (default `low`).
- `DEDALUS_API_KEY`\* — legacy fallback provider (also powers optional Context7 docs via `agents/context7_docs.py`).
- `DATABASE_URL`\* — Postgres; `postgres://` is auto-rewritten to `postgresql+asyncpg://`. Unset = SQLite.
- `STORAGE_MODE` `local|r2`; for r2: `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`\*, `S3_SECRET_KEY`\*, `S3_PUBLIC_URL`.
- `LANGFUSE_PUBLIC_KEY`\*, `LANGFUSE_SECRET_KEY`\*, `LANGFUSE_HOST`, `LANGFUSE_TRACING_ENVIRONMENT`.
- `ENVIRONMENT=production` — disables `POST /api/render` (404) unless `RENDER_API_SECRET`\* matches the
  `X-Render-Secret` header. The endpoint executes caller-supplied Python; keep it locked.
- `RATE_LIMIT_PROCESS_PER_IP` (5/h), `RATE_LIMIT_PROCESS_GLOBAL` (30/h), `RATE_LIMIT_PROCESS_WINDOW_SECONDS`
  (3600), `PROCESS_DEDUPE_TTL_SECONDS` (600) — cost fuse on `/api/process` (`api/throttle.py`).
- `TEMPORAL_ADDRESS` (`localhost:7233`), `TEMPORAL_NAMESPACE` (`default`), `TEMPORAL_TLS=1` (prod reaches
  Temporal via HTTP/2 ingress behind TLS :443 — raw TCP ingress is unroutable on Container Apps).

## Feature flags

- `USE_TEMPORAL=1` — durable orchestration; any Temporal error falls back (fail-open) to the legacy in-process path.
- `ENABLE_VISUAL_QA=1` — vision judge on rendered frames (observe-only on legacy path; verdict feeds repair on Temporal path).
- `VISUAL_QA_REPAIR=1` — one **vision-grounded** repair round for `major` defects (Temporal path only): the
  rendered video is read back through the storage backend (never the CDN URL — stable keys cache for a year),
  defect frames are sampled, and the repair model sees the pixels. Text-only repair is the fallback for every
  vision-failure mode. Measured: text-only fixed 0/6; vision-grounded fixed 2/4 in its first production run.
  Also: `VISUAL_QA_MODEL` (`gpt-5-mini`), `VISUAL_QA_REPAIR_MODEL` (defaults to the judge model),
  `VISUAL_QA_FRAMES` (3).
- `VOICEOVER_TTS_SERVICE` `openai|gtts` (default `openai` = Azure-routed), `VOICEOVER_VOICE_NAME` (`nova`),
  `VOICEOVER_TTS_MODEL` (`gpt-4o-mini-tts`), `VOICEOVER_CACHE_DIR` (`/tmp/arxivisual-tts-cache`).
- `RENDER_CONCURRENCY` (3) — parallel manim renders per host; `PIPELINE_CONCURRENCY` (2) — concurrent
  generations on the Temporal worker (surplus queues on the server).
- `RENDER_MODE` `local|modal` (default `local`; `modal` also disables the local RenderTester gate).

## Conventions — do not violate

1. **Per-task DB sessions.** `AsyncSession` is not concurrency-safe: every concurrent task/activity opens its
   own `async_session_maker()` (see `jobs/worker.py:_render_one`, all of `temporal_app/activities.py`). Never
   share one session across `asyncio.gather`ed tasks.
2. **Workflow code stays deterministic and sandbox-clean.** `temporal_app/workflows.py`: no I/O, no env reads,
   no heavy imports — side effects and env-derived decisions (e.g. `repair_recommended`) belong in activities.
3. **Never pass `cache_dir` as a str to manim-voiceover** — it crashes the cache lookup. Narration-cache
   persistence is the runner's symlink (`local_runner.py:_link_persistent_voiceover_cache`); leave the library
   on its default Path-typed codepath.
4. **viz IDs use the full sanitized arXiv id**: `viz_{arxiv_id with ./ → _}_{n}`. A truncated prefix collided
   across sibling ids (2608.23551 vs 2608.23553) and papers overwrote each other's rows.
5. **Infra changes go through `infra/*.tf`** (terraform plan first — it manages live production), never ad-hoc `az`.
6. **DB datetime columns are naive UTC** (`datetime.utcnow`). Do not introduce tz-aware datetimes; the dedupe
   and reaper queries compare naive values.
7. **All LLM calls route through `agents/base.py`** (`call_llm` / `BaseAgent._call_llm`) — provider switching
   and Langfuse tracing live there.
8. **Keep `pytest` hermetic.** `testpaths=["tests"]` exists because scripts under `tools/` fire real API calls
   on collection; new tests must not need network or real keys.
