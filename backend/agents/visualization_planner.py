"""Visualization Planner Agent - Creates storyboards for animations."""

import sys
from pathlib import Path

# Handle both package and direct imports
try:
    from ..models.generation import (
        Scene,
        VisualizationCandidate,
        VisualizationPlan,
        VisualizationType,
    )
    from .base import BaseAgent
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.base import BaseAgent
    from models.generation import (
        Scene,
        VisualizationCandidate,
        VisualizationPlan,
        VisualizationType,
    )


class VisualizationPlanner(BaseAgent):
    """
    Creates detailed storyboards for Manim visualizations.
    
    Takes a visualization candidate and produces a scene-by-scene
    breakdown of how to animate the concept, including:
    - Scene descriptions
    - Duration per scene
    - Manim elements to use
    - Transition animations
    """
    
    def __init__(self, model: str | None = None):
        super().__init__("visualization_planner.md", model=model)
    
    async def run(
        self,
        candidate: VisualizationCandidate,
        full_section_content: str,
        paper_context: str,
    ) -> VisualizationPlan:
        """
        Create a visualization plan for a concept.
        
        Args:
            candidate: The visualization candidate from the analyzer
            full_section_content: Full text of the section
            paper_context: Title + abstract for context
            
        Returns:
            VisualizationPlan with scenes and storyboard
        """
        prompt = self._format_prompt(
            concept_name=candidate.concept_name,
            concept_description=candidate.concept_description,
            visualization_type=candidate.visualization_type.value,
            context=candidate.context,
            section_content=full_section_content,
            paper_context=paper_context,
        )
        
        text = await self._call_llm(prompt)

        result = self._parse_json_response(text)
        return self._parse_result(result, candidate.visualization_type)

    def _parse_result(
        self,
        result: dict,
        viz_type: VisualizationType,
    ) -> VisualizationPlan:
        """Parse the LLM response into a VisualizationPlan."""
        scenes = []
        
        for scene_data in result.get("scenes", []):
            scene = Scene(
                order=scene_data.get("order", len(scenes) + 1),
                description=scene_data.get("description", ""),
                duration_seconds=min(30, max(1, scene_data.get("duration_seconds", 5))),
                transitions=scene_data.get("transitions", ""),
                elements=scene_data.get("elements", []),
            )
            scenes.append(scene)
        
        # Sort scenes by order
        scenes.sort(key=lambda s: s.order)
        
        # Calculate total duration
        total_duration = sum(s.duration_seconds for s in scenes)
        # Quality-first pacing target: 30-45 seconds
        total_duration = min(45, max(30, total_duration))
        
        return VisualizationPlan(
            concept_name=result.get("concept_name", "Visualization"),
            visualization_type=viz_type,
            duration_seconds=total_duration,
            scenes=scenes,
            narration_points=result.get("narration_points", []),
        )
    
    def run_sync(
        self,
        candidate: VisualizationCandidate,
        full_section_content: str,
        paper_context: str,
    ) -> VisualizationPlan:
        """Synchronous version for testing."""
        prompt = self._format_prompt(
            concept_name=candidate.concept_name,
            concept_description=candidate.concept_description,
            visualization_type=candidate.visualization_type.value,
            context=candidate.context,
            section_content=full_section_content,
            paper_context=paper_context,
        )
        
        text = self._call_llm_sync(prompt)

        result = self._parse_json_response(text)
        return self._parse_result(result, candidate.visualization_type)
