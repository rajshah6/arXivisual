# Team 3: Rendering Backend & Infrastructure

## Mission

Build the video rendering infrastructure that takes Manim code from Team 2, renders it serverlessly via Modal.com, stores videos in S3/R2, and exposes REST API endpoints that Team 4 (Frontend) consumes.

---

## Architecture

```
Team 2 Output                    Team 3 Infrastructure                       Team 4 Input
     │                                    │                                       │
     ▼                                    ▼                                       ▼
[Manim Code] ──► [Modal.com Runner] ──► [S3/R2 Storage] ──► [REST API] ──► [Frontend]
                       │                                         │
                       ▼                                         ▼
              [PostgreSQL Cache]                          [JSON + Video URLs]
                       │
                       ▼
               [Redis Job Queue]
```

---

## What We Build

1. **Modal.com Manim Runner** - Serverless Manim code execution
2. **S3/R2 Video Storage** - Upload and serve rendered videos
3. **PostgreSQL Database** - Paper metadata, job status, cached results
4. **Redis Job Queue** - Async processing with progress tracking
5. **FastAPI REST API** - Contract with Team 4 (Frontend)

---

## Key Commands

```bash
# Run API server (development)
uvicorn main:app --reload --port 8000

# Test Modal function locally
modal run rendering/modal_runner.py

# Deploy Modal function
modal deploy rendering/modal_runner.py

# Run database migrations
alembic upgrade head

# Start Redis (Docker)
docker run -d --name arxiviz-redis -p 6379:6379 redis:7

# Start PostgreSQL (Docker)
docker run -d --name arxiviz-postgres -e POSTGRES_USER=arxiviz -e POSTGRES_PASSWORD=arxiviz -e POSTGRES_DB=arxiviz -p 5432:5432 postgres:15
```

---

## API Endpoints (We Own This Contract)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/process` | Start processing a paper |
| GET | `/api/status/{job_id}` | Poll processing status |
| GET | `/api/paper/{arxiv_id}` | Get processed paper with videos |
| GET | `/api/video/{video_id}` | Get video URL |
| GET | `/api/health` | Health check |

### Response Schemas

```python
# POST /api/process
{"job_id": "uuid", "status": "queued", "paper_id": "1706.03762"}

# GET /api/status/{job_id}
{
  "job_id": "uuid",
  "status": "processing",  # queued | processing | completed | failed
  "progress": 0.6,
  "sections_completed": 3,
  "sections_total": 5,
  "current_step": "Rendering videos",
  "error": null
}

# GET /api/paper/{arxiv_id}
{
  "paper_id": "1706.03762",
  "title": "Attention Is All You Need",
  "authors": ["Ashish Vaswani", ...],
  "abstract": "...",
  "pdf_url": "https://arxiv.org/pdf/1706.03762",
  "sections": [
    {"id": "s1", "title": "Introduction", "content": "...", "video_url": "/api/video/xyz"}
  ]
}
```

---

## File Structure

```
backend/
├── __init__.py
├── main.py                      # FastAPI app entry point
├── CLAUDE.md                    # This file
├── requirements.txt
├── .env.example
├── rendering/
│   ├── __init__.py              # process_visualization(), process_all_visualizations()
│   ├── modal_runner.py          # Modal.com function: render_manim()
│   └── storage.py               # upload_video(), get_video_url()
├── db/
│   ├── __init__.py
│   ├── models.py                # Paper, Section, Visualization, ProcessingJob
│   ├── connection.py            # async engine, session factory
│   └── queries.py               # get_paper(), create_job(), update_status()
├── queue/
│   ├── __init__.py
│   └── worker.py                # process_paper_job(), create_job()
└── api/
    ├── __init__.py
    ├── routes.py                # FastAPI router with all endpoints
    └── schemas.py               # Pydantic request/response models
```

---

## Environment Variables Required

```env
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

## Integration Points

### Input from Team 2
We receive `list[Visualization]` where each has:
- `manim_code`: Complete Python code to render
- `section_id`: Which section this visualization belongs to
- `concept`: Human-readable description (e.g., "Scaled Dot-Product Attention")

### Output to Team 4
- REST API with JSON responses
- Video URLs pointing to S3/R2 public bucket
- Progress updates via `/api/status/{job_id}` polling

---

## Dependencies

```
# API
fastapi>=0.109.0
uvicorn>=0.27.0
python-multipart>=0.0.6

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

# Utilities
pydantic>=2.0.0
python-dotenv>=1.0.0
httpx>=0.26.0
```

---

## Development Strategy

### Phase 1: Local Development (No External Services)
- Use existing `manim-mcp-server` for local Manim execution
- Use local filesystem instead of S3 for videos
- Use SQLite instead of PostgreSQL
- Mock Team 2 input with hardcoded test Manim code

### Phase 2: Infrastructure Setup
- Set up PostgreSQL (Docker)
- Set up Redis (Docker)
- Set up Cloudflare R2 bucket
- Authenticate with Modal.com (`modal token new`)

### Phase 3: Modal.com Integration
- Deploy Manim runner to Modal.com
- Test with real rendering
- Connect to S3/R2 for video storage

### Phase 4: Full API Implementation
- Implement all FastAPI endpoints
- Test with curl/Postman
- Verify response schemas match Team 4 expectations

---

## Existing Resources

### 1. manim-mcp-server/ (in repo)
Local Manim execution - use for development:
```
manim-mcp-server/src/manim_server.py
```

### 2. Original MVP Code (recoverable from git)
```bash
git show da1116e^:server/render/render_tile.py  # Manim CLI pattern
git show da1116e^:server/render/templates/attention_edges_3d.py  # Example template
git show da1116e^:server/schemas.py  # Pydantic models
```

### 3. Documentation
- `docs/AgentDocs/TEAM3_BACKEND.md` - Full implementation guide
- `docs/AgentDocs/API_SPEC.md` - Detailed API specification
- `docs/AgentDocs/MANIM_PATTERNS.md` - Manim code examples

---

## Test Cases

### Test Modal Runner
```bash
modal run rendering/modal_runner.py
# Should create test_output.mp4
```

### Test API Endpoints
```bash
# Start server
uvicorn main:app --reload

# Test process
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"arxiv_id": "1706.03762"}'

# Test status
curl http://localhost:8000/api/status/{job_id}

# Test paper
curl http://localhost:8000/api/paper/1706.03762
```

### Reference Paper
Test with: **"Attention Is All You Need"** (arXiv:1706.03762)

---

## Verification Checklist

- [ ] Modal.com runner can render test Manim code
- [ ] Videos upload to S3/R2 successfully
- [ ] PostgreSQL stores paper metadata
- [ ] Redis tracks job progress
- [ ] All 4 API endpoints work
- [ ] Response schemas match Team 4 expectations
- [ ] End-to-end test with Attention paper
