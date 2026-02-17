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
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ────────────────────────────────────
FROM base AS deps

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (better layer caching)
COPY pyproject.toml ./
COPY manimations/pyproject.toml ./manimations/pyproject.toml

# Create venv and install all deps via uv sync
RUN uv venv /app/.venv && \
    uv sync --python /app/.venv/bin/python --no-dev --frozen 2>/dev/null || \
    uv pip install --python /app/.venv/bin/python \
        "fastapi>=0.109.0" "uvicorn>=0.27.0" "anthropic>=0.18.0" \
        "pydantic>=2.0.0" "python-dotenv>=0.21.1,<0.22.0" \
        "httpx>=0.25.0" "asyncio-throttle>=1.0.0" \
        "sqlalchemy>=2.0.0" "aiosqlite>=0.19.0" "asyncpg>=0.29.0" "greenlet>=3.0.0" \
        "arxiv>=2.0.0" "pymupdf4llm>=0.0.5" "pymupdf>=1.23.0" \
        "beautifulsoup4>=4.12.0" "lxml>=5.0.0" \
        "manim>=0.18.0" "manim-voiceover[elevenlabs]>=0.3.0" \
        "boto3>=1.34.0" "openai>=1.12.0" "setuptools>=65.0.0" \
        "dedalus-labs>=0.2.0" "python-multipart>=0.0.6"

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
