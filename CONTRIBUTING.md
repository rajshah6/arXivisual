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

**Frontend** (Node 18+):

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
npm run lint                  # advisory (see below)
npm run build
```

## CI Expectations

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every PR. To merge:

- **Backend tests must pass** on Python 3.11 and 3.13. The suite runs offline against dummy credentials — new tests must not hit real APIs.
- **Frontend typecheck and build must pass** (`tsc --noEmit`, `next build`).
- **Lint is advisory** for now (`continue-on-error`) while pre-existing violations on `main` are worked off — don't add new ones.
- **The Docker image must build** when you touch `backend/Dockerfile`, `backend/pyproject.toml`, or `backend/uv.lock`. If you change dependencies, run `uv lock` and commit the lockfile; CI installs with `--frozen` and fails on a stale lock.

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
