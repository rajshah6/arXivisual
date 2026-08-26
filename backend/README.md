# arXivisual Backend

FastAPI backend that turns an arXiv paper ID into narrated, animated explainer videos. An agent pipeline
(Azure OpenAI, GPT-5 family) reads the paper, picks the concepts worth animating, writes Manim code with a
synced voiceover, validates it through four quality gates, renders it, and serves the videos alongside the
parsed paper. Runs in production on Azure Container Apps behind arxivisual.org.

- Full architecture walkthrough: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
- Infrastructure (Terraform, production Azure): [`../infra/README.md`](../infra/README.md)

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11–3.13. Rendering also needs a LaTeX distribution and
ffmpeg locally (`brew install --cask basictex` + `brew install ffmpeg` on macOS).

```bash
cd backend
cp .env.example .env        # then fill in your Azure OpenAI keys (see below)
uv sync --extra dev         # install everything into .venv
uv run uvicorn main:app --reload
```

The API is now at `http://localhost:8000` (interactive docs at `/docs`). Kick off a paper:

```bash
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"arxiv_id": "1706.03762"}'
# then poll:  GET /api/status/{job_id}   and finally:  GET /api/paper/1706.03762
```

## Environment

All configuration lives in `.env` — copy [`.env.example`](.env.example) and fill in the blanks. The essentials:

| Variable | Purpose |
|---|---|
| `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` | LLM provider (required). `AZURE_OPENAI_DEPLOYMENT` defaults to `gpt-5`. |
| `VOICEOVER_TTS_SERVICE` | `openai` (default — Azure OpenAI `gpt-4o-mini-tts`, no extra key) or `gtts` (free fallback). |
| `DATABASE_URL` | Postgres in production; unset = local SQLite (`./arxiviz.db`), zero setup. |
| `STORAGE_MODE` | `local` (default, videos in `./media/videos/`) or `r2` (Cloudflare R2, needs `S3_*` vars). |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Optional — enables LLM tracing/cost tracking in Langfuse. |
| `USE_TEMPORAL` | Optional — `1` routes jobs through a Temporal workflow for durable, restart-safe execution. |

## Tests and lint

```bash
uv run pytest tests/                    # unit suite — hermetic, no API keys or network needed
TEMPORAL_TESTS=1 uv run pytest tests/test_temporal_pipeline.py   # Temporal integration (downloads a local dev server)
uvx ruff check .                        # lint (hard CI gate; tree is ruff-clean)
```

CI (`.github/workflows/ci.yml`) runs the unit suite on Python 3.11 and 3.13, typechecks and builds the
frontend, and builds the backend Docker image. A blocking secret scan and a nightly LLM-quality eval run
(`evals/` — see [`evals/README.md`](evals/README.md)) round it out; deploys go to Azure via GitHub OIDC.

## How a paper becomes videos

1. **Ingest** (`ingestion/`) — fetch metadata + ar5iv HTML (PDF fallback), parse into sections, store in the DB.
2. **Analyze & plan** (`agents/section_analyzer.py`, `agents/visualization_planner.py`) — find up to 5
   visualization-worthy concepts and storyboard each one.
3. **Generate** (`agents/manim_generator.py`) — write complete Manim `VoiceoverScene` code, narration included,
   guided by few-shot examples per visualization type.
4. **Validate** — four gates with a feedback-and-regenerate loop: code structure (`code_validator`), on-screen
   layout (`spatial_validator`), narration quality (`voiceover_script_validator`), and a real import/compile
   test (`render_tester`).
5. **Render** (`rendering/local_runner.py`) — Manim subprocess renders each scene; narration is synthesized via
   Azure OpenAI TTS and cached across retries. Videos upload to Cloudflare R2 (or local disk in dev).
6. **Visual QA** (`agents/visual_qa.py`) — a vision model inspects sampled frames for overlaps/cut-offs; on the
   Temporal path, badly defective videos get one targeted repair-and-re-render pass.

Orchestration is either a durable Temporal workflow (`temporal_app/`, `USE_TEMPORAL=1` — survives restarts,
dedupes by paper, checkpoints the LLM spend) or a plain FastAPI background task (`jobs/worker.py`, the
default). The public `/api/process` endpoint is protected by per-IP and global rate limits plus duplicate-job
detection (`api/throttle.py`).

## API surface

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/process` | Start processing a paper (rate-limited, deduped) |
| GET | `/api/status/{job_id}` | Poll job progress |
| GET | `/api/paper/{arxiv_id}` | Processed paper with sections + video URLs |
| GET | `/api/papers` | List processed papers |
| GET | `/api/video/{video_id}` | Serve/redirect to a rendered video |
| POST | `/api/render` | Render raw Manim code — dev only; disabled in production without a secret |
| GET | `/api/health` | Health of DB, Manim, and storage |
