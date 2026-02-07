"""
Pydantic schemas defining the API contract between Team 3 (Backend) and Team 4 (Frontend).

These schemas are THE CONTRACT - Team 4 builds their frontend against these response formats.
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime


# === Enums ===

class JobStatus(str, Enum):
    """Processing job status values."""
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class VisualizationStatus(str, Enum):
    """Individual visualization rendering status."""
    pending = "pending"
    rendering = "rendering"
    complete = "complete"
    failed = "failed"


# === Request Schemas ===

class ProcessRequest(BaseModel):
    """Request body for POST /api/process."""
    arxiv_id: str = Field(
        ...,
        description="arXiv paper ID (e.g., '1706.03762' or '1706.03762v1')",
        examples=["1706.03762", "2301.07041v2"]
    )


class RenderRequest(BaseModel):
    """Request body for POST /api/render (test endpoint)."""
    code: str = Field(
        ...,
        description="Complete Manim Python code to render",
        examples=[
            "from manim import *\n\nclass TestScene(Scene):\n    def construct(self):\n        circle = Circle(color=BLUE)\n        self.play(Create(circle))\n        self.wait()"
        ]
    )
    quality: str = Field(
        default="low_quality",
        description="Render quality: low_quality, medium_quality, or high_quality"
    )


class RenderResponse(BaseModel):
    """Response for POST /api/render."""
    video_id: str = Field(..., description="ID of the rendered video")
    video_url: str = Field(..., description="URL to access the rendered video")
    scene_name: str = Field(..., description="Detected scene class name")
    message: str = Field(..., description="Status message")


# === Response Schemas ===

class ProcessResponse(BaseModel):
    """Response for POST /api/process."""
    job_id: str = Field(..., description="Unique job identifier for polling")
    arxiv_id: str = Field(..., description="The arXiv paper ID being processed")
    status: JobStatus = Field(..., description="Current job status")
    message: str = Field(..., description="Human-readable status message")


class StepInfo(BaseModel):
    """Individual processing step status."""
    name: str = Field(..., description="Step name (e.g., 'fetch_paper', 'render_videos')")
    status: str = Field(..., description="Step status: pending, in_progress, complete, failed")
    duration_ms: Optional[int] = Field(None, description="Time taken in milliseconds, null if not started")


class StatusResponse(BaseModel):
    """Response for GET /api/status/{job_id}."""
    job_id: str
    arxiv_id: str
    status: JobStatus
    progress: float = Field(..., ge=0.0, le=1.0, description="Progress 0.0 to 1.0")
    current_step: Optional[str] = Field(None, description="Current processing step description")
    sections_completed: int = Field(0, description="Number of sections processed")
    sections_total: int = Field(0, description="Total number of sections")
    steps_completed: list[StepInfo] = Field(default_factory=list, description="Detailed step-by-step progress")
    error: Optional[str] = Field(None, description="Error message if status is failed")
    created_at: datetime
    estimated_completion: Optional[datetime] = None


class SectionResponse(BaseModel):
    """Section data within a paper."""
    id: str
    title: str
    content: str
    summary: Optional[str] = Field(None, description="LLM-formatted summary of the section content")
    level: int = Field(..., description="Heading level (1=H1, 2=H2, etc.)")
    order_index: int = Field(..., description="Order in which sections appear")
    equations: list[str] = Field(default_factory=list, description="LaTeX equations in this section")
    video_url: Optional[str] = Field(None, description="URL to visualization video for this section, if available")


class VisualizationResponse(BaseModel):
    """Visualization data for a paper section."""
    id: str
    section_id: str = Field(..., description="ID of the section this visualization belongs to")
    concept: str = Field(..., description="Human-readable concept being visualized")
    video_url: Optional[str] = Field(None, description="URL to rendered video, null if not ready")
    status: VisualizationStatus


class PaperResponse(BaseModel):
    """Response for GET /api/paper/{arxiv_id}."""
    paper_id: str = Field(..., description="arXiv paper ID")
    title: str
    authors: list[str]
    abstract: str
    pdf_url: str
    html_url: Optional[str] = None
    sections: list[SectionResponse]
    visualizations: list[VisualizationResponse]
    processed_at: datetime


class VideoResponse(BaseModel):
    """Response for GET /api/video/{video_id}."""
    video_id: str
    url: str = Field(..., description="Public URL to the video file")
    content_type: str = Field(default="video/mp4")


class PaperSummary(BaseModel):
    """Summary of a paper for list endpoints."""
    paper_id: str
    title: str
    authors: list[str]
    visualization_count: int = Field(0, description="Number of visualizations for this paper")
    processed_at: datetime


class PaperListResponse(BaseModel):
    """Response for GET /api/papers."""
    papers: list[PaperSummary]
    total: int


class HealthResponse(BaseModel):
    """Response for GET /api/health."""
    status: str = Field(..., description="'healthy' or 'unhealthy'")
    version: str
    services: dict[str, str] = Field(
        ...,
        description="Status of dependent services",
        examples=[{"database": "connected", "redis": "connected", "modal": "configured"}]
    )
