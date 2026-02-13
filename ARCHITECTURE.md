# ArXivisual — How the Backend Works

You give the system an arXiv paper ID. It gives you back narrated, animated explainer videos for the key concepts in that paper. No human touches the pipeline in between. This document walks through exactly what happens at every step, from the moment a user pastes `1706.03762` into the search bar to the moment video files land on disk.

```
  arXiv ID
     |
     v
 +-----------+     +-----------------+     +--------------------+     +------------+
 |  Ingestion | --> | 7-Agent AI      | --> | 4-Stage Quality    | --> | Rendering  |
 |  Pipeline  |     | Pipeline        |     | Gate (retry loop)  |     | Local/Modal|
 +-----------+     +-----------------+     +--------------------+     +------------+
                                                   |                        |
                                                   | FAIL: feedback         |
                                                   | loops back to          v
                                                   | generator          MP4 videos
                                                   +-- up to 5x        served at
                                                                      /api/video/ID
```

---

## Step 0: The User Hits "Process"

The frontend sends `POST /api/process` with an arXiv ID. The FastAPI server creates a `ProcessingJob` row in the database (status: `queued`, progress: `0.0`) and returns the job ID immediately. A background worker picks up the job and starts the pipeline. Meanwhile, the frontend polls `GET /api/status/{job_id}` every 2 seconds to show progress.

From here, the worker runs through three major phases: **Ingest**, **Generate**, **Render**.

---

## Step 1: Paper Ingestion

**File:** `backend/ingestion/__init__.py` (entry point), plus `arxiv_fetcher.py`, `html_parser.py`, `pdf_parser.py`, `section_extractor.py`, `section_formatter.py`

**What happens:**

The worker calls `ingest_paper("1706.03762")`. First it normalizes the ID and checks an in-memory cache. On a cache miss, the real work begins.

**1a. Fetch metadata.** Hits the arXiv Atom API to get the paper's title, authors, abstract, categories, PDF URL, and — if available — the ar5iv HTML URL. This comes back as an `ArxivPaperMeta` object.

**1b. Parse the content.** Two paths, chosen automatically:

```
  ar5iv HTML available?
         |
    +----+----+
    |         |
   YES        NO
    |         |
    v         v
  Parse      Download PDF
  HTML       from arXiv
  (clean     (pymupdf4llm
  headings,  extracts
  equations, markdown +
  figures)   LaTeX)
    |         |
    +----+----+
         |
         v
    ParsedContent
    (raw_text, equations[], figures[], tables[])
```

HTML is always preferred because it preserves heading hierarchy, equation boundaries, and figure captions cleanly. PDF is the fallback for older papers where ar5iv doesn't have an HTML version. If HTML parsing throws an exception, it silently falls back to PDF.

**1c. Extract sections.** The `section_extractor` walks the parsed content and splits it into `Section` objects with proper heading levels, parent relationships, and per-section equations/figures/tables.

Before sections go further, the pipeline filters out noise:
- Sections titled "References", "Bibliography", "Acknowledgments", "Appendix", "Supplementary", or "Related Work" are dropped
- Sections shorter than 100 characters are dropped

**1d. LLM summarization.** A 2-phase LLM pass (`section_formatter.py`) summarizes and organizes the sections. Phase 1 generates per-section summaries. Phase 2 consolidates into a clean set of sections. If the LLM call fails (network, rate limit), the pipeline continues with raw content — it doesn't crash.

**Output:** A `StructuredPaper` containing `ArxivPaperMeta` + an ordered list of `Section` objects. Each section has its raw content, an LLM summary, extracted equations, figures, tables, heading level, and parent ID. This gets cached in memory and stored in the database.

At this point the worker updates the job to `progress: 0.20`.

---

## Step 2: Section Analysis (SectionAnalyzer)

**File:** `backend/agents/section_analyzer.py`

**What happens:**

The pipeline takes every eligible section from the structured paper and asks Claude: "What concepts in this section would benefit from an animated visualization?"

For a paper like "Attention Is All You Need", the analyzer might look at the "Scaled Dot-Product Attention" section and return:

```
VisualizationCandidate:
  concept_name: "Scaled Dot-Product Attention"
  concept_description: "Query, key, value matrices multiplied, scaled, softmax applied..."
  visualization_type: "architecture"
  priority: 5
  context: (relevant text from section)
```

Each candidate gets a priority from 1–5 and a type — one of: `architecture`, `equation`, `algorithm`, `data_flow`, `matrix`, `three_d`.

**Concurrency:** All sections are analyzed in parallel via `asyncio.gather()`. If you have 6 eligible sections, 6 Claude calls fire simultaneously. If one fails, the rest still complete — it logs the error and moves on.

After all sections are analyzed, the candidates are sorted by priority (highest first) and capped at 5. These are the concepts that will get visualizations.

---

## Step 3: Storyboard Planning (VisualizationPlanner)

**File:** `backend/agents/visualization_planner.py`

**What happens:**

For each of the top candidates, the planner creates a scene-by-scene storyboard. It gets the candidate, the full section text, and the paper's title + abstract for context. Claude returns a structured plan:

```
VisualizationPlan:
  concept_name: "Scaled Dot-Product Attention"
  visualization_type: architecture
  duration_seconds: 35  (clamped to 30-45s range)
  scenes:
    - Scene 1: "Show query, key, value matrices side by side" (5s)
    - Scene 2: "Animate the dot product between Q and K-transpose" (8s)
    - Scene 3: "Apply scaling by sqrt(d_k)" (5s)
    - Scene 4: "Show softmax turning scores into weights" (7s)
    - Scene 5: "Multiply weights by V to get output" (10s)
  narration_points:
    - "Attention computes a weighted sum of values..."
    - "The scaling factor prevents the dot products from growing too large..."
```

Each scene has a description, duration (1–30s), transition style, and a list of Manim elements to use (Text, MathTex, Arrow, Rectangle, etc.). The total duration is clamped to 30–45 seconds — long enough to explain the concept, short enough to hold attention.

---

## Step 4: Code Generation (ManimGenerator)

**File:** `backend/agents/manim_generator.py`

This is the most complex agent. It takes a storyboard plan and generates a complete, runnable Python file using the Manim animation library — with embedded voice narration.

**What happens before generation:**

1. **Load a few-shot example.** The generator has 9 pre-written example files (6 standard, 3 voiceover) organized by visualization type. If you're generating an `architecture` visualization, it loads `architecture_diagram.py` as a reference. For voiceover mode, it loads `voiceover_architecture.py` instead.

2. **Fetch live Manim docs.** Before every generation call, the generator fetches up-to-date Manim documentation via a 3-tier fallback chain:

```
  Tier 1: Dedalus SDK + Context7 MCP
     Uses DedalusRunner with mcp_servers=["tsion/context7"]
     Automatically calls resolve-library-id("manim community")
     then get-library-docs with a topic query
     Uses claude-3-5-haiku for fast retrieval, 6-step budget
         |
         | (fails: import error, timeout, empty response)
         v
  Tier 2: Direct Context7 REST API
     Raw HTTP calls to context7.com/api/v2/search and /api/v2/context
     No Dedalus SDK dependency
         |
         | (fails: network error, no results)
         v
  Tier 3: Static manim_reference.md
     Bundled reference file, always available
```

  The fetched docs get prepended to Claude's system prompt, labeled as the PRIMARY reference source. Results are cached in-memory by topic key so the same docs aren't fetched twice in one pipeline run.

3. **Build a scene class name.** The concept name "Scaled Dot-Product Attention" becomes `ScaledDotProductAttention` as the Python class name.

**The actual generation call:**

Claude receives the storyboard plan, the few-shot example, the live Manim docs, the TTS setup snippet (which ElevenLabs voice, which model), and instructions to generate a `VoiceoverScene` class. The code must:
- Inherit from `VoiceoverScene`
- Call `self.set_speech_service(ElevenLabsService(...))` in `construct()`
- Use `with self.voiceover(text="...") as tracker:` blocks for narration
- Time animations with `run_time=tracker.duration`
- Include `# Beat N` labels matching the storyboard scenes

The generator extracts the code from Claude's response, auto-adds `from manim import *` if missing, and returns a `GeneratedCode` object with the code, class name, narration lines, and beat labels.

---

## Step 5: The 4-Stage Quality Gate

This is where the real engineering is. LLM-generated code is unreliable — it hallucinates APIs, positions elements off-screen, writes narration that describes animations instead of explaining concepts, and produces code that crashes at import time. The evaluation harness catches all of this.

Every generated Manim scene must pass 4 sequential stages. If **any** stage fails, the pipeline collects feedback from all stages, concatenates it, and sends it back to the generator for another attempt. This loops up to 5 times (3 base + 2 extra for voiceover quality).

```
  Generated Code
       |
       v
  +--[Stage 1: CodeValidator]--+
  |  AST parse, import check,  |
  |  Scene class detection,    |
  |  MathTex splitting check,  |
  |  auto-fix brackets/typos   |
  +----------------------------+
       |
       | FAIL --> feedback collected, retry
       | PASS
       v
  +--[Stage 2: SpatialValidator]--+
  |  Extract positions from        |
  |  move_to/shift/next_to,       |
  |  check screen bounds,          |
  |  detect overlapping elements,  |
  |  flag missing buff parameters  |
  +-------------------------------+
       |
       | FAIL --> feedback collected, retry
       | PASS
       v
  +--[Stage 3: VoiceoverScriptValidator]--+
  |  Hard checks: VoiceoverScene class,    |
  |  set_speech_service, voiceover blocks  |
  |                                         |
  |  Soft scoring:                          |
  |  - Alignment: does narration match      |
  |    the concept? (threshold >= 0.45)     |
  |  - Educational: is it teaching, not     |
  |    describing animations? (>= 0.50)    |
  |                                         |
  |  LLM judge for borderline cases         |
  +----------------------------------------+
       |
       | FAIL --> feedback collected, retry
       | PASS
       v
  +--[Stage 4: RenderTester]--+
  |  Write to temp file,       |
  |  compile() for syntax,     |
  |  importlib exec for        |
  |  runtime errors,           |
  |  verify Scene class exists |
  +---------------------------+
       |
       | FAIL --> feedback collected, retry
       | PASS
       v
  All 4 gates passed. Code is accepted.
```

Here's what each stage does in detail:

### Stage 1: CodeValidator

**File:** `backend/agents/code_validator.py`

This is pure static analysis — no LLM calls, no execution.

1. **AST parse.** Runs `ast.parse(code)`. If there's a syntax error, it tries to auto-fix common issues: unclosed parentheses, brackets, braces, and trailing incomplete lines. If it's still broken after fixes, `needs_regeneration = True`.

2. **Import check.** Looks for `from manim import`. If missing, injects `from manim import *` at the top (auto-fix, not a failure).

3. **Scene class check.** Regex search for `class SomeName(Scene|ThreeDScene|VoiceoverScene):`. If no Scene class is found, that's an issue.

4. **Construct method check.** Looks for `def construct(self)`. If missing, that's an issue.

5. **Typo auto-fix.** Fixes common color typos (`GREY` -> `GRAY`, `DARK_GREY` -> `DARK_GRAY`) and method name case errors (`fadein` -> `FadeIn`, `fadeOut` -> `FadeOut`).

6. **MathTex splitting detection.** This is the most critical check. LLMs love to split LaTeX formulas across MathTex arguments like `MathTex(r"\frac{", "x", r"}")` — this crashes Manim because each MathTex part must be valid LaTeX on its own. The validator uses regex to detect incomplete `\frac{}`, `\sqrt{}`, `\left/\right` pairs, and `\begin/\end` environments split across arguments. Any MathTex splitting issue immediately triggers regeneration.

**Output:** `ValidatorOutput` with `is_valid`, auto-fixed `code`, `issues_found`, `issues_fixed`, `needs_regeneration`. Regeneration triggers if there are >1 unfixed issues or any MathTex splitting.

### Stage 2: SpatialValidator

**File:** `backend/agents/spatial_validator.py`

Also pure static analysis. Checks whether animations will actually be visible on screen.

1. **Position extraction.** Scans every line for `move_to()`, `shift()`, `next_to()`, `to_edge()`, `to_corner()`, and their `.animate` variants. Parses direction*scalar patterns like `RIGHT * 5` or `3 * DOWN` to estimate x,y coordinates.

2. **Bounds checking.** Two thresholds:
   - Safe area: `|x| < 6`, `|y| < 3.5` — elements within this look good
   - Screen bounds: `|x| < 7`, `|y| < 4` — outside this, elements are invisible
   - Beyond screen bounds is a CRITICAL issue. Near the edge is a warning.

3. **Overlap detection.** Compares all extracted positions pairwise. If two different elements are within 1.5 units on X and 0.8 units on Y, they likely overlap. Same Y within 0.3 and X within 3.0 also triggers a horizontal overlap warning.

4. **Spacing checks.** Flags `next_to()` calls without a `buff` parameter and `arrange()` without `buff` — elements will touch or overlap without explicit spacing.

**Output:** `SpatialValidatorOutput` with `out_of_bounds`, `potential_overlaps`, `spacing_issues`, `suggestions`. Needs regeneration if there are >=2 bounds issues, >=2 overlaps, or any CRITICAL bound violation.

### Stage 3: VoiceoverScriptValidator

**File:** `backend/agents/voiceover_script_validator.py`

This is the only validator that combines both rule-based checks and an optional LLM call. It validates that the narration actually teaches the concept, not just describes what's happening on screen.

**Hard structural checks (instant fail if missing):**
- Code must contain `VoiceoverScene` (the class inheritance)
- Code must call `set_speech_service(...)`
- Code must have at least one `with self.voiceover(text="...") as tracker:` block

**Soft scoring (determines quality, may trigger regeneration):**

*Alignment score* — Does the narration match the concept being visualized?
- Tokenizes each narration line (words >= 3 chars, minus stopwords like "the", "and", "with")
- Compares tokens against reference terms from the `VisualizationCandidate` (concept name + description + context)
- Bonus points for anchor terms specific to ML/math: `query`, `key`, `value`, `attention`, `softmax`, `weight`, `score`, `representation`, `token`, `context`
- Formula: `0.45 + (0.20 * min(3, anchor_hits)) + (0.25 * overlap_ratio)`
- Threshold: **>= 0.45**

*Educational score* — Is the narration pedagogical, or just narrating the animation?
- Starts at base **0.95**
- Penalty **-0.45** if narration starts with animation verbs: "display", "show", "fade", "animate", "create", "draw", "move", "write"
- Penalty **-0.20** for references to the screen: "screen", "on screen"
- Penalty **-0.15** for filler phrases: "watch", "now we"
- Penalty **-0.20** for short lines (< 6 words)
- Threshold: **>= 0.50**

*LLM judge* — When heuristic scores are borderline, an LLM call (Claude) evaluates the narration against a structured rubric. The judge sees the concept, the storyboard plan, and all narration lines, and returns `score_alignment` and `score_educational` as floats. This overrides the heuristic scores when available.

**Output:** `VoiceoverValidationOutput` with `score_alignment`, `score_educational`, `issues_found`, `needs_regeneration`. In strict mode (default), any issue triggers regeneration.

### Stage 4: RenderTester

**File:** `backend/agents/render_tester.py`

This is the final gate — it actually executes the code to catch runtime errors that static analysis can't see.

1. **Compile check.** `compile(code, filename, 'exec')` — catches syntax errors with exact line numbers.

2. **Import test.** Writes the code to a temp `.py` file, creates a module spec via `importlib.util.spec_from_file_location`, and calls `spec.loader.exec_module()`. This runs all top-level code including imports and class definitions. Catches:
   - `NameError` — undefined variables or Manim classes
   - `AttributeError` — wrong method names on Manim objects
   - `TypeError` — wrong number/type of arguments
   - `ModuleNotFoundError` — missing dependencies
   - LaTeX-related errors — detected by checking for "latex" or "tex" in the error message

3. **Scene class verification.** After successful import, checks that the module contains at least one class with a `construct()` method that isn't a base Manim class (`Scene`, `ThreeDScene`, `VoiceoverScene` themselves are excluded).

4. **Specialized error parsing.** Walks the traceback to extract the exact line number in the generated code. For attribute errors, extracts the object type and missing attribute name for targeted feedback. For LaTeX errors, suggests using `set_color_by_tex()` instead of splitting.

The whole thing runs in `asyncio.to_thread()` to avoid blocking the event loop, with a configurable timeout (default 60 seconds, set via `RENDER_TEST_TIMEOUT_SECONDS` env var).

**Output:** `RenderTestOutput` with `success`, `error_type`, `error_message`, `line_number`, `fix_suggestion`.

### How the Retry Loop Works

When any stage fails, the pipeline doesn't just retry blindly. It aggregates feedback from **all** failed stages into a single message:

```
SYNTAX / STRUCTURE ISSUES:
- MathTex has incomplete \frac{} split across parts

SPATIAL ISSUES DETECTED:
- Line 45: Element 'title' at x=8.0 is outside screen bounds
  Fix: Use x position between -6 and 6

VOICEOVER QUALITY ISSUES:
- Alignment score: 0.32
- Educational score: 0.41
- Narration 2 starts with animation command style wording

RUNTIME ERROR:
- Error Type: AttributeError
- Error Message: 'Rectangle' has no attribute 'set_fill_color'
- Suggested Fix: use .set_fill() instead
```

This entire feedback block gets passed to `ManimGenerator.run_with_feedback()`, which appends it to the generation prompt alongside the previous broken code. The LLM sees exactly what went wrong and what to fix. Each retry also re-fetches live Manim docs via Context7 in case the issue was an outdated API.

After 5 failed attempts, the `VOICE_FAIL_BEHAVIOR` policy kicks in:
- `return_silent` (default) — keep the visualization with the last code, mark it pending (no video)
- `drop_viz` — discard entirely
- `hard_error` — raise an exception, fail the whole job

---

## Step 6: Rendering

**Files:** `backend/rendering/__init__.py`, `local_runner.py`, `modal_runner.py`, `storage.py`

Once a visualization passes all 4 gates, its Manim code gets rendered into an MP4 video.

**Scene name extraction.** A regex pulls the class name from `class ScaledDotProductAttention(VoiceoverScene):` — that's the scene name Manim needs to render.

**Render mode routing.** The `RENDER_MODE` env var chooses the backend:

```
  RENDER_MODE=local                    RENDER_MODE=modal
       |                                    |
       v                                    v
  asyncio.to_thread(                  modal.App("arxiviz-manim")
    subprocess.run(                   @app.function(timeout=300)
      "manim render                   Debian Slim + Python 3.11
       scene.py                       + ffmpeg + cairo + pango
       SceneName                      + manim >= 0.18.0
       -ql --format=mp4"
    )                                 Same subprocess pattern
    timeout=300s                      inside the container
  )
       |                                    |
       v                                    v
     MP4 bytes                           MP4 bytes
       |                                    |
       +----------------+------------------+
                        |
                        v
               save_video(bytes, "viz_abc123.mp4")
                        |
                        v
               media/videos/viz_abc123.mp4
               served at /api/video/viz_abc123
```

**Local runner** writes the code to a `tempfile.TemporaryDirectory`, runs `manim render` via `subprocess.run()` with quality flags (`-ql` for low, `-qm` for medium, `-qh` for high), reads back the output MP4, and cleans up the temp directory. Wrapped in `asyncio.to_thread()` so it doesn't block the event loop. 5-minute timeout.

**Modal runner** does the same thing but inside a serverless container on Modal.com. The container image is pre-built with Debian Slim, Python 3.11, ffmpeg, libcairo2-dev, libpango1.0-dev, and Manim >= 0.18.0. The `@app.function(timeout=300)` decorator handles cold starts and auto-scaling.

**Concurrent rendering.** The job worker uses `asyncio.Semaphore(3)` — at most 3 visualizations render in parallel. This prevents memory exhaustion from multiple simultaneous Manim processes. All visualizations are kicked off via `asyncio.gather()` with the semaphore gating actual execution.

**Storage.** In development, videos save to `media/videos/` on disk. Each video is accessible at `/api/video/{viz_id}`. In production, this swaps to S3 or Cloudflare R2 object storage.

---

## Step 7: Job Completion

After all visualizations are rendered (or have failed individually), the worker updates the job:

```
progress: 1.0
status: "completed"
current_step: "Complete"
```

The frontend's polling loop picks this up and loads the paper page with embedded video players for each visualization.

**Progress milestones through the whole pipeline:**

```
  0%  ----  Job created, fetching paper
  5%  ----  Metadata fetched from arXiv
  10% ----  Parsing content (HTML or PDF)
  20% ----  Sections extracted + LLM summarized
  30% ----  Section analysis + code generation starting
  40% ----  Agent pipeline complete, rendering starting
  40-90% -- Rendering visualizations (progress updates per viz)
  90% ----  All renders complete
  100% ---  Done
```

**Error isolation.** If one visualization fails to render, it gets marked `status: "failed"` in the database, but the rest of the visualizations continue. The job only fails entirely if ingestion crashes or an unhandled exception bubbles up.

---

## How the LLM Calls Work

Every agent in the pipeline needs to call Claude. The system uses a Dedalus-only configuration:

```
  1. DEDALUS_API_KEY set?  -->  Use Dedalus SDK (AsyncDedalus + DedalusRunner)
  2. Missing key?          -->  Fail fast with a configuration error
```

All agents inherit from `BaseAgent` (`agents/base.py`), which handles:

- **Provider-agnostic calls.** `_call_llm()` (async) and `_call_llm_sync()` route to whatever provider is configured. A shared `DedalusRunner` instance is reused across agents.

- **LaTeX-safe prompt formatting.** `_format_prompt()` uses `str.replace()` per variable instead of Python's `str.format()`. This matters because paper content is full of LaTeX with curly braces (`\frac{x}{y}`, `\begin{pmatrix}`) that would crash `str.format()`.

- **Response parsing.** `_parse_json_response()` handles JSON wrapped in markdown code fences (` ```json ... ``` `). `_extract_code_block()` pulls Python code from fenced blocks.

### Dedalus Multi-Model Handoffs

When using the Dedalus SDK, the system can chain multiple Claude models per task. The `DedalusBaseAgent` (`agents/dedalus_base.py`) maps task types to model chains:

```
  research:    Haiku (gather) --> Sonnet (analyze) --> Opus (synthesize)
  code:        Sonnet (plan)  --> Opus (implement)
  creative:    Opus only (best for nuanced content)
  analysis:    Haiku (scan)   --> Opus (reason)
  multi_step:  Haiku --> Sonnet --> Opus (full chain)
```

The Dedalus SDK's `DedalusRunner.run()` accepts the list of models and automatically routes subtasks to the appropriate tier — faster models handle simple parts, Opus handles the hard reasoning.

---

## Data Models

The whole system uses Pydantic v2 models at every boundary for runtime validation, and SQLAlchemy ORM for the database.

### Pipeline Domain Models

A concept flows through this chain as it gets refined from raw text into a rendered video:

```
  VisualizationCandidate    "Scaled Dot-Product Attention, priority 5, type: architecture"
         |
         v
  VisualizationPlan         5 scenes, 35 seconds, narration points
         |
         v
  GeneratedCode             VoiceoverScene Python code + narration lines + beat labels
         |
         v
  Visualization             Final object: code + storyboard JSON + video URL + status
```

### Database Tables

4 tables, all linked through the paper ID:

```
  papers
    id (PK, arxiv_id like "1706.03762")
    title, authors (JSON), abstract, pdf_url, html_url
    created_at, updated_at

  sections
    id (PK)
    paper_id (FK -> papers)
    title, content, summary
    level (heading depth), order_index
    equations (JSON), figures (JSON), tables (JSON)

  visualizations
    id (PK)
    paper_id (FK -> papers)
    section_id (FK -> sections)
    concept, storyboard (JSON), manim_code
    video_url, status (pending/rendering/complete/failed), error
    created_at

  processing_jobs
    id (PK)
    paper_id (FK -> papers)
    status (queued/processing/completed/failed)
    progress (0.0 - 1.0)
    sections_completed, sections_total
    current_step (human-readable text)
    error, created_at, completed_at
```

### Key Enums

**VisualizationType** — the 6 kinds of visualizations the system can generate:
`architecture`, `equation`, `algorithm`, `data_flow`, `matrix`, `three_d`

**VisualizationStatus** — lifecycle of a single visualization:
`pending` -> `rendering` -> `complete` (or `failed`)

---

## File Map

For quick reference — where everything lives:

```
backend/
  agents/
    pipeline.py              Orchestration: ties all agents together, retry loop
    base.py                  BaseAgent: LLM provider routing, prompt loading
    dedalus_base.py          DedalusBaseAgent: multi-model handoff chains
    section_analyzer.py      Identifies viz-worthy concepts per section
    visualization_planner.py Creates scene-by-scene storyboards
    manim_generator.py       Generates Manim + voiceover code from plans
    code_validator.py        AST parsing, MathTex split detection, auto-fix
    spatial_validator.py     Bounds checking, overlap detection
    voiceover_script_validator.py  Narration quality scoring + LLM judge
    render_tester.py         Import-time execution test
    context7_docs.py         Live Manim docs via Context7 MCP + 3-tier fallback
    voiceover_generator.py   Legacy post-transform mode (disabled)

  ingestion/
    __init__.py              Entry point: ingest_paper()
    arxiv_fetcher.py         arXiv API metadata + PDF download
    html_parser.py           ar5iv HTML parsing
    pdf_parser.py            PDF extraction via pymupdf4llm
    section_extractor.py     Splits content into Section objects
    section_formatter.py     2-phase LLM summarization

  rendering/
    __init__.py              RENDER_MODE routing + process_visualization()
    local_runner.py          Local Manim subprocess rendering
    modal_runner.py          Modal.com serverless rendering
    storage.py               Video file storage + URL generation

  jobs/
    worker.py                Background job: ingest -> generate -> render

  models/
    paper.py                 ArxivPaperMeta, Section, StructuredPaper, Equation, Figure, Table
    generation.py            VisualizationCandidate, Plan, GeneratedCode, Visualization
    spatial.py               SpatialValidatorOutput, BoundsIssue, OverlapIssue, SpacingIssue
    voiceover.py             VoiceoverValidationOutput

  db/
    models.py                SQLAlchemy ORM: Paper, Section, Visualization, ProcessingJob
    connection.py            Async database engine + session factory
    queries.py               Database query helpers

  prompts/
    section_analyzer.md      Prompt template for section analysis
    visualization_planner.md Prompt template for storyboard planning
    manim_generator.md       Prompt template for code generation
    system/
      manim_reference.md     Static Manim API reference (Tier 3 fallback)

  examples/
    equation_walkthrough.py  Few-shot example: equation visualization
    architecture_diagram.py  Few-shot example: architecture diagram
    data_flow.py             Few-shot example: data flow animation
    algorithm_steps.py       Few-shot example: algorithm walkthrough
    matrix_operations.py     Few-shot example: matrix operations
    three_d_network.py       Few-shot example: 3D visualization
    voiceover_equation.py    Few-shot example: voiceover + equation
    voiceover_architecture.py Few-shot example: voiceover + architecture
    voiceover_data_flow.py   Few-shot example: voiceover + data flow
```
