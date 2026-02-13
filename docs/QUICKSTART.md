# ArXiviz Quickstart

Transform arXiv research papers into beautiful, interactive scrollytelling experiences with Manim-generated visualizations.

## What is ArXiviz?

Simply change `arxiv.org` → `arxiviz.org` in any paper URL to get an interactive visual explanation:
```
https://arxiv.org/abs/1706.03762
              ↓
https://arxiviz.org/abs/1706.03762
```

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (optional, for database/redis)
- Git

## Quick Setup (5 minutes)

### 1. Clone and Install

```bash
# Clone the repository
git clone <your-repo-url>
cd MosiacManim

# Backend setup
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend setup (in new terminal)
cd frontend
npm install
```

### 2. Environment Variables

**Backend** - Create `backend/.env`:
```env
# Minimal setup for local testing
DATABASE_URL=sqlite+aiosqlite:///./arxiviz.db
DEDALUS_API_KEY=dsk-your-dedalus-key
ELEVEN_API_KEY=your-elevenlabs-key
```

**Frontend** - Create `frontend/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. Run It!

```bash
# Terminal 1: Backend
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev
```

Visit **http://localhost:3000** 🎉

## First Test

Try processing the "Attention Is All You Need" paper:

```bash
# Test ingestion
cd backend
python test_ingestion.py

# Or via API
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"arxiv_id": "1706.03762"}'
```

## Project Structure

```
MosiacManim/
├── backend/              # Python FastAPI
│   ├── ingestion/       # Paper parsing (arXiv → structured data)
│   ├── rendering/       # Manim video generation (Modal.com)
│   ├── api/             # REST endpoints
│   └── db/              # PostgreSQL models
├── frontend/            # Next.js app
│   ├── app/abs/        # Paper display pages
│   └── components/     # Scrollytelling UI
└── docs/AgentDocs/     # Full documentation
```

## Key API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /api/process` | Start processing a paper |
| `GET /api/status/{job_id}` | Check processing status |
| `GET /api/paper/{arxiv_id}` | Get paper with videos |

## Common Commands

```bash
# Backend (from backend/)
uvicorn main:app --reload              # Run dev server
python test_ingestion.py               # Test paper parsing
modal run rendering/modal_runner.py    # Test Manim rendering

# Frontend (from frontend/)
npm run dev                            # Run dev server
npm run build                          # Build for production
```

## Need Help?

- **Full Setup Guide**: See `docs/AgentDocs/SETUP.md` for detailed instructions
- **Architecture**: Read `docs/AgentDocs/PROJECT_OVERVIEW.md`
- **API Documentation**: Check `docs/AgentDocs/API_SPEC.md`
- **Team Guides**:
  - Team 1 (Ingestion): `docs/AgentDocs/TEAM1_INGESTION.md`
  - Team 2 (Generation): `docs/AgentDocs/TEAM2_GENERATION.md`
  - Team 3 (Backend): `docs/AgentDocs/TEAM3_BACKEND.md`
  - Team 4 (Frontend): `docs/AgentDocs/TEAM4_FRONTEND.md`

## Optional: Full Infrastructure

For production features (PostgreSQL, Redis, Modal rendering):

```bash
# Start services with Docker
docker run -d --name arxiviz-postgres \
  -e POSTGRES_USER=arxiviz \
  -e POSTGRES_PASSWORD=arxiviz \
  -e POSTGRES_DB=arxiviz \
  -p 5432:5432 postgres:15

docker run -d --name arxiviz-redis \
  -p 6379:6379 redis:7

# Setup Modal.com for Manim rendering
pip install modal
modal token new

# Update backend/.env with full config
DATABASE_URL=postgresql://arxiviz:arxiviz@localhost:5432/arxiviz
REDIS_URL=redis://localhost:6379
MODAL_TOKEN_ID=your_token_id
MODAL_TOKEN_SECRET=your_token_secret
```

## Tech Stack

- **Frontend**: Next.js 16, React 19, Tailwind CSS, Framer Motion
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy
- **AI**: Dedalus SDK (Claude models)
- **Video**: Manim Community Edition on Modal.com
- **Storage**: PostgreSQL, Redis, S3/Cloudflare R2

## Quick Troubleshooting

**"Module not found" errors:**
```bash
source venv/bin/activate  # Make sure venv is active
pip install -r requirements.txt
```

**Port already in use:**
```bash
# Backend on different port
uvicorn main:app --reload --port 8001

# Frontend on different port
npm run dev -- --port 3001
```

**Database connection errors:**
```bash
# Use SQLite for local dev
DATABASE_URL=sqlite+aiosqlite:///./arxiviz.db
```

---

**Ready to dive deeper?** Check out the full documentation in `docs/AgentDocs/` 📚

;jhk.ylkkjlh