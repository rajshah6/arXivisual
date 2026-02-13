# Team 1: Paper Ingestion Pipeline

## Your Mission

Build the pipeline that takes an arXiv URL and outputs clean, structured paper data ready for AI analysis.

## Overview

```
ArXiv URL → Fetch PDF/HTML → Parse Content → Extract Sections → Structured JSON
```

## Files You Own

```
backend/
├── ingestion/
│   ├── __init__.py
│   ├── arxiv_fetcher.py    # Fetch paper metadata and PDF
│   ├── pdf_parser.py       # Extract text from PDF
│   └── section_extractor.py # Identify sections and structure
├── models/
│   └── paper.py            # Pydantic models for paper data
```

## Detailed Requirements

### 1. ArXiv Fetcher (`arxiv_fetcher.py`)

**Purpose**: Given an arXiv ID, fetch all available paper data.

**Inputs**:
- `arxiv_id: str` - e.g., "1706.03762" or "2301.07041v1"

**Outputs**:
```python
class ArxivPaperMeta:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: datetime
    updated: datetime
    categories: list[str]      # e.g., ["cs.CL", "cs.LG"]
    pdf_url: str               # Direct PDF download URL
    html_url: str | None       # ar5iv HTML URL if available
```

**Implementation Notes**:
- Use the `arxiv` Python package (pip install arxiv)
- Handle version numbers (v1, v2, etc.)
- Check if ar5iv HTML version exists: `https://ar5iv.org/abs/{arxiv_id}`
- Prefer HTML when available (better structure), fall back to PDF

**Example Usage**:
```python
from ingestion.arxiv_fetcher import fetch_paper_meta, download_pdf

meta = await fetch_paper_meta("1706.03762")
# Returns ArxivPaperMeta with all metadata

pdf_bytes = await download_pdf(meta.pdf_url)
# Returns raw PDF bytes
```

### 2. PDF Parser (`pdf_parser.py`)

**Purpose**: Extract structured text from PDF, preserving equations and structure.

**Recommended Libraries** (choose one):
- `pymupdf4llm` - Best for LLM-ready output with markdown formatting
- `marker-pdf` - Good at preserving equations
- `pypdf` + `pdfplumber` - More control but more work

**Inputs**:
- `pdf_bytes: bytes` or `pdf_path: str`

**Outputs**:
```python
class ParsedContent:
    raw_text: str              # Full text as markdown
    equations: list[Equation] # Extracted LaTeX equations
    figures: list[Figure]     # Figure references and captions
    
class Equation:
    latex: str                # LaTeX source
    context: str              # Surrounding text for context
    is_inline: bool           # Inline vs display equation
    
class Figure:
    id: str                   # Figure number/id
    caption: str              # Figure caption text
    page: int                 # Page number
```

**Implementation Notes**:
- `pymupdf4llm` outputs clean markdown - recommended starting point
- Equations in PDFs are often images - use context to identify them
- For ar5iv HTML, use BeautifulSoup - much easier to parse!

**HTML Parsing Alternative**:
```python
async def parse_html(html_url: str) -> ParsedContent:
    """Parse ar5iv HTML version - preferred when available."""
    # ar5iv preserves LaTeX in <math> tags
    # Structure is clean with <section>, <h2>, etc.
```

### 3. Section Extractor (`section_extractor.py`)

**Purpose**: Break parsed content into logical sections based on headers.

**Inputs**:
- `content: ParsedContent`
- `meta: ArxivPaperMeta`

**Outputs**:
```python
class Section:
    id: str                   # Unique ID, e.g., "section-3-2"
    title: str                # Section header text
    level: int                # 1 = H1, 2 = H2, etc.
    content: str              # Section body text
    equations: list[Equation] # Equations in this section
    figures: list[Figure]     # Figures referenced
    parent_id: str | None     # Parent section ID for nesting
    
class StructuredPaper:
    meta: ArxivPaperMeta
    sections: list[Section]
    
    def to_dict(self) -> dict:
        """Serialize for JSON output."""
```

**Section Detection Logic**:
```python
# Common ML paper structure:
EXPECTED_SECTIONS = [
    "Abstract",
    "Introduction", 
    "Related Work",
    "Background",
    "Method",          # or "Approach", "Model", "Architecture"
    "Experiments",     # or "Results", "Evaluation"
    "Discussion",
    "Conclusion",
    "References",
    "Appendix"
]

# Header patterns in markdown from pymupdf4llm:
# # Title (level 1)
# ## Section (level 2)
# ### Subsection (level 3)
```

**Edge Cases to Handle**:
- Papers without clear headers (use heuristics)
- Appendices (often have different numbering)
- Footnotes and references
- Multi-column layouts (pymupdf4llm handles this)

## Main Integration Function

Create a single entry point in `backend/ingestion/__init__.py`:

```python
async def ingest_paper(arxiv_id: str) -> StructuredPaper:
    """
    Main entry point for paper ingestion.
    
    1. Fetch metadata from arXiv
    2. Download and parse PDF (or HTML if available)
    3. Extract sections and structure
    4. Return clean StructuredPaper object
    """
    # Check cache first
    cached = await get_cached_paper(arxiv_id)
    if cached:
        return cached
    
    # Fetch metadata
    meta = await fetch_paper_meta(arxiv_id)
    
    # Try HTML first, fall back to PDF
    if meta.html_url:
        content = await parse_html(meta.html_url)
    else:
        pdf_bytes = await download_pdf(meta.pdf_url)
        content = await parse_pdf(pdf_bytes)
    
    # Extract sections
    paper = extract_sections(content, meta)
    
    # Cache result
    await cache_paper(paper)
    
    return paper
```

## Testing Your Pipeline

Test with these papers:
1. `1706.03762` - "Attention Is All You Need" (well-structured, our demo paper)
2. `2301.07041` - A newer paper to test robustness
3. `1312.6114` - VAE paper (heavy math)

**Quick Test Script**:
```python
# backend/test_ingestion.py
import asyncio
from ingestion import ingest_paper

async def main():
    paper = await ingest_paper("1706.03762")
    
    print(f"Title: {paper.meta.title}")
    print(f"Sections: {len(paper.sections)}")
    
    for section in paper.sections:
        print(f"  [{section.level}] {section.title}")
        print(f"      Equations: {len(section.equations)}")
        print(f"      Length: {len(section.content)} chars")

asyncio.run(main())
```

## Dependencies

Add to `backend/requirements.txt`:
```
arxiv>=2.0.0
pymupdf4llm>=0.0.5
pymupdf>=1.23.0
httpx>=0.25.0
beautifulsoup4>=4.12.0
pydantic>=2.0.0
```

## Output Format

Your final output should be JSON-serializable:

```json
{
  "meta": {
    "arxiv_id": "1706.03762",
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "..."],
    "abstract": "The dominant sequence transduction models...",
    "pdf_url": "https://arxiv.org/pdf/1706.03762",
    "html_url": "https://ar5iv.org/abs/1706.03762"
  },
  "sections": [
    {
      "id": "abstract",
      "title": "Abstract",
      "level": 1,
      "content": "The dominant sequence transduction models...",
      "equations": [],
      "figures": [],
      "parent_id": null
    },
    {
      "id": "section-1",
      "title": "Introduction",
      "level": 1,
      "content": "Recurrent neural networks, long short-term memory...",
      "equations": [],
      "figures": [],
      "parent_id": null
    },
    {
      "id": "section-3",
      "title": "Model Architecture",
      "level": 1,
      "content": "Most competitive neural sequence transduction models...",
      "equations": [
        {"latex": "\\text{Attention}(Q, K, V) = \\text{softmax}(\\frac{QK^T}{\\sqrt{d_k}})V", "context": "..."}
      ],
      "figures": [
        {"id": "figure-1", "caption": "The Transformer model architecture"}
      ],
      "parent_id": null
    }
  ]
}
```

## Handoff to Team 2

Your `StructuredPaper` object will be passed directly to Team 2's Section Analyzer. They need:
- Clean section text (no PDF artifacts)
- Equations preserved as LaTeX
- Clear section hierarchy
- Figure references with captions

## Questions to Consider

1. How do we handle papers with non-standard structure?
2. Should we extract table data separately?
3. How much cleanup is needed for PDF-extracted text?
4. Should we include the references section or skip it?
