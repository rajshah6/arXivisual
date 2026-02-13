# ArXiviz API Specification

## Base URL

- Development: `http://localhost:8000`
- Production: `https://api.arxiviz.org`

## Authentication

For hackathon MVP: No authentication required.

Future: API key in header `X-API-Key: your_key`

---

## Endpoints

### 1. Process Paper

Start processing an arXiv paper. This triggers the full pipeline:
ingestion → AI analysis → visualization generation → video rendering.

**Request**
```
POST /api/process
Content-Type: application/json

{
  "arxiv_id": "1706.03762"
}
```

**Response**
```json
{
  "job_id": "job_abc123",
  "arxiv_id": "1706.03762",
  "status": "queued",
  "message": "Processing started"
}
```

**Status Codes**
- `202 Accepted` - Processing started
- `400 Bad Request` - Invalid arXiv ID format
- `429 Too Many Requests` - Rate limited

**arXiv ID Formats Supported**
- `1706.03762` - Standard format
- `1706.03762v1` - With version
- `cs/0123456` - Old format with category

---

### 2. Get Processing Status

Poll this endpoint to track processing progress.

**Request**
```
GET /api/status/{job_id}
```

**Response**
```json
{
  "job_id": "job_abc123",
  "arxiv_id": "1706.03762",
  "status": "processing",
  "progress": 45,
  "current_step": "Generating visualization 2 of 4",
  "steps_completed": [
    {"name": "fetch_paper", "status": "complete", "duration_ms": 1234},
    {"name": "parse_sections", "status": "complete", "duration_ms": 567},
    {"name": "analyze_sections", "status": "complete", "duration_ms": 8901},
    {"name": "generate_visualizations", "status": "in_progress", "duration_ms": null}
  ],
  "error": null,
  "created_at": "2024-01-15T10:30:00Z",
  "estimated_completion": "2024-01-15T10:35:00Z"
}
```

**Status Values**
| Status | Description |
|--------|-------------|
| `queued` | Job is in queue, waiting to start |
| `processing` | Actively processing |
| `complete` | Successfully finished |
| `failed` | Processing failed (see `error` field) |

**Status Codes**
- `200 OK` - Status returned
- `404 Not Found` - Job ID not found

---

### 3. Get Processed Paper

Retrieve the full processed paper with all sections and visualizations.

**Request**
```
GET /api/paper/{arxiv_id}
```

**Response**
```json
{
  "id": "1706.03762",
  "title": "Attention Is All You Need",
  "authors": [
    "Ashish Vaswani",
    "Noam Shazeer",
    "Niki Parmar",
    "Jakob Uszkoreit",
    "Llion Jones",
    "Aidan N. Gomez",
    "Lukasz Kaiser",
    "Illia Polosukhin"
  ],
  "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
  "pdf_url": "https://arxiv.org/pdf/1706.03762",
  "html_url": "https://ar5iv.org/abs/1706.03762",
  "sections": [
    {
      "id": "section-abstract",
      "title": "Abstract",
      "content": "The dominant sequence transduction models...",
      "level": 1,
      "order_index": 0,
      "equations": []
    },
    {
      "id": "section-1",
      "title": "Introduction",
      "content": "Recurrent neural networks, long short-term memory...",
      "level": 1,
      "order_index": 1,
      "equations": []
    },
    {
      "id": "section-3",
      "title": "Model Architecture",
      "content": "Most competitive neural sequence transduction models have an encoder-decoder structure...",
      "level": 1,
      "order_index": 2,
      "equations": [
        "\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V"
      ]
    }
  ],
  "visualizations": [
    {
      "id": "viz_001",
      "section_id": "section-3",
      "concept": "Scaled Dot-Product Attention",
      "video_url": "https://videos.arxiviz.org/videos/viz_001.mp4",
      "status": "complete"
    },
    {
      "id": "viz_002",
      "section_id": "section-3-2",
      "concept": "Multi-Head Attention",
      "video_url": "https://videos.arxiviz.org/videos/viz_002.mp4",
      "status": "complete"
    },
    {
      "id": "viz_003",
      "section_id": "section-3-3",
      "concept": "Positional Encoding",
      "video_url": null,
      "status": "rendering"
    }
  ],
  "processed_at": "2024-01-15T10:35:00Z"
}
```

**Status Codes**
- `200 OK` - Paper returned
- `404 Not Found` - Paper not processed yet (trigger with POST /api/process first)

---

### 4. Health Check

**Request**
```
GET /api/health
```

**Response**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "services": {
    "database": "connected",
    "redis": "connected",
    "modal": "configured"
  }
}
```

---

## WebSocket: Real-time Status (Optional Enhancement)

For real-time updates without polling:

**Connect**
```
WS /ws/status/{job_id}
```

**Messages**
```json
{
  "type": "progress",
  "progress": 50,
  "current_step": "Generating visualization 2 of 4"
}

{
  "type": "visualization_complete",
  "visualization_id": "viz_001",
  "video_url": "https://videos.arxiviz.org/videos/viz_001.mp4"
}

{
  "type": "complete",
  "paper_id": "1706.03762"
}
```

---

## Error Responses

All errors follow this format:

```json
{
  "error": {
    "code": "INVALID_ARXIV_ID",
    "message": "The provided arXiv ID is not in a valid format",
    "details": {
      "provided": "invalid-id",
      "expected_formats": ["1706.03762", "1706.03762v1", "cs/0123456"]
    }
  }
}
```

**Common Error Codes**

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_ARXIV_ID` | 400 | arXiv ID format not recognized |
| `PAPER_NOT_FOUND` | 404 | Paper doesn't exist on arXiv |
| `JOB_NOT_FOUND` | 404 | Job ID doesn't exist |
| `PROCESSING_FAILED` | 500 | Pipeline failed (see details) |
| `RATE_LIMITED` | 429 | Too many requests |
| `SERVICE_UNAVAILABLE` | 503 | Downstream service (Modal, arXiv) unavailable |

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| POST /api/process | 10 requests per minute |
| GET /api/status/* | 60 requests per minute |
| GET /api/paper/* | 60 requests per minute |

---

## Data Models (OpenAPI/Pydantic)

### Request Models

```python
from pydantic import BaseModel, Field
import re

class ProcessRequest(BaseModel):
    arxiv_id: str = Field(
        ..., 
        pattern=r'^(\d{4}\.\d{4,5}(v\d+)?|[a-z-]+/\d{7})$',
        examples=["1706.03762", "2301.07041v2"]
    )
```

### Response Models

```python
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"

class VisualizationStatus(str, Enum):
    PENDING = "pending"
    RENDERING = "rendering"
    COMPLETE = "complete"
    FAILED = "failed"

class ProcessResponse(BaseModel):
    job_id: str
    arxiv_id: str
    status: JobStatus
    message: str

class StepInfo(BaseModel):
    name: str
    status: str
    duration_ms: int | None

class StatusResponse(BaseModel):
    job_id: str
    arxiv_id: str
    status: JobStatus
    progress: int  # 0-100
    current_step: str | None
    steps_completed: list[StepInfo]
    error: str | None
    created_at: datetime
    estimated_completion: datetime | None

class Section(BaseModel):
    id: str
    title: str
    content: str
    level: int
    order_index: int
    equations: list[str]

class Visualization(BaseModel):
    id: str
    section_id: str
    concept: str
    video_url: str | None
    status: VisualizationStatus

class PaperResponse(BaseModel):
    id: str
    title: str
    authors: list[str]
    abstract: str
    pdf_url: str
    html_url: str | None
    sections: list[Section]
    visualizations: list[Visualization]
    processed_at: datetime
```

---

## FastAPI Implementation Skeleton

```python
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uuid

app = FastAPI(title="ArXiviz API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/process", response_model=ProcessResponse)
async def process_paper(request: ProcessRequest, background_tasks: BackgroundTasks):
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    # Store job in database
    await create_job(job_id, request.arxiv_id)
    
    # Queue background processing
    background_tasks.add_task(run_pipeline, job_id, request.arxiv_id)
    
    return ProcessResponse(
        job_id=job_id,
        arxiv_id=request.arxiv_id,
        status=JobStatus.QUEUED,
        message="Processing started"
    )


@app.get("/api/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str):
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/paper/{arxiv_id:path}", response_model=PaperResponse)
async def get_paper(arxiv_id: str):
    paper = await get_processed_paper(arxiv_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "0.1.0",
        "services": await check_services()
    }
```

---

## Testing the API

### cURL Examples

```bash
# Start processing
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"arxiv_id": "1706.03762"}'

# Check status
curl http://localhost:8000/api/status/job_abc123

# Get paper
curl http://localhost:8000/api/paper/1706.03762
```

### Python Examples

```python
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        # Start processing
        resp = await client.post(
            "http://localhost:8000/api/process",
            json={"arxiv_id": "1706.03762"}
        )
        job_id = resp.json()["job_id"]
        
        # Poll until complete
        while True:
            resp = await client.get(f"http://localhost:8000/api/status/{job_id}")
            status = resp.json()
            
            if status["status"] == "complete":
                break
            elif status["status"] == "failed":
                raise Exception(status["error"])
            
            await asyncio.sleep(2)
        
        # Get paper
        resp = await client.get("http://localhost:8000/api/paper/1706.03762")
        paper = resp.json()
        print(f"Got {len(paper['visualizations'])} visualizations")
```
