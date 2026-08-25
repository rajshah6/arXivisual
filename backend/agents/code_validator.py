"""Code Validator - Validates Manim code syntax without execution."""

import ast
import re
import sys
from pathlib import Path
from typing import Optional

# Handle both package and direct imports
try:
    from ..models.generation import ValidatorOutput
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from models.generation import ValidatorOutput


class CodeValidator:
    """
    Validates Manim code syntax without executing it.
    
    Performs:
    1. Python syntax checking via AST parsing
    2. Required import verification
    3. Scene class structure validation
    4. Common issue detection and auto-fixing
    """
    
    REQUIRED_IMPORTS = [
        "from manim import",
        "from manim import *",
    ]

    def validate(self, code: str) -> ValidatorOutput:
        """
        Validate Manim code and attempt to fix common issues.
        
        Args:
            code: The Manim Python code to validate
            
        Returns:
            ValidatorOutput with validation results and fixed code
        """
        issues_found: list[str] = []
        issues_fixed: list[str] = []
        fixed_code = code
        
        # Step 1: Check Python syntax
        syntax_error = self._check_syntax(code)
        if syntax_error:
            issues_found.append(syntax_error)
            # Try to fix common syntax issues
            fixed_code, syntax_fixes = self._attempt_syntax_fixes(code)
            issues_fixed.extend(syntax_fixes)
            
            # Re-check after fixes
            if self._check_syntax(fixed_code):
                # Still broken, needs regeneration
                return ValidatorOutput(
                    is_valid=False,
                    code=code,
                    issues_found=issues_found,
                    issues_fixed=issues_fixed,
                    needs_regeneration=True,
                )
        
        # Step 2: Check manim import
        if not self._has_manim_import(fixed_code):
            fixed_code = "from manim import *\n\n" + fixed_code
            issues_fixed.append("Added missing manim import")
        
        # Step 3: Check Scene class exists
        if not self._has_scene_class(fixed_code):
            issues_found.append("No Scene class found (e.g., `class MyScene(Scene):`)")
        
        # Step 4: Check construct method
        if not self._has_construct_method(fixed_code):
            issues_found.append("No construct method found (`def construct(self):`)")
        
        # Step 5: Check for common typos in Manim objects
        typo_fixes = self._fix_common_typos(fixed_code)
        if typo_fixes:
            fixed_code, typo_issues = typo_fixes
            issues_fixed.extend(typo_issues)
        
        # Step 6: Check for dangerous MathTex splitting patterns
        mathtex_issues = self._check_mathtex_splitting(fixed_code)
        if mathtex_issues:
            issues_found.extend(mathtex_issues)
        
        # Determine if regeneration is needed
        # More than 1 unfixed issue OR MathTex issues = regenerate
        needs_regeneration = len(issues_found) > 1 or bool(mathtex_issues)
        
        return ValidatorOutput(
            is_valid=len(issues_found) == 0,
            code=fixed_code,
            issues_found=issues_found,
            issues_fixed=issues_fixed,
            needs_regeneration=needs_regeneration,
        )
    
    def _check_syntax(self, code: str) -> Optional[str]:
        """Check Python syntax using AST parser."""
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"Syntax error at line {e.lineno}: {e.msg}"
    
    def _has_manim_import(self, code: str) -> bool:
        """Check if code has manim import."""
        return any(imp in code for imp in self.REQUIRED_IMPORTS)
    
    def _has_scene_class(self, code: str) -> bool:
        """Check if code has a Scene class definition."""
        # Match: class SomeName(Scene|ThreeDScene|VoiceoverScene):
        pattern = r"class\s+\w+\s*\(\s*(Scene|ThreeDScene|VoiceoverScene)\s*\)\s*:"
        return bool(re.search(pattern, code))
    
    def _has_construct_method(self, code: str) -> bool:
        """Check if code has a construct method."""
        return "def construct(self)" in code
    
    def _attempt_syntax_fixes(self, code: str) -> tuple[str, list[str]]:
        """
        Attempt to fix common syntax issues.
        
        Returns:
            Tuple of (fixed_code, list of fixes applied)
        """
        fixes = []
        fixed_code = code
        
        # Fix 1: Missing colons after class/def
        # This is tricky and may not always work
        
        # Fix 2: Unclosed parentheses (basic attempt)
        open_parens = fixed_code.count('(')
        close_parens = fixed_code.count(')')
        if open_parens > close_parens:
            fixed_code += ')' * (open_parens - close_parens)
            fixes.append(f"Added {open_parens - close_parens} missing closing parentheses")
        
        # Fix 3: Unclosed brackets
        open_brackets = fixed_code.count('[')
        close_brackets = fixed_code.count(']')
        if open_brackets > close_brackets:
            fixed_code += ']' * (open_brackets - close_brackets)
            fixes.append(f"Added {open_brackets - close_brackets} missing closing brackets")
        
        # Fix 4: Unclosed braces
        open_braces = fixed_code.count('{')
        close_braces = fixed_code.count('}')
        if open_braces > close_braces:
            fixed_code += '}' * (open_braces - close_braces)
            fixes.append(f"Added {open_braces - close_braces} missing closing braces")
        
        # Fix 5: Remove trailing incomplete lines
        lines = fixed_code.split('\n')
        if lines and lines[-1].strip().endswith(('(', '[', '{', ',', '+')):
            lines = lines[:-1]
            fixed_code = '\n'.join(lines)
            fixes.append("Removed trailing incomplete line")
        
        return fixed_code, fixes
    
    def _fix_common_typos(self, code: str) -> Optional[tuple[str, list[str]]]:
        """
        Fix common typos in Manim code.
        
        Returns:
            Tuple of (fixed_code, list of fixes) or None if no fixes
        """
        fixes = []
        fixed_code = code
        
        # Common color typos
        color_typos = {
            "GREY": "GRAY",
            "DARKGRAY": "DARK_GRAY",
            "DARK_GREY": "DARK_GRAY",
        }
        
        for typo, correct in color_typos.items():
            if typo in fixed_code:
                fixed_code = fixed_code.replace(typo, correct)
                fixes.append(f"Fixed color typo: {typo} -> {correct}")
        
        # Common method typos
        method_typos = {
            "fadein": "FadeIn",
            "fadeout": "FadeOut",
            "fadeIn": "FadeIn",
            "fadeOut": "FadeOut",
        }
        
        for typo, correct in method_typos.items():
            # Use word boundary to avoid partial matches
            pattern = r'\b' + typo + r'\b'
            if re.search(pattern, fixed_code):
                fixed_code = re.sub(pattern, correct, fixed_code)
                fixes.append(f"Fixed method typo: {typo} -> {correct}")
        
        if fixes:
            return fixed_code, fixes
        return None
    
    def _check_mathtex_splitting(self, code: str) -> list[str]:
        """
        Check for dangerous MathTex splitting patterns that will crash Manim.
        
        MathTex parts must each be valid LaTeX on their own.
        Patterns like MathTex(r"\\frac{", "x", r"}") will crash.
        """
        issues = []
        
        # Find MathTex calls with multiple arguments
        # Look for patterns that open LaTeX commands but don't close them
        
        # Dangerous patterns: opening braces without closing in same string
        dangerous_patterns = [
            # Incomplete \frac - opens { but numerator not closed in same part
            (r'r?"\\\\frac\s*\{[^}]*"', 'MathTex has incomplete \\frac{} - numerator/denominator split across parts'),
            # Incomplete \sqrt
            (r'r?"\\\\sqrt\s*\{[^}]*"(?=\s*,)', 'MathTex has incomplete \\sqrt{} split across parts'),
            # Incomplete \left( without matching \right)
            (r'r?"[^"]*\\\\left\s*[\(\[\{][^"]*"(?=\s*,)', 'MathTex has \\left( without \\right) in same part'),
            # Incomplete \begin without \end
            (r'r?"[^"]*\\\\begin\s*\{[^}]+\}[^"]*"(?=\s*,)(?![^"]*\\\\end)', 'MathTex has \\begin{} without \\end{} in same part'),
            # Opening brace at end of string (very common LLM mistake)
            (r'r?"[^"]*\{[^}"]*"\s*,\s*r?"[^{}"]+"\s*,\s*r?"[^{]*\}', 'MathTex splits content inside braces'),
        ]
        
        for pattern, message in dangerous_patterns:
            if re.search(pattern, code):
                issues.append(f"CRITICAL: {message}. Each MathTex part must be valid LaTeX alone. Use set_color_by_tex() instead.")
                break  # One issue is enough to trigger regeneration
        
        # Also check for the specific pattern we saw: \text{...}\left(\frac{
        if re.search(r'r?"[^"]*\\\\frac\s*\{"', code):
            # Check if it's followed by a comma (meaning it's split)
            if re.search(r'r?"[^"]*\\\\frac\s*\{"\s*,', code):
                issues.append("CRITICAL: MathTex splits \\frac{} across parts - this will crash. Write formula as single string and use set_color_by_tex().")
        
        return issues
    
    def get_error_summary(self, output: ValidatorOutput) -> str:
        """Get a human-readable summary of validation errors."""
        if output.is_valid:
            return "Code is valid."
        
        lines = ["Validation failed:"]
        
        if output.issues_found:
            lines.append("\nIssues found:")
            for issue in output.issues_found:
                lines.append(f"  - {issue}")
        
        if output.issues_fixed:
            lines.append("\nIssues auto-fixed:")
            for fix in output.issues_fixed:
                lines.append(f"  - {fix}")
        
        if output.needs_regeneration:
            lines.append("\nCode needs to be regenerated.")
        
        return "\n".join(lines)
