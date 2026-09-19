"""Static import/call gate on generated scenes (CodeValidator).

A Manim scene needs manim, manim_voiceover, numpy and a little pure-math
stdlib. It never needs the filesystem, a process, a socket or the interpreter
itself — and the text steering the generator is an arbitrary arXiv paper. The
gate is AST-based (a regex would flag ``"import os"`` inside a narration
string) and its message has to be specific enough for regeneration to fix.

It is a tripwire, not a sandbox: the secret-scrubbed render environment
(rendering/sandbox_env.py) is the control that holds when this is bypassed.
"""

import asyncio
from pathlib import Path

import pytest

from agents import pipeline
from agents.code_validator import CodeValidator
from models.generation import (
    GeneratedCode,
    Scene,
    ValidatorOutput,
    VisualizationCandidate,
    VisualizationPlan,
    VisualizationType,
)

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _scene(body: str = "        self.wait(1)", header: str = "") -> str:
    return (
        "from manim import *\n"
        "from manim_voiceover import VoiceoverScene\n"
        f"{header}\n"
        "class Demo(VoiceoverScene):\n"
        "    def construct(self):\n"
        f"{body}\n"
    )


FORBIDDEN_IMPORTS = [
    ("import os", "os"),
    ("import os.path", "os"),
    ("import os as operating_system", "os"),
    ("from os import environ", "os"),
    ("from os.path import join", "os"),
    ("import sys", "sys"),
    ("import subprocess", "subprocess"),
    ("import socket", "socket"),
    ("import requests", "requests"),
    ("import httpx", "httpx"),
    ("import urllib.request", "urllib"),
    ("from urllib import request", "urllib"),
    ("import http.client", "http"),
    ("from http import client", "http"),
    ("import ctypes", "ctypes"),
    ("import importlib", "importlib"),
    ("from importlib import import_module", "importlib"),
    ("import shutil", "shutil"),
    ("import pickle", "pickle"),
    ("import math, os", "os"),
]


@pytest.mark.parametrize("statement, module", FORBIDDEN_IMPORTS)
def test_forbidden_imports_fail_validation_with_a_targeted_message(statement, module):
    out = CodeValidator().validate(_scene(header=statement))

    assert not out.is_valid
    assert out.needs_regeneration
    assert out.security_issues
    message = out.security_issues[0]
    assert f"`{module}`" in message
    assert "line 3" in message  # where the statement sits in _scene()
    assert "Remove" in message  # tells the generator what to do about it
    assert message in out.issues_found  # rides the normal regeneration feedback


def test_import_inside_construct_is_caught_too():
    out = CodeValidator().validate(_scene(body="        import subprocess\n        self.wait(1)"))
    assert any("`subprocess`" in issue for issue in out.security_issues)


FORBIDDEN_CALLS = [
    ('        eval("1 + 1")', "eval"),
    ('        exec("x = 1")', "exec"),
    ('        compile("x = 1", "s", "exec")', "compile"),
    ('        __import__("os")', "__import__"),
    ('        data = open("/etc/passwd").read()', "open"),
]


@pytest.mark.parametrize("body, name", FORBIDDEN_CALLS)
def test_forbidden_calls_fail_validation_with_a_targeted_message(body, name):
    out = CodeValidator().validate(_scene(body=body + "\n        self.wait(1)"))

    assert not out.is_valid
    assert out.needs_regeneration
    assert any(f"`{name}()`" in issue and "line 6" in issue for issue in out.security_issues)


ALLOWED = [
    "import math",
    "import random",
    "import itertools",
    "import numpy as np",
    "from functools import partial",
    "from manim_voiceover.services.openai import OpenAIService",
    "import colorsys",
    # Names that merely START like a forbidden one (the gate is static, so the
    # module need not exist): matching is on the exact top-level package.
    "import osutils",
    "import systematic",
    "from pickleball import paddle",
]


@pytest.mark.parametrize("statement", ALLOWED)
def test_ordinary_scene_imports_pass(statement):
    out = CodeValidator().validate(_scene(header=statement))
    assert out.is_valid, out.issues_found
    assert not out.security_issues


def test_attribute_calls_and_strings_are_not_mistaken_for_builtins():
    body = (
        "        import re\n"
        "        pattern = re.compile(r'x+')\n"  # attribute call, not builtin compile()
        "        label = Text('import os; open the gate; eval(this)')\n"  # just a string
        "        self.play(Write(label))"
    )
    out = CodeValidator().validate(_scene(body=body))
    assert out.is_valid, out.issues_found
    assert not out.security_issues


def test_each_module_is_reported_once():
    out = CodeValidator().validate(_scene(header="import os\nimport os.path\nfrom os import environ"))
    assert len([i for i in out.security_issues if "`os`" in i]) == 1


def test_every_few_shot_example_and_the_reference_pass_the_gate():
    # The gate must never reject what the prompts teach: every example the
    # generator is shown, and every python block in the static reference.
    validator = CodeValidator()
    sources = [p.read_text() for p in sorted((BACKEND_ROOT / "examples").glob("*.py")) if p.name != "__init__.py"]
    assert sources, "no few-shot examples found"

    import re

    for md in [BACKEND_ROOT / "prompts" / "system" / "manim_reference.md", BACKEND_ROOT / "prompts" / "manim_generator.md"]:
        sources += re.findall(r"```python\n(.*?)```", md.read_text(), re.DOTALL)

    for source in sources:
        assert validator._check_forbidden_imports_and_calls(source) == [], source[:200]


# --- the pipeline must not ship code that failed the gate on its last attempt ---


class _FakePaper:
    def get_section_by_id(self, _sid):
        return None

    def get_context(self):
        return "context"


class _FakePlanner:
    async def run(self, candidate, full_section_content, paper_context):
        return VisualizationPlan(
            concept_name="Attention",
            visualization_type=VisualizationType.DATA_FLOW,
            duration_seconds=30,
            scenes=[Scene(order=1, description="beat", duration_seconds=10, transitions="Write", elements=["Text"])],
            narration_points=[],
        )


class _FakeGenerator:
    def _code(self):
        return GeneratedCode(
            code=_scene(header="import os"), scene_class_name="Demo", dependencies=["manim"],
            voiceover_enabled=False, narration_lines=[], narration_beats=[],
        )

    async def run(self, **_kwargs):
        return self._code()

    async def run_with_feedback(self, **_kwargs):
        return self._code()


def _candidate() -> VisualizationCandidate:
    return VisualizationCandidate(
        section_id="section-1", concept_name="Attention", concept_description="d",
        visualization_type=VisualizationType.DATA_FLOW, priority=5, context="c",
    )


def _generate(validator, monkeypatch):
    monkeypatch.setattr(pipeline, "ENABLE_VOICEOVER", False)
    monkeypatch.setattr(pipeline, "VOICE_FAIL_BEHAVIOR", "return_silent")
    return asyncio.run(
        pipeline.generate_single_visualization(
            candidate=_candidate(), paper=_FakePaper(), planner=_FakePlanner(),
            generator=_FakeGenerator(), validator=validator,
            spatial_validator=None, voiceover_script_validator=None, render_tester=None,
        )
    )


def test_exhausted_retries_drop_the_viz_when_the_last_attempt_failed_the_gate(monkeypatch):
    # return_silent ships the final attempt's code to the renderer even though
    # it failed validation — fine for a layout nit, not for `import os`.
    assert _generate(CodeValidator(), monkeypatch) is None


def test_exhausted_retries_still_ship_ordinary_validation_failures(monkeypatch):
    class _AlwaysInvalid:
        def validate(self, code):
            return ValidatorOutput(
                is_valid=False, code=code, issues_found=["No construct method found"],
                needs_regeneration=True,
            )

    viz = _generate(_AlwaysInvalid(), monkeypatch)
    assert viz is not None and viz.manim_code
