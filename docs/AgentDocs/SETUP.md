# ArXiviz Development Setup Guide

## Current State (team2 branch)

Only the **backend** (Team 2 AI pipeline) is built. There is no frontend, no database, no Docker setup yet. Everything runs locally with `uv`.

---

## Prerequisites

- **Python 3.11+** (tested with 3.13 and 3.14)
- **[uv](https://docs.astral.sh/uv/)** - Fast Python package manager
- **LaTeX** (for Manim rendering) - BasicTeX or TeX Live
- **An API key** - Martian (recommended) or Anthropic

### Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with Homebrew
brew install uv
```

### Install LaTeX (for rendering Manim videos)

```bash
# macOS (BasicTeX - minimal, ~100MB)
brew install --cask basictex
sudo tlmgr update --self
sudo tlmgr install standalone preview dvisvgm

# Or full TeX Live (~4GB, everything included)
brew install --cask mactex
```

LaTeX is only needed if you want to render the generated `.py` files into video. The pipeline itself (code generation + validation) does not require LaTeX.

---

## Setup Steps

### 1. Enter the project and switch to the team2 branch

```bash
cd "New project"
git checkout team2
```

### 2. Set up API keys

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env`:

```env
# REQUIRED:
DEDALUS_API_KEY=dsk-your-dedalus-key-here

# REQUIRED - For AI voiceovers:
ELEVEN_API_KEY=your-elevenlabs-key-here       # From elevenlabs.io (free tier works)
```

**Where to get keys:**

| Key | Sign Up | Notes |
|-----|---------|-------|
| Dedalus | [dedaluslabs.ai](https://www.dedaluslabs.ai/dashboard/api-keys) | Required LLM provider for this project |
| ElevenLabs | [elevenlabs.io](https://elevenlabs.io) | Free tier: 10k characters/month; enough for ~5-10 visualizations |

### 3. Install dependencies

```bash
cd backend
uv sync
```

This creates a `.venv/`, resolves all dependencies, and installs them. You never need to manually activate the venv - `uv run` handles it.

### 4. Verify setup (offline tests)

```bash
cd backend
uv run python tools/test_pipeline.py
```

Expected output:
```
============================================================
Running OFFLINE tests (no API key required)
============================================================
...
All offline tests passed!
============================================================
```

### 5. Run the full pipeline

```bash
cd backend
uv run python tools/run_demo.py
```

This takes ~60-90 seconds (uses Claude Opus 4.5) and generates Manim `.py` files in `backend/generated_output/`.

### 6. Render a video (optional)

```bash
# Quick preview (480p)
cd backend
uv run python tools/run_demo.py --render --quality low

# Or render manually
cd generated_output
uv run manim -ql filename.py
```

---

## All Commands Reference

```bash
# Always run from backend/ directory

# ─── Setup ────────────────────────────────────
uv sync                                            # Install/update dependencies

# ─── Offline Tests (no API key needed) ────────
uv run python tools/test_pipeline.py                     # Test models + code validator

# ─── Online Tests (need API key in .env) ──────
uv run python tools/test_pipeline.py --online                     # All agents + pipeline
uv run python tools/test_pipeline.py --online --test analyzer     # Just section analyzer
uv run python tools/test_pipeline.py --online --test planner      # Just visualization planner
uv run python tools/test_pipeline.py --online --test generator    # Just Manim generator
uv run python tools/test_pipeline.py --online --test pipeline     # Full pipeline (1 viz)

# ─── Demo Runner ──────────────────────────────
uv run python tools/run_demo.py                          # Generate 2 visualizations
uv run python tools/run_demo.py --max 3                  # Generate up to 3
uv run python tools/run_demo.py --verbose                # Show detailed agent logs
uv run python tools/run_demo.py --render                 # Generate + render to video
uv run python tools/run_demo.py --render --quality low   # Render at 480p (fastest)
uv run python tools/run_demo.py --render --quality high  # Render at 1080p

# ─── Manual Rendering ─────────────────────────
cd generated_output
uv run manim -ql filename.py                       # 480p preview
uv run manim -qm filename.py                       # 720p
uv run manim -qh filename.py                       # 1080p
```

---

## Troubleshooting

### "No API key found"
- Make sure `.env` exists in `backend/` (not the project root)
- Make sure the key value is not still the placeholder from `.env.example`

### "uv: command not found"
- Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Restart your terminal after installing

### "Module not found" errors
- Run `uv sync` in the `backend/` directory
- Always use `uv run python ...` not bare `python ...`

### Manim render fails with LaTeX errors
- Install BasicTeX: `brew install --cask basictex`
- Install required packages: `sudo tlmgr install standalone preview dvisvgm`
- Or avoid LaTeX by using `Text()` instead of `MathTex()` in examples

### Pipeline generates 0 visualizations
- Run with `--verbose` to see detailed logs
- Test individual agents: `uv run python tools/test_pipeline.py --online --test analyzer`
- Check the logs for which validation stage is failing

### ElevenLabs voiceover fails
- Check `ELEVEN_API_KEY` is set in `.env`
- Check your usage at elevenlabs.io (free tier has character limits)
- Pipeline will still work without voiceovers (graceful degradation)

---

## Future Setup (when other teams are ready)

When Team 1 (ingestion) and Team 3 (rendering/frontend) are built, additional setup will include:
- **Frontend**: Next.js with `npm install` and `npm run dev`
- **Database**: PostgreSQL for caching paper data and video metadata
- **Redis**: Job queue for async processing
- **Modal.com**: Cloud rendering of Manim videos
- **S3/R2**: Video file storage

For now, everything runs locally through the `uv run` commands above.
