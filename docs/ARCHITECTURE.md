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

`POST /api/process` creates a `ProcessingJob` row (status `queued`) and schedules `jobs/worker.py:process_paper_job` as a FastAPI background task, returning the job ID immediately. The frontend polls `GET /api/status/{job_id}`; the worker writes progress milestones as it moves through three phases:

1. **Ingest** (progress 0.10 → 0.30) — fetch and parse the paper, store paper + sections in the database. Skipped if the paper was processed before.
2. **Generate** (0.50) — run the agent pipeline to produce validated Manim code for up to 5 concepts.
3. **Render** (0.75 → 0.95) — render each visualization to MP4 and upload it, at most 3 concurrently (`asyncio.Semaphore(3)`). Each render task commits through its own DB session; a lock serializes progress updates.

**Visual QA + self-repair** (`agents/visual_qa.py`, `temporal_app/activities.py`): after each render, a vision model samples 3 frames and judges layout defects (overlap / cutoff / collisions), scoring every verdict into Langfuse (`visual_qa_defect`). On the Temporal path, a `major` verdict triggers one **vision-grounded repair**: the video is read back through the storage backend (never the CDN — stable keys cache for a year), the defect frames plus the judge's issues go to a multimodal model, and the repaired code is re-rendered and re-judged. Every vision-failure mode falls back to a text-only repair; an unusable repair keeps the original video. Measured in production: text-only repair fixed 0/6 flagged videos; vision-grounded fixed 2/4 in its first run — the pixels carry information the text descriptions provably don't.

**Terminal status is honest** (`resolve_terminal_job_status` in `jobs/worker.py`): a job is `completed` only if at least one visualization actually rendered. Zero generated or all-failed renders mark the job `failed` with an explanatory error, while the parsed paper text remains readable. Individual render failures are recorded per visualization and don't sink the job.

## Ingestion (`backend/ingestion/`)

`ingest_paper(arxiv_id)` fetches metadata from the arXiv API, then parses content — ar5iv HTML when available (clean headings, equations, figure captions), PDF via pymupdf4llm otherwise. Sections are extracted with heading levels and per-section equations/figures/tables, noise sections (references, acknowledgments, etc.) are dropped, and an LLM summarization pass produces per-section summaries. Output is a `StructuredPaper` (Pydantic), persisted to the `papers` and `sections` tables.

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
- **RenderTester** (`render_tester.py`) — the only gate that executes the code: `compile()` for syntax in-process, then **full `construct()` execution in a dry-run subprocess** (`dry_run_driver.py`): manim's `dry_run` config processes every animation without writing frames, TTS is replaced by an embedded silent MP3 (manim-voiceover has no dry-run support and would otherwise call the real service), `add_sound` is a no-op (drops the ffmpeg dependency), and subcaptions are disabled (under dry_run `config.output_file` is an empty string, so their writer raises at finish()). ~0.2s per scene, no network, no spend. This catches the runtime class import testing structurally can't — a production render died on `if a.get_center() == b.get_center():` (numpy truth-value `ValueError`) that only fires when `construct()` runs. Verdicts come from stdout sentinels; a driver crash without a verdict fails OPEN (the real render still guards, and a gate must never block all videos on its own infrastructure). `RENDER_TEST_EXECUTE=0` falls back to legacy import-only validation; `RENDER_TEST_TIMEOUT_SECONDS` (60) bounds it.

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

A Dedalus Labs provider remains selectable as a legacy fallback (`DEDALUS_API_KEY`). Historical footnote: `agents/dedalus_base.py` (multi-model handoff chains) and `agents/voiceover_generator.py` (a post-hoc voiceover transform, superseded by unified generation and disabled by default) are legacy code from that era, slated for removal.

## Voiceover / TTS

Narration audio is produced **at render time** by manim-voiceover. The generator injects the service setup verbatim into each scene:

```python
self.set_speech_service(OpenAIService(voice="nova", model="gpt-4o-mini-tts", transcription_model=None))
```

`VOICEOVER_TTS_SERVICE` defaults to `openai`; voice and model come from `VOICEOVER_VOICE_NAME` / `VOICEOVER_TTS_MODEL`. There is no separate OpenAI key: the render subprocess environment (`rendering/local_runner.py:_tts_subprocess_env`) maps `AZURE_OPENAI_*` to `OPENAI_API_KEY`/`OPENAI_BASE_URL` (pinning `OPENAI_API_TYPE=openai`), so manim-voiceover's `OpenAIService` transparently talks to an Azure `gpt-4o-mini-tts` deployment. A real `OPENAI_API_KEY`, if set, takes precedence. `VOICEOVER_TTS_SERVICE=gtts` is the free, keyless fallback.

## Rendering (`backend/rendering/`)

`RENDER_MODE=local` (the production setting) renders in-process on the API container: the code is written to a temp directory and `manim render <file> <SceneName> -ql --format=mp4` runs via `subprocess.run` with a 300 s timeout, wrapped in `asyncio.to_thread`. Quality maps to Manim's `-ql`/`-qm`/`-qh`; the pipeline renders at `low_quality`. The worker's `Semaphore(3)` bounds concurrent renders. A `RENDER_MODE=modal` path (serverless rendering on Modal.com via `modal_runner.py`) exists and also disables the local RenderTester gate, but is not used in production.

## Storage (`rendering/storage.py`)

`STORAGE_MODE` selects a backend behind one protocol:

- `local` (default) — MP4s under `media/videos/`, served by `GET /api/video/{id}` as a `FileResponse`.
- `r2` (production) — uploads to Cloudflare R2 (S3-compatible, `boto3`) under a `videos/` prefix with a one-year immutable cache header and one retry; `video_url` becomes a public `S3_PUBLIC_URL` link. `GET /api/video/{id}` 302-redirects to it.

## API Surface (`backend/api/routes.py`)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/process` | Start processing a paper; returns a job ID |
| GET | `/api/status/{job_id}` | Poll job progress |
| GET | `/api/paper/{arxiv_id}` | Processed paper: sections + visualizations with video URLs |
| GET | `/api/papers` | Explore gallery: all processed papers |
| GET | `/api/video/{video_id}` | Serve or redirect to a rendered video |
| POST | `/api/render` | Dev-only raw Manim render — in production, 404 unless `RENDER_API_SECRET` is configured and presented via `X-Render-Secret` (timing-safe compare) |
| GET | `/api/health` | Database / Manim / storage health |

CORS allows `arxivisual.org`, this project's Vercel preview deployments, and localhost dev.

## Persistence (`backend/db/`)

SQLAlchemy async ORM, four tables keyed off the arXiv ID: `papers`, `sections` (content, summary, equations/figures/tables as JSON), `visualizations` (concept, storyboard, Manim code, video URL, status), and `processing_jobs`. `DATABASE_URL` selects Postgres (asyncpg, used in production); unset falls back to local SQLite (aiosqlite).

## Observability (Langfuse)

Tracing activates when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are both set, and degrades to no-ops otherwise:

- `base.py` swaps the OpenAI SDK for the `langfuse.openai` drop-in, so every LLM call is captured with model, tokens, cost, and latency; each generation is named after its agent's prompt file (e.g. `manim_generator`).
- `@observe` spans build the trace hierarchy: `process-paper` → `generate-visualizations` → `generate-single-visualization`, with `session_id = job_id` grouping everything for one paper run.
- The worker flushes traces before the background task exits, since it runs off-request.

`LANGFUSE_TRACING_ENVIRONMENT` separates production traces from development.

## File Map

```
backend/
  main.py                    FastAPI app: CORS, lifespan DB init
  api/
    routes.py                All endpoints; /api/render auth gate
    schemas.py               Request/response models
  jobs/
    worker.py                Background job: ingest -> generate -> render;
                             honest terminal status
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
    dedalus_base.py          LEGACY (slated for removal)
    voiceover_generator.py   LEGACY post-transform voiceover (disabled)
  ingestion/                 arXiv fetch, HTML/PDF parse, section extraction
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
```
