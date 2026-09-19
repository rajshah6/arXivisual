"""A voiceover 3D scene has two bases, and three places must agree on it.

``class X(ThreeDScene, VoiceoverScene):`` is exactly what the generator is
asked to write for 3D concepts with narration. The validator's single-base
regex rejected it (a paid regeneration on every attempt, so 3D vizzes burned
the whole retry budget), and the generator's and runner's name extraction fell
back to a made-up class name that does not exist in the file.
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

from agents.code_validator import CodeValidator
from agents.manim_generator import ManimGenerator
from rendering.local_runner import extract_scene_name

MULTI_BASE = [
    "class Orbit3D(ThreeDScene, VoiceoverScene):",
    "class Orbit3D(VoiceoverScene, ThreeDScene):",
    "class Orbit3D( ThreeDScene , VoiceoverScene ):",
    "class Orbit3D(Scene):",
    "class Orbit3D(VoiceoverScene):",
    "class Orbit3D(ThreeDScene):",
]


def _code(class_line: str) -> str:
    return f"""from manim import *
from manim_voiceover import VoiceoverScene

{class_line}
    def construct(self):
        self.wait(1)
"""


@pytest.mark.parametrize("class_line", MULTI_BASE)
def test_validator_accepts_every_supported_base_combination(class_line):
    assert CodeValidator()._has_scene_class(_code(class_line))


@pytest.mark.parametrize("class_line", MULTI_BASE)
def test_generator_extracts_the_real_class_name(class_line):
    generator = ManimGenerator.__new__(ManimGenerator)
    assert generator._extract_scene_class_name(_code(class_line)) == "Orbit3D"


@pytest.mark.parametrize("class_line", MULTI_BASE)
def test_runner_extracts_the_real_class_name(class_line):
    assert extract_scene_name(_code(class_line)) == "Orbit3D"


def test_unrelated_classes_are_still_rejected():
    code = "from manim import *\nclass Helper(object):\n    pass\n"
    assert not CodeValidator()._has_scene_class(code)
    assert ManimGenerator.__new__(ManimGenerator)._extract_scene_class_name(code) == "GeneratedScene"
