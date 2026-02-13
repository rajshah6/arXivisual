"""
Test script for the Team 2 Generation Pipeline.

This script tests the pipeline with a mock paper structure
similar to what Team 1 would provide.

Usage:
    # From the backend directory:
    cd backend

    # Run offline tests (no API key required):
    uv run python tools/test_pipeline.py

    # Run full online tests (requires API key in .env):
    uv run python tools/test_pipeline.py --online

    # Run a specific agent test:
    uv run python tools/test_pipeline.py --online --test analyzer
    uv run python tools/test_pipeline.py --online --test planner
    uv run python tools/test_pipeline.py --online --test generator
    uv run python tools/test_pipeline.py --online --test pipeline
"""

import sys
from pathlib import Path

# Add the backend directory to path for direct script execution
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import asyncio
from datetime import datetime

# Now imports will work
from models.paper import (
    ArxivPaperMeta,
    Equation,
    Section,
    StructuredPaper,
)
from models.generation import (
    VisualizationType,
    VisualizationCandidate,
    VisualizationPlan,
    Scene,
    GeneratedCode,
)
from agents.code_validator import CodeValidator


def create_test_paper() -> StructuredPaper:
    """Create a mock paper for testing (simplified Attention Is All You Need)."""
    
    meta = ArxivPaperMeta(
        arxiv_id="1706.03762",
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        abstract="""The dominant sequence transduction models are based on complex 
        recurrent or convolutional neural networks that include an encoder and a decoder. 
        The best performing models also connect the encoder and decoder through an 
        attention mechanism. We propose a new simple network architecture, the Transformer, 
        based solely on attention mechanisms, dispensing with recurrence and convolutions 
        entirely.""",
        published=datetime(2017, 6, 12),
        updated=datetime(2017, 12, 6),
        categories=["cs.CL", "cs.LG"],
        pdf_url="https://arxiv.org/pdf/1706.03762",
        html_url="https://ar5iv.org/abs/1706.03762",
    )
    
    sections = [
        Section(
            id="abstract",
            title="Abstract",
            level=1,
            content=meta.abstract,
            equations=[],
            figures=[],
            parent_id=None,
        ),
        Section(
            id="section-1",
            title="Introduction",
            level=1,
            content="""Recurrent neural networks, long short-term memory and gated 
            recurrent neural networks in particular, have been firmly established as 
            state of the art approaches in sequence modeling and transduction problems 
            such as language modeling and machine translation.""",
            equations=[],
            figures=[],
            parent_id=None,
        ),
        Section(
            id="section-3",
            title="Model Architecture",
            level=1,
            content="""Most competitive neural sequence transduction models have an 
            encoder-decoder structure. Here, the encoder maps an input sequence of 
            symbol representations to a sequence of continuous representations. 
            Given z, the decoder then generates an output sequence of symbols one 
            element at a time.""",
            equations=[],
            figures=[],
            parent_id=None,
        ),
        Section(
            id="section-3-2",
            title="Attention",
            level=2,
            content="""An attention function can be described as mapping a query and 
            a set of key-value pairs to an output, where the query, keys, values, 
            and output are all vectors. The output is computed as a weighted sum of 
            the values, where the weight assigned to each value is computed by a 
            compatibility function of the query with the corresponding key.
            
            We call our particular attention "Scaled Dot-Product Attention". The input 
            consists of queries and keys of dimension d_k, and values of dimension d_v. 
            We compute the dot products of the query with all keys, divide each by 
            sqrt(d_k), and apply a softmax function to obtain the weights on the values.""",
            equations=[
                Equation(
                    latex=r"\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V",
                    context="The attention formula computes weighted values based on query-key similarity",
                    is_inline=False,
                ),
            ],
            figures=[],
            parent_id="section-3",
        ),
        Section(
            id="section-3-2-2",
            title="Multi-Head Attention",
            level=2,
            content="""Instead of performing a single attention function with 
            d_model-dimensional keys, values and queries, we found it beneficial 
            to linearly project the queries, keys and values h times with different, 
            learned linear projections. On each of these projected versions we 
            perform the attention function in parallel, yielding d_v-dimensional 
            output values. These are concatenated and once again projected.""",
            equations=[
                Equation(
                    latex=r"\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, ..., \text{head}_h)W^O",
                    context="Multi-head attention concatenates multiple attention outputs",
                    is_inline=False,
                ),
            ],
            figures=[],
            parent_id="section-3",
        ),
    ]
    
    return StructuredPaper(meta=meta, sections=sections)


def test_code_validator():
    """Test the code validator with various code samples."""
    print("\n=== Testing Code Validator ===")
    validator = CodeValidator()
    
    # Test 1: Valid code
    valid_code = '''from manim import *

class TestScene(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
        self.wait()
'''
    result = validator.validate(valid_code)
    print(f"✓ Valid code test: is_valid={result.is_valid}")
    assert result.is_valid, "Valid code should pass validation"
    
    # Test 2: Missing import
    no_import_code = '''class TestScene(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
'''
    result = validator.validate(no_import_code)
    print(f"✓ Missing import test: auto-fixed={len(result.issues_fixed) > 0}")
    assert "from manim import" in result.code, "Should add missing import"
    
    # Test 3: Syntax error
    syntax_error_code = '''from manim import *

class TestScene(Scene):
    def construct(self)  # Missing colon
        circle = Circle()
'''
    result = validator.validate(syntax_error_code)
    print(f"✓ Syntax error test: detected={not result.is_valid}, needs_regen={result.needs_regeneration}")
    assert not result.is_valid, "Syntax error should fail validation"
    
    print("All Code Validator tests passed!")


def test_visualization_models():
    """Test the Pydantic models."""
    print("\n=== Testing Models ===")
    
    # Test VisualizationCandidate
    candidate = VisualizationCandidate(
        section_id="section-3-2",
        concept_name="Scaled Dot-Product Attention",
        concept_description="The attention mechanism computation",
        visualization_type=VisualizationType.DATA_FLOW,
        priority=5,
        context="Attention(Q,K,V) = softmax(QK^T/sqrt(d_k))V",
    )
    print(f"✓ Created candidate: {candidate.concept_name}")
    
    # Test VisualizationPlan
    plan = VisualizationPlan(
        concept_name="Test Concept",
        visualization_type=VisualizationType.EQUATION,
        duration_seconds=30,
        scenes=[
            Scene(order=1, description="Title", duration_seconds=5, transitions="Write", elements=["Text"]),
            Scene(order=2, description="Main", duration_seconds=20, transitions="FadeIn", elements=["MathTex"]),
        ],
        narration_points=["First...", "Then..."],
    )
    print(f"✓ Created plan with {len(plan.scenes)} scenes")
    
    # Test StructuredPaper
    paper = create_test_paper()
    print(f"✓ Created paper: {paper.meta.title}")
    print(f"  Sections: {len(paper.sections)}")
    
    print("All Model tests passed!")


async def test_section_analyzer():
    """Test the Section Analyzer agent (requires API key)."""
    print("\n=== Testing Section Analyzer ===")
    
    from agents.section_analyzer import SectionAnalyzer
    
    paper = create_test_paper()
    analyzer = SectionAnalyzer()
    
    # Analyze the attention section (should find visualization candidates)
    attention_section = paper.get_section_by_id("section-3-2")
    
    print(f"Analyzing section: {attention_section.title}")
    result = await analyzer.run(
        paper_title=paper.meta.title,
        paper_abstract=paper.meta.abstract,
        section=attention_section,
    )
    
    print(f"✓ Needs visualization: {result.needs_visualization}")
    print(f"✓ Found {len(result.candidates)} candidates")
    for c in result.candidates:
        print(f"  - {c.concept_name} (type: {c.visualization_type.value}, priority: {c.priority})")
    print(f"✓ Reasoning: {result.reasoning[:100]}...")
    
    return result


async def test_visualization_planner():
    """Test the Visualization Planner agent (requires API key)."""
    print("\n=== Testing Visualization Planner ===")
    
    from agents.visualization_planner import VisualizationPlanner
    
    paper = create_test_paper()
    planner = VisualizationPlanner()
    
    # Create a test candidate
    candidate = VisualizationCandidate(
        section_id="section-3-2",
        concept_name="Scaled Dot-Product Attention",
        concept_description="The computation flow of Q, K, V matrices through dot product, scaling, softmax, and weighted sum",
        visualization_type=VisualizationType.DATA_FLOW,
        priority=5,
        context=r"Attention(Q,K,V) = softmax(QK^T/sqrt(d_k))V",
    )
    
    section = paper.get_section_by_id("section-3-2")
    
    print(f"Planning visualization for: {candidate.concept_name}")
    plan = await planner.run(
        candidate=candidate,
        full_section_content=section.content,
        paper_context=paper.get_context(),
    )
    
    print(f"✓ Created plan with {len(plan.scenes)} scenes")
    print(f"✓ Total duration: {plan.duration_seconds}s")
    for scene in plan.scenes:
        print(f"  Scene {scene.order}: {scene.description[:50]}... ({scene.duration_seconds}s)")
    
    return plan


async def test_manim_generator():
    """Test the Manim Generator agent (requires API key)."""
    print("\n=== Testing Manim Generator ===")
    
    from agents.manim_generator import ManimGenerator
    
    generator = ManimGenerator()
    
    # Create a simple plan to test
    plan = VisualizationPlan(
        concept_name="Softmax Function",
        visualization_type=VisualizationType.EQUATION,
        duration_seconds=25,
        scenes=[
            Scene(order=1, description="Show title 'Softmax Function'", duration_seconds=4, 
                  transitions="Write title, move to top", elements=["Text"]),
            Scene(order=2, description="Display the softmax equation", duration_seconds=8,
                  transitions="Write equation", elements=["MathTex"]),
            Scene(order=3, description="Highlight the numerator and explain", duration_seconds=6,
                  transitions="set_color to highlight", elements=["MathTex"]),
            Scene(order=4, description="Show the property that outputs sum to 1", duration_seconds=7,
                  transitions="Write result, Circumscribe", elements=["MathTex"]),
        ],
        narration_points=[
            "The softmax function converts values to probabilities",
            "The exponential ensures all values are positive",
            "The sum in denominator normalizes to 1",
        ],
    )
    
    print(f"Generating Manim code for: {plan.concept_name}")
    result = await generator.run(plan=plan)
    
    print(f"✓ Generated code ({len(result.code)} chars)")
    print(f"✓ Scene class: {result.scene_class_name}")
    
    # Validate the generated code
    validator = CodeValidator()
    validation = validator.validate(result.code)
    print(f"✓ Validation: is_valid={validation.is_valid}")
    
    if validation.issues_found:
        print(f"  Issues: {validation.issues_found}")
    
    print("\n--- Generated Code Preview ---")
    print(result.code[:800])
    print("...")
    
    return result


async def test_full_pipeline():
    """Test the full pipeline with a mock paper (requires API key)."""
    print("\n=== Testing Full Pipeline ===")
    
    from agents.pipeline import generate_visualizations
    
    paper = create_test_paper()
    print(f"Processing paper: {paper.meta.title}")
    print(f"Sections: {len(paper.sections)}")
    
    # Run the pipeline (limit to 1 visualization for testing)
    visualizations = await generate_visualizations(paper, max_visualizations=1)
    
    print(f"\n✓ Generated {len(visualizations)} visualization(s)")
    
    for viz in visualizations:
        print(f"\n--- Visualization: {viz.concept} ---")
        print(f"ID: {viz.id}")
        print(f"Section: {viz.section_id}")
        print(f"Status: {viz.status}")
        print(f"Code length: {len(viz.manim_code)} chars")
        print(f"\nCode preview:\n{viz.manim_code[:600]}...")
    
    return visualizations


async def test_pipeline_voice_enabled_path_passes_quality_gate():
    """Integration-style test for strict voice mode pipeline stage order."""

    from agents.pipeline import generate_single_visualization
    from models.voiceover import VoiceoverValidationOutput

    class FakePlanner:
        async def run(self, candidate, full_section_content, paper_context):
            return VisualizationPlan(
                concept_name=candidate.concept_name,
                visualization_type=candidate.visualization_type,
                duration_seconds=36,
                scenes=[
                    Scene(order=1, description="Title", duration_seconds=5, transitions="Write", elements=["Text"]),
                    Scene(order=2, description="Explain scoring", duration_seconds=15, transitions="Create", elements=["Arrow"]),
                    Scene(order=3, description="Explain weighting", duration_seconds=16, transitions="Write", elements=["MathTex"]),
                ],
                narration_points=[],
            )

    class FakeGenerator:
        async def run(self, **kwargs):
            code = '''from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.elevenlabs import ElevenLabsService

class StrictVoiceExample(VoiceoverScene):
    def construct(self):
        self.set_speech_service(ElevenLabsService(voice_id="pNInz6obpgDQGcFmaJgB", model="eleven_flash_v2_5", transcription_model=None))
        # Beat 1: frame
        title = Text("Attention")
        self.play(Write(title))
        # Beat 2: score
        arrow = Arrow(LEFT, RIGHT)
        with self.voiceover(text="Queries compare keys to compute relevance scores across contextual token relationships.") as tracker:
            self.play(Create(arrow), run_time=tracker.duration)
        # Beat 3: aggregate
        eq = MathTex(r"\\text{softmax}(\\frac{QK^T}{\\sqrt{d_k}})V")
        with self.voiceover(text="Softmax-normalized weights control value aggregation, yielding context-aware token representations.") as tracker:
            self.play(Write(eq), run_time=tracker.duration)
'''
            return GeneratedCode(
                code=code,
                scene_class_name="StrictVoiceExample",
                dependencies=["manim", "manim_voiceover"],
                voiceover_enabled=True,
                narration_lines=[
                    "Queries compare keys to compute relevance scores across contextual token relationships.",
                    "Softmax-normalized weights control value aggregation, yielding context-aware token representations.",
                ],
                narration_beats=["# Beat 2: score", "# Beat 3: aggregate"],
            )

        async def run_with_feedback(self, **kwargs):
            return await self.run(**kwargs)

    class FakeValidator:
        def validate(self, code):
            return type(
                "Validation",
                (),
                {
                    "is_valid": True,
                    "code": code,
                    "issues_found": [],
                    "issues_fixed": [],
                    "needs_regeneration": False,
                },
            )()

    class FakeSpatialValidator:
        def validate(self, code):
            return type(
                "SpatialResult",
                (),
                {
                    "has_spatial_issues": False,
                    "out_of_bounds": [],
                    "potential_overlaps": [],
                    "spacing_issues": [],
                    "needs_regeneration": False,
                    "get_feedback_message": lambda self: "",
                },
            )()

    class FakeVoiceoverScriptValidator:
        def validate(self, generated_code, plan, candidate):
            return VoiceoverValidationOutput(
                is_valid=True,
                issues_found=[],
                score_alignment=0.92,
                score_educational=0.91,
                needs_regeneration=False,
            )

    class FakeRenderTester:
        async def test_render(self, code):
            return type(
                "RenderResult",
                (),
                {"success": True, "error_type": None, "error_message": None, "get_feedback_message": lambda self: ""},
            )()

    paper = create_test_paper()
    candidate = VisualizationCandidate(
        section_id="section-3-2",
        concept_name="Scaled Dot-Product Attention",
        concept_description="Attention flow",
        visualization_type=VisualizationType.DATA_FLOW,
        priority=5,
        context="Attention formula",
    )

    viz = await generate_single_visualization(
        candidate=candidate,
        paper=paper,
        planner=FakePlanner(),
        generator=FakeGenerator(),
        validator=FakeValidator(),
        spatial_validator=FakeSpatialValidator(),
        voiceover_script_validator=FakeVoiceoverScriptValidator(),
        render_tester=FakeRenderTester(),
        legacy_voiceover_generator=None,
    )

    assert viz is not None
    assert "VoiceoverScene" in viz.manim_code
    assert "run_time=tracker.duration" in viz.manim_code


async def test_pipeline_drops_visualization_when_voice_quality_fails():
    """Integration-style test for strict voice quality fallback policy."""

    from agents import pipeline as pipeline_module
    from agents.pipeline import generate_single_visualization
    from models.voiceover import VoiceoverValidationOutput

    class FakePlanner:
        async def run(self, candidate, full_section_content, paper_context):
            return VisualizationPlan(
                concept_name=candidate.concept_name,
                visualization_type=candidate.visualization_type,
                duration_seconds=36,
                scenes=[
                    Scene(order=1, description="Title", duration_seconds=5, transitions="Write", elements=["Text"]),
                    Scene(order=2, description="Content", duration_seconds=15, transitions="Create", elements=["Arrow"]),
                ],
                narration_points=[],
            )

    class FakeGenerator:
        async def run(self, **kwargs):
            return GeneratedCode(
                code='''from manim import *\nfrom manim_voiceover import VoiceoverScene\nclass BadVoice(VoiceoverScene):\n    def construct(self):\n        self.set_speech_service(None)\n        with self.voiceover(text=\"Show the arrows now\") as tracker:\n            self.play(Create(Circle()), run_time=tracker.duration)\n''',
                scene_class_name="BadVoice",
                dependencies=["manim", "manim_voiceover"],
                voiceover_enabled=True,
                narration_lines=["Show the arrows now"],
                narration_beats=["# Beat 2"],
            )

        async def run_with_feedback(self, **kwargs):
            return await self.run(**kwargs)

    class FakeValidator:
        def validate(self, code):
            return type(
                "Validation",
                (),
                {
                    "is_valid": True,
                    "code": code,
                    "issues_found": [],
                    "issues_fixed": [],
                    "needs_regeneration": False,
                },
            )()

    class FakeVoiceoverScriptValidator:
        def validate(self, generated_code, plan, candidate):
            return VoiceoverValidationOutput(
                is_valid=False,
                issues_found=["Alignment score 0.2 below threshold 0.85"],
                score_alignment=0.2,
                score_educational=0.3,
                needs_regeneration=True,
            )

    class FakeRenderTester:
        async def test_render(self, code):
            return type(
                "RenderResult",
                (),
                {"success": True, "error_type": None, "error_message": None, "get_feedback_message": lambda self: ""},
            )()

    old_max_retries = pipeline_module.MAX_RETRIES
    old_voice_retries = pipeline_module.VOICE_QUALITY_RETRIES
    old_fail_behavior = pipeline_module.VOICE_FAIL_BEHAVIOR
    try:
        pipeline_module.MAX_RETRIES = 1
        pipeline_module.VOICE_QUALITY_RETRIES = 1
        pipeline_module.VOICE_FAIL_BEHAVIOR = "drop_viz"

        paper = create_test_paper()
        candidate = VisualizationCandidate(
            section_id="section-3-2",
            concept_name="Scaled Dot-Product Attention",
            concept_description="Attention flow",
            visualization_type=VisualizationType.DATA_FLOW,
            priority=5,
            context="Attention formula",
        )

        viz = await generate_single_visualization(
            candidate=candidate,
            paper=paper,
            planner=FakePlanner(),
            generator=FakeGenerator(),
            validator=FakeValidator(),
            spatial_validator=None,
            voiceover_script_validator=FakeVoiceoverScriptValidator(),
            render_tester=FakeRenderTester(),
            legacy_voiceover_generator=None,
        )
    finally:
        pipeline_module.MAX_RETRIES = old_max_retries
        pipeline_module.VOICE_QUALITY_RETRIES = old_voice_retries
        pipeline_module.VOICE_FAIL_BEHAVIOR = old_fail_behavior

    assert viz is None


def run_offline_tests():
    """Run tests that don't require API calls."""
    print("=" * 60)
    print("Running OFFLINE tests (no API key required)")
    print("=" * 60)
    
    test_visualization_models()
    test_code_validator()
    
    print("\n" + "=" * 60)
    print("All offline tests passed!")
    print("=" * 60)


async def run_online_tests(test_type: str = "all"):
    """Run tests that require API calls."""
    print("\n" + "=" * 60)
    print("Running ONLINE tests")
    print("=" * 60)
    
    import os
    dedalus_key = os.environ.get("DEDALUS_API_KEY")

    if dedalus_key:
        print("✓ Using DEDALUS_API_KEY")
    else:
        print("\n⚠️  WARNING: No API key set!")
        print("Add one to backend/.env:")
        print("  DEDALUS_API_KEY=your_dedalus_key")
        return
    
    if test_type in ["analyzer", "all"]:
        await test_section_analyzer()
    
    if test_type in ["planner", "all"]:
        await test_visualization_planner()
    
    if test_type in ["generator", "all"]:
        await test_manim_generator()
    
    if test_type in ["pipeline", "all"]:
        await test_full_pipeline()
    
    print("\n" + "=" * 60)
    print("Online tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test the ArXiviz Generation Pipeline")
    parser.add_argument("--online", action="store_true", help="Run tests that require API calls")
    parser.add_argument("--test", choices=["analyzer", "planner", "generator", "pipeline", "all"],
                        default="all", help="Which online test to run")
    args = parser.parse_args()
    
    # Always run offline tests
    run_offline_tests()
    
    # Run online tests if requested
    if args.online:
        asyncio.run(run_online_tests(args.test))
    else:
        print("\n💡 To run API tests:")
        print("   1. Set your API key in backend/.env:")
        print("      DEDALUS_API_KEY=your_key")
        print("")
        print("   2. Run tests (from the backend/ directory):")
        print("      uv run python tools/test_pipeline.py --online                    # Full pipeline")
        print("      uv run python tools/test_pipeline.py --online --test analyzer    # Just analyzer")
        print("      uv run python tools/test_pipeline.py --online --test generator   # Just generator")
