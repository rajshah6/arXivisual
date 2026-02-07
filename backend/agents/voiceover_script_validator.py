"""Strict voiceover script validator for narration quality and alignment."""

from __future__ import annotations

import os
import re
import json
from typing import Optional

# Handle imports for both package and direct execution
try:
    from .base import _get_client, get_model_name
    from ..models.generation import GeneratedCode, VisualizationCandidate, VisualizationPlan
    from ..models.voiceover import VoiceoverValidationOutput
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.base import _get_client, get_model_name
    from models.generation import GeneratedCode, VisualizationCandidate, VisualizationPlan
    from models.voiceover import VoiceoverValidationOutput


class VoiceoverScriptValidator:
    """Validate that generated narration is concept-aligned and educational."""

    BANNED_STARTS = ("display", "show", "fade", "animate", "create", "draw", "move", "write")
    STOPWORDS = {
        "the", "and", "that", "with", "from", "this", "these", "those", "into", "onto",
        "their", "about", "each", "for", "are", "its", "while", "where", "when", "then",
        "using", "through", "across", "between", "before", "after", "over", "under", "into",
    }

    def __init__(
        self,
        strict: bool = True,
        min_words: int = 6,
        max_words: int = 40,
        alignment_threshold: float = 0.70,
        educational_threshold: float = 0.70,
        use_llm_judge: bool = True,
        model: Optional[str] = None,
    ):
        self.strict = strict
        self.min_words = min_words
        self.max_words = max_words
        self.alignment_threshold = alignment_threshold
        self.educational_threshold = educational_threshold
        self.use_llm_judge = use_llm_judge
        self._client = _get_client() if use_llm_judge else None
        self.model = get_model_name(model)

    def validate(
        self,
        generated_code: GeneratedCode,
        plan: VisualizationPlan,
        candidate: VisualizationCandidate,
    ) -> VoiceoverValidationOutput:
        """Run strict validation for narration + voiceover code shape."""
        issues: list[str] = []
        code = generated_code.code
        narrations = generated_code.narration_lines
        beat_labels = generated_code.narration_beats

        # Required voiceover structures (hard fail — code won't work without these)
        if "VoiceoverScene" not in code:
            issues.append("Missing VoiceoverScene inheritance.")
        if "set_speech_service(" not in code:
            issues.append("Missing set_speech_service(...) call in construct().")

        voiceover_blocks = re.findall(
            r'with\s+self\.voiceover\s*\(\s*text\s*=\s*"([^"]+)"\s*\)\s+as\s+tracker\s*:',
            code,
        )
        if not voiceover_blocks:
            # Also support old positional style
            positional = re.findall(
                r'with\s+self\.voiceover\s*\(\s*"([^"]+)"\s*\)\s+as\s+tracker\s*:',
                code,
            )
            voiceover_blocks = positional
            if not positional:
                issues.append("No voiceover narration blocks found.")

        # Soft checks below — logged but do NOT block generation

        # Narration lexical rules
        alignment_rule_scores: list[float] = []
        educational_rule_scores: list[float] = []
        reference_terms = self._build_reference_terms(candidate)
        for idx, line in enumerate(narrations, 1):
            stripped = line.strip()
            if not stripped:
                continue
            # Banned animation-command starts (hard fail — bad narration quality)
            if stripped.lower().startswith(self.BANNED_STARTS):
                issues.append(f"Narration {idx} starts with animation command style wording.")

            alignment_rule_scores.append(self._rule_alignment_score(stripped, reference_terms))
            educational_rule_scores.append(self._rule_educational_score(stripped))

        rule_alignment = (
            sum(alignment_rule_scores) / len(alignment_rule_scores)
            if alignment_rule_scores else 0.0
        )
        rule_educational = (
            sum(educational_rule_scores) / len(educational_rule_scores)
            if educational_rule_scores else 0.0
        )

        llm_alignment = None
        llm_educational = None
        llm_issue = None
        if self.use_llm_judge and narrations:
            llm_alignment, llm_educational, llm_issue = self._llm_judge(
                candidate=candidate,
                plan=plan,
                narrations=narrations,
            )
            # Do not fail hard on judge unavailability; heuristic scores remain active.
            _ = llm_issue

        final_alignment = llm_alignment if llm_alignment is not None else rule_alignment
        final_educational = llm_educational if llm_educational is not None else rule_educational

        if final_alignment < self.alignment_threshold:
            issues.append(
                f"Alignment score {final_alignment:.2f} is below threshold {self.alignment_threshold:.2f}."
            )
        if final_educational < self.educational_threshold:
            issues.append(
                f"Educational score {final_educational:.2f} is below threshold {self.educational_threshold:.2f}."
            )

        is_valid = len(issues) == 0
        needs_regeneration = not is_valid if self.strict else False

        return VoiceoverValidationOutput(
            is_valid=is_valid,
            issues_found=issues,
            score_alignment=max(0.0, min(1.0, final_alignment)),
            score_educational=max(0.0, min(1.0, final_educational)),
            needs_regeneration=needs_regeneration,
        )

    def _word_count(self, text: str) -> int:
        return len(re.findall(r"[A-Za-z0-9']+", text))

    def _build_reference_terms(self, candidate: VisualizationCandidate) -> set[str]:
        joined = f"{candidate.concept_name} {candidate.concept_description} {candidate.context}"
        raw_terms = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", joined.lower())
        return {self._normalize_token(t) for t in raw_terms if t not in self.STOPWORDS}

    def _rule_alignment_score(self, line: str, reference_terms: set[str]) -> float:
        terms = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", line.lower()))
        terms = {self._normalize_token(t) for t in terms if t not in self.STOPWORDS}
        if not terms:
            return 0.0
        if not reference_terms:
            return 0.5

        overlap = len(terms & reference_terms)
        overlap_ratio = overlap / max(1, min(8, len(terms)))

        # Anchor terms for ML explanation quality.
        anchors = {
            "query", "key", "value", "attention", "softmax", "weight",
            "score", "representation", "token", "context",
        }
        anchor_hits = len(terms & anchors)

        # Start with conservative base and boost using overlap+anchor evidence.
        score = 0.45 + (0.20 * min(3, anchor_hits)) + (0.25 * overlap_ratio)
        return max(0.0, min(1.0, score))

    def _rule_educational_score(self, line: str) -> float:
        low = line.lower()
        penalties = 0.0
        if any(low.startswith(bad) for bad in self.BANNED_STARTS):
            penalties += 0.45
        if "screen" in low or "on screen" in low:
            penalties += 0.20
        if "watch" in low or "now we" in low:
            penalties += 0.15
        if self._word_count(line) < self.min_words:
            penalties += 0.20
        base = 0.95
        return max(0.0, min(1.0, base - penalties))

    def _normalize_token(self, token: str) -> str:
        """Light normalization for overlap matching."""
        if token.endswith("ies") and len(token) > 4:
            return token[:-3] + "y"
        if token.endswith("s") and len(token) > 3:
            return token[:-1]
        return token

    def _llm_judge(
        self,
        candidate: VisualizationCandidate,
        plan: VisualizationPlan,
        narrations: list[str],
    ) -> tuple[Optional[float], Optional[float], Optional[str]]:
        """LLM rubric scorer. Returns None scores if unavailable."""
        if not (os.environ.get("MARTIAN_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
            return None, None, None

        try:
            prompt = (
                "You are an evaluator of educational narration quality.\n"
                "Return JSON only with keys: score_alignment, score_educational, issues.\n"
                "Scores must be floats in [0,1].\n\n"
                f"Concept: {candidate.concept_name}\n"
                f"Concept description: {candidate.concept_description}\n"
                f"Section context: {candidate.context}\n"
                f"Plan scenes: {plan.model_dump_json(indent=2)}\n"
                f"Narrations: {json.dumps(narrations, ensure_ascii=True)}\n\n"
                "Rubric:\n"
                "- score_alignment: how well narration matches concept and planned beats\n"
                "- score_educational: friendly, approachable clarity — like a tutor explaining to a "
                "high schooler. Still technically accurate but uses plain language. Not animation commands.\n"
                "- issues: short list of concrete problems\n"
            )

            response = self._client.messages.create(
                model=self.model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
            payload = match.group(1).strip() if match else text
            result = json.loads(payload)
            score_alignment = float(result.get("score_alignment", 0.0))
            score_educational = float(result.get("score_educational", 0.0))
            return score_alignment, score_educational, None
        except Exception as exc:  # noqa: BLE001
            return None, None, f"LLM judge unavailable: {type(exc).__name__}"
