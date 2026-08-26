"""
Render Tester Agent for validating Manim code by attempting to execute it.

This agent catches runtime errors that static analysis cannot detect:
1. Import errors (missing dependencies)
2. Runtime exceptions in construct()
3. Invalid Manim API usage
4. LaTeX compilation errors
"""

import asyncio
import contextlib
import importlib.util
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


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
    
    async def test_render(self, code: str, scene_class: str | None = None) -> RenderTestOutput:
        """
        Test Manim code by attempting to import it.
        
        Args:
            code: The Manim Python code to test
            scene_class: Optional scene class name (extracted if not provided)
            
        Returns:
            RenderTestOutput with success status and error details
        """
        try:
            # Run the validation in a thread to avoid blocking
            result = await asyncio.wait_for(
                asyncio.to_thread(self._validate_by_import, code),
                timeout=self.timeout_seconds
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
    
    def _validate_by_import(self, code: str) -> RenderTestOutput:
        """
        Validate code by attempting to import it as a Python module.
        
        This catches most runtime errors without actually rendering video.
        """
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
            # Try to compile first (catches syntax errors with line numbers)
            try:
                compile(code, temp_path.name, 'exec')
            except SyntaxError as e:
                return RenderTestOutput(
                    success=False,
                    error_type="SyntaxError",
                    error_message=str(e.msg),
                    line_number=e.lineno,
                    fix_suggestion=f"Fix syntax at line {e.lineno}: {e.msg}"
                )
            
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
        error_type = type(error).__name__
        error_msg = str(error)
        
        # Try to get line number from traceback
        line_number = None
        tb = traceback.extract_tb(error.__traceback__)
        for frame in reversed(tb):
            if "test_manim_scene" in frame.filename:
                line_number = frame.lineno
                break
        
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
            "line": line_number,
            "suggestion": suggestion
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
