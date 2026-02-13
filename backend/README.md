# ArXiviz Backend - Team 2 AI Generation Pipeline

This is the core AI pipeline that transforms structured paper data into validated Manim visualization code with AI-generated voiceovers.

---

## Quick Reference

```bash
# All commands from the backend/ directory

# Setup
cp .env.example .env              # Then edit .env with your API keys
uv sync                           # Install all dependencies

# Test
uv run python tools/test_pipeline.py                         # Offline (no API key)
uv run python tools/test_pipeline.py --online                # Full pipeline test
uv run python tools/test_pipeline.py --online --test analyzer    # Individual agent

# Run
uv run python tools/run_demo.py                              # Generate visualizations
uv run python tools/run_demo.py --max 3 --verbose            # 3 visualizations, debug logs
uv run python tools/run_demo.py --render --quality low       # Generate + render at 480p

# Render manually
cd generated_output
uv run manim -ql filename.py                           # Preview quality
uv run manim -qm filename.py                           # Medium quality
```

---

## Environment Setup

### 1. Install uv (if not already installed)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```env
# REQUIRED:
DEDALUS_API_KEY=dsk-your-dedalus-key

# REQUIRED - For AI voiceovers:
ELEVEN_API_KEY=your-elevenlabs-key       # elevenlabs.io free tier works
```

### 3. Install dependencies

```bash
uv sync    # Creates .venv, resolves deps, installs everything
```

That's it. `uv run` automatically uses the virtual environment.

---

## How the Pipeline Works (Step by Step)

Here's exactly what happens when you run `uv run python tools/run_demo.py`:

### Step 0: Input Construction

Currently, `tools/run_demo.py` and `tools/test_pipeline.py` construct a **hardcoded** `StructuredPaper` object simulating what Team 1 would provide. This includes:
- Paper metadata (title, authors, abstract, arXiv ID)
- Sections with their text content
- Equations extracted from each section (LaTeX)

When Team 1 is ready, this will be replaced by actual arXiv paper fetching.

### Step 1: Section Analysis (SectionAnalyzer)

**File:** `agents/section_analyzer.py` | **Prompt:** `prompts/section_analyzer.md`

The pipeline loops through every section and asks Claude: *"Does this section contain concepts that would benefit from a Manim visualization?"*

**Filtering (before sending to Claude):**
- Skips sections titled "References", "Bibliography", "Acknowledgments", "Related Work"
- Skips sections shorter than 100 characters

**What Claude returns (per section):**
```json
{
  "needs_visualization": true,
  "reasoning": "Contains the core attention formula...",
  "candidates": [
    {
      "section_id": "section-3-2",
      "concept_name": "Scaled Dot-Product Attention",
      "concept_description": "Q, K, V matrix flow through dot product...",
      "visualization_type": "data_flow",
      "priority": 5,
      "context": "Attention(Q,K,V) = softmax(QK^T/sqrt(d_k))V"
    }
  ]
}
```

**After analysis:** Candidates are sorted by priority (highest first) and limited to `MAX_VISUALIZATIONS` (default: 5).

### Step 2: Visualization Planning (VisualizationPlanner)

**File:** `agents/visualization_planner.py` | **Prompt:** `prompts/visualization_planner.md`

For each candidate, Claude creates a scene-by-scene storyboard:

```json
{
  "concept_name": "Scaled Dot-Product Attention",
  "duration_seconds": 24,
  "scenes": [
    {"order": 1, "description": "Title: 'Attention Mechanism'", "duration_seconds": 4},
    {"order": 2, "description": "Show Q, K, V as colored blocks", "duration_seconds": 6},
    {"order": 3, "description": "Animate dot product computation", "duration_seconds": 8},
    {"order": 4, "description": "Show softmax + final output", "duration_seconds": 6}
  ],
  "narration_points": [
    "Query vectors search for relevant keys in the input.",
    "The dot product measures similarity between positions.",
    "Softmax normalizes scores into attention weights."
  ]
}
```

The planner now targets a 30-45 second quality window by default.

### Step 3: Manim Code Generation (ManimGenerator)

**File:** `agents/manim_generator.py` | **Prompt:** `prompts/manim_generator.md`

Claude writes complete, runnable Manim Python code. Key features:

**Few-shot example selection:** The generator picks the example file that matches the visualization type:
- `data_flow` candidate → sends `examples/data_flow.py` as reference
- `architecture` candidate → sends `examples/architecture_diagram.py`
- etc.

This dramatically improves code quality because Claude sees a working pattern to follow.

**System prompt:** `prompts/system/manim_reference.md` is sent as the system message to every LLM call. It's a curated Manim API reference covering mobjects, animations, positioning, colors, and screen dimensions.

**Voice-aware generation (new):**
- If voiceover is enabled, the generator emits `VoiceoverScene` code directly
- It inserts beat-level voice blocks using `with self.voiceover(text=\"...\") as tracker:`
- Narrated `self.play(...)` calls are timed with `run_time=tracker.duration`
- It extracts and returns narration metadata (`narration_lines`, `narration_beats`)

**Output:** A `GeneratedCode` object with code + scene class + narration metadata.

### Step 4: Multi-Stage Validation + Voice Quality Gate

Each generated visualization passes through validation stages. If any fail, combined feedback is sent to `ManimGenerator.run_with_feedback()` for regeneration.

#### Stage 1: CodeValidator (`agents/code_validator.py`)

Pure Python static analysis (no LLM call):
- **AST parse** - catches syntax errors
- **Import check** - ensures `from manim import *` exists (auto-adds if missing)
- **Scene class check** - looks for `class Name(Scene):`
- **Construct method check** - looks for `def construct(self):`
- **MathTex safety** - detects dangerous splitting patterns that crash Manim (e.g., splitting `\frac{}{}` across MathTex arguments)
- **Auto-fixes** - color typos (`GREY`→`GRAY`), method case (`fadein`→`FadeIn`), unclosed brackets

#### Stage 2: SpatialValidator (`agents/spatial_validator.py`)

Regex-based static analysis (no LLM call):
- **Bounds checking** - detects elements positioned outside screen (|x|>7 or |y|>4)
- **Overlap detection** - finds elements at similar positions that may overlap
- **Spacing issues** - flags `next_to()` or `arrange()` calls missing `buff` parameter
- **Positioning suggestions** - recommends relative positioning over hardcoded coordinates

Screen safe area: x in [-6, 6], y in [-3.5, 3.5]

#### Stage 3: VoiceoverScriptValidator (`agents/voiceover_script_validator.py`)

Strict quality gate for narration (enabled in unified voice mode):
- Requires `VoiceoverScene` and `set_speech_service(...)`
- Requires tracker-timed narrated plays (`run_time=tracker.duration`)
- Rejects narration that starts with animation-command language
- Enforces narration length window (12-24 words)
- Enforces minimum narration coverage across content beats
- Scores alignment and educational quality (thresholds: 0.85 / 0.85)

#### Stage 4: RenderTester (`agents/render_tester.py`)

Runtime validation (no LLM call):
- Writes code to a temp file
- Compiles with `compile()` (catches syntax errors with line numbers)
- Imports the module with `importlib` (catches NameError, ImportError, TypeError, etc.)
- Verifies a Scene class with `construct()` method exists
- 30-second timeout (Manim imports can be slow)

**Retry feedback loop:** When validation fails, the pipeline builds a combined error message like:

```
SYNTAX ISSUES:
- No Scene class found

SPATIAL ISSUES DETECTED:
- Line 15: Element 'box1' at x=8.0 is outside screen bounds

RUNTIME ERROR DETECTED:
- Error Type: NameError
- Error Message: name 'InvalidClass' is not defined
```

This is sent to `ManimGenerator.run_with_feedback()` along with the previous broken code, so Claude can see exactly what went wrong and fix it.

### Step 5: Legacy Voiceover Fallback (optional)

**File:** `agents/voiceover_generator.py`

By default, voice is generated *inside* `ManimGenerator` (unified mode).  
`VoiceoverGenerator` is kept as a legacy post-transform fallback mode and is disabled by default.
Strict fallback policy:
- If voice quality fails after retry budget, visualization is dropped (`VOICE_FAIL_BEHAVIOR=\"drop_viz\"`).

### Step 6: Output

The final `Visualization` object is returned with:
- `manim_code`: Fully validated Python file (with or without voiceover)
- `concept`: What this visualization explains
- `section_id`: Which paper section it belongs to
- `storyboard`: The original plan (JSON) for reference

`tools/run_demo.py` saves each visualization as a `.py` file in `generated_output/`.

---

## Configuration

Pipeline behavior is controlled by constants at the top of `agents/pipeline.py`:

```python
MAX_VISUALIZATIONS = 5      # Max visualizations per paper
MAX_RETRIES = 3             # Code generation retry limit
CONCURRENT_ANALYSIS = True  # Analyze sections in parallel
CONCURRENT_GENERATION = True # Generate visualizations in parallel
ENABLE_SPATIAL_VALIDATION = True   # Check positioning/overlaps
ENABLE_RENDER_TESTING = True       # Runtime import validation
ENABLE_VOICEOVER = True
VOICE_MODE = "unified_generator"      # unified_generator | legacy_post_transform
VOICE_QUALITY_STRICT = True
VOICE_QUALITY_RETRIES = 2
VOICE_FAIL_BEHAVIOR = "drop_viz"      # drop_viz | return_silent | hard_error
VOICEOVER_TTS_SERVICE = "elevenlabs"
VOICEOVER_VOICE_NAME = "Adam"
VOICEOVER_NARRATION_STYLE = "concept_teacher"
VOICEOVER_TARGET_DURATION_SECONDS = (30, 45)
```

### Model Selection

The LLM model is configured in `agents/base.py`:

```python
DEFAULT_MODEL = "claude-opus-4-5-20251101"               # Best quality (~60-90s/viz)
# Change to:
DEFAULT_MODEL = "claude-sonnet-4-20250514"               # Faster (~20-30s/viz)
```

### ElevenLabs Voices

Available voices (configured in `agents/voiceover_generator.py`):

| Voice | ID | Style |
|-------|-----|-------|
| Adam (default) | `pNInz6obpgDQGcFmaJgB` | Deep, warm male |
| Antoni | `ErXwobaYiN019PkySvjV` | Young male |
| Bella | `EXAVITQu4vr4xnSDxMaL` | Friendly female |
| Josh | `TxGEqnHWrfWFTfGW9XjX` | Conversational male |
| Rachel | `21m00Tcm4TlvDq8ikWAM` | Clear female |

---

## Adding a New Visualization Type

1. **Add the type** to `models/generation.py`:
   ```python
   class VisualizationType(str, Enum):
       # ... existing types ...
       COMPARISON = "comparison"  # New!
   ```

2. **Create a few-shot example** at `examples/comparison.py`:
   ```python
   from manim import *

   class ComparisonExample(Scene):
       def construct(self):
           # Your example code here
           pass
   ```

3. **Register it** in `agents/manim_generator.py`:
   ```python
   EXAMPLE_FILES = {
       # ... existing mappings ...
       VisualizationType.COMPARISON: "comparison.py",
   }
   ```

4. **Add guidance** to `prompts/visualization_planner.md`:
   ```markdown
   ### For `comparison` (Before/After, Baseline vs Proposed):
   - Show both approaches side by side
   - Highlight the differences
   - ...
   ```

---

## Troubleshooting

### "No API key found"
- Make sure `.env` exists in the `backend/` directory (not the project root)
- Check the key is not still the placeholder value from `.env.example`

### "Pipeline generated 0 visualizations"
- Check the logs for which stage failed (analyzer, planner, generator, or validation)
- Run with `--verbose` flag for detailed logs
- Try running individual tests: `uv run python tools/test_pipeline.py --online --test analyzer`

### Manim render fails
- Make sure you have LaTeX installed: `brew install --cask basictex` (macOS)
- After installing: `sudo tlmgr update --self && sudo tlmgr install standalone preview`
- Or use `Text()` instead of `MathTex()` in your examples to avoid LaTeX dependency

### Voiceover fails
- Check `ELEVEN_API_KEY` is set in `.env`
- ElevenLabs free tier has character limits - check your usage at elevenlabs.io
- The pipeline continues without voiceovers if this fails (graceful degradation)

### "Module not found" errors
- Run `uv sync` to ensure all dependencies are installed
- Make sure you're running from the `backend/` directory
- Use `uv run python ...` not bare `python ...`
