"""Tests for RenderTester's dry-run execution mode.

The subprocess tests genuinely execute construct() through dry_run_driver.py
(manim is a real dependency; no network, no TTS, no rendering) — they exist
because this entire bug class is invisible to import-only validation: a
production render died on a numpy truth-value ValueError that only fires when
construct() runs.
"""

import asyncio

import pytest

import agents.render_tester as rt_module
from agents.render_tester import RenderTester

VALID_SCENE = """
from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.openai import OpenAIService

class ValidScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(OpenAIService(voice="nova", transcription_model=None))
        box = RoundedRectangle(width=2, height=1)
        with self.voiceover(text="A box appears.") as tracker:
            self.play(Create(box), run_time=tracker.duration)
"""

# The exact production failure shape (viz_1706_03762_1): comparing numpy
# arrays with == in a boolean context, which import testing cannot see.
NUMPY_BUG_SCENE = """
from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.openai import OpenAIService

class BugScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(OpenAIService(voice="nova", transcription_model=None))
        a = Dot([1, 1, 0]); b = Dot([2, 2, 0])
        with self.voiceover(text="Comparing points.") as tracker:
            if a.get_center() == b.get_center():
                self.play(FadeIn(a), run_time=tracker.duration)
"""


@pytest.fixture()
def tester(monkeypatch):
    monkeypatch.setenv("RENDER_TEST_EXECUTE", "1")
    return RenderTester(timeout_seconds=120)


class TestDryRunExecution:
    def test_valid_voiceover_scene_passes(self, tester):
        result = asyncio.run(tester.test_render(VALID_SCENE))
        assert result.success, f"{result.error_type}: {result.error_message}"

    def test_numpy_truth_value_bug_is_caught(self, tester):
        result = asyncio.run(tester.test_render(NUMPY_BUG_SCENE))
        assert not result.success
        assert result.error_type == "ValueError"
        assert "truth value" in result.error_message
        assert result.line_number is not None
        # The feedback must carry enough for the generator to fix it.
        assert "ValueError" in result.get_feedback_message()

    def test_syntax_error_caught_in_process(self, tester):
        result = asyncio.run(tester.test_render("def broken(:\n    pass"))
        assert not result.success
        assert result.error_type == "SyntaxError"
        assert result.line_number == 1

    def test_harness_breakage_fails_open(self, tester, monkeypatch, tmp_path):
        # A driver that dies without printing a verdict sentinel is an
        # infrastructure fault, not a code fault — the gate must not block.
        broken = tmp_path / "broken_driver.py"
        broken.write_text("import sys; sys.exit(2)")
        monkeypatch.setattr(rt_module, "_DRIVER_PATH", broken)
        result = asyncio.run(tester.test_render(VALID_SCENE))
        assert result.success

    def test_sys_exit_in_scene_fails_closed(self, tester):
        # SystemExit is not an Exception — without the driver's BaseException
        # handler it would exit sentinel-less and be misread as infra (pass).
        code = VALID_SCENE.replace(
            "box = RoundedRectangle(width=2, height=1)",
            "import sys; sys.exit(1)",
        )
        result = asyncio.run(tester.test_render(code))
        assert not result.success

    def test_missing_scene_keeps_typed_feedback(self, tester):
        result = asyncio.run(tester.test_render("from manim import *\nx = 1\n"))
        assert not result.success
        assert result.error_type == "MissingSceneError"
        assert "inherits from Scene" in result.fix_suggestion


class TestSubprocessErrorParsing:
    def test_extracts_type_message_and_line(self):
        stderr = (
            "/x/manim_voiceover/__init__.py:4: UserWarning: pkg_resources deprecated\n"
            "Traceback (most recent call last):\n"
            '  File "/tmp/dry-run-gate-abc/scene.py", line 9, in construct\n'
            "    if a.get_center() == b.get_center():\n"
            "ValueError: The truth value of an array with more than one element is ambiguous.\n"
        )
        out = RenderTester()._parse_subprocess_error(stderr)
        assert out.error_type == "ValueError"
        assert "truth value" in out.error_message
        assert out.line_number == 9

    def test_manim_internal_scene_py_frames_are_not_reported_as_user_lines(self):
        # Errors raised inside manim's own play/wait machinery traceback
        # through .../manim/scene/scene.py — a bare scene.py match reported
        # manim's line 972 as the user's error line into regeneration.
        stderr = (
            "Traceback (most recent call last):\n"
            '  File "/tmp/dry-run-gate-xyz/scene.py", line 7, in construct\n'
            "    self.play(c)\n"
            '  File "/app/.venv/lib/python3.13/site-packages/manim/scene/scene.py", line 972, in play\n'
            "    raise TypeError(...)\n"
            "TypeError: Unexpected argument Circle passed to Scene.play().\n"
        )
        out = RenderTester()._parse_subprocess_error(stderr)
        assert out.error_type == "TypeError"
        assert out.line_number == 7  # the user frame, not manim's 972

    def test_latex_errors_get_targeted_suggestion(self):
        stderr = (
            "Traceback (most recent call last):\n"
            '  File "/tmp/x/scene.py", line 4, in construct\n'
            "RuntimeError: latex error converting to dvi\n"
        )
        out = RenderTester()._parse_subprocess_error(stderr)
        assert out.error_type == "LaTeXError"
        assert "LaTeX" in out.fix_suggestion

    def test_garbage_stderr_still_produces_feedback(self):
        out = RenderTester()._parse_subprocess_error("something exploded, no traceback")
        assert not out.success
        assert out.error_message
