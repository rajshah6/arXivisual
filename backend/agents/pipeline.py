"""
Pipeline Orchestration - Coordinates all agents to generate visualizations.

Main pipeline (quality-first voice mode):
  SectionAnalyzer -> VisualizationPlanner -> ManimGenerator (voice-aware)
  -> CodeValidator -> SpatialValidator -> VoiceoverScriptValidator -> RenderTester
"""

import asyncio
import logging
import os
import re
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

try:
    from langfuse import observe
except ImportError:  # langfuse optional — degrade to no-op decorator
    def observe(*_args, **_kwargs):
        def _decorator(fn):
            return fn
        return _decorator

# Handle both package and direct imports
try:
    from ..models.generation import (
        GeneratedCode,
        ValidatorOutput,
        Visualization,
        VisualizationCandidate,
        VisualizationStatus,
    )
    from ..models.paper import StructuredPaper
    from ..models.spatial import SpatialValidatorOutput
    from ..models.voiceover import VoiceoverValidationOutput
    from .code_validator import CodeValidator
    from .manim_generator import ManimGenerator
    from .render_tester import RenderTester, RenderTestOutput
    from .section_analyzer import SectionAnalyzer
    from .spatial_validator import SpatialValidator
    from .visualization_planner import VisualizationPlanner
    from .voiceover_script_validator import VoiceoverScriptValidator
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.code_validator import CodeValidator
    from agents.manim_generator import ManimGenerator
    from agents.render_tester import RenderTester, RenderTestOutput
    from agents.section_analyzer import SectionAnalyzer
    from agents.spatial_validator import SpatialValidator
    from agents.visualization_planner import VisualizationPlanner
    from agents.voiceover_script_validator import VoiceoverScriptValidator
    from models.generation import (
        GeneratedCode,
        ValidatorOutput,
        Visualization,
        VisualizationCandidate,
        VisualizationStatus,
    )
    from models.paper import StructuredPaper
    from models.spatial import SpatialValidatorOutput
    from models.voiceover import VoiceoverValidationOutput


logger = logging.getLogger(__name__)


# Core configuration
MAX_VISUALIZATIONS = 5
MAX_RETRIES = 3
CONCURRENT_ANALYSIS = True
CONCURRENT_GENERATION = True
ENABLE_SPATIAL_VALIDATION = True

# Skip local render testing when rendering is offloaded to Modal —
# Modal has its own complete environment (manim, ffmpeg, cairo, pkg_resources).
# The local import test fails on hosts without those system deps (e.g. Render native Python).
RENDER_MODE = os.getenv("RENDER_MODE", "local")
ENABLE_RENDER_TESTING = RENDER_MODE != "modal"

# Voiceover configuration
# TTS defaults to Azure OpenAI (gpt-4o-mini-tts, routed via the OpenAI-compatible
# endpoint at render time); set VOICEOVER_TTS_SERVICE=gtts for the free fallback.
ENABLE_VOICEOVER = True
VOICEOVER_TTS_SERVICE = os.getenv("VOICEOVER_TTS_SERVICE", "openai")
VOICEOVER_VOICE_NAME = os.getenv("VOICEOVER_VOICE_NAME", "nova")
VOICEOVER_NARRATION_STYLE = "friendly_tutor"
VOICEOVER_TARGET_DURATION_SECONDS = (30, 45)

# Voice quality policy. Narration is produced by the unified (voice-aware)
# ManimGenerator; there is no separate post-transform voice step.
VOICE_QUALITY_STRICT = True
VOICE_QUALITY_RETRIES = 2
VOICE_FAIL_BEHAVIOR = "return_silent"  # drop_viz | return_silent | hard_error

# Optional observation seam for the eval harness (backend/evals). When set, it
# is called after every quality gate as metrics_hook(gate_name, attempt, passed).
# None (the default) changes no behavior.
metrics_hook: Callable[[str, int, bool], None] | None = None


def _report_gate(gate: str, attempt: int, passed: bool) -> None:
    if metrics_hook is not None:
        try:
            metrics_hook(gate, attempt, passed)
        except Exception:
            logger.debug("metrics_hook raised for gate %s", gate, exc_info=True)


def _extract_voiceover_metadata(code: str) -> tuple[list[str], list[str]]:
    """Extract narration lines and beat labels from generated code."""
    narrations = re.findall(
        r'with\s+self\.voiceover\s*\(\s*text\s*=\s*"([^"]+)"\s*\)\s+as\s+tracker\s*:',
        code,
    )
    if not narrations:
        narrations = re.findall(
            r'with\s+self\.voiceover\s*\(\s*"([^"]+)"\s*\)\s+as\s+tracker\s*:',
            code,
        )

    beats = []
    for line in code.splitlines():
        stripped = line.strip()
        if re.match(r"#\s*Beat\s*\d+", stripped, re.IGNORECASE):
            beats.append(stripped)

    return [n.strip() for n in narrations if n.strip()], beats


@observe(name="generate-visualizations", capture_input=False)
async def generate_visualizations(
    paper: StructuredPaper,
    max_visualizations: int = MAX_VISUALIZATIONS,
) -> list[Visualization]:
    """Generate validated visualizations from a structured paper."""
    logger.info("Starting visualization generation for paper: %s", paper.meta.title)
    logger.info(
        "Pipeline config: max_viz=%s, spatial=%s, render=%s, voice=%s",
        max_visualizations,
        ENABLE_SPATIAL_VALIDATION,
        ENABLE_RENDER_TESTING,
        ENABLE_VOICEOVER,
    )

    analyzer = SectionAnalyzer()
    planner = VisualizationPlanner()
    generator = ManimGenerator()
    validator = CodeValidator()
    spatial_validator = SpatialValidator() if ENABLE_SPATIAL_VALIDATION else None
    voiceover_script_validator = (
        VoiceoverScriptValidator(strict=VOICE_QUALITY_STRICT)
        if ENABLE_VOICEOVER
        else None
    )
    render_tester = RenderTester() if ENABLE_RENDER_TESTING else None

    logger.info(
        "  Agents ready: Analyzer, Planner, Generator, Validator%s%s%s",
        ", SpatialValidator" if spatial_validator else "",
        ", VoiceoverScriptValidator" if voiceover_script_validator else "",
        ", RenderTester" if render_tester else "",
    )

    logger.info("=" * 50)
    logger.info("STEP 1: Analyzing sections for visualization candidates")
    candidates = await _analyze_all_sections(analyzer, paper)

    if not candidates:
        logger.warning("No visualization candidates found in paper")
        return []

    candidates.sort(key=lambda x: x.priority, reverse=True)
    candidates = candidates[:max_visualizations]

    logger.info("Found %s visualization candidates", len(candidates))
    for candidate in candidates:
        logger.debug("  - %s (priority: %s)", candidate.concept_name, candidate.priority)

    logger.info("=" * 50)
    logger.info("STEP 2-7: Planning, generating, and quality validation")

    if CONCURRENT_GENERATION:
        tasks = [
            generate_single_visualization(
                candidate=candidate,
                paper=paper,
                planner=planner,
                generator=generator,
                validator=validator,
                spatial_validator=spatial_validator,
                voiceover_script_validator=voiceover_script_validator,
                render_tester=render_tester,
            )
            for candidate in candidates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        visualizations: list[Visualization] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Visualization generation failed: %s", result)
            elif result is not None:
                visualizations.append(result)
    else:
        visualizations = []
        for candidate in candidates:
            viz = await generate_single_visualization(
                candidate=candidate,
                paper=paper,
                planner=planner,
                generator=generator,
                validator=validator,
                spatial_validator=spatial_validator,
                voiceover_script_validator=voiceover_script_validator,
                render_tester=render_tester,
            )
            if viz is not None:
                visualizations.append(viz)

    logger.info("Successfully generated %s visualizations", len(visualizations))
    return visualizations


async def _analyze_all_sections(
    analyzer: SectionAnalyzer,
    paper: StructuredPaper,
) -> list[VisualizationCandidate]:
    """Analyze all paper sections to find visualization candidates."""
    candidates: list[VisualizationCandidate] = []

    skip_titles = {
        "references",
        "bibliography",
        "acknowledgments",
        "acknowledgements",
        "appendix",
        "supplementary",
        "related work",
    }

    sections_to_analyze = [
        section
        for section in paper.sections
        if section.title.lower() not in skip_titles and len(section.content) > 100
    ]

    if CONCURRENT_ANALYSIS:
        tasks = [
            analyzer.run(
                paper_title=paper.meta.title,
                paper_abstract=paper.meta.abstract,
                section=section,
            )
            for section in sections_to_analyze
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("Section analysis failed: %s", result)
            elif result.needs_visualization:
                candidates.extend(result.candidates)
    else:
        for section in sections_to_analyze:
            try:
                result = await analyzer.run(
                    paper_title=paper.meta.title,
                    paper_abstract=paper.meta.abstract,
                    section=section,
                )
                if result.needs_visualization:
                    candidates.extend(result.candidates)
            except Exception as exc:
                logger.error("Failed to analyze section %s: %s", section.id, exc)

    return candidates


@observe(name="generate-single-visualization", capture_input=False)
async def generate_single_visualization(
    candidate: VisualizationCandidate,
    paper: StructuredPaper,
    planner: VisualizationPlanner,
    generator: ManimGenerator,
    validator: CodeValidator,
    spatial_validator: SpatialValidator | None = None,
    voiceover_script_validator: VoiceoverScriptValidator | None = None,
    render_tester: RenderTester | None = None,
) -> Visualization | None:
    """Generate one visualization with strict quality gates."""
    viz_id = f"viz_{uuid.uuid4().hex[:8]}"
    logger.info("")
    logger.info("%s", "─" * 50)
    logger.info("Generating: %s", candidate.concept_name)
    logger.info("  ID: %s", viz_id)
    logger.info("  Type: %s", candidate.visualization_type)
    logger.info("  Priority: %s/5", candidate.priority)

    try:
        section = paper.get_section_by_id(candidate.section_id)
        section_content = section.content if section else ""

        logger.info("  Creating visualization plan (storyboard)...")
        plan = await planner.run(
            candidate=candidate,
            full_section_content=section_content,
            paper_context=paper.get_context(),
        )
        logger.info("  Plan ready: %s scenes, %ss target", len(plan.scenes), plan.duration_seconds)

        code_result: GeneratedCode | None = None
        validation: ValidatorOutput | None = None
        spatial_result: SpatialValidatorOutput | None = None
        voice_result: VoiceoverValidationOutput | None = None
        render_result: RenderTestOutput | None = None

        voiceover_enabled_for_generation = ENABLE_VOICEOVER
        max_attempts = MAX_RETRIES + (VOICE_QUALITY_RETRIES if voiceover_enabled_for_generation else 0)

        for attempt in range(max_attempts):
            logger.info("  Attempt %s/%s...", attempt + 1, max_attempts)

            feedback_parts: list[str] = []
            if attempt == 0:
                code_result = await generator.run(
                    plan=plan,
                    voiceover_enabled=voiceover_enabled_for_generation,
                    tts_service=VOICEOVER_TTS_SERVICE,
                    voice_name=VOICEOVER_VOICE_NAME,
                    narration_style=VOICEOVER_NARRATION_STYLE,
                    target_duration_seconds=VOICEOVER_TARGET_DURATION_SECONDS,
                )
            else:
                if validation and validation.issues_found:
                    feedback_parts.append("SYNTAX / STRUCTURE ISSUES:\n" + "\n".join(validation.issues_found))
                if spatial_result and spatial_result.has_spatial_issues:
                    feedback_parts.append(spatial_result.get_feedback_message())
                if voice_result and voice_result.issues_found:
                    feedback_parts.append(voice_result.get_feedback_message())
                if render_result and not render_result.success:
                    feedback_parts.append(render_result.get_feedback_message())

                combined_feedback = "\n\n".join(feedback_parts) if feedback_parts else "Unknown issue; regenerate with cleaner structure and narration alignment."
                code_result = await generator.run_with_feedback(
                    plan=plan,
                    previous_code=code_result.code if code_result else "",
                    error_message=combined_feedback,
                    voiceover_enabled=voiceover_enabled_for_generation,
                    tts_service=VOICEOVER_TTS_SERVICE,
                    voice_name=VOICEOVER_VOICE_NAME,
                    narration_style=VOICEOVER_NARRATION_STYLE,
                    target_duration_seconds=VOICEOVER_TARGET_DURATION_SECONDS,
                )

            # Clear the previous attempt's gate results now that this attempt's
            # regeneration feedback has been built from them. Otherwise a later
            # attempt that fails early (e.g. at stage 1) would carry forward a
            # stale spatial/voice/render result and feed the model issues that
            # no longer exist.
            validation = None
            spatial_result = None
            voice_result = None
            render_result = None

            # Stage 1: code validation
            logger.info("    [1/4] CodeValidator: Checking syntax & structure...")
            validation = validator.validate(code_result.code)
            _report_gate("code_validator", attempt, validation.is_valid and not validation.needs_regeneration)
            if validation.needs_regeneration or not validation.is_valid:
                logger.warning(
                    "    [1/4] FAILED: %s issues - regenerating",
                    len(validation.issues_found),
                )
                continue
            current_code = validation.code
            if validation.issues_fixed:
                logger.info("    [1/4] Auto-fixed %s minor issues", len(validation.issues_fixed))
            else:
                logger.info("    [1/4] PASSED")

            # Stage 2: spatial validation
            if spatial_validator:
                logger.info("    [2/4] SpatialValidator: Checking positioning...")
                spatial_result = spatial_validator.validate(current_code)
                _report_gate("spatial_validator", attempt, not spatial_result.needs_regeneration)
                if spatial_result.needs_regeneration:
                    logger.warning(
                        "    [2/4] FAILED: bounds=%s overlaps=%s - regenerating",
                        len(spatial_result.out_of_bounds),
                        len(spatial_result.potential_overlaps),
                    )
                    continue
                logger.info("    [2/4] PASSED")
            else:
                logger.info("    [2/4] SpatialValidator: Skipped")

            # Stage 3: strict voiceover quality validation (unified mode)
            if voiceover_enabled_for_generation and voiceover_script_validator:
                logger.info("    [3/4] VoiceoverScriptValidator: Checking narration quality...")
                narrations, beats = _extract_voiceover_metadata(current_code)
                code_result.code = current_code
                code_result.narration_lines = narrations
                code_result.narration_beats = beats
                code_result.voiceover_enabled = True

                # Run the (synchronous, LLM-backed) judge in a worker thread so
                # it doesn't block the event loop. Without this, the sync judge
                # call serializes all 5 gathered visualization tasks at this gate
                # and stalls /api/status polling. Running off-thread also avoids
                # the nested-asyncio.run failure on the Dedalus provider path.
                voice_result = await asyncio.to_thread(
                    voiceover_script_validator.validate,
                    generated_code=code_result,
                    plan=plan,
                    candidate=candidate,
                )
                _report_gate("voiceover_script_validator", attempt, not voice_result.needs_regeneration)

                if voice_result.needs_regeneration:
                    logger.warning(
                        "    [3/4] FAILED: alignment=%.2f educational=%.2f",
                        voice_result.score_alignment,
                        voice_result.score_educational,
                    )
                    continue

                logger.info(
                    "    [3/4] PASSED: alignment=%.2f educational=%.2f",
                    voice_result.score_alignment,
                    voice_result.score_educational,
                )
            else:
                logger.info("    [3/4] VoiceoverScriptValidator: Skipped")

            # Stage 4: render test
            if render_tester:
                logger.info("    [4/4] RenderTester: Testing import & execution...")
                render_result = await render_tester.test_render(current_code)
                _report_gate("render_tester", attempt, render_result.success)
                if not render_result.success:
                    logger.warning(
                        "    [4/4] FAILED: %s - %s",
                        render_result.error_type,
                        (render_result.error_message or "")[:120],
                    )
                    continue
                logger.info("    [4/4] PASSED")
            else:
                logger.info("    [4/4] RenderTester: Skipped")

            code_result.code = current_code
            logger.info("  ✓ All validations passed on attempt %s", attempt + 1)
            break
        else:
            logger.error("  ✗ FAILED after %s attempts", max_attempts)
            if VOICE_FAIL_BEHAVIOR == "hard_error":
                raise RuntimeError(f"Strict quality checks failed for {candidate.concept_name}")
            if VOICE_FAIL_BEHAVIOR == "return_silent":
                logger.warning("  Returning silent visualization based on fallback policy.")
                if code_result:
                    return Visualization(
                        id=viz_id,
                        section_id=candidate.section_id,
                        concept=candidate.concept_name,
                        storyboard=plan.model_dump_json(),
                        manim_code=code_result.code,
                        video_url=None,
                        status=VisualizationStatus.PENDING,
                    )
            # drop_viz default
            return None

        final_code = code_result.code if code_result else ""

        return Visualization(
            id=viz_id,
            section_id=candidate.section_id,
            concept=candidate.concept_name,
            storyboard=plan.model_dump_json(),
            manim_code=final_code,
            video_url=None,
            status=VisualizationStatus.PENDING,
        )

    except Exception as exc:
        logger.error("Failed to generate visualization %s: %s", viz_id, exc)
        return None


def generate_visualizations_sync(
    paper: StructuredPaper,
    max_visualizations: int = MAX_VISUALIZATIONS,
) -> list[Visualization]:
    """Synchronous wrapper for testing."""
    return asyncio.run(generate_visualizations(paper, max_visualizations))
