# ArXiviz: Project Overview

## Vision

ArXiviz transforms dense academic research papers from arXiv into beautiful, interactive scrollytelling experiences with Manim-generated visualizations. Our goal is to make cutting-edge research accessible to everyone without dumbing it down.

## The Problem

- Research papers are locked behind dense language, equations, and PDFs
- Even incredible work goes unnoticed because it's hard to understand
- Knowledge stays siloed within tiny expert communities
- No easy way for researchers to communicate impact to broader audiences

## Our Solution

A seamless URL transformation: change `arxiv.org` to `arxiviz.org` to get an interactive, visual explanation of any ML/CS paper.

```
https://arxiv.org/abs/1706.03762
                ↓
https://arxiviz.org/abs/1706.03762
```

## Core Features

1. **Automatic Paper Parsing**: Extract structure, sections, equations, and figures from arXiv papers
2. **Intelligent Visualization Selection**: AI determines which concepts benefit from visual explanation
3. **Manim Video Generation**: Create 3Blue1Brown-style animations for complex concepts
4. **Scrollytelling Display**: Beautiful, flowing presentation that guides readers through the paper

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ArXiviz Pipeline                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────────────┐    │
│  │   TEAM 1    │    │      TEAM 2      │    │        TEAM 3           │    │
│  │  Ingestion  │───▶│    Generation    │───▶│   Rendering & Display   │    │
│  └─────────────┘    └──────────────────┘    └─────────────────────────┘    │
│        │                    │                          │                    │
│        ▼                    ▼                          ▼                    │
│  ┌───────────┐      ┌─────────────┐           ┌──────────────┐             │
│  │ ArXiv API │      │ Claude API  │           │  Modal.com   │             │
│  │ PDF Parse │      │ Multi-Agent │           │  Next.js     │             │
│  │ Sections  │      │ Manim Code  │           │  PostgreSQL  │             │
│  └───────────┘      └─────────────┘           └──────────────┘             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Frontend | Next.js 14 (App Router) | Scrollytelling UI |
| Styling | Tailwind CSS + Framer Motion | Beautiful animations |
| Backend API | Python FastAPI | REST endpoints |
| LLM | Anthropic Claude | Paper analysis & code generation |
| Video Rendering | Manim CE on Modal.com | 3B1B-style animations |
| Database | PostgreSQL | Paper & video metadata cache |
| Cache | Redis | Job queue & fast lookups |
| Storage | S3/Cloudflare R2 | Video file storage |

## Project Structure

```
arxiviz/
├── frontend/                 # Next.js application
│   ├── app/
│   │   ├── abs/[...id]/     # Paper display pages
│   │   └── api/             # API routes (proxy to backend)
│   ├── components/          # React components
│   └── lib/                 # Utilities
│
├── backend/                  # Python FastAPI
│   ├── main.py              # FastAPI app entry
│   ├── ingestion/           # Team 1: Paper parsing
│   │   ├── arxiv_fetcher.py
│   │   ├── pdf_parser.py
│   │   └── section_extractor.py
│   ├── agents/              # Team 2: AI pipeline
│   │   ├── section_analyzer.py
│   │   ├── visualization_planner.py
│   │   ├── manim_generator.py
│   │   └── code_validator.py
│   ├── rendering/           # Team 3: Video pipeline
│   │   ├── modal_runner.py
│   │   └── storage.py
│   ├── prompts/             # Claude prompt templates
│   ├── examples/            # Few-shot Manim examples
│   ├── models/              # Pydantic data models
│   └── db/                  # Database models & queries
│
├── AgentDocs/               # This documentation folder
└── docker-compose.yml       # Local dev environment
```

## Data Models

### Paper (Parsed)

```python
class ParsedPaper:
    arxiv_id: str           # e.g., "1706.03762"
    title: str
    authors: list[str]
    abstract: str
    sections: list[Section]
    
class Section:
    id: str                 # Unique section identifier
    title: str              # Section header
    content: str            # Raw text content
    equations: list[str]    # LaTeX equations found
    figures: list[Figure]   # Referenced figures
    level: int              # Header level (1, 2, 3)
```

### Visualization

```python
class Visualization:
    section_id: str
    concept: str            # What concept this visualizes
    storyboard: str         # Step-by-step visual plan
    manim_code: str         # Generated Manim Python code
    video_url: str | None   # URL after rendering
    status: str             # pending, rendering, complete, failed
```

## Team Responsibilities

### Team 1: Paper Ingestion
- Fetch papers from arXiv (API + PDF download)
- Parse PDF/HTML into structured text
- Extract sections, equations, figures
- Output clean JSON for downstream processing

### Team 2: Content Generation
- Analyze which sections need visualization
- Plan visualizations (storyboards)
- Generate Manim code with multi-agent pipeline
- Validate and iterate on code quality

### Team 3: Rendering & Display
- Execute Manim on Modal.com
- Store videos in S3/R2
- Build scrollytelling Next.js frontend
- Implement caching layer

## Success Metrics

For the hackathon demo:
1. Successfully process "Attention Is All You Need" paper end-to-end
2. Generate at least 3 high-quality Manim visualizations
3. Display in a polished scrollytelling format
4. Handle arbitrary ML/CS papers gracefully

## Reference Links

- [ArXiv API Documentation](https://info.arxiv.org/help/api/index.html)
- [Manim Community Documentation](https://docs.manim.community/)
- [Modal.com Docs](https://modal.com/docs)
- [Next.js App Router](https://nextjs.org/docs/app)
- [Anthropic Claude API](https://docs.anthropic.com/)
