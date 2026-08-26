"""Generation pipeline models for Team 2 agents."""

from enum import Enum

from pydantic import BaseModel, Field


class VisualizationType(str, Enum):
    """Types of visualizations that can be generated."""
    
    ARCHITECTURE = "architecture"
    EQUATION = "equation"
    ALGORITHM = "algorithm"
    DATA_FLOW = "data_flow"
    MATRIX = "matrix"
    THREE_D = "three_d"  # 3D visualizations (neural networks, data cubes, etc.)


class VisualizationStatus(str, Enum):
    """Status of a visualization in the pipeline."""
    
    PENDING = "pending"
    RENDERING = "rendering"
    COMPLETE = "complete"
    FAILED = "failed"


class VisualizationCandidate(BaseModel):
    """A concept identified as needing visualization."""
    
    section_id: str = Field(..., description="ID of the section containing this concept")
    concept_name: str = Field(..., description="Name of the concept, e.g., 'Scaled Dot-Product Attention'")
    concept_description: str = Field(..., description="What needs to be visualized")
    visualization_type: VisualizationType = Field(..., description="Type of visualization needed")
    priority: int = Field(..., ge=1, le=5, description="Priority 1-5, higher = more important")
    context: str = Field(..., description="Relevant text from section")


class AnalyzerOutput(BaseModel):
    """Output from the Section Analyzer agent."""
    
    section_id: str = Field(..., description="ID of the analyzed section")
    needs_visualization: bool = Field(..., description="Whether this section needs visualization")
    candidates: list[VisualizationCandidate] = Field(default_factory=list, description="Visualization candidates")
    reasoning: str = Field("", description="Explanation of the decision")


class Scene(BaseModel):
    """A single scene in a visualization storyboard."""
    
    order: int = Field(..., description="Scene order (1, 2, 3, ...)")
    description: str = Field(..., description="What appears on screen")
    duration_seconds: int = Field(..., ge=1, le=30, description="Scene duration")
    transitions: str = Field(..., description="How to animate in/out")
    elements: list[str] = Field(default_factory=list, description="Manim objects needed")


class VisualizationPlan(BaseModel):
    """Storyboard plan for a visualization."""
    
    concept_name: str = Field(..., description="Name of the concept being visualized")
    visualization_type: VisualizationType = Field(..., description="Type of visualization")
    duration_seconds: int = Field(..., ge=15, le=60, description="Target video length")
    scenes: list[Scene] = Field(default_factory=list, description="Ordered list of scenes")
    narration_points: list[str] = Field(default_factory=list, description="Key points to convey")


class GeneratedCode(BaseModel):
    """Output from the Manim Generator agent."""
    
    code: str = Field(..., description="Full Manim Python code")
    scene_class_name: str = Field(..., description="Name of the Scene class")
    dependencies: list[str] = Field(default_factory=list, description="Extra imports needed")
    voiceover_enabled: bool = Field(False, description="Whether code is generated with VoiceoverScene")
    narration_lines: list[str] = Field(default_factory=list, description="Narration lines extracted from voiceover blocks")
    narration_beats: list[str] = Field(default_factory=list, description="Beat labels in code order (e.g. '# Beat 1')")


class ValidatorOutput(BaseModel):
    """Output from the Code Validator."""
    
    is_valid: bool = Field(..., description="Whether the code is valid")
    code: str = Field(..., description="Fixed code if needed")
    issues_found: list[str] = Field(default_factory=list, description="Issues that couldn't be auto-fixed")
    issues_fixed: list[str] = Field(default_factory=list, description="Issues that were auto-fixed")
    needs_regeneration: bool = Field(False, description="If True, code should be regenerated")


class Visualization(BaseModel):
    """Final visualization output for Team 3."""
    
    id: str = Field(..., description="Unique visualization ID")
    section_id: str = Field(..., description="Which section this belongs to")
    concept: str = Field(..., description="Human-readable concept name")
    storyboard: str = Field(..., description="JSON storyboard from planner")
    manim_code: str = Field(..., description="Complete, validated Python code")
    video_url: str | None = Field(None, description="URL after rendering (filled by Team 3)")
    status: VisualizationStatus = Field(VisualizationStatus.PENDING, description="Current status")
