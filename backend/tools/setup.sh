#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# ArXivisual Backend — One-Shot Setup
# Run: cd backend && bash tools/setup.sh
#
# NOTE: We use Text() instead of MathTex() in all Manim scenes
# so LaTeX/BasicTeX is NOT required. This keeps setup simple.
# ═══════════════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${GREEN}▸ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }

echo "═══════════════════════════════════════════════════"
echo "  ArXivisual Backend Setup"
echo "═══════════════════════════════════════════════════"

# ── 1. Homebrew dependencies ──────────────────────────
step "Installing Homebrew dependencies (ffmpeg, cairo, pango)..."
brew install ffmpeg cairo pango 2>/dev/null || true

# ── 2. Python environment ───────────────────────────
step "Setting up Python 3.13 + uv..."
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# Pin Python 3.13 (3.14 breaks pkg_resources needed by manim-voiceover)
echo "3.13" > .python-version

UV_HTTP_TIMEOUT=120 uv sync 2>&1
uv pip install setuptools 2>&1      # needed for manim-voiceover pkg_resources
uv pip install python-multipart 2>&1 # needed for FastAPI file uploads

# ── 3. .env file ────────────────────────────────────
step "Checking .env file..."
if [ ! -f .env ]; then
    cat > .env << 'ENVEOF'
# Dedalus API (required for all LLM calls)
DEDALUS_API_KEY=your-key-here

# ElevenLabs TTS (for voiceover generation)
ELEVEN_API_KEY=your-key-here

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
ENVEOF
    warn "Created .env with placeholders — edit it with your real API keys!"
else
    echo "  .env already exists"
fi

# ── 4. Verify everything ───────────────────────────
step "Verifying installation..."
echo ""

check() {
    if $1 &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $2"
    else
        echo -e "  ${RED}✗${NC} $2"
    fi
}

check "command -v ffmpeg"    "ffmpeg"
check "command -v uv"        "uv (package manager)"
check "uv run python -c 'import manim'" "manim (Python)"
check "uv run python -c 'import fastapi'" "fastapi (Python)"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Setup complete! Next steps:"
echo ""
echo "  1. Edit .env with your API keys (if needed)"
echo "  2. Test Manim render:"
echo "     uv run manim -ql demo_scenes/scaled_dot_product_attention.py ScaledDotProductAttention"
echo "  3. Start the server:"
echo "     uv run uvicorn main:app --reload --port 8000"
echo "═══════════════════════════════════════════════════"
