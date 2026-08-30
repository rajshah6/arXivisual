"""Unit tests for render-error distillation (pure function, no subprocess).

Regression source: viz_1706_03762_1 in production failed with a numpy
ValueError, but the stored error was only manim-voiceover's pkg_resources
deprecation warning — the head of stderr — leaving the failure undiagnosable
from the DB.
"""

from rendering.local_runner import _extract_render_error

# The shape prod stderr actually had: import-time warnings first, then manim's
# rich-boxed traceback with the real exception at the end.
PROD_STDERR = """\
/app/.venv/lib/python3.13/site-packages/manim_voiceover/__init__.py:4: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html.
  import pkg_resources
/app/.venv/lib/python3.13/site-packages/manim_voiceover/helper.py:21: SyntaxWarning: invalid escape sequence '\\s'
╭───────────────────── Traceback (most recent call last) ──────────────────────╮
│ /app/.venv/lib/python3.13/site-packages/manim/scene/scene.py:259 in render   │
╰──────────────────────────────────────────────────────────────────────────────╯
ValueError: The truth value of an array with more than one element is ambiguous."""


def test_traceback_wins_over_leading_warnings():
    out = _extract_render_error(PROD_STDERR, "")
    assert out.startswith("Traceback (most recent call last)")
    assert "ValueError: The truth value of an array" in out
    assert "pkg_resources is deprecated" not in out


def test_last_traceback_is_used_when_several_appear():
    text = (
        "Traceback (most recent call last):\n  first\nKeyError: 'a'\n"
        "retrying...\n"
        "Traceback (most recent call last):\n  second\nValueError: real one"
    )
    out = _extract_render_error(text, "")
    assert "ValueError: real one" in out
    assert "KeyError" not in out


def test_warning_only_stderr_is_filtered_to_remaining_lines():
    text = (
        "/x/manim_voiceover/__init__.py:4: UserWarning: pkg_resources is deprecated\n"
        "Error: LaTeX compilation failed for MathTex"
    )
    out = _extract_render_error(text, "")
    assert out == "Error: LaTeX compilation failed for MathTex"


def test_all_noise_falls_back_to_full_text():
    text = "/x/helper.py:21: SyntaxWarning: invalid escape sequence"
    # Everything is noise — better the warning than an empty error message.
    assert _extract_render_error(text, "") == text


def test_stdout_fallback_and_empty():
    assert _extract_render_error("", "some stdout failure") == "some stdout failure"
    assert _extract_render_error("", "") == "Unknown error"


def test_long_output_keeps_the_tail():
    text = ("x" * 10000) + "\nRuntimeError: the actual error"
    out = _extract_render_error(text, "")
    assert out.endswith("RuntimeError: the actual error")
    assert len(out) <= 4000
