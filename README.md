<div align="center">
    <img alt="Logo" src="frontend/public/icon.png" width=100 />
</div>
<h1 align="center">
  <a href="https://www.arxivisual.org/" target="_blank">arXivisual</a>
</h1>
<p align="center">
   Transform research papers into visual stories
</p>

[![arXivisual Video](frontend/public/arXivisual.mp4)](https://github.com/user-attachments/assets/5453760b-5f82-4fd1-9a77-fe8818fea059)

![arXivisual Landing Page](frontend/public/landing.jpeg)

![arXivisual Manim](frontend/public/manim.png)

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
- API keys for Dedalus Labs (or any Anthropic provider)

### Frontend Setup

```bash
cd frontend
```
```bash
npm install
```
```bash
npm run dev
```

### Backend Setup

```bash
cd backend
```
```bash
cp .env.example .env          # Add your API keys
```
```bash
uv sync
```
```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Inspiration

Research papers arrive as monoliths — dense, opaque, intimidating. Within them lies a mosaic of brilliant ideas waiting to be seen.

**arXivisual** transforms fragments of academic text into animated visual explanations, making complex research accessible to everyone.
