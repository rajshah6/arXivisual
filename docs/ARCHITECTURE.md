# arXivisual — Backend Architecture

You give the system an arXiv paper ID. It gives you back narrated, animated explainer videos for the key concepts in that paper, embedded in a readable, sectioned presentation of the paper itself. This document describes how, at the level of what actually runs.

```
  arXiv ID
     |
     v
 +-----------+     +------------------+     +--------------------+     +-----------------+
 | Ingestion  | --> | Agent pipeline   | --> | 4 validation gates | --> | Render (Manim   |
 | fetch/parse|     | analyze/plan/gen |     | retry w/ feedback  |     | + TTS) -> R2    |
 +-----------+     +------------------+     +--------------------+     +-----------------+
```

## Job Lifecycle

Two Container Apps run the same backend image. **`arxivisual-api`** (FastAPI, `main.py`) admits jobs and serves reads; **`arxivisual-worker`** (`temporal_app/worker.py`) executes them. A self-hosted Temporal server (`arxivisual-temporal`) sits between the two. Production sets `USE_TEMPORAL=1`; with the flag off, or whenever Temporal cannot be reached, the API runs the whole pipeline itself as a FastAPI background task (see [Fallback](#fallback-the-in-process-path-jobsworkerpy)).

```
POST /api/process ─ admission ─ ProcessingJob row (queued) ─ start workflow  paper-{arxiv_id}
                                                              └ any Temporal error: in-process fallback
arxivisual-worker
  task queue paper-pipeline   ingest_paper → generate_visualizations_for_paper → (repair) → finalize_job
  task queue paper-render     render_visualization × N      at most RENDER_CONCURRENCY per replica

GET /api/status/{job_id}  ←  the job row, written by the activities
```

### Admission (`api/routes.py`)

`POST /api/process`, in order:

1. **Reap.** Jobs stranded at `queued`/`processing` for more than two hours are marked failed (`queries.reap_stale_jobs`), so a zombie can never satisfy the dedupe below.
2. **Dedupe.** An in-flight job for the same paper is returned as-is: an in-memory `recent_jobs` map covers the seconds before the job row is linked to its paper, the jobs table covers everything after.
3. **Admission control**, each layer assuming the previous one is being gamed: the durable daily cap and the global rolling window (both counted from the jobs table, and checked first so a capped day does not burn a human's single-use Turnstile token) → server-verified Turnstile, bound to this paper → per-IP hourly and daily windows (in memory). See `SECURITY.md`.
4. **Start.** A `ProcessingJob` row is created (`queued`) and `PaperPipelineWorkflow` is started on task queue `paper-pipeline` with workflow id `paper-{arxiv_id}`. The id is the orchestrator-level dedupe: a second start for a paper that is still running raises `WorkflowAlreadyStartedError`, and the API retires the row it just created and answers with the active job.

The job id is returned immediately and the frontend polls `GET /api/status/{job_id}`, which only reads the job row — the polling contract is identical on both paths.

### The workflow (`temporal_app/workflows.py`)

`PaperPipelineWorkflow` is orchestration only: no I/O, no env reads, no heavy imports, so it stays deterministic on replay. Every side effect is an activity in `temporal_app/activities.py`, and every activity opens its own DB session.

| Step | Activity | Task queue | Start-to-close, attempts | Job progress |
|------|----------|------------|--------------------------|--------------|
| Ingest | `ingest_paper` | `paper-pipeline` | 15 min, 2, no heartbeat | 0.10 → 0.30 |
| Generate | `generate_visualizations_for_paper` | `paper-pipeline` | 40 min, 2, heartbeat timeout 8 min | 0.50 → 0.75 |
| Render | `render_visualization` × N, then `update_render_progress` | `paper-render` | 25 min, 2, no heartbeat | 0.75 → 0.95 |
| Repair | `repair_visualization_code`, then `render_visualization` again | `paper-pipeline`, `paper-render` | 18 min and 25 min, 1 each, no heartbeat | — |
| Finalize | `finalize_job` | `paper-pipeline` | 1 min, 2 | 1.0 |

- **Ingest** fetches and parses the paper and stores paper + sections. It is skipped if the paper was processed before; a pre-fix abstract-only ingest (`queries.is_stale`) is re-ingested instead. Deterministic failures (`SourceTooShortError`, a formatting failure after its own retry) are raised non-retryable and reach the job row verbatim.
- **Generate** runs the agent pipeline for up to 5 concepts and returns one render input (viz id + Manim code) per visualization.
- **Render**: all renders are started at once. The render worker's `max_concurrent_activities` (`RENDER_CONCURRENCY`, 3 in production) throttles per replica and Temporal queues the surplus — no semaphore. Each render is wrapped so that one failed activity becomes a failed result (its row marked by `record_render_failure`) instead of aborting the workflow. The workflow owns the completion counters and issues the progress writes as results arrive, so concurrent renders share no mutable state.
- **Any exception** escaping the workflow runs `mark_job_failed` — the real reason goes on the job row, rows still `pending` are failed — and then the workflow itself fails, leaving its full history in Temporal.

**Checkpoints.** Each completed activity is a durable checkpoint in workflow history: a worker killed mid-run (a redeploy did this twice) resumes after the last completed activity. Generation's return value is stored in history, so the LLM spend is never paid twice. Inside generation the checkpoints are finer: each finished visualization is INSERTed into `visualizations` the moment it is ready (`queries.insert_visualization_with_next_index` — the id is minted at write time and never upserted, so two overlapping attempts cannot overwrite each other) and the activity heartbeats, on top of a 30-second heartbeat timer. A retried attempt reloads this run's rows (those created since the job began), skips their concepts, and fills only the remaining slots. Generation is the only activity with a heartbeat: a worker replaced under an ingest, a render or a repair is noticed only when that activity's start-to-close timeout expires, which is why backend rolls belong in a quiet window (`docs/DEPLOY.md`).

**Finalize.** `finalize_job` writes the honest terminal status (below), fails any row of this run still `pending`, and — only if the run produced at least one video — marks previous runs' rows `superseded`. Old rows are never deleted (feedback references them) and superseded rows never reach the API, so a re-run does not blank an already-visualized paper while it is in progress.

**The worker process** (`temporal_app/worker.py`) runs two Temporal workers on one event loop: `paper-pipeline` (the workflow plus every light activity, `PIPELINE_CONCURRENCY` = 2 concurrent activities) and `paper-render` (the render activity only). It retries its Temporal connection six times with backoff, because a revision rollover used to fail the first attempt. The worker app scales from 1 to 3 replicas on a KEDA rule that counts queued and processing jobs (`infra/container_apps.tf`).

### Fallback: the in-process path (`jobs/worker.py`)

If `USE_TEMPORAL` is off, or **anything** raises while the workflow is being started (import, connect, start), the API logs `Temporal unavailable — falling back to in-process pipeline` and schedules `process_paper_job` as a FastAPI background task. Fail-open on purpose: orchestrator trouble must never stop papers from processing. The path reuses the same building blocks (`_ingest_and_store_paper`, `generate_visualizations`, `process_visualization`) and reports progress on the same job row, but:

- it runs inside the API container and does not survive a restart — the stale-job reaper is what eventually fails such a job;
- renders are bounded by an `asyncio.Semaphore(RENDER_CONCURRENCY)`, each committing through its own DB session, with a lock serializing the progress writes;
- rows are upserted as `viz_{id}_{n}` only after all generation has finished: no per-visualization checkpoints, no superseding;
- visual QA is observe-only — there is no repair pass.

The `paper_accepted` product event records which path took the job (`path: temporal | legacy`).

### After a render: QA, feedback, terminal status

**Visual QA + self-repair** (`agents/visual_qa.py`, `temporal_app/activities.py`): after each render, a vision model samples 3 frames and judges layout defects (overlap / cutoff / collisions), scoring every verdict into Langfuse (`visual_qa_defect`). On the Temporal path, a `major` verdict triggers one **vision-grounded repair**: the video is read back through the storage backend (never the CDN — stable keys cache for a year), the defect frames plus the judge's issues go to a multimodal model, and the repaired code is re-rendered and re-judged. Every vision-failure mode falls back to a text-only repair; an unusable repair keeps the original video. Measured in production: text-only repair fixed 0/6 flagged videos; vision-grounded fixed 2/4 in its first run — the pixels carry information the text descriptions provably don't.

**Human feedback loop** (`POST /api/feedback`): viewers vote 👍/👎 per video (optional reason chip) or leave site suggestions; rows land in the `feedback` table with `paper_id` denormalized from the visualization row. Video votes are human-labeled defect data — the ground truth the vision judge can be calibrated against, and seed material for the eval golden set.

**Terminal status is honest** (`resolve_terminal_job_status` in `jobs/worker.py`): a job is `completed` only if at least one visualization actually rendered. Zero generated or all-failed renders mark the job `failed` with an explanatory error, while the parsed paper text remains readable. Individual render failures are recorded per visualization and don't sink the job.

## Ingestion (`backend/ingestion/`)

`ingest_paper(arxiv_id)` fetches metadata from the arXiv API, then parses content — LaTeXML HTML when available (probed at `arxiv.org/html`, then `ar5iv.labs.arxiv.org/html`, redirects not followed and bodies must carry `ltx_document`, so an abstract page is never mistaken for the paper) (clean headings, equations, figure captions), PDF via pymupdf4llm otherwise. Sections are extracted with heading levels and per-section equations/figures/tables, noise sections (references, acknowledgments, etc.) are dropped, and an LLM summarization pass produces per-section summaries. Output is a `StructuredPaper` (Pydantic), normalized for display by `ingestion/text_normalize.normalize_display_text` (small-caps/zero-width cleanup, organizer scaffold strip, JSON-escape undo, math-fence repair, per-`$` currency escaping, bare-TeX run wrapping, `\[ \]`/`\( \)` conversion) and persisted to the `papers` and `sections` tables. The same idempotent function runs on `GET /api/paper` output (abstracts with `from_organizer=False`), so papers stored before a rule existed render cleanly without a migration; titles go through `tex_to_text`.

## The Agent Pipeline (`backend/agents/pipeline.py`)

The chain, in order:

**SectionAnalyzer → VisualizationPlanner → ManimGenerator → CodeValidator → SpatialValidator → VoiceoverScriptValidator → RenderTester**

All LLM-backed agents extend `BaseAgent` (`agents/base.py`) and load their prompt from `backend/prompts/`.

### 1. SectionAnalyzer (`section_analyzer.py`)

Asks the LLM, per section: which concepts here deserve an animated visualization? Sections are analyzed concurrently via `asyncio.gather`; one failure doesn't stop the rest. Each `VisualizationCandidate` carries a concept name/description, a type (`architecture`, `equation`, `algorithm`, `data_flow`, `matrix`, `three_d`), and a 1–5 priority. Candidates are sorted by priority and capped at 5 (`MAX_VISUALIZATIONS`).

### 2. VisualizationPlanner (`visualization_planner.py`)

Turns a candidate plus its section text into a `VisualizationPlan`: an ordered list of scenes with descriptions and durations, plus narration points, targeting 30–45 seconds total.

### 3. ManimGenerator (`manim_generator.py`)

Generates a complete Python file: a `VoiceoverScene` subclass whose narration is written together with the animation. Before each call it selects a voiceover few-shot example matching the visualization type (`backend/examples/voiceover_*.py`) and fetches current Manim documentation (`context7_docs.py`: the Context7 REST API, with a bundled static reference as fallback; a Dedalus-MCP path exists but only runs on the legacy Dedalus provider). Generated code must set up the speech service in `construct()`, wrap each beat in `with self.voiceover(text=...) as tracker:`, and time animations with `run_time=tracker.duration`. The generator extracts narration lines and `# Beat N` labels as metadata.

### 4–7. The Validation Gates

Each generated scene must pass four gates in sequence. Any failure aborts the attempt, and feedback from **all** failed gates is concatenated and fed to `ManimGenerator.run_with_feedback()` along with the previous code. Stale gate results are cleared between attempts so retries never chase issues that no longer exist. Budget: `MAX_RETRIES` (3) + `VOICE_QUALITY_RETRIES` (2) = 5 attempts.

- **CodeValidator** (`code_validator.py`) — pure static analysis: AST parse, `from manim import *` injection, Scene-class and `construct()` checks, auto-fixes for common typos and unclosed brackets, and detection of LaTeX split across `MathTex` arguments (which crashes Manim and always forces regeneration).
- **SpatialValidator** (`spatial_validator.py`) — regex-extracts positions from `move_to`/`shift`/`next_to`/`to_edge` calls, flags elements outside screen bounds (|x| > 7, |y| > 4) or the safe area, likely overlaps, and `next_to`/`arrange` calls missing `buff`. Static analysis only, so positioning it can't parse (pure `next_to` chains) goes unchecked.
- **VoiceoverScriptValidator** (`voiceover_script_validator.py`) — hard checks (`VoiceoverScene`, `set_speech_service`, at least one voiceover block, tracker-timed plays), then narration quality: a 6–40 word window per line, rejection of animation-command phrasing ("Now we display…"), and alignment (≥ 0.45) and educational (≥ 0.50) scores from heuristics, overridden by an LLM judge when available. The judge is synchronous, so the pipeline runs it in `asyncio.to_thread` to avoid stalling concurrent visualizations.
- **RenderTester** (`render_tester.py`) — the only gate that executes the code: `compile()` for syntax in-process, then **full `construct()` execution in a dry-run subprocess** (`dry_run_driver.py`): manim's `dry_run` config processes every animation without writing frames, TTS is replaced by an embedded silent MP3 (manim-voiceover has no dry-run support and would otherwise call the real service), `add_sound` is a no-op (drops the ffmpeg dependency), and subcaptions are disabled (under dry_run `config.output_file` is an empty string, so their writer raises at finish()). ~0.2s per scene, no network, no spend. This catches the runtime class import testing structurally can't — a production render died on `if a.get_center() == b.get_center():` (numpy truth-value `ValueError`) that only fires when `construct()` runs. Verdicts come from stdout sentinels; a driver crash without a verdict fails OPEN (the real render still guards, and a gate must never block all videos on its own infrastructure). `RENDER_TEST_EXECUTE=0` falls back to legacy import-only validation; `RENDER_TEST_TIMEOUT_SECONDS` (120) bounds it; a timeout fails open (CPU starvation under load is not a code verdict — 1,405 valid scenes were rejected in one week before this).

If all 5 attempts fail, `VOICE_FAIL_BEHAVIOR` (default `return_silent`) keeps the last generated code as a pending, videoless visualization; `drop_viz` and `hard_error` are the alternatives.

### Pipeline Configuration

Behavior knobs at the top of `agents/pipeline.py` (constants unless noted as env vars):

```python
MAX_VISUALIZATIONS = 5            # candidates kept per paper
MAX_RETRIES = 3                   # base generation attempts
VOICE_QUALITY_RETRIES = 2         # extra attempts for voiceover quality
CONCURRENT_ANALYSIS = True        # analyze sections in parallel
CONCURRENT_GENERATION = True      # generate visualizations in parallel
ENABLE_SPATIAL_VALIDATION = True
ENABLE_VOICEOVER = True
VOICE_MODE = "unified_generator"  # narration written with the animation
VOICE_FAIL_BEHAVIOR = "return_silent"
RENDER_MODE                       # env: "local" | "modal"; "modal" also skips RenderTester
VOICEOVER_TTS_SERVICE             # env: "openai" (default) | "gtts"
VOICEOVER_VOICE_NAME              # env: default "nova"
```

## LLM Provider Layer (`agents/base.py`)

Every agent call routes through `call_llm` / `call_llm_sync`, which resolve a provider from the environment: **Azure OpenAI is the primary** (set `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT`, or force with `LLM_PROVIDER=azure`). Details that matter:

- Calls go through Azure's OpenAI-compatible v1 endpoint (`{endpoint}/openai/v1/`) using the standard `openai` SDK, against the deployment named by `AZURE_OPENAI_DEPLOYMENT`.
- GPT-5 reasoning tokens count against `max_completion_tokens`, so each request adds 4096 tokens of headroom above the agent's visible-answer budget; `AZURE_OPENAI_REASONING_EFFORT` (default `low`) trades depth for speed and cost.
- Prompt templates are formatted with `str.replace`, not `str.format` — paper text is full of LaTeX braces.

A Dedalus Labs provider remains selectable as a legacy fallback (`DEDALUS_API_KEY`, or `LLM_PROVIDER=dedalus`); it lives in the same `agents/base.py`. The separate modules from that era — `agents/dedalus_base.py` (multi-model handoff chains) and `agents/voiceover_generator.py` (a post-hoc voiceover transform, superseded by unified generation) — have been deleted.

## Voiceover / TTS

Narration audio is produced **at render time** by manim-voiceover. The generator injects the service setup verbatim into each scene:

```python
self.set_speech_service(OpenAIService(voice="nova", model="gpt-4o-mini-tts", transcription_model=None))
```

`VOICEOVER_TTS_SERVICE` defaults to `openai`; voice and model come from `VOICEOVER_VOICE_NAME` / `VOICEOVER_TTS_MODEL`. There is no separate OpenAI key: the render subprocess environment (`rendering/local_runner.py:_tts_subprocess_env`) maps `AZURE_OPENAI_*` to `OPENAI_API_KEY`/`OPENAI_BASE_URL` (pinning `OPENAI_API_TYPE=openai`), so manim-voiceover's `OpenAIService` transparently talks to an Azure `gpt-4o-mini-tts` deployment. A real `OPENAI_API_KEY`, if set, takes precedence. `VOICEOVER_TTS_SERVICE=gtts` is the free, keyless fallback.

## Rendering (`backend/rendering/`)

`RENDER_MODE=local` (the production setting) renders in a subprocess of whichever process runs the pipeline. In production that is the `arxivisual-worker` container (the `render_visualization` activity on the `paper-render` queue); the API container renders only on the in-process fallback, or for the dev-only `POST /api/render`. The code is written to a temp directory and `manim render <file> <SceneName> -ql --format=mp4` runs via `subprocess.run` with a 300 s timeout, wrapped in `asyncio.to_thread`. Quality maps to Manim's `-ql`/`-qm`/`-qh`; the pipeline renders at `low_quality`. `RENDER_CONCURRENCY` (default 3) bounds concurrent renders per host: as the render worker's `max_concurrent_activities` on the Temporal path, as a semaphore on the fallback. A `RENDER_MODE=modal` path (serverless rendering on Modal.com via `modal_runner.py`) exists and also disables the local RenderTester gate, but is not used in production.

## Storage (`rendering/storage.py`)

`STORAGE_MODE` selects a backend behind one protocol:

- `local` (default) — MP4s under `media/videos/`, served by `GET /api/video/{id}` as a `FileResponse`.
- `r2` (production) — uploads to Cloudflare R2 (S3-compatible, `boto3`) under a `videos/` prefix with a one-year immutable cache header and one retry; `video_url` becomes a public `S3_PUBLIC_URL` link. `GET /api/video/{id}` 302-redirects to it.

## API Surface (`backend/api/routes.py`)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/process` | Start processing a paper; returns a job ID |
| GET | `/api/status/{job_id}` | Poll job progress |
| GET | `/api/paper/{arxiv_id}` | Processed paper: sections (each with `videos` = every `complete` visualization, newest first; `video_url` = `videos[0]` for older clients) + visualizations; superseded rows excluded; 404 for stale (pre-fix abstract-only) papers so the reader offers re-processing |
| GET | `/api/papers` | Explore gallery: all processed papers |
| GET | `/api/video/{video_id}` | Serve or redirect to a rendered video |
| POST | `/api/render` | Dev-only raw Manim render — in production, 404 unless `RENDER_API_SECRET` is configured and presented via `X-Render-Secret` (timing-safe compare) |
| POST | `/api/feedback` | Store viewer feedback: per-video 👍/👎 (labeled QA ground truth) or site suggestion |
| GET | `/api/health` | Database / Manim / storage health and the deployed commit (the only health path — there is no `/health`) |

CORS allows `arxivisual.org`, `www.arxivisual.org`, localhost dev, and whatever `CORS_EXTRA_ORIGINS` adds (in production: the frontend Container App's own FQDN) — see `backend/api/cors.py`.

## Persistence (`backend/db/`)

SQLAlchemy async ORM, five tables keyed off the arXiv ID: `papers`, `sections` (content, summary, equations/figures/tables as JSON), `visualizations` (concept, storyboard, Manim code, video URL, status — `pending`, `complete`, `failed` or `superseded`), `feedback` (per-video votes and site suggestions), and `processing_jobs`. There are no migrations: `init_db()` runs `Base.metadata.create_all` at API startup. `DATABASE_URL` selects Postgres (asyncpg, used in production); unset falls back to local SQLite (aiosqlite). Temporal keeps its own two databases on the same Postgres server.

## Observability

Four sinks, each answering a different question and each off unless its own configuration is present — local dev and CI run with none of them.

**Langfuse — what did the LLM do, and what did it cost?** Active when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are both set, no-ops otherwise:

- `base.py` swaps the OpenAI SDK for the `langfuse.openai` drop-in, so every LLM call is captured with model, tokens, cost, and latency; each generation is named after its agent's prompt file (e.g. `manim_generator`).
- `@observe` spans build the hierarchy `generate-visualizations` → `generate-single-visualization` under a trace named `process-paper`, with `session_id = job_id` grouping everything for one paper run. The Temporal generation activity sets those attributes with `propagate_attributes` (tags `pipeline`, `temporal`); the in-process path wraps the whole job in an `@observe` span and flushes before the background task exits, since it runs off-request.
- The visual-QA judge scores each trace (`visual_qa_defect`), so defect rates can be charted.
- `LANGFUSE_TRACING_ENVIRONMENT` separates production traces from development.

**Application Insights — is the service healthy?** (`telemetry.py`) When `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, `telemetry.configure()` loads the Azure Monitor OpenTelemetry distro (`azure-monitor-opentelemetry`): request telemetry from the API, outbound HTTP dependencies and exceptions from both the API and the worker. It must be the first thing `main.py` and `temporal_app/worker.py` do — the distro instruments by swapping the FastAPI class, and Langfuse has to be bound to its own tracer provider before any client exists. Production samples request traces at a fixed 20% (`OTEL_TRACES_SAMPLER=microsoft.fixed_percentage` with `OTEL_TRACES_SAMPLER_ARG=0.2`; the argument alone would mean 0.2 traces *per second*) and sets `OTEL_LOGS_EXPORTER=none`, because console logs already reach the workspace.

Both integrations are OpenTelemetry-based and both want the global tracer provider. Left alone, Langfuse would adopt Azure's: every LLM span, prompts included, would also be exported to Application Insights, and Azure's sampler would drop 80% of LLM traces before Langfuse saw them. So `telemetry.py` starts Langfuse on an isolated, never-global, always-on provider, forces its scores in-sample, and gives the in-process pipeline a detached trace context so its Langfuse trace is not parented to the request span.

**PostHog — is the product being used?** (`analytics.py`, no-op without `POSTHOG_API_KEY`) Three server-side events: `paper_accepted` from the API (distinct id = the hashed client fingerprint the admission logs already use) and `paper_completed` / `paper_failed_server` from whichever process finalizes the job (distinct id = the job id — no client identity reaches the pipeline). Person profiles and GeoIP are off, capture never raises and never blocks, and the queue is flushed on shutdown. The browser-side events are described in [DEPLOY.md → Analytics](DEPLOY.md#analytics).

**Log Analytics — what did the containers print?** The Container Apps environment ships every app's console output to one Log Analytics workspace (30-day retention), which also backs the workspace-based Application Insights resource (1 GB/day cap) — [infra/container_apps.tf](../infra/container_apps.tf), [infra/insights.tf](../infra/insights.tf). Admission decisions are logged with the client fingerprint first, which is what the log queries key on.

## File Map

```
backend/
  main.py                    FastAPI app: telemetry first, CORS, lifespan DB init
  telemetry.py               Application Insights bootstrap; isolates Langfuse on
                             its own tracer provider
  analytics.py               PostHog server-side product events (no-op without a key)
  api/
    routes.py                All endpoints; admission; workflow start with
                             in-process fallback; /api/render auth gate
    temporal_client.py       USE_TEMPORAL switch + lazy cached Temporal client
                             (the API only ever starts workflows)
    cors.py                  Allowed browser origins: fixed hosts + CORS_EXTRA_ORIGINS
    throttle.py              Sliding-window limiters, daily-cap and global-window
                             verdicts, client IP + hashed fingerprint, recent-jobs map
    turnstile.py             Server-side Cloudflare Turnstile verification: action +
                             cData bound to the paper, hostname allow-list, fails
                             closed when configured
    schemas.py               Request/response models
  temporal_app/
    workflows.py             PaperPipelineWorkflow: deterministic orchestration,
                             timeouts and retry policies, task-queue names
    activities.py            Every side effect: ingest, generate (checkpointed),
                             render + visual QA, repair, progress, finalize, failure
    worker.py                Worker entrypoint: paper-pipeline + paper-render workers
  jobs/
    worker.py                In-process fallback pipeline (FastAPI background task);
                             shared helpers: ingest-and-store, honest terminal
                             status, RENDER_CONCURRENCY parsing
  agents/
    pipeline.py              Orchestration, gate sequence, retry loop
    base.py                  Provider routing (Azure OpenAI / Dedalus),
                             Langfuse wrapper, prompt loading
    section_analyzer.py      Finds visualization-worthy concepts
    visualization_planner.py Scene-by-scene storyboards
    manim_generator.py       VoiceoverScene code generation, TTS snippet
    code_validator.py        Gate 1: static syntax/structure checks
    spatial_validator.py     Gate 2: bounds/overlap checks
    voiceover_script_validator.py  Gate 3: narration quality + LLM judge
    render_tester.py         Gate 4: dry-run construct() execution (subprocess)
    dry_run_driver.py        subprocess harness for the gate: dry_run config + TTS/add_sound stubs
    context7_docs.py         Live Manim docs fetch with static fallback
    visual_qa.py             Vision judge on sampled frames; vision-grounded repair
  ingestion/                 arXiv fetch, HTML/PDF parse, section extraction,
                             text_normalize.py (the one owner of display text)
  rendering/
    __init__.py              RENDER_MODE routing, process_visualization()
    local_runner.py          Manim subprocess + TTS env mapping
    modal_runner.py          Modal.com serverless path (unused in prod)
    storage.py               local / R2 storage backends
  models/                    Pydantic domain models
  db/                        SQLAlchemy ORM, connection, queries
  prompts/                   Agent prompt templates + Manim reference
  examples/                  Few-shot Manim examples (incl. voiceover_*)
  tests/                     Offline unit suite (run: uv run pytest tests/)
  evals/                     Golden-set LLM-quality evals + baseline regression check
  tools/                     Manual CLI scripts (real API calls; never collected by pytest)
```

`tests/`, `evals/` and `tools/` are excluded from the production image (`backend/.dockerignore`).
