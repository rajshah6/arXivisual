# ── arXivisual Backend ──────────────────────────────────────
# Multi-stage build: system deps + Python deps + app code
# Optimized for Render deployment with Manim rendering
# ────────────────────────────────────────────────────────────

FROM python:3.13-slim AS base

# System packages required by Manim, ffmpeg, cairo, pango, sox, LaTeX
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libcairo2-dev \
    libpango1.0-dev \
    pkg-config \
    sox \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    texlive-fonts-extra \
    cm-super \
    dvipng \
    dvisvgm \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ────────────────────────────────────
FROM base AS deps

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (better layer caching)
COPY pyproject.toml uv.lock ./

# Create venv and install the exact locked dependency set. This must fail the
# build if uv.lock is missing or out of sync — a silent fallback to a
# hand-maintained pip list previously shipped an incomplete/stale dependency
# set (missing alembic/redis/modal, broken manim) that only surfaced at runtime.
RUN uv venv /app/.venv && \
    uv sync --python /app/.venv/bin/python --no-dev --frozen

# ── Application ────────────────────────────────────────────
FROM base AS runtime

WORKDIR /app

# Copy venv from deps stage
COPY --from=deps /app/.venv /app/.venv

# Add venv to PATH so manim, uvicorn, etc. are available
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Copy application code
COPY . .

# Create media directory (will be overridden by persistent disk mount)
RUN mkdir -p /app/media/videos

# Default port (overridden by Render's PORT env var)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:8000/api/health'); r.raise_for_status()" || exit 1

# Start the server
# Render sets PORT automatically; we read it via the shell expansion
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
