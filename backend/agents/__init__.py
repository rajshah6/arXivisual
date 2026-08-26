"""
ArXiviz Agent Pipeline - Team 2

This module provides the multi-agent AI pipeline for generating Manim visualizations
from structured academic papers.

Sponsor Integrations:
    - Context7: Live Manim documentation via MCP

Usage:
    from agents import generate_visualizations
    from models import StructuredPaper

    paper = StructuredPaper(...)
    visualizations = await generate_visualizations(paper)
"""

try:
    from .base import BaseAgent
    from .code_validator import CodeValidator
    from .context7_docs import clear_docs_cache, get_manim_docs
    from .manim_generator import ManimGenerator
    from .pipeline import generate_single_visualization, generate_visualizations
    from .section_analyzer import SectionAnalyzer
    from .visualization_planner import VisualizationPlanner
    from .voiceover_script_validator import VoiceoverScriptValidator
except ImportError:
    from base import BaseAgent
    from code_validator import CodeValidator
    from context7_docs import clear_docs_cache, get_manim_docs
    from manim_generator import ManimGenerator
    from pipeline import generate_single_visualization, generate_visualizations
    from section_analyzer import SectionAnalyzer
    from visualization_planner import VisualizationPlanner
    from voiceover_script_validator import VoiceoverScriptValidator

__all__ = [
    # Base agents
    "BaseAgent",
    "CodeValidator",
    "ManimGenerator",
    # Pipeline agents
    "SectionAnalyzer",
    "VisualizationPlanner",
    "VoiceoverScriptValidator",
    "clear_docs_cache",
    "generate_single_visualization",
    "generate_visualizations",
    # Utilities
    "get_manim_docs",
]
