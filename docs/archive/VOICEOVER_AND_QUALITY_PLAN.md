# Voiceover & Script Quality Plan

## The Problem You’re Nailing

- **Script quality** = what the voice is *saying* (educational, clear, aligned to the visual), not TTS glitches.
- Right now the script often feels off because:
  1. **Narration is written before the animation exists** – planner’s `narration_points` are generic; the actual Manim code is generated later, so “Scene 2” text may not match what Scene 2 actually shows.
  2. **Placement is heuristic** – we put narration only on the *first* `self.play()` after `# Scene N:`, so one line carries a whole scene and may not match the exact beat.
  3. **No sync to audio length** – we don’t use `run_time=tracker.duration`, so animation length and voice length can mismatch (unlike the Recorder example).

So: same model that designs the animation should also write the words and place them in the code, and we should validate that the script is educational and not animation-command language.

---

## Current Flow (What We Have)

```
Planner → narration_points (generic, per “scene”)
    ↓
ManimGenerator → Scene code (no voice)
    ↓
CodeValidator → SpatialValidator → RenderTester
    ↓
VoiceoverGenerator → transforms code:
  - Scene → VoiceoverScene
  - Adds with self.voiceover("...") around first self.play() per # Scene N:
  - Does NOT add run_time=tracker.duration
  - Script = planner’s narration_points (unchanged)
```

**Result:** Script is written before we know the exact animation; placement and sync are best-effort.

---

## Option A: Voice During ManimGenerator (Unified)

**Idea:** One model produces both animation and narration. Generator outputs `VoiceoverScene` with `with self.voiceover(text="...")` and `run_time=tracker.duration` already in the code.

**Flow:**
```
Planner → plan (scenes + optional narration hints)
    ↓
ManimGenerator (voiceover=True) → VoiceoverScene code with:
  - self.set_speech_service(...)
  - with self.voiceover(text="...") as tracker:
        self.play(..., run_time=tracker.duration)
  - Narration text written by same model that writes the animation
    ↓
CodeValidator → SpatialValidator → RenderTester (all still work)
    ↓
Optional: VoiceoverScriptValidator on extracted narration lines
```

**Pros:**
- Script and animation are aligned (same “mind”).
- Correct placement (narration at the exact play that needs it).
- Sync is correct by construction (`run_time=tracker.duration`).
- One less post-step (no separate VoiceoverGenerator transform).

**Cons:**
- ManimGenerator prompt and examples get more complex.
- Need to pass “voiceover enabled” (and maybe TTS service) into generator.
- Validators must accept VoiceoverScene (they already do).

**Verdict:** Best for **script quality** and **sync**. Recommended as the target design.

---

## Option B: Keep Voice After Validators, Improve It

**Idea:** Keep current order (Generator → Validators → VoiceoverGenerator), but:
- Add **VoiceoverScriptValidator** to check narration lines (no “display/show/fade…”, length, concept-focused).
- In VoiceoverGenerator, **inject `run_time=tracker.duration`** when wrapping `self.play()` so animation syncs to audio.
- Tighten planner prompt so `narration_points` are more educational and scene-specific.

**Pros:**
- Smaller change; no refactor of generator.
- Script validator improves quality of what we read; run_time fixes sync.

**Cons:**
- Script is still written before animation exists, so alignment is still approximate.
- Placement still heuristic (first `self.play()` per scene).

**Verdict:** Good **short-term** improvement; script quality will still lag Option A.

---

## Recommendation: Two Phases

- **Phase 1 (now):** Option B  
  - Add VoiceoverScriptValidator.  
  - Inject `run_time=tracker.duration` in VoiceoverGenerator.  
  - Harden manim_generator.md for general quality (and add a VoiceoverScene pattern for when we switch).

- **Phase 2 (next):** Option A  
  - Move voice *into* ManimGenerator: generator outputs VoiceoverScene with voiceover blocks and `run_time=tracker.duration`.  
  - Remove or simplify VoiceoverGenerator (e.g. only for “add voice to existing Scene” if needed).  
  - Run VoiceoverScriptValidator on narrations extracted from generated code (or from generator output if structured).

---

## Where Should Voice Live? (Direct Answers)

- **Should the voice step be done in ManimGenerator or after?**  
  **Best quality:** In ManimGenerator (Option A). Script and animation then match and sync.  
  **Fastest improvement:** Keep it after but add script validation and run_time (Option B).

- **Is placement of the current voice agent “good enough”?**  
  **Functionally:** Yes (after validators, so we only add voice to code that already passes).  
  **For script quality:** No. Placement is heuristic and script comes from planner, not from the actual animation. Moving voice into the generator (Option A) fixes that.

- **Should we add a validator for voice?**  
  **Yes.** A **VoiceoverScriptValidator** that checks:
  - No animation-command verbs (display, show, fade, animate, create, draw, move, write, etc.).
  - Length (e.g. 10–25 words per line).
  - Optional: LLM or rules to ensure “concept-focused, educational” and not describing visuals.

  Run it on the list of narration strings (from planner or from generated code). If it fails, either reject and retry script generation or strip voice and keep silent code.

- **Where to run the script validator?**  
  - **Option B:** After VoiceoverGenerator, on `script.scene_narrations`.  
  - **Option A:** After ManimGenerator, on narrations extracted from the generated code (or from a structured “script” field if the generator returns one).

---

## How to Execute (Concrete Steps)

### Phase 1 (Current PR / immediate work)

1. **VoiceoverScriptValidator (new module)**  
   - Input: `list[str]` (narration lines).  
   - Rules: no forbidden starts (display, show, fade, …), word count 10–25, optional regex/list of “animation” words.  
   - Output: `valid: bool`, `issues: list[str]`, optional `suggested_fixes`.  
   - Used after we have a script (planner or voiceover generator).

2. **VoiceoverGenerator: inject `run_time=tracker.duration`**  
   - When wrapping `self.play(...)` in `with self.voiceover(...) as tracker:`, add `run_time=tracker.duration` to the `self.play()` call (regex or simple string insert before the closing `)` of `self.play(...)`).  
   - Handle multi-line `self.play(` and edge cases (already has `run_time=...` etc.).

3. **manim_generator.md prompt upgrade**  
   - Stricter quality: screen bounds, buff usage, LaTeX rules, color convention.  
   - Add a **VoiceoverScene pattern** section: inherit from VoiceoverScene, `set_speech_service`, `with self.voiceover(text="...") as tracker:` and `self.play(..., run_time=tracker.duration)`.  
   - State that narration text must be: one short sentence per beat, educational, no animation verbs, 10–25 words.  
   - Use this pattern when “voiceover is enabled” (Phase 2); for Phase 1 we can keep generating Scene and still use this as the reference pattern for future move.

4. **Pipeline**  
   - After VoiceoverGenerator, run VoiceoverScriptValidator on `voiceover_output.script.scene_narrations`.  
   - If invalid: log warning, optionally overwrite bad lines with placeholder or skip voice for that viz; do not fail the whole viz.

### Phase 2 (Follow-up)

5. **ManimGenerator: voiceover-aware mode**  
   - Pipeline passes `enable_voiceover: bool` (and maybe TTS service name).  
   - When True, prompt and examples ask for VoiceoverScene with voiceover blocks and `run_time=tracker.duration`; generator writes narration text itself per scene/beat.  
   - Output remains one .py file (VoiceoverScene with voice baked in).

6. **Pipeline**  
   - When `ENABLE_VOICEOVER` is True, call ManimGenerator with `enable_voiceover=True`.  
   - Skip or simplify VoiceoverGenerator (no more regex transform).  
   - Run VoiceoverScriptValidator on narrations extracted from generated code (or from generator if it returns structured script).

7. **Docs**  
   - Update README/AGENT_ANALYSIS to describe “voice during generation” and script validator.

---

## How to Formulate This for Codex (or Another Agent)

You can paste something like this:

**Goal:** Improve voiceover script quality (what the voice says) and sync (animation length = audio length). Prefer moving voice into ManimGenerator so the same model writes animation and narration.

**Tasks:**  
1. Add `VoiceoverScriptValidator`: input list of narration strings; check no animation-command verbs, length 10–25 words; output valid + issues.  
2. In VoiceoverGenerator, when wrapping `self.play()` in a voiceover block, add `run_time=tracker.duration` to the play call so animation syncs to audio.  
3. Upgrade `prompts/manim_generator.md`: stricter quality rules and a VoiceoverScene pattern (VoiceoverScene, `with self.voiceover(text="...") as tracker:` and `self.play(..., run_time=tracker.duration)`), plus rules that narration must be educational and 10–25 words.  
4. After VoiceoverGenerator in the pipeline, run VoiceoverScriptValidator on the script; on failure log and optionally drop or fix bad lines.  
5. (Phase 2) Add `enable_voiceover` to ManimGenerator and pipeline; when True, generator outputs VoiceoverScene with voiceover blocks and run_time=tracker.duration; remove/simplify VoiceoverGenerator transform and run script validator on extracted narrations.

**Constraints:** Don’t break existing runs when voiceover is disabled. Keep validators (CodeValidator, SpatialValidator, RenderTester) working on both Scene and VoiceoverScene.

That gives a clear, executable plan and separates Phase 1 (quick wins) from Phase 2 (unified voice in generator).
