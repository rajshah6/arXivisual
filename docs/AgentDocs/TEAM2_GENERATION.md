# Team 2: Content Generation (AI Agent Pipeline)

## Your Mission

Build the multi-agent AI pipeline that analyzes paper sections and generates high-quality, validated Manim visualization code with AI voiceovers.

**Status: Fully built and operational.** The pipeline takes a `StructuredPaper` as input and outputs validated `Visualization` objects with runnable Manim code.

---

## Pipeline Architecture

```
StructuredPaper
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Section Analysis (parallel)                            │
│  SectionAnalyzer × N sections → VisualizationCandidate[]        │
│  • Skips: references, related work, short sections              │
│  • Claude decides what needs visualization and what type        │
│  • Priority 1-10, sorted, limited to MAX_VISUALIZATIONS (5)    │
└───────────────────────┬─────────────────────────────────────────┘
                        │ Top N candidates
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: Visualization Planning (per candidate)                 │
│  VisualizationPlanner → VisualizationPlan                       │
│  • Scene-by-scene storyboard (3-5 scenes, 15-30s total)        │
│  • Narration points for voiceover                               │
│  • Manim elements + transitions per scene                       │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: Code Generation + Multi-Stage Validation (3 retries)   │
│                                                                  │
│  ManimGenerator → code                                          │
│       │ (uses type-matched few-shot example)                    │
│       ▼                                                          │
│  [1/3] CodeValidator     → syntax, imports, structure           │
│       │                    (auto-fixes minor issues)            │
│       ▼                                                          │
│  [2/3] SpatialValidator  → bounds, overlaps, spacing            │
│       │                    (flags off-screen elements)          │
│       ▼                                                          │
│  [3/3] RenderTester      → runtime import test                  │
│       │                    (catches NameError, TypeError, etc.)  │
│       │                                                          │
│  ✗ Any fail → combined feedback → ManimGenerator (retry)        │
│  ✓ All pass → continue                                          │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: Voiceover Generation (optional)                        │
│  VoiceoverGenerator → VoiceoverScene + ElevenLabs TTS           │
│  • Generates educational narration script                       │
│  • Transforms Scene → VoiceoverScene                            │
│  • Wraps self.play() calls with voiceover blocks                │
│  • Graceful: if it fails, visualization still works (silent)    │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
                list[Visualization]
                (validated Manim code, ready for Team 3)
```

---

## Files You Own

```
backend/
├── agents/                          # AI agent implementations
│   ├── __init__.py
│   ├── base.py                      # Base agent: Anthropic client, Martian proxy, prompt loading
│   ├── pipeline.py                  # Orchestrator: coordinates all agents, handles retries
│   ├── section_analyzer.py          # Agent 1: identifies visualizable concepts
│   ├── visualization_planner.py     # Agent 2: creates storyboards
│   ├── manim_generator.py           # Agent 3: generates Manim Python code
│   ├── code_validator.py            # Validator 1: AST syntax, imports, structure
│   ├── spatial_validator.py         # Validator 2: positioning, overlaps, bounds
│   ├── render_tester.py             # Validator 3: runtime import testing
│   └── voiceover_generator.py       # Agent 4: AI narration with ElevenLabs
│
├── models/                          # Pydantic data models
│   ├── __init__.py
│   ├── paper.py                     # StructuredPaper, Section, Equation (input from Team 1)
│   ├── generation.py                # VisualizationCandidate, Plan, Code, Visualization (output)
│   └── spatial.py                   # PositionInfo, BoundsIssue, OverlapIssue
│
├── prompts/                         # Claude prompt templates
│   ├── __init__.py
│   ├── section_analyzer.md          # "Which sections need visualization?"
│   ├── visualization_planner.md     # "Create a scene-by-scene storyboard"
│   ├── manim_generator.md           # "Write Manim code from this plan"
│   ├── voiceover_generator.md       # "Generate educational narration"
│   └── system/
│       ├── __init__.py
│       └── manim_reference.md       # Curated Manim API reference (system prompt)
│
├── examples/                        # Few-shot Manim code examples
│   ├── __init__.py
│   ├── equation_walkthrough.py      # equation type
│   ├── architecture_diagram.py      # architecture type
│   ├── data_flow.py                 # data_flow type
│   ├── algorithm_steps.py           # algorithm type
│   ├── matrix_operations.py         # matrix type
│   └── three_d_network.py           # three_d type
│
├── tools/run_demo.py                # Demo runner (generate + render)
├── tools/test_pipeline.py           # Test harness (offline + online)
├── test_voiceover.py                # Voiceover-specific tests
├── pyproject.toml                   # Project config + dependencies (uv)
├── uv.lock                          # Locked dependency versions
├── requirements.txt                 # Pip-compatible dependency list
├── .env.example                     # API key template
└── .env                             # Your actual API keys (DO NOT COMMIT)
```

---

## Agent Specifications

### Agent 1: SectionAnalyzer (`agents/section_analyzer.py`)

**Purpose:** Read each paper section and decide if it needs visualization, and what type.

**Prompt:** `prompts/section_analyzer.md`

**Input:**
```python
paper_title: str        # "Attention Is All You Need"
paper_abstract: str     # Full abstract for context
section: Section        # Section object from Team 1 (id, title, content, equations)
```

**Output:** `AnalyzerOutput`
```python
class AnalyzerOutput:
    section_id: str
    needs_visualization: bool
    candidates: list[VisualizationCandidate]  # Concepts to visualize
    reasoning: str                             # Why this decision
```

**Decision criteria (encoded in prompt):**
- Architecture diagrams, attention mechanisms → YES (priority 5)
- Complex equations with multiple terms → YES (priority 4)
- Algorithm step-by-step descriptions → YES (priority 3)
- Data flow / tensor transformations → YES (priority 4)
- Related work discussions → NO
- References / bibliography → NO
- Short sections (<100 chars) → SKIPPED (before Claude call)

**Visualization types:** `architecture`, `equation`, `algorithm`, `data_flow`, `matrix`, `three_d`

---

### Agent 2: VisualizationPlanner (`agents/visualization_planner.py`)

**Purpose:** Create a detailed scene-by-scene storyboard for each concept.

**Prompt:** `prompts/visualization_planner.md`

**Input:**
```python
candidate: VisualizationCandidate  # From analyzer
full_section_content: str          # Full text of the section
paper_context: str                 # Title + abstract
```

**Output:** `VisualizationPlan`
```python
class VisualizationPlan:
    concept_name: str
    visualization_type: VisualizationType
    duration_seconds: int       # 15-60s (clamped)
    scenes: list[Scene]         # 3-5 scenes typically
    narration_points: list[str] # Educational explanations per scene
```

**Guidelines encoded in prompt:**
- 3-5 focused scenes (not 8-10 rushed ones)
- Total duration 15-30 seconds ideal
- Color coding convention: BLUE=Query, GREEN=Key/Value, RED=Loss, PURPLE=Weights
- Narration points must be concept-focused (not "display the title")
- Build complexity gradually: simple → complex

---

### Agent 3: ManimGenerator (`agents/manim_generator.py`)

**Purpose:** Generate complete, working Manim Python code from a storyboard.

**Prompt:** `prompts/manim_generator.md` | **System prompt:** `prompts/system/manim_reference.md`

**Key feature - Few-shot example matching:**
```python
EXAMPLE_FILES = {
    VisualizationType.EQUATION:     "equation_walkthrough.py",
    VisualizationType.ARCHITECTURE: "architecture_diagram.py",
    VisualizationType.DATA_FLOW:    "data_flow.py",
    VisualizationType.ALGORITHM:    "algorithm_steps.py",
    VisualizationType.MATRIX:       "matrix_operations.py",
    VisualizationType.THREE_D:      "three_d_network.py",
}
```

The generator automatically selects the example that matches the visualization type and includes it in the prompt. This gives Claude a working pattern to follow.

**Input:**
```python
plan: VisualizationPlan   # Storyboard from planner
```

**Output:** `GeneratedCode`
```python
class GeneratedCode:
    code: str               # Complete .py file
    scene_class_name: str   # e.g., "ScaledDotProductAttention"
    dependencies: list[str] # ["manim"]
```

**Retry method:** `run_with_feedback(plan, previous_code, error_message)` accepts validation errors and the broken code, allowing Claude to see exactly what went wrong.

**Important prompt constraints:**
- BasicTeX only (no `\mathcal`, `\mathbb`, custom packages)
- MathTex splitting rules: never split `\frac{}{}` across parts (use `set_color_by_tex()` instead)
- Color coding convention consistent with planner

---

### Validator 1: CodeValidator (`agents/code_validator.py`)

**Purpose:** Static analysis of Python/Manim code quality. No LLM call.

**Checks:**
1. **AST syntax** - `ast.parse()` catches Python syntax errors
2. **Manim import** - ensures `from manim import *` exists
3. **Scene class** - looks for `class Name(Scene):` or `class Name(ThreeDScene):`
4. **Construct method** - looks for `def construct(self):`
5. **MathTex safety** - detects dangerous splitting patterns that crash Manim
6. **Common typos** - auto-fixes color names, method names

**Auto-fixes:**
- Missing `from manim import *` → adds it
- `GREY` → `GRAY`, `DARK_GREY` → `DARK_GRAY`
- `fadein` → `FadeIn`, `fadeout` → `FadeOut`
- Unclosed parentheses/brackets/braces

**Output:** `ValidatorOutput` with `is_valid`, `issues_found`, `issues_fixed`, `needs_regeneration`

---

### Validator 2: SpatialValidator (`agents/spatial_validator.py`)

**Purpose:** Detect positioning and layout problems. No LLM call.

**Checks:**
1. **Out of bounds** - Elements positioned outside screen (|x|>7 or |y|>4)
2. **Near edge** - Elements in unsafe area (|x|>6 or |y|>3.5)
3. **Overlaps** - Two elements at similar coordinates
4. **Missing spacing** - `next_to()` or `arrange()` without `buff` parameter
5. **Large shifts** - `DOWN * 5` etc. that push elements off screen

**Method:** Regex-based extraction of `shift()`, `move_to()`, `next_to()`, `to_edge()`, `to_corner()` calls; parses direction vectors and scalar multipliers.

**Regeneration threshold:** 2+ bounds issues or 2+ overlaps triggers regeneration.

---

### Validator 3: RenderTester (`agents/render_tester.py`)

**Purpose:** Runtime validation by actually importing the code. No LLM call.

**Method:**
1. Write code to temp file
2. `compile()` - catches syntax errors with line numbers
3. `importlib.util.spec_from_file_location()` + `exec_module()` - catches runtime errors
4. Check that a Scene class with `construct()` method exists
5. 30-second timeout (Manim imports can be slow)

**Catches:** NameError, ImportError, TypeError, AttributeError, LaTeX errors, ModuleNotFoundError

**Does NOT execute `construct()`** - just verifies the code can be imported. Actual rendering is Team 3's job.

---

### Agent 4: VoiceoverGenerator (`agents/voiceover_generator.py`)

**Purpose:** Add synchronized AI narration to Manim visualizations.

**Prompt:** `prompts/voiceover_generator.md`

**How it works:**
1. Takes narration points from the planner (or generates new ones via LLM)
2. Transforms the code:
   - `from manim import *` → adds `from manim_voiceover import VoiceoverScene` + TTS import
   - `class Name(Scene):` → `class Name(VoiceoverScene):`
   - Adds `self.set_speech_service(ElevenLabsService(...))` at start of `construct()`
   - Finds `# Scene N:` comments → wraps next `self.play()` with voiceover block

**TTS services supported:** gTTS (free, low quality), Azure, ElevenLabs (best), Recorder (manual)

**ElevenLabs config:** Uses `voice_id` (not voice name) to bypass API permission issues. Uses `eleven_flash_v2_5` model for speed. `transcription_model=None` avoids whisper dependency on Python 3.13+.

**Graceful degradation:** If voiceover fails, the visualization is returned without narration.

---

## Pipeline Orchestrator (`agents/pipeline.py`)

**Configuration (top of file):**
```python
MAX_VISUALIZATIONS = 5        # Max per paper
MAX_RETRIES = 3               # Code generation retries
CONCURRENT_ANALYSIS = True    # Analyze sections in parallel
CONCURRENT_GENERATION = True  # Generate visualizations in parallel
ENABLE_SPATIAL_VALIDATION = True
ENABLE_RENDER_TESTING = True
ENABLE_VOICEOVER = True
VOICEOVER_TTS_SERVICE = "elevenlabs"
VOICEOVER_VOICE_NAME = "Adam"
```

**Retry loop (per visualization):**
```
Attempt 1: Generate → Validate [1/3] → [2/3] → [3/3] → Pass or...
Attempt 2: Regenerate (with combined feedback) → Validate → Pass or...
Attempt 3: Regenerate (with combined feedback) → Validate → Pass or FAIL
```

Feedback from all 3 validators is combined into a single message sent to `ManimGenerator.run_with_feedback()`.

---

## Base Agent Class (`agents/base.py`)

All agents inherit from `BaseAgent`, which provides:

1. **Dedalus client routing** - enforces `DEDALUS_API_KEY` and routes all calls via Dedalus
2. **Model name handling** - auto-converts `claude-opus-4-5-20251101` ↔ `anthropic/claude-opus-4-5-20251101`
3. **System prompt** - loads `prompts/system/manim_reference.md` (curated Manim API reference)
4. **Prompt template loading** - reads `.md` files from `prompts/` directory
5. **JSON response parsing** - extracts JSON from markdown code blocks
6. **Code block extraction** - extracts Python code from LLM responses

**API requirement:** `DEDALUS_API_KEY` is required

**Default model:** `claude-opus-4-5-20251101` (best quality, ~60-90s per viz). Change to `claude-sonnet-4-20250514` in `base.py` line 25 for faster but slightly lower quality.

---

## Data Models

### Input from Team 1: `models/paper.py`

```python
StructuredPaper
├── meta: ArxivPaperMeta
│   ├── arxiv_id: str          # "1706.03762"
│   ├── title: str
│   ├── authors: list[str]
│   ├── abstract: str
│   ├── pdf_url: str
│   └── html_url: str | None
│
└── sections: list[Section]
    ├── id: str                # "section-3-2"
    ├── title: str             # "Scaled Dot-Product Attention"
    ├── level: int             # 1=H1, 2=H2, etc.
    ├── content: str           # Section body text
    ├── equations: list[Equation]
    │   ├── latex: str         # Raw LaTeX
    │   ├── context: str       # Surrounding text
    │   └── is_inline: bool
    ├── figures: list[Figure]
    └── parent_id: str | None  # For nesting
```

### Output to Team 3: `models/generation.py`

```python
Visualization
├── id: str                    # "viz_abc12345"
├── section_id: str            # Which paper section
├── concept: str               # "Scaled Dot-Product Attention"
├── storyboard: str            # JSON of VisualizationPlan
├── manim_code: str            # Complete .py file (with voiceover if enabled)
├── video_url: str | None      # Filled by Team 3 after rendering
└── status: VisualizationStatus  # pending → rendering → complete
```

---

## Running Tests

```bash
cd backend

# Offline (no API key needed) - tests models + code validator
uv run python tools/test_pipeline.py

# Online - test individual agents
uv run python tools/test_pipeline.py --online --test analyzer     # Section analysis
uv run python tools/test_pipeline.py --online --test planner      # Storyboard planning
uv run python tools/test_pipeline.py --online --test generator    # Manim code generation
uv run python tools/test_pipeline.py --online --test pipeline     # Full pipeline (1 viz)

# Demo - generate + save code
uv run python tools/run_demo.py                                   # 2 visualizations
uv run python tools/run_demo.py --max 3 --verbose                 # 3 viz + debug logs
uv run python tools/run_demo.py --render --quality low            # Generate + render
```

---

## Handoff to Team 3

Team 2 outputs `list[Visualization]`. Each visualization has:
- `manim_code`: Complete, validated `.py` file ready to render with `uv run manim -qm file.py`
- `concept`: Human-readable name (used for filenames, UI labels)
- `section_id`: Maps back to the paper section
- `status`: `"pending"` (Team 3 changes to `"rendering"` → `"complete"`)
- `video_url`: `None` (Team 3 fills this after rendering)

Team 3 will:
1. Send `.py` file to Modal.com for cloud rendering
2. Store the output `.mp4` in S3/R2
3. Update `video_url` with the public URL
4. Display in the Next.js scrollytelling frontend

---

## How to Improve the Pipeline

### Highest Impact

1. **Better few-shot examples** (`examples/`) - Adding more diverse, high-quality examples directly improves generated code. Add examples for: GAN architectures, diffusion process, RL environments, loss landscapes, embedding spaces.

2. **Prompt tuning** (`prompts/`) - The manim_generator.md prompt has the biggest impact on code quality. Add more constraints, anti-patterns, and working patterns.

3. **Connect to Team 1** - Replace hardcoded mock papers with real arXiv paper data. The pipeline is already dynamic and works for any paper content.

4. **Model selection** - Switch between Opus (best, slow) and Sonnet (good, fast) in `agents/base.py` line 25.

### Medium Impact

5. **Add visualization types** - Add to `VisualizationType` enum + create matching example file + add guidance to planner prompt. Ideas: `comparison`, `training_loop`, `embedding_space`, `loss_landscape`.

6. **Improve spatial validator** - Better heuristics for detecting overlaps, especially for `VGroup.arrange()` chains.

7. **Add more auto-fixes** to code validator - Common LLM mistakes like wrong color names, deprecated API usage.

### Lower Impact

8. **Toggle pipeline features** - Disable voiceovers for speed, disable spatial validation for less strict checks. Edit `agents/pipeline.py` config section.

9. **Add more ElevenLabs voices** - Update `ELEVENLABS_VOICES` dict in `agents/voiceover_generator.py`.

10. **Caching** - Cache LLM responses for identical section inputs to avoid redundant API calls during development.
