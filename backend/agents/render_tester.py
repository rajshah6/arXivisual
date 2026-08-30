"""
Render Tester Agent for validating Manim code by attempting to execute it.

Two validation modes (RENDER_TEST_EXECUTE env, default on):

- Execution mode: runs construct() in a subprocess under manim's dry_run
  config via ``dry_run_driver.py`` — animations are processed but nothing is
  rendered to disk and TTS is stubbed (~0.2s for a typical scene). This
  catches the runtime-error class that import testing structurally cannot:
  a production render died on ``if a.get_center() == b.get_center():`` (numpy
  truth-value ValueError) that only fires when construct() executes.
- Import mode (legacy fallback): compile + import the module in-process.

Execution mode fails OPEN on harness trouble (driver crash without a verdict
sentinel — e.g. a broken environment): the real render still guards, and a
gate must never block all videos because of its own infrastructure.
"""

import asyncio
import contextlib
import importlib.util
import logging
import os
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agents.dry_run_driver import SENTINEL_FAIL, SENTINEL_OK

logger = logging.getLogger(__name__)

_DRIVER_PATH = Path(__file__).with_name("dry_run_driver.py")
_TMPDIR_PREFIX = "dry-run-gate-"
# The dry run needs no real credentials (TTS is stubbed, nothing uploads) and
# it executes LLM-generated code — scrub secrets from the child environment.
_SECRET_ENV_PREFIXES = ("AZURE_", "S3_", "LANGFUSE_", "DEDALUS_")
_SECRET_ENV_KEYS = ("DATABASE_URL", "RENDER_API_SECRET", "OPENAI_API_KEY")


class RenderTestOutput(BaseModel):
    """Output from the Render Tester."""
    
    success: bool = Field(..., description="Whether the render test passed")
    error_type: str | None = Field(None, description="Type of error if failed")
    error_message: str | None = Field(None, description="Error message if failed")
    line_number: int | None = Field(None, description="Line number of error if available")
    fix_suggestion: str | None = Field(None, description="Suggested fix for the error")
    
    def get_feedback_message(self) -> str:
        """Generate feedback for the generator to fix issues."""
        if self.success:
            return ""
        
        lines = ["RUNTIME ERROR DETECTED - Please fix the following:"]
        lines.append(f"\nError Type: {self.error_type}")
        lines.append(f"Error Message: {self.error_message}")
        
        if self.line_number:
            lines.append(f"Line Number: {self.line_number}")
        
        if self.fix_suggestion:
            lines.append(f"\nSuggested Fix: {self.fix_suggestion}")
        
        return "\n".join(lines)


class RenderTester:
    """
    Tests Manim code by attempting to import and validate it.
    
    This catches runtime errors that static analysis cannot detect:
    - Missing imports
    - Invalid method calls
    - Type errors
    - LaTeX errors (partially)
    """
    
    # Known error patterns and their fixes
    ERROR_FIXES = {
        "NameError": "Check that all variables and Manim classes are properly defined/imported",
        "AttributeError": "Check that the method exists on the object - consult Manim reference",
        "TypeError": "Check the number and types of arguments passed to the function",
        "ValueError": "Check that the values passed are valid for the function",
        "LaTeX": "Check LaTeX syntax - each MathTex part must be valid LaTeX on its own",
        "ModuleNotFoundError": "Check imports - use 'from manim import *' for all Manim classes",
        "SyntaxError": "Fix the Python syntax error at the indicated line",
        "MissingSceneError": "Ensure code has a class that inherits from Scene with a construct(self) method",
        "IndentationError": "Fix the indentation - Python requires consistent indentation",
    }
    
    def __init__(self, timeout_seconds: float | None = None):
        """
        Initialize the render tester.
        
        Args:
            timeout_seconds: Maximum time to wait for import/validation
                            Defaults to env RENDER_TEST_TIMEOUT_SECONDS or 60s.
        """
        if timeout_seconds is None:
            timeout_seconds = float(os.getenv("RENDER_TEST_TIMEOUT_SECONDS", "60"))
        self.timeout_seconds = timeout_seconds
        self.execute_mode = os.getenv("RENDER_TEST_EXECUTE", "1") == "1"

    async def test_render(self, code: str, scene_class: str | None = None) -> RenderTestOutput:
        """
        Test Manim code by executing construct() in a dry-run subprocess
        (or, with RENDER_TEST_EXECUTE=0, by importing it in-process).

        Args:
            code: The Manim Python code to test
            scene_class: Optional scene class name (extracted if not provided)

        Returns:
            RenderTestOutput with success status and error details
        """
        validate = self._validate_by_execution if self.execute_mode else self._validate_by_import
        # Execution mode: the subprocess enforces the real timeout, so the
        # outer wait only guards the wrapper and gets a margin. Import mode has
        # no inner timeout — the outer wait IS its documented 60s bound.
        outer_timeout = self.timeout_seconds + 15 if self.execute_mode else self.timeout_seconds
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(validate, code, scene_class),
                timeout=outer_timeout,
            )
            return result
        except TimeoutError:
            return RenderTestOutput(
                success=False,
                error_type="TimeoutError",
                error_message=f"Code validation timed out after {self.timeout_seconds}s",
                fix_suggestion="Check for infinite loops or very complex computations in the Scene class definition"
            )
        except Exception as e:
            return RenderTestOutput(
                success=False,
                error_type=type(e).__name__,
                error_message=str(e),
                fix_suggestion=self.ERROR_FIXES.get(type(e).__name__, "Review the error and fix accordingly")
            )

    def _validate_by_execution(self, code: str, scene_class: str | None = None) -> RenderTestOutput:
        """Execute construct() in a dry-run subprocess (see dry_run_driver.py).

        Verdicts come from the driver's sentinels; a missing sentinel means
        the harness itself broke, which fails OPEN — the real render is still
        downstream, and a gate must not block videos on its own infra.
        """
        syntax_error = self._check_syntax(code)
        if syntax_error is not None:
            return syntax_error

        with tempfile.TemporaryDirectory(prefix=_TMPDIR_PREFIX) as tmpdir:
            scene_path = Path(tmpdir) / "scene.py"
            scene_path.write_text(code, encoding="utf-8")
            env = {
                k: v for k, v in os.environ.items()
                if not k.startswith(_SECRET_ENV_PREFIXES) and k not in _SECRET_ENV_KEYS
            }
            # The generated code instantiates OpenAIService before the driver
            # swaps it out; its __init__ only needs a key to exist.
            env["OPENAI_API_KEY"] = "dry-run-placeholder"
            cmd = [sys.executable, str(_DRIVER_PATH), str(scene_path)]
            if scene_class:
                cmd.append(scene_class)
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=tmpdir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                return RenderTestOutput(
                    success=False,
                    error_type="TimeoutError",
                    error_message=f"construct() did not finish within {self.timeout_seconds}s",
                    fix_suggestion="Check for infinite loops or excessive animation counts in construct()",
                )

        if SENTINEL_OK in result.stdout:
            return RenderTestOutput(success=True)
        if SENTINEL_FAIL in result.stdout:
            return self._parse_subprocess_error(result.stderr)
        # No sentinel: the driver never reached a verdict — infra, not code.
        # Fail open, but LOUDLY: a persistently broken driver must not look
        # like a healthy passing gate in the logs.
        logger.warning(
            "Dry-run driver produced no verdict (rc=%s) — failing open. stderr tail: %s",
            result.returncode, (result.stderr or "")[-500:],
        )
        return RenderTestOutput(success=True)

    def _check_syntax(self, code: str) -> RenderTestOutput | None:
        """In-process syntax check (precise line numbers, no subprocess cost)."""
        try:
            compile(code, "scene.py", "exec")
        except SyntaxError as e:
            return RenderTestOutput(
                success=False,
                error_type="SyntaxError",
                error_message=str(e.msg),
                line_number=e.lineno,
                fix_suggestion=f"Fix syntax at line {e.lineno}: {e.msg}",
            )
        return None

    def _parse_subprocess_error(self, stderr: str) -> RenderTestOutput:
        """Turn the driver's traceback into gate feedback for regeneration."""
        text = stderr.strip()
        idx = text.rfind("Traceback (most recent call last)")
        trace = text[idx:] if idx != -1 else text

        error_type, error_message = "RuntimeError", trace[-500:]
        for line in reversed(trace.splitlines()):
            match = re.match(r"([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):\s*(.*)", line)
            if match:
                error_type, error_message = match.group(1).split(".")[-1], match.group(2)
                break

        # Anchor to the gate's own tempdir: a bare scene.py pattern also
        # matches manim's internal manim/scene/scene.py frames and would
        # report a library line number into regeneration feedback.
        line_number = None
        for match in re.finditer(
            rf'File "[^"]*{_TMPDIR_PREFIX}[^"]*scene\.py", line (\d+)', trace
        ):
            line_number = int(match.group(1))

        info = self._refine_error(error_type, error_message)
        return RenderTestOutput(
            success=False,
            error_type=info["type"],
            error_message=info["message"],
            line_number=line_number,
            fix_suggestion=info["suggestion"],
        )
    
    def _validate_by_import(self, code: str, scene_class: str | None = None) -> RenderTestOutput:
        """
        Validate code by attempting to import it as a Python module.
        
        This catches most runtime errors without actually rendering video.
        """
        syntax_error = self._check_syntax(code)
        if syntax_error is not None:
            return syntax_error

        # Create a temporary file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write(code)
            temp_path = Path(f.name)
        
        try:
            # Try to import the module
            spec = importlib.util.spec_from_file_location(
                "test_manim_scene",
                temp_path
            )
            if spec is None or spec.loader is None:
                return RenderTestOutput(
                    success=False,
                    error_type="ImportError",
                    error_message="Could not create module spec",
                    fix_suggestion="Check that the code is valid Python"
                )
            
            module = importlib.util.module_from_spec(spec)
            
            # Add to sys.modules temporarily to allow relative imports
            sys.modules["test_manim_scene"] = module
            
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                # Parse the error for useful info
                error_info = self._parse_error(e, code)
                return RenderTestOutput(
                    success=False,
                    error_type=error_info["type"],
                    error_message=error_info["message"],
                    line_number=error_info.get("line"),
                    fix_suggestion=error_info["suggestion"]
                )
            finally:
                # Clean up sys.modules
                sys.modules.pop("test_manim_scene", None)
            
            # Check if Scene class exists and has construct method
            scene_classes = [
                obj for name, obj in module.__dict__.items()
                if isinstance(obj, type) and 
                hasattr(obj, 'construct') and
                name not in ('Scene', 'ThreeDScene', 'VoiceoverScene')
            ]
            
            if not scene_classes:
                return RenderTestOutput(
                    success=False,
                    error_type="MissingScene",
                    error_message="No Scene class with construct() method found",
                    fix_suggestion="Ensure code has a class that inherits from Scene with a construct(self) method"
                )
            
            # Success!
            return RenderTestOutput(success=True)
            
        finally:
            # Clean up temp file
            with contextlib.suppress(Exception):
                temp_path.unlink()
    
    def _parse_error(self, error: Exception, code: str) -> dict[str, Any]:
        """Parse an exception to extract useful error information."""
        # Try to get line number from traceback
        line_number = None
        tb = traceback.extract_tb(error.__traceback__)
        for frame in reversed(tb):
            if "test_manim_scene" in frame.filename:
                line_number = frame.lineno
                break

        info = self._refine_error(type(error).__name__, str(error))
        info["line"] = line_number
        return info

    def _refine_error(self, error_type: str, error_msg: str) -> dict[str, Any]:
        """Map an error type/message onto a targeted fix suggestion."""
        # Get suggestion based on error type
        suggestion = self.ERROR_FIXES.get(error_type, "Review the error and fix accordingly")

        # Special handling for common Manim errors
        if "latex" in error_msg.lower() or "tex" in error_msg.lower():
            suggestion = (
                "LaTeX error detected. Common fixes:\n"
                "1. Each MathTex part must be valid LaTeX on its own\n"
                "2. Don't split \\frac{}{}, \\sqrt{}, \\begin{} across parts\n"
                "3. Use set_color_by_tex() instead of splitting for highlighting"
            )
            error_type = "LaTeXError"
        
        elif "has no attribute" in error_msg:
            # Try to extract the attribute name
            attr_match = error_msg.split("'")
            if len(attr_match) >= 4:
                obj_type = attr_match[1]
                attr_name = attr_match[3]
                suggestion = f"The object of type '{obj_type}' doesn't have attribute '{attr_name}'. Check Manim documentation for correct method names."
        
        elif "positional argument" in error_msg or "keyword argument" in error_msg:
            suggestion = "Check the function signature - you may have too many or too few arguments, or incorrect keyword names."
        
        return {
            "type": error_type,
            "message": error_msg,
            "suggestion": suggestion,
        }
    
    def test_render_sync(self, code: str) -> RenderTestOutput:
        """
        Synchronous version of test_render for simpler usage.
        """
        return asyncio.run(self.test_render(code))


# For testing
if __name__ == "__main__":
    # Test with valid code
    valid_code = '''
from manim import *

class TestScene(Scene):
    def construct(self):
        circle = Circle(color=BLUE)
        self.play(Create(circle))
        self.wait(1)
'''
    
    # Test with invalid code (missing import)
    invalid_code1 = '''
class TestScene(Scene):
    def construct(self):
        circle = Circle(color=BLUE)
        self.play(Create(circle))
'''
    
    # Test with runtime error
    invalid_code2 = '''
from manim import *

class TestScene(Scene):
    def construct(self):
        circle = Circle(color=BLUE)
        circle.nonexistent_method()  # This will fail
'''
    
    # Test with syntax error
    invalid_code3 = '''
from manim import *

class TestScene(Scene):
    def construct(self)  # Missing colon
        circle = Circle(color=BLUE)
'''
    
    tester = RenderTester()
    
    print("Testing valid code...")
    result = tester.test_render_sync(valid_code)
    print(f"  Success: {result.success}")
    
    print("\nTesting code with missing import...")
    result = tester.test_render_sync(invalid_code1)
    print(f"  Success: {result.success}")
    print(f"  Error: {result.error_type} - {result.error_message}")
    
    print("\nTesting code with runtime error...")
    result = tester.test_render_sync(invalid_code2)
    print(f"  Success: {result.success}")
    print(f"  Error: {result.error_type} - {result.error_message}")
    
    print("\nTesting code with syntax error...")
    result = tester.test_render_sync(invalid_code3)
    print(f"  Success: {result.success}")
    print(f"  Error: {result.error_type} - {result.error_message}")
    if result.line_number:
        print(f"  Line: {result.line_number}")
    
    print("\n" + "=" * 50)
    print("Feedback message example:")
    print(result.get_feedback_message())
