<div align="center">
    <img alt="Logo" src="frontend/public/icon.png" width=100 />
</div>
<h1 align="center">
  <a href="https://www.arxivisual.org/" target="_blank">ArXivisual</a>
</h1>
<p align="center">
   Transform research papers into visual stories
</p>

[![ArXivisual Video](frontend/public/demo.mp4)](https://github.com/user-attachments/assets/516d2217-53b9-435d-93b2-e50a6b32317e)

![ArXivisual Landing Page](frontend/public/landing.jpeg)

![ArXivisual Manim](frontend/public/manim.png)

## How It Works

1. **Ingest**: Paste any arXiv paper URL and watch as it's decomposed into digestible sections
2. **Analyze**: AI agents analyze each section to identify key concepts and visual opportunities
3. **Generate**: Multi-agent pipeline creates 3Blue1Brown-style Manim animations for complex ideas
4. **Validate**: Four-stage quality gates ensure syntactic correctness, spatial coherence, and runtime stability
5. **Experience**: Read through an interactive scrollytelling interface with embedded animated visualizations

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.11+
- FFmpeg, Cairo, Pango (for Manim)
- API keys: **Dedalus Labs** and ElevenLabs

### Backend Setup

```bash
cd backend
cp .env.example .env
# Edit .env and add your keys (see Environment Variables below)
uv sync
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Visit **http://localhost:3000** — paste an arXiv URL (e.g. `https://arxiv.org/abs/2512.24601`) and click through.

### Environment Variables (Backend)

Add these to `backend/.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `DEDALUS_API_KEY` | Yes | Dedalus Labs API key (LLM). Sign up at [dedaluslabs.ai](https://www.dedaluslabs.ai/dashboard/api-keys) |
| `ELEVEN_API_KEY` | Yes | ElevenLabs API key (voiceover) |
| `STORAGE_MODE` | No | `local` (default) or `r2` for cloud storage |
| `S3_*` | If R2 | `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_PUBLIC_URL` |

### Environment Variables (Frontend)

Optional. Create `frontend/.env.local` to override defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL |
| `NEXT_PUBLIC_USE_MOCK` | `false` | Set `true` for demo mode (no backend needed) |

## Inspiration

Research papers arrive as monoliths — dense, opaque, intimidating. Within them lies a mosaic of brilliant ideas waiting to be seen.

**ArXivisual** transforms fragments of academic text into animated visual explanations, making complex research accessible to everyone.
