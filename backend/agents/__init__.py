"""
ArXiviz Agent Pipeline - Team 2

This module provides the multi-agent AI pipeline for generating Manim visualizations
from structured academic papers.

Sponsor Integrations:
    - Dedalus: MCP gateway for Context7 tool calling (live doc retrieval)
    - Context7: Live Manim documentation via MCP

Usage:
    from agents import generate_visualizations
    from models import StructuredPaper

    paper = StructuredPaper(...)
    visualizations = await generate_visualizations(paper)
"""

try:
    from .base import BaseAgent
    from .section_analyzer import SectionAnalyzer
    from .visualization_planner import VisualizationPlanner
    from .manim_generator import ManimGenerator
    from .code_validator import CodeValidator
    from .voiceover_script_validator import VoiceoverScriptValidator
    from .context7_docs import get_manim_docs, clear_docs_cache
    from .pipeline import generate_visualizations, generate_single_visualization
except ImportError:
    from base import BaseAgent
    from section_analyzer import SectionAnalyzer
    from visualization_planner import VisualizationPlanner
    from manim_generator import ManimGenerator
    from code_validator import CodeValidator
    from voiceover_script_validator import VoiceoverScriptValidator
    from context7_docs import get_manim_docs, clear_docs_cache
    from pipeline import generate_visualizations, generate_single_visualization

__all__ = [
    "BaseAgent",
    "SectionAnalyzer",
    "VisualizationPlanner",
    "ManimGenerator",
    "CodeValidator",
    "VoiceoverScriptValidator",
    "get_manim_docs",
    "clear_docs_cache",
    "generate_visualizations",
    "generate_single_visualization",
]
