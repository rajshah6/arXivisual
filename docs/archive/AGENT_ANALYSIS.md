# Deep Dive: Agent Pipeline Analysis

## Voiceover Transformation: Before vs After

### Does Voiceover Degrade Quality?

**NO** - Voiceover does NOT degrade animation quality. It's a **pure code transformation** that:
1. Adds imports (doesn't change existing code)
2. Changes class inheritance (`Scene` → `VoiceoverScene`)
3. Adds TTS setup (one line at start)
4. **Wraps** existing `self.play()` calls with `with self.voiceover(...)` blocks

The animation code itself is **unchanged**. VoiceoverGenerator uses regex-based string manipulation - it doesn't regenerate code or modify animation logic.

### Before Voiceover (from ManimGenerator)

```python
from manim import *

class ScaledDotProductAttention(Scene):
    def construct(self):
        # Scene 1: Title
        title = Text("Attention Mechanism", font_size=44)
        self.play(Write(title))
        self.wait(0.5)
        
        # Scene 2: Show Q, K, V
        q_block = create_matrix_block("Q", BLUE)
        k_block = create_matrix_block("K", ORANGE)
        v_block = create_matrix_block("V", GREEN)
        
        self.play(
            FadeIn(q_block, shift=UP * 0.3),
            FadeIn(k_block, shift=UP * 0.3),
            FadeIn(v_block, shift=UP * 0.3),
        )
        # ... rest of animation code
```

### After Voiceover (from VoiceoverGenerator)

```python
from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.elevenlabs import ElevenLabsService

class ScaledDotProductAttention(VoiceoverScene):  # ← Changed
    def construct(self):
        self.set_speech_service(ElevenLabsService(...))  # ← Added
        
        # Scene 1: Title (no voiceover - title scenes are skipped)
        title = Text("Attention Mechanism", font_size=44)
        self.play(Write(title))
        self.wait(0.5)
        
        # Scene 2: Show Q, K, V
        q_block = create_matrix_block("Q", BLUE)
        k_block = create_matrix_block("K", ORANGE)
        v_block = create_matrix_block("V", GREEN)
        
        # ← WRAPPED with voiceover block
        with self.voiceover("Query vectors search for relevant keys in the input sequence.") as tracker:
            self.play(
                FadeIn(q_block, shift=UP * 0.3),
                FadeIn(k_block, shift=UP * 0.3),
                FadeIn(v_block, shift=UP * 0.3),
            )
        # ... rest unchanged
```

**Key Points:**
- Animation code is **identical** - only wrapped in `with self.voiceover(...)` blocks
- VoiceoverGenerator looks for `# Scene N:` comments and places narration at the **first** `self.play()` after each scene comment
- Scene 1 (title) is skipped - no narration
- Scene 2+ get narrations from `plan.narration_points`

### Why Voiceover is Separate (Not in ManimGenerator)

**Design decision:** Keep ManimGenerator focused on animation code quality. Voiceover is optional and can fail gracefully without breaking the visualization.

**Flow:**
```
ManimGenerator → generates clean Scene code
     ↓
CodeValidator → validates Scene code
     ↓
SpatialValidator → validates positioning
     ↓
RenderTester → validates runtime
     ↓
VoiceoverGenerator → transforms Scene → VoiceoverScene (if enabled)
```

If voiceover fails, the pipeline returns the original Scene code (silent but working).

---

## Agent-by-Agent Deep Dive

### Agent 1: SectionAnalyzer

**File:** `agents/section_analyzer.py` | **Prompt:** `prompts/section_analyzer.md`

#### Input
```python
paper_title: str           # "Attention Is All You Need"
paper_abstract: str         # Full abstract for context
section: Section           # {
                           #   id: "section-3-2",
                           #   title: "Scaled Dot-Product Attention",
                           #   content: "An attention function...",
                           #   equations: [Equation(...)],
                           #   level: 2
                           # }
```

#### Output
```python
AnalyzerOutput {
    section_id: "section-3-2",
    needs_visualization: True,
    reasoning: "Contains core attention formula...",
    candidates: [
        VisualizationCandidate {
            section_id: "section-3-2",
            concept_name: "Scaled Dot-Product Attention",
            concept_description: "Q, K, V matrix flow...",
            visualization_type: VisualizationType.DATA_FLOW,
            priority: 5,  # 1-10 scale
            context: "Attention(Q,K,V) = softmax(...)"
        }
    ]
}
```

#### Bottlenecks & Quality Issues

**Bottleneck:** LLM API call (~5-10 seconds per section)
- **Concurrency:** Sections analyzed in parallel (`CONCURRENT_ANALYSIS = True`)
- **Speed:** ~5 sections × 7s = 35s sequential, ~7s parallel

**Quality Issues:**
1. **False positives:** Sometimes suggests visualization for simple prose
   - **Fix:** Better prompt filtering (already filters "references", "related work")
   - **Fix:** Add priority threshold (currently accepts priority 1-10, could require ≥3)

2. **Wrong visualization type:** May classify "architecture" as "equation"
   - **Fix:** Better examples in prompt showing the difference
   - **Fix:** Post-process: if section has architecture keywords → force type

3. **Too many candidates:** One section might generate 3-4 candidates
   - **Fix:** Already limited by `MAX_VISUALIZATIONS = 5` per paper
   - **Fix:** Could deduplicate similar concepts

**Expected Input Quality:**
- Needs clean section text (Team 1's job)
- Equations should have proper LaTeX (not corrupted)
- Section titles should be meaningful (not "Section 3.2.1")

**Expected Output Quality:**
- ~70% of candidates are good (need visualization)
- ~20% are marginal (could skip)
- ~10% are false positives (should skip)

---

### Agent 2: VisualizationPlanner

**File:** `agents/visualization_planner.py` | **Prompt:** `prompts/visualization_planner.md`

#### Input
```python
candidate: VisualizationCandidate {
    concept_name: "Scaled Dot-Product Attention",
    visualization_type: VisualizationType.DATA_FLOW,
    concept_description: "Q, K, V matrix flow...",
    priority: 5
}
full_section_content: str  # Full section text
paper_context: str          # Title + abstract
```

#### Output
```python
VisualizationPlan {
    concept_name: "Scaled Dot-Product Attention",
    visualization_type: VisualizationType.DATA_FLOW,
    duration_seconds: 24,  # Clamped to 15-60s
    scenes: [
        Scene {
            order: 1,
            description: "Title: 'Attention Mechanism'",
            duration_seconds: 4,
            transitions: "Write",
            elements: ["Text"]
        },
        Scene {
            order: 2,
            description: "Show Q, K, V as colored blocks",
            duration_seconds: 5,
            transitions: "FadeIn",
            elements: ["RoundedRectangle", "Text"]
        },
        # ... more scenes
    ],
    narration_points: [
        "Query vectors search for relevant keys...",
        "The dot product measures similarity...",
        "Softmax converts scores into probabilities..."
    ]
}
```

#### Bottlenecks & Quality Issues

**Bottleneck:** LLM API call (~8-12 seconds per plan)
- **Concurrency:** Plans generated in parallel (`CONCURRENT_GENERATION = True`)
- **Speed:** ~5 plans × 10s = 50s sequential, ~10s parallel

**Quality Issues:**
1. **Too many scenes:** Sometimes plans 8-10 scenes (should be 3-5)
   - **Fix:** Prompt says "3-5 focused scenes" but Claude ignores it
   - **Fix:** Post-process: merge short scenes (<3s) or split long ones (>8s)

2. **Unrealistic durations:** Scene durations don't add up to total
   - **Fix:** Already clamped total to 15-60s, but individual scenes can be wrong
   - **Fix:** Normalize scene durations to sum to `duration_seconds`

3. **Bad narration points:** Sometimes includes animation commands ("Display the title")
   - **Fix:** Already filters bad starts in `_expand_narration_points()`
   - **Fix:** Could use LLM to rewrite narration points to be concept-focused

4. **Vague descriptions:** "Show something" instead of "Show Q, K, V as blue/orange/green blocks"
   - **Fix:** Prompt asks for specific Manim elements, but Claude is vague
   - **Fix:** Add examples of good scene descriptions in prompt

**Expected Input Quality:**
- Candidate should have clear `concept_description`
- Visualization type should match the concept

**Expected Output Quality:**
- ~60% of plans are good (clear scenes, good narration)
- ~30% need minor fixes (too many scenes, vague descriptions)
- ~10% are poor (unclear what to visualize)

---

### Agent 3: ManimGenerator

**File:** `agents/manim_generator.py` | **Prompt:** `prompts/manim_generator.md`

#### Input
```python
plan: VisualizationPlan {
    concept_name: "Scaled Dot-Product Attention",
    visualization_type: VisualizationType.DATA_FLOW,
    duration_seconds: 24,
    scenes: [Scene(...), ...],
    narration_points: [...]
}
```

**Also uses:** Few-shot example from `examples/data_flow.py` (matched by `visualization_type`)

#### Output
```python
GeneratedCode {
    code: "from manim import *\n\nclass ScaledDotProductAttention(Scene):\n    def construct(self):\n        ...",
    scene_class_name: "ScaledDotProductAttention",
    dependencies: ["manim"]
}
```

#### Bottlenecks & Quality Issues

**Bottleneck:** LLM API call (~30-60 seconds per generation, Opus model)
- **Concurrency:** Generations run in parallel (`CONCURRENT_GENERATION = True`)
- **Speed:** ~5 visualizations × 45s = 225s sequential, ~45s parallel
- **Retries:** Up to 3 attempts (if validation fails) = up to 135s per viz worst case

**Quality Issues (THE MAIN BOTTLENECK):**

1. **MathTex splitting errors** (CRITICAL - crashes Manim)
   - **Problem:** Claude splits `\frac{}{}` across MathTex parts: `MathTex(r"\frac{", "x", r"}{y}")`
   - **Why:** Claude tries to highlight parts by splitting, but LaTeX must be valid per-part
   - **Fix:** CodeValidator detects this and forces regeneration
   - **Better fix:** Prompt explicitly says "use `set_color_by_tex()` instead of splitting"

2. **Out-of-bounds positioning** (common)
   - **Problem:** `element.shift(RIGHT * 10)` pushes elements off-screen
   - **Why:** Claude doesn't know screen bounds (x: [-7, 7], y: [-4, 4])
   - **Fix:** SpatialValidator detects and flags, but doesn't always force regeneration
   - **Better fix:** Add screen bounds to system prompt (`manim_reference.md`)

3. **Missing `buff` parameters** (common)
   - **Problem:** `element.next_to(other, DOWN)` - elements touch
   - **Why:** Claude forgets spacing
   - **Fix:** SpatialValidator flags but doesn't force regeneration
   - **Better fix:** Examples should always show `buff=0.3` in `next_to()` calls

4. **Inconsistent color coding** (minor)
   - **Problem:** Uses RED for Query instead of BLUE
   - **Why:** Claude doesn't follow color convention
   - **Fix:** Prompt says "BLUE=Query, GREEN=Key" but Claude ignores
   - **Better fix:** Examples should enforce color convention

5. **Too verbose code** (minor)
   - **Problem:** Generates 200+ lines for a simple visualization
   - **Why:** Claude adds unnecessary helper functions, comments
   - **Fix:** Prompt says "keep it concise" but Claude is verbose
   - **Better fix:** Examples should be concise

6. **Wrong Manim API usage** (occasional)
   - **Problem:** Uses deprecated methods or wrong method names
   - **Why:** System prompt (`manim_reference.md`) might be outdated
   - **Fix:** RenderTester catches runtime errors, forces regeneration
   - **Better fix:** Keep `manim_reference.md` updated with latest Manim API

**Expected Input Quality:**
- Plan should have clear scene descriptions
- Few-shot example should match visualization type

**Expected Output Quality:**
- **First attempt:** ~40% pass all validations
- **After 1 retry:** ~70% pass
- **After 2 retries:** ~85% pass
- **After 3 retries:** ~95% pass (5% fail completely)

**Main Quality Bottleneck:** ManimGenerator is where most quality issues originate. The validators catch them, but retries are slow (30-60s each).

---

### Validator 1: CodeValidator

**File:** `agents/code_validator.py` | **No LLM call** (pure Python)

#### Input
```python
code: str  # Raw Python code from ManimGenerator
```

#### Output
```python
ValidatorOutput {
    is_valid: False,
    code: "from manim import *\n\nclass ...",  # Auto-fixed code
    issues_found: [
        "No Scene class found",
        "CRITICAL: MathTex splits \\frac{} across parts"
    ],
    issues_fixed: [
        "Added missing manim import"
    ],
    needs_regeneration: True  # If >1 unfixed issue or MathTex issue
}
```

#### Bottlenecks & Quality Issues

**Bottleneck:** None - runs in <1ms (AST parse + regex)

**Auto-fixes:**
- Missing `from manim import *` → adds it
- Color typos (`GREY` → `GRAY`)
- Method case (`fadein` → `FadeIn`)
- Unclosed brackets (basic attempt)

**Detection:**
- Python syntax errors (AST parse)
- Missing Scene class (regex)
- Missing construct method (regex)
- **MathTex splitting** (regex - critical!)

**Quality Issues:**
- **Can't fix complex syntax errors** - just detects and flags
- **MathTex detection is heuristic** - might miss edge cases
- **Auto-fixes are basic** - doesn't understand code structure

**Expected Input:** Raw code from ManimGenerator (may have syntax errors)

**Expected Output:** ~60% of code passes on first try, ~40% needs regeneration

---

### Validator 2: SpatialValidator

**File:** `agents/spatial_validator.py` | **No LLM call** (regex-based)

#### Input
```python
code: str  # Validated code from CodeValidator
```

#### Output
```python
SpatialValidatorOutput {
    has_spatial_issues: True,
    out_of_bounds: [
        BoundsIssue {
            element_name: "box1",
            line_number: 15,
            issue: "Element at x=8.0 is outside screen bounds",
            suggested_fix: "Use x position between -6 and 6"
        }
    ],
    potential_overlaps: [
        OverlapIssue {
            element1: "label1",
            element2: "label2",
            issue: "Elements may overlap at (2.0, -2.0)",
            suggested_fix: "Use next_to() with buff=0.5"
        }
    ],
    spacing_issues: [
        SpacingIssue {
            line_number: 20,
            issue: "next_to() called without buff parameter",
            suggested_fix: "Add buff parameter"
        }
    ],
    needs_regeneration: False  # Only if 2+ bounds issues or 2+ overlaps
}
```

#### Bottlenecks & Quality Issues

**Bottleneck:** None - runs in <10ms (regex parsing)

**Detection Method:**
- Parses `shift()`, `move_to()`, `next_to()`, `to_edge()` calls
- Estimates positions from direction vectors (`RIGHT * 5` → x=5)
- Heuristic - can't know exact positions without execution

**Quality Issues:**
- **False positives:** Flags elements that aren't actually off-screen (heuristic is conservative)
- **Misses dynamic positioning:** Can't detect `element.next_to(other)` where `other` position is unknown
- **Can't detect VGroup.arrange() overlaps:** Doesn't parse `arrange()` well

**Expected Input:** Valid Python code (syntax-correct)

**Expected Output:** ~70% have no spatial issues, ~25% have warnings (don't force regeneration), ~5% have critical issues (force regeneration)

---

### Validator 3: RenderTester

**File:** `agents/render_tester.py` | **No LLM call** (runtime import test)

#### Input
```python
code: str  # Validated code from CodeValidator
```

#### Output
```python
RenderTestOutput {
    success: False,
    error_type: "NameError",
    error_message: "name 'InvalidClass' is not defined",
    line_number: 25,
    fix_suggestion: "Check that all variables and Manim classes are properly defined/imported"
}
```

#### Bottlenecks & Quality Issues

**Bottleneck:** Manim import time (~5-15 seconds)
- **Timeout:** 30 seconds (Manim imports can be slow)
- **Runs in thread:** `asyncio.to_thread()` to avoid blocking

**Detection:**
- Compiles code with `compile()` (catches syntax errors with line numbers)
- Imports module with `importlib` (catches NameError, ImportError, TypeError, AttributeError)
- Verifies Scene class exists

**Quality Issues:**
- **Slow:** Manim import takes 5-15s (can't avoid)
- **Can't catch LaTeX errors:** LaTeX compilation happens at render time, not import time
- **Can't catch runtime logic errors:** Only catches import/definition errors

**Expected Input:** Valid Python code (syntax + structure correct)

**Expected Output:** ~80% pass on first try, ~20% have runtime errors (NameError, AttributeError, etc.)

---

### Agent 4: VoiceoverGenerator

**File:** `agents/voiceover_generator.py` | **Prompt:** `prompts/voiceover_generator.md`

#### Input
```python
plan: VisualizationPlan {
    narration_points: ["Query vectors search...", ...]
}
manim_code: str  # Validated code from RenderTester
```

#### Output
```python
VoiceoverOutput {
    transformed_code: str,  # Code with VoiceoverScene + voiceover blocks
    script: VoiceoverScript {
        scene_narrations: ["Query vectors search...", ...]
    },
    tts_service: "elevenlabs"
}
```

#### Bottlenecks & Quality Issues

**Bottleneck:** LLM call only if narration_points are missing (~3-5 seconds)
- **If narration_points exist:** No LLM call, just uses them (instant)
- **If missing:** Generates narrations via LLM (~3-5s)

**Transformation:** Pure regex-based string manipulation (<1ms)

**Quality Issues:**
1. **Narration placement:** Only places at first `self.play()` after `# Scene N:` comment
   - **Problem:** If scene has multiple `self.play()` calls, only first gets narration
   - **Fix:** Could wrap all `self.play()` calls in a scene, but that's verbose

2. **Narration doesn't match animation:** Narration says "Query vectors" but animation shows Q, K, V blocks
   - **Problem:** Narration points from planner might not match actual generated code
   - **Fix:** Could regenerate narrations after seeing the actual code (but adds LLM call)

3. **ElevenLabs API failures:** Sometimes TTS API is down or rate-limited
   - **Problem:** Voiceover fails, but code still works (graceful degradation)
   - **Fix:** Already handles gracefully - returns original code without voiceover

**Expected Input:** Validated Manim code + plan with narration_points

**Expected Output:** ~95% success rate (5% fail due to API issues, but code still works)

---

## Concurrency: Who Handles It?

### Current Implementation

**Pipeline orchestrator** (`agents/pipeline.py`) handles concurrency:

```python
# Step 1: Analyze sections (parallel)
if CONCURRENT_ANALYSIS:
    tasks = [analyzer.run(...) for section in sections]
    results = await asyncio.gather(*tasks)  # ← Parallel execution

# Step 2-4: Generate visualizations (parallel)
if CONCURRENT_GENERATION:
    tasks = [generate_single_visualization(...) for candidate in candidates]
    results = await asyncio.gather(*tasks)  # ← Parallel execution
```

**You control it** via config flags:
- `CONCURRENT_ANALYSIS = True` → sections analyzed in parallel
- `CONCURRENT_GENERATION = True` → visualizations generated in parallel

### Speed Comparison

**Sequential (all flags False):**
- 5 sections × 7s = 35s (analysis)
- 5 visualizations × 45s = 225s (generation)
- **Total: ~260s** (4.3 minutes)

**Parallel (all flags True):**
- max(5 sections × 7s) = 7s (analysis)
- max(5 visualizations × 45s) = 45s (generation)
- **Total: ~52s** (0.9 minutes)

**~5x speedup** with concurrency enabled.

### API Rate Limits

**Martian API:** No rate limits (unlimited for hackathon)
**Anthropic API:** Rate limits apply (check your tier)
- Free tier: ~50 requests/minute
- Paid tier: Higher limits

**Concurrency is safe** with Martian. With direct Anthropic, you might hit rate limits if generating many visualizations simultaneously.

### Future: Team 3 Concurrency

**Team 3** (rendering) will handle their own concurrency:
- Render videos on Modal.com (parallel cloud rendering)
- Not your concern - Team 2 just outputs `.py` files

---

## Quality Bottleneck Summary

**Main bottleneck:** **ManimGenerator** (~60% of quality issues)

**Issues:**
1. MathTex splitting (critical - crashes)
2. Out-of-bounds positioning (common)
3. Missing buff parameters (common)
4. Wrong API usage (occasional)

**Why:** Claude doesn't know Manim's constraints (screen bounds, LaTeX rules, API details)

**Fixes:**
1. **Better few-shot examples** - Show correct patterns
2. **Better system prompt** - Add screen bounds, LaTeX rules to `manim_reference.md`
3. **Better prompt** - More explicit constraints in `manim_generator.md`
4. **Post-processing** - Auto-fix common issues (add buff, clamp positions)

**Speed bottleneck:** LLM API calls (~45s per visualization with Opus)

**Fixes:**
1. Use Sonnet instead of Opus (2-3x faster, slightly lower quality)
2. Cache LLM responses for identical inputs
3. Parallel generation (already implemented)

---

## Expected Input/Output Quality

### Input Quality (from Team 1)

**Good:**
- Clean section text (no OCR errors)
- Proper LaTeX equations (not corrupted)
- Meaningful section titles
- Equations have context

**Bad:**
- OCR errors in text
- Corrupted LaTeX (`\frac{` without closing)
- Generic titles ("Section 3.2.1")
- Missing equation context

### Output Quality (to Team 3)

**Good visualization (70%):**
- Valid Manim code (passes all validations)
- Clear animations (3-5 scenes, 15-30s)
- Proper positioning (within bounds, no overlaps)
- Educational narration (if voiceover enabled)

**Marginal visualization (25%):**
- Valid but verbose code
- Some positioning issues (warnings, not errors)
- Narration might not perfectly match animation

**Poor visualization (5%):**
- Fails after 3 retries
- Unclear what it's visualizing
- Code is valid but animation is confusing

---

## Recommendations for Improving Quality

1. **Improve few-shot examples** (`examples/`) - Highest impact
2. **Update system prompt** (`prompts/system/manim_reference.md`) - Add screen bounds, LaTeX rules
3. **Tune ManimGenerator prompt** (`prompts/manim_generator.md`) - More explicit constraints
4. **Add post-processing** - Auto-fix common issues (buff, bounds clamping)
5. **Better narration matching** - Regenerate narrations after seeing actual code
6. **Switch to Sonnet** - 2-3x faster, slightly lower quality (acceptable tradeoff)
