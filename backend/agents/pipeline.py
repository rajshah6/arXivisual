"""
Pipeline Orchestration - Coordinates all agents to generate visualizations.

Main pipeline (quality-first voice mode):
  SectionAnalyzer -> VisualizationPlanner -> ManimGenerator (voice-aware)
  -> CodeValidator -> SpatialValidator -> VoiceoverScriptValidator -> RenderTester

Legacy fallback mode (disabled by default):
  ... -> RenderTester -> VoiceoverGenerator
"""

import asyncio
import logging
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

# Handle both package and direct imports
try:
    from ..models.paper import StructuredPaper
    from ..models.generation import (
        Visualization,
        VisualizationCandidate,
        VisualizationPlan,
        GeneratedCode,
        ValidatorOutput,
        VisualizationStatus,
    )
    from ..models.spatial import SpatialValidatorOutput
    from ..models.voiceover import VoiceoverValidationOutput
    from .section_analyzer import SectionAnalyzer
    from .visualization_planner import VisualizationPlanner
    from .manim_generator import ManimGenerator
    from .code_validator import CodeValidator
    from .spatial_validator import SpatialValidator
    from .render_tester import RenderTester, RenderTestOutput
    from .voiceover_script_validator import VoiceoverScriptValidator
    from .voiceover_generator import VoiceoverGenerator, VoiceoverOutput
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from models.paper import StructuredPaper
    from models.generation import (
        Visualization,
        VisualizationCandidate,
        VisualizationPlan,
        GeneratedCode,
        ValidatorOutput,
        VisualizationStatus,
    )
    from models.spatial import SpatialValidatorOutput
    from models.voiceover import VoiceoverValidationOutput
    from agents.section_analyzer import SectionAnalyzer
    from agents.visualization_planner import VisualizationPlanner
    from agents.manim_generator import ManimGenerator
    from agents.code_validator import CodeValidator
    from agents.spatial_validator import SpatialValidator
    from agents.render_tester import RenderTester, RenderTestOutput
    from agents.voiceover_script_validator import VoiceoverScriptValidator
    from agents.voiceover_generator import VoiceoverGenerator, VoiceoverOutput


logger = logging.getLogger(__name__)


# Core configuration
MAX_VISUALIZATIONS = 5
MAX_RETRIES = 3
CONCURRENT_ANALYSIS = True
CONCURRENT_GENERATION = True
ENABLE_SPATIAL_VALIDATION = True
ENABLE_RENDER_TESTING = True

# Voiceover configuration
ENABLE_VOICEOVER = True
VOICEOVER_TTS_SERVICE = "elevenlabs"  # gtts, azure, elevenlabs, recorder
VOICEOVER_VOICE_NAME = "Custom"
VOICEOVER_NARRATION_STYLE = "friendly_tutor"
VOICEOVER_TARGET_DURATION_SECONDS = (30, 45)

# Voice mode and quality policy
VOICE_MODE = "unified_generator"  # unified_generator | legacy_post_transform
VOICE_QUALITY_STRICT = True
VOICE_QUALITY_RETRIES = 2
VOICE_FAIL_BEHAVIOR = "drop_viz"  # drop_viz | return_silent | hard_error


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


async def generate_visualizations(
    paper: StructuredPaper,
    max_visualizations: int = MAX_VISUALIZATIONS,
) -> list[Visualization]:
    """Generate validated visualizations from a structured paper."""
    logger.info("Starting visualization generation for paper: %s", paper.meta.title)
    logger.info(
        "Pipeline config: max_viz=%s, spatial=%s, render=%s, voice=%s, voice_mode=%s",
        max_visualizations,
        ENABLE_SPATIAL_VALIDATION,
        ENABLE_RENDER_TESTING,
        ENABLE_VOICEOVER,
        VOICE_MODE,
    )

    analyzer = SectionAnalyzer()
    planner = VisualizationPlanner()
    generator = ManimGenerator()
    validator = CodeValidator()
    spatial_validator = SpatialValidator() if ENABLE_SPATIAL_VALIDATION else None
    voiceover_script_validator = (
        VoiceoverScriptValidator(strict=VOICE_QUALITY_STRICT)
        if ENABLE_VOICEOVER and VOICE_MODE == "unified_generator"
        else None
    )
    render_tester = RenderTester() if ENABLE_RENDER_TESTING else None
    legacy_voiceover_generator = (
        VoiceoverGenerator(tts_service=VOICEOVER_TTS_SERVICE, voice_name=VOICEOVER_VOICE_NAME)
        if ENABLE_VOICEOVER and VOICE_MODE == "legacy_post_transform"
        else None
    )

    logger.info(
        "  Agents ready: Analyzer, Planner, Generator, Validator%s%s%s%s",
        ", SpatialValidator" if spatial_validator else "",
        ", VoiceoverScriptValidator" if voiceover_script_validator else "",
        ", RenderTester" if render_tester else "",
        f", LegacyVoiceoverGenerator ({VOICEOVER_TTS_SERVICE})" if legacy_voiceover_generator else "",
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
                legacy_voiceover_generator=legacy_voiceover_generator,
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
                legacy_voiceover_generator=legacy_voiceover_generator,
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
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to analyze section %s: %s", section.id, exc)

    return candidates


async def generate_single_visualization(
    candidate: VisualizationCandidate,
    paper: StructuredPaper,
    planner: VisualizationPlanner,
    generator: ManimGenerator,
    validator: CodeValidator,
    spatial_validator: Optional[SpatialValidator] = None,
    voiceover_script_validator: Optional[VoiceoverScriptValidator] = None,
    render_tester: Optional[RenderTester] = None,
    legacy_voiceover_generator: Optional[VoiceoverGenerator] = None,
) -> Optional[Visualization]:
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

        code_result: Optional[GeneratedCode] = None
        validation: Optional[ValidatorOutput] = None
        spatial_result: Optional[SpatialValidatorOutput] = None
        voice_result: Optional[VoiceoverValidationOutput] = None
        render_result: Optional[RenderTestOutput] = None
        legacy_voiceover_output: Optional[VoiceoverOutput] = None

        voiceover_enabled_for_generation = ENABLE_VOICEOVER and VOICE_MODE == "unified_generator"
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

            # Stage 1: code validation
            logger.info("    [1/4] CodeValidator: Checking syntax & structure...")
            validation = validator.validate(code_result.code)
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

                voice_result = voiceover_script_validator.validate(
                    generated_code=code_result,
                    plan=plan,
                    candidate=candidate,
                )

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

        # Legacy voiceover mode remains available but disabled by default.
        if ENABLE_VOICEOVER and VOICE_MODE == "legacy_post_transform" and legacy_voiceover_generator:
            logger.info("  Applying legacy VoiceoverGenerator transform...")
            legacy_voiceover_output = await legacy_voiceover_generator.run(plan=plan, manim_code=final_code)
            final_code = legacy_voiceover_output.transformed_code

        return Visualization(
            id=viz_id,
            section_id=candidate.section_id,
            concept=candidate.concept_name,
            storyboard=plan.model_dump_json(),
            manim_code=final_code,
            video_url=None,
            status=VisualizationStatus.PENDING,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to generate visualization %s: %s", viz_id, exc)
        return None


def generate_visualizations_sync(
    paper: StructuredPaper,
    max_visualizations: int = MAX_VISUALIZATIONS,
) -> list[Visualization]:
    """Synchronous wrapper for testing."""
    return asyncio.run(generate_visualizations(paper, max_visualizations))
