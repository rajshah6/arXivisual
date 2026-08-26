"""
Spatial Validator Agent for detecting positioning issues in Manim code.

Analyzes generated Manim code for:
1. Out-of-bounds elements (off-screen)
2. Overlapping elements
3. Missing spacing/buff parameters
4. Poor positioning patterns
"""

import re

# Handle imports for both package and direct execution
try:
    from ..models.spatial import (
        BoundsIssue,
        OverlapIssue,
        PositionInfo,
        SpacingIssue,
        SpatialValidatorOutput,
    )
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from models.spatial import (
        BoundsIssue,
        OverlapIssue,
        PositionInfo,
        SpacingIssue,
        SpatialValidatorOutput,
    )


class SpatialValidator:
    """
    Validates Manim code for spatial/positioning issues.
    
    Uses static analysis to detect:
    - Elements positioned outside screen bounds
    - Elements that may overlap each other
    - Missing buff/spacing parameters
    - Poor positioning patterns (hardcoded values vs relative positioning)
    """
    
    # Manim default screen bounds (16:9 aspect ratio)
    # Actual bounds are ~14.22 x 8 but we use safe margins
    SCREEN_BOUNDS_X = (-7.0, 7.0)
    SCREEN_BOUNDS_Y = (-4.0, 4.0)
    SAFE_BOUNDS_X = (-6.0, 6.0)  # Safe area with margin
    SAFE_BOUNDS_Y = (-3.5, 3.5)  # Safe area with margin
    
    # Direction constants in Manim
    DIRECTION_VALUES = {
        "UP": (0, 1),
        "DOWN": (0, -1),
        "LEFT": (-1, 0),
        "RIGHT": (1, 0),
        "UL": (-1, 1),
        "UR": (1, 1),
        "DL": (-1, -1),
        "DR": (1, -1),
        "ORIGIN": (0, 0),
    }
    
    # Minimum recommended spacing
    MIN_SPACING = 0.3
    
    def validate(self, code: str) -> SpatialValidatorOutput:
        """
        Validate Manim code for spatial issues.
        
        Args:
            code: The Manim Python code to validate
            
        Returns:
            SpatialValidatorOutput with detected issues and suggestions
        """
        # Extract all positioning operations
        positions = self._extract_positions(code)
        
        # Check for out-of-bounds issues
        bounds_issues = self._check_bounds(positions)
        
        # Check for potential overlaps
        overlap_issues = self._detect_overlaps(positions)
        
        # Check for missing spacing parameters
        spacing_issues = self._check_spacing(code)
        
        # Generate general suggestions
        suggestions = self._generate_suggestions(code, positions)
        
        # Determine if regeneration is needed
        has_issues = bool(bounds_issues or overlap_issues or spacing_issues)
        
        # Only force regeneration for serious issues
        needs_regen = (
            len(bounds_issues) >= 2 or  # Multiple off-screen elements
            len(overlap_issues) >= 2 or  # Multiple overlaps
            any("critical" in issue.issue.lower() for issue in bounds_issues)
        )
        
        return SpatialValidatorOutput(
            has_spatial_issues=has_issues,
            out_of_bounds=bounds_issues,
            potential_overlaps=overlap_issues,
            spacing_issues=spacing_issues,
            suggestions=suggestions,
            needs_regeneration=needs_regen,
        )
    
    def _extract_positions(self, code: str) -> list[PositionInfo]:
        """Extract all positioning operations from code."""
        positions = []
        lines = code.split("\n")
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Skip comments and empty lines
            if not stripped or stripped.startswith("#"):
                continue
            
            # Look for positioning methods
            position_patterns = [
                # move_to patterns
                (r"(\w+)\.move_to\s*\((.*?)\)", "move_to"),
                # shift patterns
                (r"(\w+)\.shift\s*\((.*?)\)", "shift"),
                # next_to patterns
                (r"(\w+)\.next_to\s*\((.*?)\)", "next_to"),
                # to_edge patterns
                (r"(\w+)\.to_edge\s*\((.*?)\)", "to_edge"),
                # to_corner patterns
                (r"(\w+)\.to_corner\s*\((.*?)\)", "to_corner"),
                # animate.shift patterns
                (r"(\w+)\.animate\.shift\s*\((.*?)\)", "animate.shift"),
                # animate.move_to patterns
                (r"(\w+)\.animate\.move_to\s*\((.*?)\)", "animate.move_to"),
            ]
            
            for pattern, method in position_patterns:
                matches = re.findall(pattern, stripped)
                for match in matches:
                    element_name = match[0]
                    args = match[1]
                    
                    # Try to parse the position
                    x_pos, y_pos = self._parse_position(args)
                    
                    positions.append(PositionInfo(
                        element_name=element_name,
                        line_number=i,
                        x_position=x_pos,
                        y_position=y_pos,
                        position_method=method,
                        raw_code=stripped,
                    ))
        
        return positions
    
    def _parse_position(self, args: str) -> tuple[float | None, float | None]:
        """
        Parse position arguments to estimate x, y coordinates.
        
        This is heuristic - we can't know exact positions without execution,
        but we can detect obvious issues like RIGHT * 10.
        """
        x_pos = 0.0
        y_pos = 0.0
        
        # Handle direction * scalar patterns
        # RIGHT * 5, DOWN * 3, UP * 2.5, etc.
        direction_pattern = r"(UP|DOWN|LEFT|RIGHT|UL|UR|DL|DR)\s*\*\s*([\d.]+)"
        matches = re.findall(direction_pattern, args)
        
        for direction, scalar in matches:
            try:
                scalar_val = float(scalar)
                dx, dy = self.DIRECTION_VALUES.get(direction, (0, 0))
                x_pos += dx * scalar_val
                y_pos += dy * scalar_val
            except ValueError:
                pass
        
        # Handle scalar * direction patterns (e.g., 5 * RIGHT)
        reverse_pattern = r"([\d.]+)\s*\*\s*(UP|DOWN|LEFT|RIGHT|UL|UR|DL|DR)"
        matches = re.findall(reverse_pattern, args)
        
        for scalar, direction in matches:
            try:
                scalar_val = float(scalar)
                dx, dy = self.DIRECTION_VALUES.get(direction, (0, 0))
                x_pos += dx * scalar_val
                y_pos += dy * scalar_val
            except ValueError:
                pass
        
        # Handle ORIGIN
        if "ORIGIN" in args and "+" not in args and "-" not in args:
            return 0.0, 0.0
        
        # If we found any direction components, return the position
        if matches or "ORIGIN" in args:
            return x_pos, y_pos
        
        # Couldn't determine position
        return None, None
    
    def _check_bounds(self, positions: list[PositionInfo]) -> list[BoundsIssue]:
        """Check for elements that may be out of screen bounds."""
        issues = []
        
        for pos in positions:
            # Skip if we couldn't determine position
            if pos.x_position is None and pos.y_position is None:
                continue
            
            # Check X bounds
            if pos.x_position is not None:
                if abs(pos.x_position) > self.SCREEN_BOUNDS_X[1]:
                    issues.append(BoundsIssue(
                        element_name=pos.element_name,
                        line_number=pos.line_number,
                        issue=f"CRITICAL: Element '{pos.element_name}' at x={pos.x_position:.1f} is outside screen bounds (max |x| = 7)",
                        suggested_fix=f"Use x position between -6 and 6. Try: {pos.element_name}.move_to(RIGHT * {min(6, abs(pos.x_position)):.1f})"
                    ))
                elif abs(pos.x_position) > self.SAFE_BOUNDS_X[1]:
                    issues.append(BoundsIssue(
                        element_name=pos.element_name,
                        line_number=pos.line_number,
                        issue=f"Element '{pos.element_name}' at x={pos.x_position:.1f} is near screen edge (safe area: |x| < 6)",
                        suggested_fix="Consider moving closer to center for better visibility"
                    ))
            
            # Check Y bounds
            if pos.y_position is not None:
                if abs(pos.y_position) > self.SCREEN_BOUNDS_Y[1]:
                    issues.append(BoundsIssue(
                        element_name=pos.element_name,
                        line_number=pos.line_number,
                        issue=f"CRITICAL: Element '{pos.element_name}' at y={pos.y_position:.1f} is outside screen bounds (max |y| = 4)",
                        suggested_fix="Use y position between -3.5 and 3.5. Reduce the multiplier."
                    ))
                elif abs(pos.y_position) > self.SAFE_BOUNDS_Y[1]:
                    issues.append(BoundsIssue(
                        element_name=pos.element_name,
                        line_number=pos.line_number,
                        issue=f"Element '{pos.element_name}' at y={pos.y_position:.1f} is near screen edge (safe area: |y| < 3.5)",
                        suggested_fix="Consider moving closer to center for better visibility"
                    ))
        
        return issues
    
    def _detect_overlaps(self, positions: list[PositionInfo]) -> list[OverlapIssue]:
        """Detect elements that may be overlapping based on similar positions."""
        issues = []
        
        # Group positions by approximate location
        for i, pos1 in enumerate(positions):
            if pos1.x_position is None or pos1.y_position is None:
                continue
                
            for pos2 in positions[i + 1:]:
                if pos2.x_position is None or pos2.y_position is None:
                    continue
                
                # Skip if same element (might be repositioned)
                if pos1.element_name == pos2.element_name:
                    continue
                
                # Check if positions are very close
                x_diff = abs(pos1.x_position - pos2.x_position) if pos1.x_position and pos2.x_position else float('inf')
                y_diff = abs(pos1.y_position - pos2.y_position) if pos1.y_position and pos2.y_position else float('inf')
                
                # If both coordinates are close, potential overlap
                if x_diff < 1.5 and y_diff < 0.8:
                    issues.append(OverlapIssue(
                        element1=pos1.element_name,
                        element2=pos2.element_name,
                        line1=pos1.line_number,
                        line2=pos2.line_number,
                        issue=f"Elements '{pos1.element_name}' and '{pos2.element_name}' may overlap at approximately ({pos1.x_position:.1f}, {pos1.y_position:.1f}) and ({pos2.x_position:.1f}, {pos2.y_position:.1f})",
                        suggested_fix=f"Use next_to() for relative positioning: {pos2.element_name}.next_to({pos1.element_name}, DOWN, buff=0.5)"
                    ))
                
                # If Y is same but X might overlap (common issue with DOWN positioning)
                elif y_diff < 0.3 and x_diff < 3:
                    issues.append(OverlapIssue(
                        element1=pos1.element_name,
                        element2=pos2.element_name,
                        line1=pos1.line_number,
                        line2=pos2.line_number,
                        issue=f"Elements '{pos1.element_name}' and '{pos2.element_name}' are at similar y-position ({pos1.y_position:.1f}), may overlap horizontally",
                        suggested_fix=f"Use arrange() or add horizontal spacing: {pos2.element_name}.next_to({pos1.element_name}, RIGHT, buff=0.5)"
                    ))
        
        return issues
    
    def _check_spacing(self, code: str) -> list[SpacingIssue]:
        """Check for missing buff/spacing parameters."""
        issues = []
        lines = code.split("\n")
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # Check next_to without buff
            if ".next_to(" in stripped and "buff" not in stripped:
                # Only flag if it's positioning important elements
                if not any(skip in stripped for skip in ["label", "text", "annotation"]):
                    issues.append(SpacingIssue(
                        line_number=i,
                        issue="next_to() called without buff parameter - may cause elements to touch",
                        suggested_fix="Add buff parameter: .next_to(other, DIRECTION, buff=0.3)"
                    ))
            
            # Check arrange without buff
            if ".arrange(" in stripped and "buff" not in stripped:
                issues.append(SpacingIssue(
                    line_number=i,
                    issue="arrange() called without buff parameter - elements may be too close",
                    suggested_fix="Add buff parameter: .arrange(DIRECTION, buff=0.3)"
                ))
            
            # Check for hardcoded DOWN * or UP * without considering other elements
            if re.search(r"\.(move_to|shift)\s*\(.*DOWN\s*\*\s*[3-9]", stripped):
                issues.append(SpacingIssue(
                    line_number=i,
                    issue="Large downward shift (DOWN * 3+) may push element to bottom of screen",
                    suggested_fix="Use to_edge(DOWN, buff=0.5) or next_to() for safer positioning"
                ))
        
        return issues
    
    def _generate_suggestions(self, code: str, positions: list[PositionInfo]) -> list[str]:
        """Generate general improvement suggestions."""
        suggestions = []
        
        # Count absolute vs relative positioning
        absolute_count = sum(1 for p in positions if p.position_method in ["move_to", "shift", "animate.shift", "animate.move_to"])
        relative_count = sum(1 for p in positions if p.position_method in ["next_to", "to_edge", "to_corner"])
        
        if absolute_count > relative_count * 2:
            suggestions.append(
                "Consider using more relative positioning (next_to, to_edge) instead of absolute (move_to, shift) for better layout consistency"
            )
        
        # Check if VGroup.arrange is used
        if "arrange(" not in code and len(positions) > 5:
            suggestions.append(
                "Consider using VGroup(...).arrange(DOWN, buff=0.3) for organizing multiple elements"
            )
        
        # Check for scene cleanup
        if "FadeOut(*self.mobjects)" not in code and code.count("self.play(") > 10:
            suggestions.append(
                "Consider clearing the scene between major sections: self.play(FadeOut(*self.mobjects))"
            )
        
        # Check for to_edge usage with buff
        if "to_edge(" in code and "buff" not in code.split("to_edge")[1][:30]:
            suggestions.append(
                "When using to_edge(), consider adding buff parameter: to_edge(UP, buff=0.5)"
            )
        
        return suggestions


# For testing
if __name__ == "__main__":
    test_code = '''
from manim import *

class TestScene(Scene):
    def construct(self):
        title = Text("Test")
        title.to_edge(UP)
        
        box1 = Rectangle()
        box1.shift(LEFT * 8)  # Off screen!
        
        box2 = Rectangle()
        box2.shift(DOWN * 5)  # Off screen!
        
        label1 = Text("Label 1")
        label1.move_to(DOWN * 2)
        
        label2 = Text("Label 2")
        label2.move_to(DOWN * 2 + RIGHT * 0.5)  # Very close to label1
        
        group = VGroup(box1, box2)
        group.arrange(DOWN)  # No buff
        
        self.play(Write(title))
    '''
    
    validator = SpatialValidator()
    result = validator.validate(test_code)
    
    print("Has spatial issues:", result.has_spatial_issues)
    print("\nOut of bounds issues:")
    for issue in result.out_of_bounds:
        print(f"  - Line {issue.line_number}: {issue.issue}")
    
    print("\nPotential overlaps:")
    for issue in result.potential_overlaps:
        print(f"  - {issue.issue}")
    
    print("\nSpacing issues:")
    for issue in result.spacing_issues:
        print(f"  - Line {issue.line_number}: {issue.issue}")
    
    print("\nSuggestions:")
    for s in result.suggestions:
        print(f"  - {s}")
    
    print("\n" + "=" * 50)
    print("Feedback message for regeneration:")
    print(result.get_feedback_message())
