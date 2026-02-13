# Team 3: Rendering Backend & Infrastructure

## Your Mission

Build the video rendering infrastructure on Modal.com, manage storage/database, and expose API endpoints that Team 4 (Frontend) consumes.

## Overview

```
Manim Code → Modal.com Runner → S3 Storage → PostgreSQL Cache → REST API → [Team 4 Frontend]
```

**Important**: You own the API contract. Team 4 (Frontend) builds against your endpoints. Coordinate on schemas early.

## Files You Own

```
backend/
├── rendering/
│   ├── __init__.py
│   ├── modal_runner.py      # Modal.com Manim execution
│   └── storage.py           # S3/R2 upload utilities
├── db/
│   ├── __init__.py
│   ├── models.py            # SQLAlchemy models
│   ├── connection.py        # Database connection management
│   └── queries.py           # Database queries
├── queue/
│   ├── __init__.py
│   └── worker.py            # Redis job worker
├── api/
│   ├── __init__.py
│   ├── routes.py            # FastAPI endpoint definitions
│   └── schemas.py           # Request/response Pydantic models
```

---

## Part 1: API Endpoints (Contract with Team 4)

### Endpoint Definitions (`api/routes.py`)

```python
from fastapi import APIRouter, HTTPException, BackgroundTasks
from .schemas import ProcessRequest, ProcessResponse, StatusResponse, PaperResponse
from db.queries import get_paper, get_job_status, create_job
from queue.worker import process_paper_job

router = APIRouter(prefix="/api")

@router.post("/process", response_model=ProcessResponse)
async def start_processing(request: ProcessRequest, background_tasks: BackgroundTasks):
    """
    Start processing a paper. Returns immediately with a job_id.
    Team 4 polls /status/{job_id} for progress.
    """
    job_id = await create_job(request.arxiv_id)
    background_tasks.add_task(process_paper_job, job_id, request.arxiv_id)
    return ProcessResponse(
        job_id=job_id,
        status="queued",
        paper_id=request.arxiv_id
    )


@router.get("/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str):
    """
    Get processing status. Team 4 polls this endpoint.
    """
    status = await get_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@router.get("/paper/{arxiv_id}", response_model=PaperResponse)
async def get_paper_data(arxiv_id: str):
    """
    Get processed paper with all sections and video URLs.
    Returns 404 if paper not yet processed.
    """
    paper = await get_paper(arxiv_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("/video/{video_id}")
async def get_video(video_id: str):
    """
    Redirect to S3/R2 video URL or stream directly.
    """
    from rendering.storage import get_video_url
    url = await get_video_url(video_id)
    if not url:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"url": url}
```

### Request/Response Schemas (`api/schemas.py`)

```python
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum

class ProcessRequest(BaseModel):
    arxiv_id: str

class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"

class ProcessResponse(BaseModel):
    job_id: str
    status: JobStatus
    paper_id: str

class StatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float  # 0.0 to 1.0
    sections_completed: int
    sections_total: int
    current_step: Optional[str] = None
    error: Optional[str] = None

class SectionResponse(BaseModel):
    id: str
    title: str
    content: str
    level: int
    order_index: int
    equations: List[str]
    video_url: Optional[str] = None

class PaperResponse(BaseModel):
    paper_id: str
    title: str
    authors: List[str]
    abstract: str
    pdf_url: str
    html_url: Optional[str] = None
    sections: List[SectionResponse]
```

---

## Part 2: Modal.com Manim Runner

### Setup Modal

1. Create Modal account at [modal.com](https://modal.com)
2. Install CLI: `pip install modal`
3. Authenticate: `modal token new`

### Modal Function (`rendering/modal_runner.py`)

```python
import modal
from pathlib import Path

# Define the Modal image with Manim dependencies
manim_image = modal.Image.debian_slim(python_version="3.11").apt_install(
    "ffmpeg",
    "libcairo2-dev",
    "libpango1.0-dev",
    "texlive",
    "texlive-latex-extra",
    "texlive-fonts-extra",
    "texlive-science",
    "dvisvgm"
).pip_install(
    "manim>=0.18.0",
    "numpy",
    "scipy"
)

app = modal.App("arxiviz-manim")

@app.function(
    image=manim_image,
    timeout=300,  # 5 minutes max
    memory=2048,  # 2GB RAM
)
def render_manim(code: str, scene_name: str, quality: str = "medium_quality") -> bytes:
    """
    Render Manim code and return the video bytes.

    Args:
        code: Complete Manim Python code
        scene_name: Name of the Scene class to render
        quality: "low_quality", "medium_quality", or "high_quality"

    Returns:
        MP4 video file as bytes
    """
    import tempfile
    import subprocess
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write code to file
        code_path = Path(tmpdir) / "scene.py"
        code_path.write_text(code)

        # Run Manim
        output_dir = Path(tmpdir) / "media"
        cmd = [
            "manim",
            "render",
            str(code_path),
            scene_name,
            f"--{quality}",
            "--format=mp4",
            f"--media_dir={output_dir}"
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=240
        )

        if result.returncode != 0:
            raise RuntimeError(f"Manim render failed: {result.stderr}")

        # Find the output video
        video_files = list(output_dir.rglob("*.mp4"))
        if not video_files:
            raise RuntimeError("No video file produced")

        return video_files[0].read_bytes()


# For local testing
@app.local_entrypoint()
def main():
    test_code = '''
from manim import *

class TestScene(Scene):
    def construct(self):
        circle = Circle(color=BLUE)
        self.play(Create(circle))
        self.wait()
'''
    video_bytes = render_manim.remote(test_code, "TestScene", "low_quality")
    Path("test_output.mp4").write_bytes(video_bytes)
    print("Rendered to test_output.mp4")
```

### Render Queue Manager (`rendering/__init__.py`)

```python
import asyncio
import re
from .modal_runner import render_manim
from .storage import upload_video
from db.queries import update_visualization_status

async def process_visualization(viz_id: str, manim_code: str, scene_name: str):
    """
    Process a single visualization: render and upload.
    """
    try:
        # Update status to rendering
        await update_visualization_status(viz_id, "rendering")

        # Render on Modal (this is sync, runs remotely)
        video_bytes = render_manim.remote(
            code=manim_code,
            scene_name=scene_name,
            quality="medium_quality"
        )

        # Upload to S3/R2
        video_url = await upload_video(
            video_bytes,
            filename=f"{viz_id}.mp4"
        )

        # Update status to complete
        await update_visualization_status(
            viz_id,
            "complete",
            video_url=video_url
        )

        return video_url

    except Exception as e:
        await update_visualization_status(viz_id, "failed", error=str(e))
        raise


async def process_all_visualizations(visualizations: list):
    """
    Process all visualizations for a paper in parallel.
    """
    tasks = [
        process_visualization(
            viz.id,
            viz.manim_code,
            extract_scene_name(viz.manim_code)
        )
        for viz in visualizations
    ]

    # Run up to 5 in parallel (Modal handles scaling)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results


def extract_scene_name(code: str) -> str:
    """Extract the Scene class name from Manim code."""
    match = re.search(r'class\s+(\w+)\s*\(\s*Scene\s*\)', code)
    if match:
        return match.group(1)
    return "MainScene"  # fallback
```

---

## Part 3: Storage (`rendering/storage.py`)

### S3/Cloudflare R2 Upload

```python
import boto3
from botocore.config import Config
import os

# Use environment variables for credentials
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://xxx.r2.cloudflarestorage.com")
S3_BUCKET = os.getenv("S3_BUCKET", "arxiviz-videos")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_PUBLIC_URL = os.getenv("S3_PUBLIC_URL", "https://videos.arxiviz.org")

s3_client = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    config=Config(signature_version="s3v4")
)

async def upload_video(video_bytes: bytes, filename: str) -> str:
    """
    Upload video to S3/R2 and return public URL.
    """
    key = f"videos/{filename}"

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=video_bytes,
        ContentType="video/mp4",
        CacheControl="public, max-age=31536000"  # 1 year cache
    )

    return f"{S3_PUBLIC_URL}/{key}"


async def get_video_url(video_id: str) -> str | None:
    """
    Get the public URL for a video.
    """
    key = f"videos/{video_id}.mp4"
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=key)
        return f"{S3_PUBLIC_URL}/{key}"
    except:
        return None
```

---

## Part 4: Database Models (`db/models.py`)

### SQLAlchemy Models

```python
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class Paper(Base):
    __tablename__ = "papers"

    id = Column(String, primary_key=True)  # arxiv_id
    title = Column(String, nullable=False)
    authors = Column(JSON)  # list of author names
    abstract = Column(Text)
    pdf_url = Column(String)
    html_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sections = relationship("Section", back_populates="paper")
    visualizations = relationship("Visualization", back_populates="paper")


class Section(Base):
    __tablename__ = "sections"

    id = Column(String, primary_key=True)
    paper_id = Column(String, ForeignKey("papers.id"))
    title = Column(String)
    content = Column(Text)
    level = Column(Integer)
    order_index = Column(Integer)
    equations = Column(JSON)  # list of LaTeX strings

    paper = relationship("Paper", back_populates="sections")


class Visualization(Base):
    __tablename__ = "visualizations"

    id = Column(String, primary_key=True)
    paper_id = Column(String, ForeignKey("papers.id"))
    section_id = Column(String, ForeignKey("sections.id"))
    concept = Column(String)
    storyboard = Column(JSON)
    manim_code = Column(Text)
    video_url = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, rendering, complete, failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    paper = relationship("Paper", back_populates="visualizations")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(String, primary_key=True)
    paper_id = Column(String, ForeignKey("papers.id"))
    status = Column(String, default="queued")  # queued, processing, complete, failed
    progress = Column(Float, default=0.0)  # 0.0 to 1.0
    sections_completed = Column(Integer, default=0)
    sections_total = Column(Integer, default=0)
    current_step = Column(String)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
```

### Database Connection (`db/connection.py`)

```python
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/arxiviz")

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        yield session
```

---

## Part 5: Redis Job Queue (`queue/worker.py`)

```python
import os
import uuid
from datetime import datetime
from db.connection import async_session
from db.models import ProcessingJob, Paper
from rendering import process_all_visualizations

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

async def create_job(arxiv_id: str) -> str:
    """Create a new processing job."""
    job_id = str(uuid.uuid4())
    async with async_session() as session:
        job = ProcessingJob(
            id=job_id,
            paper_id=arxiv_id,
            status="queued"
        )
        session.add(job)
        await session.commit()
    return job_id


async def process_paper_job(job_id: str, arxiv_id: str):
    """
    Main job processing function. Called as a background task.

    Pipeline:
    1. Call Team 1's ingestion endpoint
    2. Call Team 2's generation endpoint
    3. Render all visualizations
    4. Update job status
    """
    async with async_session() as session:
        job = await session.get(ProcessingJob, job_id)

        try:
            # Update status to processing
            job.status = "processing"
            job.current_step = "Fetching paper from arXiv"
            await session.commit()

            # Step 1: Call Team 1's ingestion
            # (In practice, this would be an internal API call)
            job.current_step = "Parsing document structure"
            job.progress = 0.2
            await session.commit()

            # Step 2: Call Team 2's generation
            job.current_step = "Generating visualizations"
            job.progress = 0.4
            await session.commit()

            # Step 3: Render all visualizations
            job.current_step = "Rendering videos"
            job.progress = 0.6
            await session.commit()

            # Get visualizations from DB and render them
            paper = await session.get(Paper, arxiv_id)
            if paper and paper.visualizations:
                job.sections_total = len(paper.visualizations)
                await process_all_visualizations(paper.visualizations)

            # Step 4: Complete
            job.status = "completed"
            job.progress = 1.0
            job.current_step = "Complete"
            job.completed_at = datetime.utcnow()
            await session.commit()

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            await session.commit()
            raise
```

---

## Environment Variables

### Backend (`.env`)

```
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/arxiviz

# Redis
REDIS_URL=redis://localhost:6379

# S3/R2 Storage
S3_ENDPOINT=https://xxx.r2.cloudflarestorage.com
S3_BUCKET=arxiviz-videos
S3_ACCESS_KEY=your_key
S3_SECRET_KEY=your_secret
S3_PUBLIC_URL=https://videos.arxiviz.org

# Modal.com
MODAL_TOKEN_ID=your_id
MODAL_TOKEN_SECRET=your_secret
```

---

## Dependencies

### `requirements.txt` additions

```
# API
fastapi>=0.109.0
uvicorn>=0.27.0

# Database
sqlalchemy>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0

# Storage
boto3>=1.34.0

# Queue
redis>=5.0.0

# Modal.com
modal>=0.60.0
```

---

## Testing

### Test Modal Runner

```bash
cd backend
modal run rendering/modal_runner.py
# Should create test_output.mp4
```

### Test API Endpoints

```bash
# Start server
uvicorn api.routes:router --reload

# Test endpoints
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"arxiv_id": "1706.03762"}'

curl http://localhost:8000/api/status/{job_id}
curl http://localhost:8000/api/paper/1706.03762
```

---

## Integration with Other Teams

### Input from Team 2

You receive `list[Visualization]` from Team 2, each with:
- `manim_code`: Complete Python code to render
- `section_id`: Which section this belongs to
- `concept`: Human-readable label

### Output to Team 4

Team 4 (Frontend) consumes your API:
- `POST /api/process` - Start processing
- `GET /api/status/{job_id}` - Poll for progress
- `GET /api/paper/{arxiv_id}` - Get final result with video URLs

**Coordinate early on the exact response schemas!**

---

## Handoff Checklist

- [ ] Modal.com account created and authenticated
- [ ] S3/R2 bucket created with public access
- [ ] PostgreSQL database provisioned
- [ ] API endpoints implemented and tested
- [ ] Response schemas documented for Team 4
- [ ] Integration tested with Team 2's Manim code output
