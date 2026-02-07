"""
ArXiviz Agent Pipeline - Team 2

This module provides the multi-agent AI pipeline for generating Manim visualizations
from structured academic papers.

Sponsor Integrations:
    - Dedalus: Multi-model handoffs via DedalusBaseAgent (Best Use of Dedalus API prize!)
    - Context7: Live Manim documentation via MCP

Usage:
    from agents import generate_visualizations
    from models import StructuredPaper

    paper = StructuredPaper(...)
    visualizations = await generate_visualizations(paper)

Dedalus Handoffs Usage:
    from agents import DedalusBaseAgent, CodeAgent
    
    # Extend DedalusBaseAgent for multi-model handoffs
    class MyAgent(DedalusBaseAgent):
        def __init__(self):
            super().__init__(prompt_file="my_prompt.md", task_type="code")
    
    # Or use convenience classes
    agent = CodeAgent(prompt_file="code_gen.md")  # Claude + Codex handoff
"""

try:
    from .base import BaseAgent
    from .dedalus_base import (
        DedalusBaseAgent,
        ResearchAgent,
        CodeAgent,
        CreativeAgent,
        AnalysisAgent,
    )
    from .section_analyzer import SectionAnalyzer
    from .visualization_planner import VisualizationPlanner
    from .manim_generator import ManimGenerator
    from .code_validator import CodeValidator
    from .voiceover_script_validator import VoiceoverScriptValidator
    from .context7_docs import get_manim_docs, clear_docs_cache
    from .pipeline import generate_visualizations, generate_single_visualization
except ImportError:
    from base import BaseAgent
    from dedalus_base import (
        DedalusBaseAgent,
        ResearchAgent,
        CodeAgent,
        CreativeAgent,
        AnalysisAgent,
    )
    from section_analyzer import SectionAnalyzer
    from visualization_planner import VisualizationPlanner
    from manim_generator import ManimGenerator
    from code_validator import CodeValidator
    from voiceover_script_validator import VoiceoverScriptValidator
    from context7_docs import get_manim_docs, clear_docs_cache
    from pipeline import generate_visualizations, generate_single_visualization

__all__ = [
    # Base agents
    "BaseAgent",
    "DedalusBaseAgent",
    # Dedalus convenience classes (multi-model handoffs)
    "ResearchAgent",
    "CodeAgent", 
    "CreativeAgent",
    "AnalysisAgent",
    # Pipeline agents
    "SectionAnalyzer",
    "VisualizationPlanner",
    "ManimGenerator",
    "CodeValidator",
    "VoiceoverScriptValidator",
    # Utilities
    "get_manim_docs",
    "clear_docs_cache",
    "generate_visualizations",
    "generate_single_visualization",
]
