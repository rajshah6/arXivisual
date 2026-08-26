#!/usr/bin/env python3
"""
Show BEFORE and AFTER code in unified voice generation mode.

BEFORE: regular Scene generation (voiceover disabled)
AFTER: VoiceoverScene generation (voiceover enabled)
"""

import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.manim_generator import ManimGenerator
from models.generation import Scene, VisualizationPlan, VisualizationType


async def test_voiceover_transformation():
    print("=" * 80)
    print("UNIFIED VOICEOVER GENERATION TEST")
    print("=" * 80)

    plan = VisualizationPlan(
        concept_name="Scaled Dot-Product Attention",
        visualization_type=VisualizationType.DATA_FLOW,
        duration_seconds=36,
        scenes=[
            Scene(order=1, description="Title beat", duration_seconds=5, transitions="Write", elements=["Text"]),
            Scene(order=2, description="Show Q,K interaction", duration_seconds=12, transitions="Create arrows", elements=["Arrow"]),
            Scene(order=3, description="Show weighted aggregation", duration_seconds=14, transitions="Write formula", elements=["MathTex"]),
            Scene(order=4, description="Final takeaway", duration_seconds=5, transitions="FadeIn", elements=["Text"]),
        ],
        narration_points=[
            "Queries compare against keys to score relevance.",
            "Softmax normalizes scores into attention probabilities.",
            "Weighted values produce context-aware output embeddings.",
        ],
    )

    generator = ManimGenerator()

    print("\nStep 1: Generating WITHOUT voiceover (before)")
    before = await generator.run(plan=plan, voiceover_enabled=False)

    print("\nStep 2: Generating WITH unified voiceover (after)")
    after = await generator.run(
        plan=plan,
        voiceover_enabled=True,
        tts_service="gtts",
        voice_name="",
        narration_style="concept_teacher",
        target_duration_seconds=(30, 45),
    )

    print("\n" + "=" * 80)
    print("BEFORE (Scene)")
    print("=" * 80)
    print(before.code)

    print("\n" + "=" * 80)
    print("AFTER (VoiceoverScene)")
    print("=" * 80)
    print(after.code)

    print("\nExtracted narration lines:")
    for i, line in enumerate(after.narration_lines, 1):
        print(f"  {i}. {line}")

    output_dir = Path(__file__).parent / "generated_output"
    output_dir.mkdir(exist_ok=True)

    before_file = output_dir / "before_voiceover.py"
    after_file = output_dir / "after_voiceover.py"
    before_file.write_text(before.code)
    after_file.write_text(after.code)

    print(f"\nSaved BEFORE: {before_file}")
    print(f"Saved AFTER:  {after_file}")


if __name__ == "__main__":
    asyncio.run(test_voiceover_transformation())
