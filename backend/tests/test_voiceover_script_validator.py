from agents.voiceover_script_validator import VoiceoverScriptValidator
from models.generation import (
    GeneratedCode,
    Scene,
    VisualizationCandidate,
    VisualizationPlan,
    VisualizationType,
)


def _candidate() -> VisualizationCandidate:
    return VisualizationCandidate(
        section_id="section-1",
        concept_name="Scaled Dot-Product Attention",
        concept_description="Compute query-key similarity, normalize with softmax, and aggregate values.",
        visualization_type=VisualizationType.DATA_FLOW,
        priority=5,
        context="Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V",
    )


def _plan() -> VisualizationPlan:
    return VisualizationPlan(
        concept_name="Scaled Dot-Product Attention",
        visualization_type=VisualizationType.DATA_FLOW,
        duration_seconds=36,
        scenes=[
            Scene(order=1, description="Title beat", duration_seconds=5, transitions="Write", elements=["Text"]),
            Scene(order=2, description="Query key scoring", duration_seconds=12, transitions="Create arrows", elements=["Arrow"]),
            Scene(order=3, description="Softmax weighting", duration_seconds=12, transitions="Highlight", elements=["MathTex"]),
        ],
        narration_points=[],
    )


def _valid_code() -> str:
    return '''from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService

class AttentionVoice(VoiceoverScene):
    def construct(self):
        self.set_speech_service(GTTSService(transcription_model=None))

        # Beat 1: framing
        title = Text("Attention")
        self.play(Write(title))

        # Beat 2: relevance scoring
        arrow = Arrow(LEFT, RIGHT)
        with self.voiceover(text="Queries compare against keys to compute relevance scores across all token positions.") as tracker:
            self.play(Create(arrow), run_time=tracker.duration)

        # Beat 3: weighted aggregation
        eq = MathTex(r"\\text{softmax}(\\frac{QK^T}{\\sqrt{d_k}})V")
        with self.voiceover(text="Softmax-normalized weights control how strongly each value contributes to the output representation.") as tracker:
            self.play(Write(eq), run_time=tracker.duration)
'''


def test_validator_passes_high_quality_voiceover():
    validator = VoiceoverScriptValidator(use_llm_judge=False)
    generated = GeneratedCode(
        code=_valid_code(),
        scene_class_name="AttentionVoice",
        dependencies=["manim", "manim_voiceover"],
        voiceover_enabled=True,
        narration_lines=[
            "Queries compare against keys to compute relevance scores across all token positions.",
            "Softmax-normalized weights control how strongly each value contributes to the output representation.",
        ],
        narration_beats=["# Beat 2: relevance scoring", "# Beat 3: weighted aggregation"],
    )

    result = validator.validate(generated_code=generated, plan=_plan(), candidate=_candidate())
    assert result.is_valid is True
    assert result.needs_regeneration is False
    assert result.score_alignment >= 0.85
    assert result.score_educational >= 0.85


def test_validator_fails_banned_animation_verb():
    validator = VoiceoverScriptValidator(use_llm_judge=False)
    code = _valid_code().replace(
        "Queries compare against keys to compute relevance scores across all token positions.",
        "Show arrows connecting query and key blocks before calculating scores.",
    )
    generated = GeneratedCode(
        code=code,
        scene_class_name="AttentionVoice",
        dependencies=["manim", "manim_voiceover"],
        voiceover_enabled=True,
        narration_lines=[
            "Show arrows connecting query and key blocks before calculating scores.",
            "Softmax-normalized weights control how strongly each value contributes to the output representation.",
        ],
        narration_beats=["# Beat 2", "# Beat 3"],
    )

    result = validator.validate(generated_code=generated, plan=_plan(), candidate=_candidate())
    assert result.is_valid is False
    assert result.needs_regeneration is True
    assert any("animation command" in issue.lower() for issue in result.issues_found)


def test_validator_fails_missing_tracker_runtime_and_voice_blocks():
    validator = VoiceoverScriptValidator(use_llm_judge=False)
    code = '''from manim import *
class Plain(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
'''
    generated = GeneratedCode(
        code=code,
        scene_class_name="Plain",
        dependencies=["manim"],
        voiceover_enabled=True,
        narration_lines=[],
        narration_beats=[],
    )

    result = validator.validate(generated_code=generated, plan=_plan(), candidate=_candidate())
    assert result.is_valid is False
    assert result.needs_regeneration is True
    assert any("voiceoverscene" in issue.lower() for issue in result.issues_found)
    assert any("no voiceover narration blocks" in issue.lower() for issue in result.issues_found)


def test_validator_fails_word_count_rule():
    validator = VoiceoverScriptValidator(use_llm_judge=False)
    code = _valid_code().replace(
        "Softmax-normalized weights control how strongly each value contributes to the output representation.",
        "Softmax helps.",
    )
    generated = GeneratedCode(
        code=code,
        scene_class_name="AttentionVoice",
        dependencies=["manim", "manim_voiceover"],
        voiceover_enabled=True,
        narration_lines=[
            "Queries compare against keys to compute relevance scores across all token positions.",
            "Softmax helps.",
        ],
        narration_beats=["# Beat 2", "# Beat 3"],
    )

    result = validator.validate(generated_code=generated, plan=_plan(), candidate=_candidate())
    assert result.is_valid is False
    assert any("outside" in issue.lower() and "words" in issue.lower() for issue in result.issues_found)


def test_validator_flags_blank_narration_as_zero_words():
    """A whitespace-only narration entry must fail the word-count rule instead
    of being silently skipped (regression for CodeRabbit finding on PR #15)."""
    validator = VoiceoverScriptValidator(use_llm_judge=False)
    code = _valid_code().replace(
        "Softmax-normalized weights control how strongly each value contributes to the output representation.",
        "   ",
    )
    generated = GeneratedCode(
        code=code,
        scene_class_name="AttentionVoice",
        dependencies=["manim", "manim_voiceover"],
        voiceover_enabled=True,
        narration_lines=[
            "Queries compare against keys to compute relevance scores across all token positions.",
            "   ",
        ],
        narration_beats=["# Beat 2", "# Beat 3"],
    )

    result = validator.validate(generated_code=generated, plan=_plan(), candidate=_candidate())
    assert result.is_valid is False
    assert any("0 words" in issue for issue in result.issues_found)
