"""
Modal.com serverless Manim rendering.

Deploy with: modal deploy rendering/modal_runner.py
Test with: modal run rendering/modal_runner.py
"""

import modal
from pathlib import Path

# Define the Modal app
app = modal.App("arxiviz-manim")

# Create image with Manim and dependencies
manim_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(["ffmpeg", "libcairo2-dev", "libpango1.0-dev", "sox"])
    .pip_install(["setuptools>=75.0.0,<81"])  # Must keep pkg_resources (removed in 81+)
    .pip_install([
        "manim>=0.18.0",
        "manim-voiceover[elevenlabs]>=0.3.0",
    ])
)


@app.function(
    image=manim_image,
    timeout=300,
    secrets=[modal.Secret.from_name("elevenlabs-key")],
)
def render_manim_modal(code: str, scene_name: str, quality: str = "low_quality") -> bytes:
    """
    Render Manim code on Modal.com and return video bytes.

    Args:
        code: Complete Manim Python code
        scene_name: Name of the Scene class to render
        quality: "low_quality", "medium_quality", or "high_quality"

    Returns:
        MP4 video file as bytes
    """
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Write code to file
        code_path = tmpdir_path / "scene.py"
        code_path.write_text(code)

        # Set up output directory
        output_dir = tmpdir_path / "media"

        # Map quality names to manim flags
        quality_flags = {
            "low_quality": "-ql",
            "medium_quality": "-qm",
            "high_quality": "-qh",
        }
        quality_flag = quality_flags.get(quality, "-ql")

        # Build manim command
        cmd = [
            "manim",
            "render",
            str(code_path),
            scene_name,
            quality_flag,
            "--format=mp4",
            f"--media_dir={output_dir}",
        ]

        # Run manim (stdin=DEVNULL prevents any interactive input() from hanging)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=tmpdir,
            stdin=subprocess.DEVNULL,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            raise RuntimeError(f"Manim render failed: {error_msg}")

        # Find the output video file
        video_files = list(output_dir.rglob("*.mp4"))
        if not video_files:
            raise RuntimeError(
                f"No video file produced. Manim output:\n{result.stdout}\n{result.stderr}"
            )

        return video_files[0].read_bytes()


# For local testing
@app.local_entrypoint()
def main():
    test_code = '''
from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.elevenlabs import ElevenLabsService

class TestScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(ElevenLabsService(
            voice_id="pNInz6obpgDQGcFmaJgB",
            model="eleven_flash_v2_5",
            transcription_model=None,
        ))
        circle = Circle(color=BLUE)
        with self.voiceover(text="Here is a blue circle.") as tracker:
            self.play(Create(circle), run_time=tracker.duration)
        self.wait()
'''
    print("Rendering voiceover test scene on Modal...")
    video_bytes = render_manim_modal.remote(test_code, "TestScene", "low_quality")

    output_path = Path("modal_test_output.mp4")
    output_path.write_bytes(video_bytes)
    print(f"Success! Video saved to {output_path} ({len(video_bytes)} bytes)")
