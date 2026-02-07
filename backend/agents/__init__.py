"""
ArXiviz Agent Pipeline - Team 2

This module provides the multi-agent AI pipeline for generating Manim visualizations
from structured academic papers.

Usage:
    from agents import generate_visualizations
    from models import StructuredPaper
    
    paper = StructuredPaper(...)
    visualizations = await generate_visualizations(paper)
"""

# Use relative imports for package usage
from .base import BaseAgent
from .section_analyzer import SectionAnalyzer
from .visualization_planner import VisualizationPlanner
from .manim_generator import ManimGenerator
from .code_validator import CodeValidator
from .voiceover_script_validator import VoiceoverScriptValidator
from .pipeline import generate_visualizations, generate_single_visualization

__all__ = [
    "BaseAgent",
    "SectionAnalyzer",
    "VisualizationPlanner",
    "ManimGenerator",
    "CodeValidator",
    "VoiceoverScriptValidator",
    "generate_visualizations",
    "generate_single_visualization",
]
