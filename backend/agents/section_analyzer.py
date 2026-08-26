"""Section Analyzer Agent - Identifies concepts that need visualization."""

import sys
from pathlib import Path

# Handle both package and direct imports
try:
    from ..models.generation import AnalyzerOutput, VisualizationCandidate, VisualizationType
    from ..models.paper import Section
    from .base import BaseAgent
except ImportError:
    # Add parent to path for direct execution
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.base import BaseAgent
    from models.generation import AnalyzerOutput, VisualizationCandidate, VisualizationType
    from models.paper import Section


class SectionAnalyzer(BaseAgent):
    """
    Analyzes paper sections to identify concepts that would benefit from visualization.
    
    This agent reads each section and determines:
    1. Whether visualization would help understanding
    2. What specific concepts should be visualized
    3. What type of visualization (architecture, equation, algorithm, data_flow)
    4. Priority ranking for each concept
    """
    
    def __init__(self, model: str | None = None):
        super().__init__("section_analyzer.md", model=model)
    
    def _format_equations(self, section: Section) -> str:
        """Format equations for the prompt."""
        if not section.equations:
            return "No equations in this section."
        
        equations_text = []
        for eq in section.equations:
            eq_str = f"- LaTeX: {eq.latex}"
            if eq.context:
                eq_str += f"\n  Context: {eq.context}"
            equations_text.append(eq_str)
        
        return "\n".join(equations_text)
    
    async def run(
        self,
        paper_title: str,
        paper_abstract: str,
        section: Section,
    ) -> AnalyzerOutput:
        """
        Analyze a section to identify visualization candidates.
        
        Args:
            paper_title: Title of the paper
            paper_abstract: Abstract for context
            section: The section to analyze
            
        Returns:
            AnalyzerOutput with visualization candidates
        """
        prompt = self._format_prompt(
            paper_title=paper_title,
            paper_abstract=paper_abstract,
            section_id=section.id,
            section_title=section.title,
            section_content=section.content,
            equations=self._format_equations(section),
        )
        
        text = await self._call_llm(prompt)

        result = self._parse_json_response(text)
        return self._parse_result(result, section.id)

    def _parse_result(self, result: dict, section_id: str) -> AnalyzerOutput:
        """Parse the LLM response into an AnalyzerOutput."""
        candidates = []
        
        for candidate_data in result.get("candidates", []):
            # Map string visualization type to enum
            viz_type_str = candidate_data.get("visualization_type", "equation")
            try:
                viz_type = VisualizationType(viz_type_str)
            except ValueError:
                viz_type = VisualizationType.EQUATION
            
            candidate = VisualizationCandidate(
                section_id=section_id,  # Always use the actual section ID, not LLM-generated one
                concept_name=candidate_data.get("concept_name", "Unknown Concept"),
                concept_description=candidate_data.get("concept_description", ""),
                visualization_type=viz_type,
                priority=min(5, max(1, candidate_data.get("priority", 3))),
                context=candidate_data.get("context", ""),
            )
            candidates.append(candidate)
        
        return AnalyzerOutput(
            section_id=section_id,
            needs_visualization=result.get("needs_visualization", False),
            candidates=candidates,
            reasoning=result.get("reasoning", ""),
        )
    
    def run_sync(
        self,
        paper_title: str,
        paper_abstract: str,
        section: Section,
    ) -> AnalyzerOutput:
        """Synchronous version for testing."""
        prompt = self._format_prompt(
            paper_title=paper_title,
            paper_abstract=paper_abstract,
            section_id=section.id,
            section_title=section.title,
            section_content=section.content,
            equations=self._format_equations(section),
        )
        
        text = self._call_llm_sync(prompt)

        result = self._parse_json_response(text)
        return self._parse_result(result, section.id)
