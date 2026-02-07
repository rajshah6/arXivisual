# ArXivisual

**Turn any arXiv paper into 3Blue1Brown-style animated explainer videos — fully AI-generated with voiceover.**

ArXivisual is a multi-agent AI system that ingests academic papers from arXiv, identifies key concepts, and generates [Manim](https://www.manim.community/) animations with synchronized ElevenLabs narration. The frontend presents papers as interactive scrollytelling experiences with embedded video explainers.

```
arxiv.org/abs/1706.03762  →  AI Agent Pipeline  →  Animated Explainer Videos
       (paper)               (Claude Opus 4.5)      (Manim + ElevenLabs TTS)
```

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Running the Pipeline](#running-the-pipeline)
- [Frontend](#frontend)
- [Backend](#backend)
  - [AI Agent Pipeline](#ai-agent-pipeline)
  - [Paper Ingestion](#paper-ingestion)
  - [Voiceover & Narration](#voiceover--narration)
  - [Validation Pipeline](#validation-pipeline)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Key Design Decisions](#key-design-decisions)
- [Recent Changes](#recent-changes)

---

## How It Works

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         ArXivisual Pipeline Flow                             │
│                                                                              │
│   arXiv Paper (ID or URL)                                                   │
│         │                                                                    │
│         ▼                                                                    │
│   ┌─────────────────┐                                                        │
│   │   Ingestion      │   Fetch from arXiv API → Parse HTML/PDF              │
│   │   Pipeline       │   → Extract sections, equations, metadata             │
│   └────────┬────────┘   → LLM-format each section (Claude Sonnet)           │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐   Claude Opus reads each section and decides:         │
│   │ SectionAnalyzer  │   "Does this concept need a visual explanation?"      │
│   └────────┬────────┘   Outputs: VisualizationCandidate[] (ranked)          │
│            │                                                                 │
│            ▼                                                                 │
│   ┌──────────────────┐   Claude Opus creates scene-by-scene storyboards:    │
│   │ Visualization     │   "Beat 1: Title. Beat 2: Show Q,K,V matrices..."   │
│   │ Planner           │   Outputs: VisualizationPlan with 4-6 scenes        │
│   └────────┬─────────┘                                                       │
│            │                                                                 │
│            ▼                                                                 │
│   ┌──────────────────┐   Claude Opus writes Manim Python code with          │
│   │ ManimGenerator   │   ElevenLabs voiceover blocks embedded.              │
│   │ + Context7 Docs  │   Uses Dedalus SDK to fetch live Manim docs.         │
│   └────────┬─────────┘   Outputs: Complete .py file with narration          │
│            │                                                                 │
│            ▼                                                                 │
│   ┌────────────────────────────────────────────────┐                        │
│   │         4-Stage Validation (retries up to 5x)   │                        │
│   │  [1] CodeValidator       → syntax, imports, AST  │                       │
│   │  [2] SpatialValidator    → positioning, overlaps  │                      │
│   │  [3] VoiceoverValidator  → narration quality      │                      │
│   │  [4] RenderTester        → runtime import test    │                      │
│   │      ↳ Failures → feedback → ManimGenerator       │                      │
│   └────────┬───────────────────────────────────────┘                        │
│            │                                                                 │
│            ▼                                                                 │
│   ┌──────────────────┐   Render with Manim → .mp4 with synced voiceover    │
│   │  Final Videos     │   ElevenLabs TTS (eleven_flash_v2_5 model)          │
│   └──────────────────┘   480p/720p/1080p output                             │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  Frontend (Next.js 16)              Backend (FastAPI)               │
│  ├── App Router                     ├── REST API (/api/...)         │
│  ├── React 19                       ├── AI Agent Pipeline           │
│  ├── Tailwind CSS v4                │   └── Claude Opus 4.5         │
│  │   (Mosaic Fragments theme)       │       via Martian proxy       │
│  ├── Framer Motion 12               ├── Paper Ingestion             │
│  ├── React Query                    │   └── arXiv + HTML/PDF parse  │
│  ├── KaTeX (LaTeX rendering)        ├── Manim Rendering             │
│  └── Scrollytelling UI              │   └── ElevenLabs voiceover    │
│                                     ├── Dedalus SDK + Context7      │
│                                     │   └── Live Manim docs (MCP)   │
│                                     └── SQLite Database              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | Next.js 16, React 19, Tailwind v4 | Interactive paper viewer |
| **UI Theme** | Mosaic Fragments (glass-on-black) | Monochrome glassmorphism design |
| **Animations** | Framer Motion 12.31 | UI transitions and effects |
| **LaTeX** | KaTeX + remark-math | Equation rendering in browser |
| **Backend** | FastAPI + Python 3.11+ | REST API and pipeline orchestration |
| **AI Model** | Claude Opus 4.5 via Martian | Code generation, analysis, planning |
| **Live Docs** | Dedalus SDK + Context7 MCP | Real-time Manim documentation retrieval |
| **Animation** | Manim Community Edition | 3Blue1Brown-style math animations |
| **Voiceover** | ElevenLabs (`eleven_flash_v2_5`) | AI text-to-speech narration |
| **TTS Sync** | manim-voiceover | Synchronize audio with animation |
| **Ingestion** | arxiv API + pymupdf4llm + BeautifulSoup | Paper fetching and parsing |
| **Database** | SQLAlchemy + SQLite/PostgreSQL | Paper metadata and job tracking |
| **Package Mgr** | uv (backend), npm (frontend) | Dependency management |

---

## Quick Start

### Prerequisites

- **Python 3.11+** (tested with 3.13/3.14)
- **Node.js 18+** (for frontend)
- **[uv](https://docs.astral.sh/uv/)** — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **LaTeX** — `brew install texlive` (macOS) for Manim's MathTex rendering
- **ffmpeg** — `brew install ffmpeg` (macOS) for video encoding

### 1. Clone and set up

```bash
git clone <repo-url> arXivisual
cd arXivisual
```

### 2. Backend setup

```bash
cd backend
cp .env.example .env
# Edit .env with your API keys (see Configuration section)
uv sync
```

### 3. Frontend setup

```bash
cd frontend
npm install
```

### 4. Run the demo pipeline

```bash
cd backend
uv run python run_demo.py --render --quality low --max 5
```

### 5. Start the frontend

```bash
cd frontend
npm run dev
# Open http://localhost:3000
```

### 6. Start the API server

```bash
cd backend
uvicorn main:app --reload --port 8000
```

---

## Running the Pipeline

All commands run from `backend/`:

```bash
# Generate visualizations (curated 5-section Attention paper)
uv run python run_demo.py                              # Generate 2 (default)
uv run python run_demo.py --max 5                      # Generate up to 5
uv run python run_demo.py --max 5 --verbose            # With detailed logs

# Generate AND render videos
uv run python run_demo.py --render --quality low        # 480p (fastest)
uv run python run_demo.py --render --quality medium     # 720p
uv run python run_demo.py --render --quality high       # 1080p

# Manual rendering of generated code
cd generated_output
uv run manim -ql filename.py                            # 480p
uv run manim -qm filename.py --disable_caching          # 720p with voiceover

# Run tests
uv run python test_pipeline.py                          # Offline tests
uv run python test_pipeline.py --online                 # Full pipeline test

# Start API server
uvicorn main:app --reload --port 8000
```

### Output

Generated files go to `backend/generated_output/`:
- `.py` files — Complete Manim code with voiceover
- `MANIFEST.txt` — Summary of generated visualizations
- `media/videos/` — Rendered .mp4 files

---

## Frontend

### Mosaic Fragments Design System

The frontend uses a custom **Mosaic Fragments** theme — a monochrome glass-on-black aesthetic:

| Token | Value | Usage |
|-------|-------|-------|
| Background | `#000000` | Page background |
| Card bg | `bg-white/[0.04]` | Glass card fill |
| Card border | `border-white/[0.08]` | Default borders |
| Hover border | `border-white/[0.14]` | Interactive state |
| Primary text | `text-white/90` | Headings |
| Body text | `text-white/55` | Paragraphs |
| Muted text | `text-white/30` | Secondary info |
| Success | `#7dd19b` | Positive states |
| Error | `#f27066` | Error states |

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Glass Shard | `components/ui/glass-shard.tsx` | Floating glass fragments with CSS clip-path |
| Mosaic Background | `components/ui/mosaic-background.tsx` | SVG tessellation background |
| Glass Card | `components/ui/glass-card.tsx` | Reusable glass container with spotlight |
| ScrollyReader | `components/ScrollyReader.tsx` | Scrollytelling paper reader |
| VideoPlayer | `components/VideoPlayer.tsx` | Embedded video player |
| PaperHeader | `components/PaperHeader.tsx` | Paper metadata display |
| MarkdownContent | `components/MarkdownContent.tsx` | Markdown + LaTeX rendering |
| Floating Dock | `components/ui/floating-dock.tsx` | Navigation dock |

### Pages

- `/` — Home page with paper search
- `/abs/[...id]` — Paper detail view with sections and embedded videos

---

## Backend

### AI Agent Pipeline

The pipeline uses **Claude Opus 4.5** via the Martian API proxy. Each agent has a dedicated prompt template in `backend/prompts/`.

#### Agent 1: SectionAnalyzer

Reads each section and identifies concepts that need visualization.

- Skips: references, bibliography, acknowledgments
- Prioritizes: attention mechanisms, architectures, equations, algorithms
- Output: Ranked `VisualizationCandidate[]` with concept names and types

#### Agent 2: VisualizationPlanner

Creates scene-by-scene storyboards for each candidate.

- Plans 4-6 scenes per visualization
- Sets target duration (~42 seconds)
- Defines animation elements and transitions per scene

#### Agent 3: ManimGenerator

Writes complete, runnable Manim Python code.

- Fetches live Manim docs via **Dedalus SDK + Context7 MCP** before generating
- Selects few-shot examples matched to visualization type (architecture, data_flow, equation, etc.)
- Generates voiceover narration blocks inline with animation code
- Narration style: **friendly tutor** — approachable language a high schooler can follow, still technically accurate

#### Agent 4: VoiceoverScriptValidator

LLM judge that scores narration quality.

- **Alignment score**: Does narration match the concept and planned beats?
- **Educational score**: Is it clear, friendly, and concept-focused?
- **Banned starts**: Narration must not begin with animation commands (show, display, fade, etc.)
- Thresholds: 0.70 for both scores (lenient to avoid unnecessary retries)

### Paper Ingestion

The ingestion pipeline (`backend/ingestion/`) handles fetching and parsing arXiv papers:

| File | Purpose |
|------|---------|
| `arxiv_fetcher.py` | Fetches papers from arXiv API by ID |
| `html_parser.py` | Parses ar5iv HTML version for better section extraction |
| `pdf_parser.py` | Parses PDF using pymupdf4llm (fallback) |
| `section_extractor.py` | Extracts markdown sections from parsed content |
| `section_formatter.py` | LLM-formats each section via Claude Sonnet for clean summaries |

The pipeline also supports a **curated paper mode** (`create_attention_paper()` in `run_demo.py`) with 5 hand-crafted sections from "Attention Is All You Need" designed to reliably produce high-quality visualizations.

### Voiceover & Narration

Voiceover is generated inline by the ManimGenerator (unified mode):

- **TTS Engine**: ElevenLabs (`eleven_flash_v2_5` model)
- **Voice**: Custom voice ID `2fe8mwpfJcqvj9RGBsC1`
- **Style**: Friendly tutor — explains concepts in approachable language
- **Sync**: Each `self.play()` inside a `with self.voiceover(text="...") as tracker:` block syncs animation duration to speech
- **Fallback**: gTTS (free) if ElevenLabs is unavailable

### Validation Pipeline

Every generated visualization goes through 4 validation stages (up to 5 retry attempts):

| Stage | Validator | What It Checks |
|-------|-----------|----------------|
| 1 | CodeValidator | Python syntax (AST), manim imports, Scene class, construct method. Auto-fixes common typos. |
| 2 | SpatialValidator | Element positioning (x: [-6,6], y: [-3.5,3.5]), overlapping, missing `buff` params |
| 3 | VoiceoverScriptValidator | Narration quality (LLM judge), banned animation-command starts, score thresholds |
| 4 | RenderTester | Runtime import test — actually loads the code as a Python module (30s timeout) |

If any stage fails, the error feedback is passed back to the ManimGenerator for a retry with context about what went wrong.

### Dedalus SDK + Context7 MCP

Before generating Manim code, the pipeline fetches **live documentation** from the Manim Community Edition docs:

1. **Dedalus SDK** (`context7_docs.py`) calls the Dedalus API with `mcp_servers=["tsion/context7"]`
2. **Context7 MCP** resolves the library and returns relevant documentation snippets
3. Documentation is injected into the generator prompt so Claude has up-to-date API knowledge
4. **Fallback**: If Context7 is unavailable, uses the static `manim_reference.md` system prompt

---

## Project Structure

```
arXivisual/
├── README.md                         ← You are here
├── QUICKSTART.md                     # Quick start guide
├── HACKATHON_PLAN.md                 # Hackathon planning
├── AgentDocs/                        # Architecture documentation
│
├── frontend/                         # Next.js 16 application
│   ├── app/                          # App Router pages
│   │   ├── layout.tsx                # Root layout (Mosaic Fragments)
│   │   ├── page.tsx                  # Home / search page
│   │   └── abs/[...id]/             # Paper detail view
│   │       ├── page.tsx
│   │       └── loading.tsx
│   ├── components/                   # React components
│   │   ├── ScrollyReader.tsx         # Scrollytelling reader
│   │   ├── VideoPlayer.tsx           # Video player
│   │   ├── PaperHeader.tsx           # Paper metadata
│   │   ├── MarkdownContent.tsx       # Markdown + LaTeX
│   │   └── ui/                       # Design system components
│   │       ├── glass-shard.tsx       # Glass shard effect
│   │       ├── glass-card.tsx        # Glass container
│   │       └── mosaic-background.tsx # SVG tessellation
│   ├── hooks/                        # React hooks
│   ├── lib/                          # Utils, API client, types
│   ├── package.json
│   └── tsconfig.json
│
├── backend/                          # FastAPI + AI pipeline
│   ├── main.py                       # FastAPI entry point
│   ├── run_demo.py                   # Demo pipeline runner
│   ├── pyproject.toml                # Python deps (uv)
│   ├── .env / .env.example           # API keys
│   │
│   ├── agents/                       # AI agents
│   │   ├── base.py                   # Base class (Anthropic client, Martian proxy)
│   │   ├── pipeline.py               # Orchestrator
│   │   ├── section_analyzer.py       # Identifies visualizable concepts
│   │   ├── visualization_planner.py  # Creates storyboards
│   │   ├── manim_generator.py        # Generates Manim code + voiceover
│   │   ├── voiceover_generator.py    # Legacy voiceover transformer
│   │   ├── voiceover_script_validator.py  # Narration quality judge
│   │   ├── code_validator.py         # AST syntax validation
│   │   ├── spatial_validator.py      # Positioning validation
│   │   ├── render_tester.py          # Runtime import test
│   │   └── context7_docs.py          # Dedalus + Context7 live docs
│   │
│   ├── models/                       # Pydantic data models
│   │   ├── paper.py                  # StructuredPaper, Section, Equation
│   │   ├── generation.py             # Candidate, Plan, Code, Visualization
│   │   ├── voiceover.py              # Voiceover validation output
│   │   └── spatial.py                # Spatial validation models
│   │
│   ├── prompts/                      # Claude prompt templates
│   │   ├── section_analyzer.md
│   │   ├── visualization_planner.md
│   │   ├── manim_generator.md        # Main generation prompt
│   │   ├── voiceover_generator.md
│   │   └── system/
│   │       └── manim_reference.md    # Manim API reference
│   │
│   ├── ingestion/                    # Paper ingestion pipeline
│   │   ├── arxiv_fetcher.py          # arXiv API client
│   │   ├── html_parser.py            # ar5iv HTML parser
│   │   ├── pdf_parser.py             # PDF parser (pymupdf4llm)
│   │   ├── section_extractor.py      # Section extraction
│   │   └── section_formatter.py      # LLM section formatting
│   │
│   ├── api/                          # REST API
│   │   ├── routes.py                 # Endpoints
│   │   └── schemas.py                # Request/response models
│   │
│   ├── db/                           # Database
│   │   ├── models.py                 # SQLAlchemy ORM
│   │   ├── connection.py             # Engine setup
│   │   └── queries.py                # Common queries
│   │
│   ├── rendering/                    # Video rendering
│   │   ├── local_runner.py           # Local Manim execution
│   │   ├── modal_runner.py           # Modal.com serverless
│   │   └── storage.py                # S3/R2 video storage
│   │
│   ├── examples/                     # Few-shot Manim examples (6 types)
│   ├── scenes/                       # Pre-built demo scenes
│   ├── generated_output/             # Pipeline output (.py + videos)
│   └── media/                        # Manim render cache
```

---

## Configuration

### Environment Variables (`backend/.env`)

```env
# LLM API (choose one)
MARTIAN_API_KEY=sk-...          # Martian proxy (recommended)
# ANTHROPIC_API_KEY=sk-ant-...  # Direct Anthropic (fallback)

# Dedalus SDK + Context7 MCP (live Manim docs)
DEDALUS_API_KEY=dsk-...

# ElevenLabs TTS (voiceover)
ELEVEN_API_KEY=sk_...

# API Server
API_HOST=0.0.0.0
API_PORT=8000
```

### Pipeline Config (`backend/agents/pipeline.py`)

| Setting | Value | Purpose |
|---------|-------|---------|
| `MAX_VISUALIZATIONS` | 5 | Max videos per paper |
| `MAX_RETRIES` | 5 | Retry attempts per visualization |
| `ENABLE_SPATIAL_VALIDATION` | True | Check element positioning |
| `ENABLE_RENDER_TESTING` | True | Runtime import test |
| `ENABLE_VOICEOVER` | True | Generate voiceover narration |
| `VOICEOVER_TTS_SERVICE` | `"elevenlabs"` | TTS engine |
| `VOICEOVER_NARRATION_STYLE` | `"friendly_tutor"` | Narration tone |

### Model Config (`backend/agents/base.py`)

| Setting | Value |
|---------|-------|
| `DEFAULT_MODEL_MARTIAN` | `claude-opus-4-5-20251101` |
| `DEFAULT_MODEL_ANTHROPIC` | `claude-opus-4-5-20251101` |
| `MARTIAN_BASE_URL` | `https://api.withmartian.com/v1` |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/process` | Start processing a paper by arXiv ID |
| `GET` | `/api/status/{job_id}` | Poll processing status |
| `GET` | `/api/paper/{arxiv_id}` | Get processed paper with video URLs |
| `GET` | `/api/video/{video_id}` | Get video file |
| `GET` | `/health` | Health check |

---

## Key Design Decisions

### Unified Voiceover Generation
Voiceover narration is generated **inline** by the ManimGenerator rather than as a separate post-processing step. This ensures narration text is tightly coupled with animation beats, producing better sync.

### Friendly Tutor Narration Style
Narration uses approachable, conversational language — like a smart friend explaining concepts to someone new to the topic. Still technically accurate, but avoids dense academic phrasing. This makes the videos accessible to a broader audience.

### Curated Paper Mode
The demo uses a hand-crafted 5-section version of "Attention Is All You Need" with content specifically written to produce reliable, high-quality visualizations. This bypasses the variability of raw paper parsing.

### Relaxed Validation
The voiceover validator focuses on critical issues (missing VoiceoverScene, banned animation-command narration starts) rather than strict structural checks. Score thresholds are set at 0.70 to avoid unnecessary retries while still catching poor quality.

### Dedalus SDK + Context7 for Live Docs
Rather than relying solely on a static Manim API reference, the pipeline fetches real-time documentation from Manim Community Edition before each generation. This helps Claude use current APIs correctly.

---

## Recent Changes

### Model Upgrade
- Switched from `claude-sonnet-4-5-20250929` to **`claude-opus-4-5-20251101`** for best generation quality
- All agents (analyzer, planner, generator) now use Opus

### ElevenLabs Integration
- Switched from gTTS (free) to **ElevenLabs** paid TTS
- Model: `eleven_flash_v2_5` (fast, high quality)
- Custom voice ID: `2fe8mwpfJcqvj9RGBsC1`

### Narration Style
- Changed from academic "concept_teacher" to **"friendly_tutor"**
- Prompt updated: "like a smart friend explaining to a high schooler"
- Plain language preferred over jargon, short punchy sentences
- Still technically accurate — just more accessible

### Validator Relaxation
- Removed word count hard-fail (was 12-24, caused most failures)
- Removed `run_time=tracker.duration` hard-fail
- Removed narration count strict check
- Lowered score thresholds from 0.85 to 0.70
- Kept: banned animation-command starts, VoiceoverScene structure checks

### Expanded Demo Paper
- `create_attention_paper()` expanded from 3 to **5 curated sections**:
  1. The Transformer Architecture
  2. Scaled Dot-Product Attention
  3. Multi-Head Attention
  4. Positional Encoding
  5. Why Self-Attention

### Martian API
- Updated API key and model support
- Auto-detects Martian vs direct Anthropic and adjusts model names

---

## License

MIT
