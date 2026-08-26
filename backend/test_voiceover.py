"""
Test script for voiceover integration.

This creates a simple Manim scene with gTTS voiceover.

Usage:
    python3 test_voiceover.py           # Generate gTTS test (free, no API key needed)
    python3 test_voiceover.py --render  # Also render the scene

Notes:
- gTTS is free but requires internet connection
"""

import sys
from pathlib import Path

print("Using gTTS (free, no API key required)")

TEST_SCENE_CODE = '''"""Test scene with gTTS voiceover (free, no API key needed)."""
from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.gtts import GTTSService


class VoiceoverTestScene(VoiceoverScene):
    """Simple test scene demonstrating gTTS voiceover integration."""

    def construct(self):
        # Initialize gTTS service (free, uses Google Translate API)
        # transcription_model=None disables whisper (incompatible with Python 3.13)
        self.set_speech_service(GTTSService(transcription_model=None))

        # Introduction
        with self.voiceover("Welcome to this visualization demo. Let me show you how voiceovers sync with animations.") as tracker:
            title = Text("Voiceover Demo", font_size=48)
            self.play(Write(title), run_time=tracker.duration)

        self.wait(0.5)

        # Move title and show circle
        with self.voiceover("Watch as I create a circle on the screen.") as tracker:
            self.play(title.animate.to_edge(UP), run_time=tracker.duration * 0.3)
            circle = Circle(color=BLUE, radius=1.5)
            self.play(Create(circle), run_time=tracker.duration * 0.7)

        # Transform to square
        with self.voiceover("Now let's transform this circle into a square.") as tracker:
            square = Square(side_length=3, color=GREEN)
            self.play(Transform(circle, square), run_time=tracker.duration)

        # Conclusion
        with self.voiceover("That's the power of synchronized animations and voiceovers. Thank you for watching!") as tracker:
            self.play(FadeOut(circle), FadeOut(title), run_time=tracker.duration)

        self.wait(1)
'''

# Create the test scene file
output_dir = Path(__file__).parent / "generated_output"
output_dir.mkdir(exist_ok=True)

test_scene_file = output_dir / "voiceover_test_scene.py"
test_scene_file.write_text(TEST_SCENE_CODE)

print(f"\nGenerated test scene (gTTS): {test_scene_file}")
print("\nTo render the scene with voiceover, run:")
print(f"  cd {output_dir}")
print("  manim -pql voiceover_test_scene.py VoiceoverTestScene --disable_caching")
print("\nNote: --disable_caching is required for voiceover sync to work correctly.")

# Optionally try to render
if "--render" in sys.argv:
    import subprocess
    print("\n" + "=" * 50)
    print("Attempting to render scene...")
    print("=" * 50 + "\n")

    result = subprocess.run(
        [sys.executable, "-m", "manim",
         "-ql", "voiceover_test_scene.py", "VoiceoverTestScene", "--disable_caching"],
        cwd=output_dir,
        capture_output=False,
    )

    if result.returncode == 0:
        print("\nScene rendered successfully!")
        print(f"Check {output_dir}/media/videos/ for the output.")
    else:
        print(f"\nRendering failed with exit code {result.returncode}")
else:
    print("\nTip: Run with --render flag to automatically render the scene:")
    print("  python3 test_voiceover.py --render")
