# Contributing to arXivisual

Thanks for your interest in contributing. This is a short guide to getting a change from your machine into `main`.

## Development Setup

**Backend** (Python 3.11+, managed with [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
cp .env.example .env          # fill in Azure OpenAI keys for online work
uv sync --extra dev
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Manim needs FFmpeg, Cairo, and Pango installed locally (plus LaTeX for `MathTex` scenes), but the unit tests never render — you can develop against the test suite without them.

**Frontend** (Node 20.9+):

```bash
cd frontend
npm install
npm run dev
```

See [backend/.env.example](backend/.env.example) for every configuration option and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pipeline fits together.

## Running Tests

```bash
cd backend
uv run pytest tests/          # offline — no API keys or network needed
```

Frontend checks:

```bash
cd frontend
npx tsc --noEmit              # typecheck
npm run lint                  # hard CI gate
npm run build
```

## CI Expectations

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every PR. To merge:

- **Backend tests must pass** on Python 3.11 and 3.13. The suite runs offline against dummy credentials — new tests must not hit real APIs.
- **Frontend typecheck, lint and build must pass** (`tsc --noEmit`, `eslint`, `next build`). Both lint steps (ruff, eslint) are hard gates; the trees are lint-clean.
- **The Docker images must build.** Backend: when you touch `backend/Dockerfile`, `backend/pyproject.toml`, or `backend/uv.lock` (run `uv lock` after dependency changes; CI installs with `--frozen`). Frontend: when you touch `frontend/Dockerfile`, `.dockerignore`, `package*.json`, or `next.config.ts` (CI runs `npm ci`, which fails on a stale lockfile).

## Branches and Pull Requests

- Branch from `main` with a short descriptive name (e.g. `explore-gallery`, `security-hardening`); open a PR back to `main`.
- PRs need green CI and a review. Automated code-review bots comment on PRs — address or explicitly rebut their findings rather than ignoring them.
- Keep PRs focused; stack dependent branches as separate PRs rather than batching unrelated changes. If you do stack, retarget child PRs to `main` before merging the parent.

## Commit Style

Conventional-ish prefixes, matching the existing history:

```
feat: add Explore gallery of processed papers
fix: enforce narration word-count rule in voiceover validator
chore: gitignore .claude/ local agent state
ci: install pango/cairo build deps for the backend job
perf: cache TTS audio between renders
```

Use `feat:` / `fix:` / `chore:` / `ci:` / `perf:` with an imperative, lower-case summary.
