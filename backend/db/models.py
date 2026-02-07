"""
SQLAlchemy database models for ArXiviz.

Models:
- Paper: arXiv paper metadata
- Section: Paper sections/chapters
- Visualization: Manim visualizations for sections
- ProcessingJob: Background processing job status
"""

from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, Float, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class Paper(Base):
    """ArXiv paper metadata."""
    __tablename__ = "papers"

    id = Column(String, primary_key=True)  # arxiv_id (e.g., "1706.03762")
    title = Column(String, nullable=False)
    authors = Column(JSON)  # List of author names
    abstract = Column(Text)
    pdf_url = Column(String)
    html_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sections = relationship("Section", back_populates="paper", cascade="all, delete-orphan")
    visualizations = relationship("Visualization", back_populates="paper", cascade="all, delete-orphan")
    jobs = relationship("ProcessingJob", back_populates="paper", cascade="all, delete-orphan")


class Section(Base):
    """Paper section/chapter."""
    __tablename__ = "sections"

    id = Column(String, primary_key=True)
    paper_id = Column(String, ForeignKey("papers.id"), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text)
    summary = Column(Text, nullable=True)  # LLM-formatted summary
    level = Column(Integer, default=1)  # Heading level (1=H1, 2=H2, etc.)
    order_index = Column(Integer, default=0)  # Order in paper
    equations = Column(JSON, default=list)  # List of LaTeX equation strings
    figures = Column(JSON, default=list)  # List of figure dicts from ingestion
    tables = Column(JSON, default=list)  # List of table dicts from ingestion

    # Relationships
    paper = relationship("Paper", back_populates="sections")


class Visualization(Base):
    """Manim visualization for a paper section."""
    __tablename__ = "visualizations"

    id = Column(String, primary_key=True)
    paper_id = Column(String, ForeignKey("papers.id"), nullable=True)  # Nullable for standalone uploads
    section_id = Column(String, ForeignKey("sections.id"), nullable=True)
    concept = Column(String, nullable=False)  # Human-readable concept name
    storyboard = Column(JSON, nullable=True)  # Animation storyboard data
    manim_code = Column(Text, nullable=True)  # Generated Manim Python code
    video_url = Column(String, nullable=True)  # URL to rendered video
    status = Column(String, default="pending")  # pending, rendering, complete, failed
    error = Column(Text, nullable=True)  # Error message if failed
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    paper = relationship("Paper", back_populates="visualizations")


class ProcessingJob(Base):
    """Background processing job for paper pipeline."""
    __tablename__ = "processing_jobs"

    id = Column(String, primary_key=True)
    paper_id = Column(String, ForeignKey("papers.id"), nullable=True)
    status = Column(String, default="queued")  # queued, processing, completed, failed
    progress = Column(Float, default=0.0)  # 0.0 to 1.0
    sections_completed = Column(Integer, default=0)
    sections_total = Column(Integer, default=0)
    current_step = Column(String, nullable=True)  # Human-readable current step
    error = Column(Text, nullable=True)  # Error message if failed
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    paper = relationship("Paper", back_populates="jobs")
