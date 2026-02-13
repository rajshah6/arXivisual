# ArXivisual Hackathon Battle Plan

## Context

ArXivisual transforms arXiv papers into 3Blue1Brown-style animated visual explanations. The AI generation pipeline (Team 2) is complete. The frontend is built with mock data. What's missing is **wiring everything end-to-end**: ingestion → pipeline → rendered videos → API → frontend.

**Theme — MOSAIC**: "Nothing arrives whole; everything begins as a piece." ArXivisual IS this metaphor: a paper enters as a monolith, gets shattered into section fragments, AI transforms each fragment into a visual tile, and the tiles reassemble into a mosaic of understanding.

**Due**: Tomorrow 5pm (~18 hours)

---

## The Three Roles

### Ajith — "Pipeline Architect" (Backend Brain)
**What you do**: Wire up ingestion → generation pipeline. Create handcrafted Manim scenes for the Transformer demo paper. Make the general pipeline work for any paper.

**Files you own**:
- `backend/ingestion/` (all files)
- `backend/agents/pipeline.py` (integration tweaks only)
- `backend/run_demo.py`
- `backend/generated_output/` (new handcrafted Manim .py files)
- New: `backend/demo_scenes/` (handcrafted Manim code for Transformer paper)

### Raj — "API & Rendering Bridge" (Glue Layer)
**What you do**: Install Manim. Render Ajith's .py files to .mp4 videos. Set up FastAPI + database so the frontend can fetch paper data and stream videos. You're the bridge between Ajith's backend and Nikhil's frontend.

**Files you own**:
- `backend/main.py`
- `backend/api/routes.py`
- `backend/api/schemas.py`
- `backend/db/` (all files)
- `backend/rendering/` (all files)
- `backend/jobs/worker.py`
- `backend/media/` (rendered video files)
- `backend/.env`

### Nikhil — "Frontend & MOSAIC Designer"
**What you do**: Fix 2 known bugs in the API client. Build MOSAIC-themed UI. Connect to Raj's real API. Polish the demo.

**Files you own**:
- `frontend/` (everything)

### DO NOT TOUCH
- `backend/agents/` (except pipeline.py for integration) — generation pipeline is complete
- `backend/models/` — shared data contracts, stable
- `backend/prompts/`, `backend/examples/` — generation pipeline assets

---

## Known Bugs (Fix First!)

### Bug 1: Frontend `paper_id` field mismatch — NIKHIL
- **File**: `frontend/lib/api.ts` line 192
- **Problem**: reads `data.id` but backend sends field named `paper_id`
- **Fix**: change `paper_id: data.id` → `paper_id: data.paper_id`

### Bug 2: Progress format — NIKHIL
- **File**: `frontend/lib/api.ts` line 244
- **Problem**: divides `response.progress / 100` but backend already sends 0.0–1.0
- **Fix**: change to just `progress: response.progress` (remove the `/ 100`)

### Bug 3: Seed data has fake video URLs — RAJ
- **File**: `backend/db/queries.py` lines 322-329
- **Problem**: URLs point to `https://placeholder.arxiviz.org/...` which doesn't exist
- **Fix**: change to `/api/video/viz_001` and `/api/video/viz_002`

---

## Timeline

### PHASE 0: Setup (Hour 0–1) — ALL THREE in parallel

**Ajith**:
1. Set up `backend/.env` with Martian API key + model
2. `cd backend && uv sync` (or `pip install -r requirements.txt`)
3. Verify pipeline works: `python run_demo.py --max 1 --verbose`

**Raj**:
1. Install Manim dependencies: `brew install ffmpeg cairo pango`
2. Install Manim: `pip install manim`
3. Verify: `manim --version`
4. Install backend deps: `cd backend && uv sync`
5. Start server: `cd backend && uvicorn main:app --reload --port 8000`
6. Verify: visit `http://localhost:8000/docs`

**Nikhil**:
1. `cd frontend && npm install && npm run dev`
2. Create `frontend/.env.local` with `NEXT_PUBLIC_USE_MOCK=true`
3. Verify mock UI at `http://localhost:3000`

**Git**: Each person creates their own branch:
- `ajith/pipeline-integration`
- `raj/api-rendering`
- `nikhil/frontend-mosaic`

---

### PHASE 1: Core Work (Hours 1–6) — parallel, NO file overlap

---

#### Ajith (Hours 1–6): Pipeline + Handcrafted Demo

**Hour 1–3: Handcraft the Transformer demo Manim scenes**

Create beautiful, hand-tuned Manim `.py` files specifically for "Attention Is All You Need":
- Scene 1: Scaled Dot-Product Attention visualization (Q, K, V matrices, softmax flow)
- Scene 2: Multi-Head Attention (parallel heads, concatenation)
- Scene 3: (optional) Transformer Architecture overview (encoder-decoder stack)

Put these in `backend/demo_scenes/` or `backend/generated_output/`. These are the **hero content** for the demo — make them look amazing.

> **Give the `.py` files to Raj as soon as each is done so he can render them to `.mp4`.**

**Hour 3–5: Wire up ingestion → generation pipeline**
- Test ingestion with a real paper: `python test_ingestion.py 1706.03762`
- Fix any bugs in the ingestion pipeline (import errors, parsing issues)
- Verify it produces a valid `StructuredPaper` object
- Connect the output to `generate_visualizations()` from `agents/pipeline.py`

**Hour 5–6: Build the "fast path" for the demo paper**
- For `1706.03762`: skip the pipeline, load pre-made results instantly (handcrafted videos + paper data)
- For any other paper: run the full ingestion → generation → rendering pipeline
- This means modifying the worker or creating a bypass: if paper is `1706.03762` and pre-built content exists, serve it instantly

**Handoff**: Tell Raj what sections/visualizations to seed in the database to match your handcrafted content.

---

#### Raj (Hours 1–6): API + Rendering + Database

**Hour 1–2: Fix seed data + auto-seed on startup**
- Fix `backend/db/queries.py` lines 322-329: change placeholder URLs to `/api/video/viz_001` and `/api/video/viz_002`
- In `backend/main.py` lifespan function (line 23-29), add auto-seeding after `init_db()`:
  ```python
  from db.connection import async_session_maker
  from db.queries import seed_mock_paper
  async with async_session_maker() as db:
      await seed_mock_paper(db)
  ```
- Verify: `GET http://localhost:8000/api/paper/1706.03762` returns proper JSON

**Hour 2–3: Render Ajith's Manim files to .mp4**

As Ajith hands you `.py` files:
```bash
cd backend && manim -ql demo_scenes/scene1.py SceneName
```
- Save rendered `.mp4` files to `backend/media/videos/` as `viz_001.mp4`, `viz_002.mp4`, etc.
- Verify: `GET http://localhost:8000/api/video/viz_001` serves the actual video

**Hour 3–5: Test full API contract**

Test every endpoint the frontend will hit:
1. `POST /api/process` with `{"arxiv_id": "1706.03762"}` → returns `{job_id, status: "queued"}`
2. `GET /api/status/{job_id}` → returns progress (0.0–1.0 format)
3. `GET /api/paper/1706.03762` → returns paper with sections + visualization data
4. `GET /api/video/viz_001` → streams the .mp4 file
5. `GET /api/health` → returns service status

**Hour 5–6: Handle the processing flow**

The `POST /api/process` → background task flow in `jobs/worker.py`:
- For the demo paper (seeded): the worker sees `paper_exists == True` (line 46-54), skips ingestion
- For Ajith's "fast path": worker should detect pre-built content and return immediately
- Consider: add a check — if all visualizations already have `status: "complete"`, skip everything

---

#### Nikhil (Hours 1–6): Bug Fixes + MOSAIC Theme

**Hour 1–2: Fix the two API bugs (CRITICAL)**
1. `frontend/lib/api.ts` line 192 — change `paper_id: data.id` → `paper_id: data.paper_id`
2. `frontend/lib/api.ts` line 244 — change `response.progress / 100` → `response.progress`

**Hour 2–5: MOSAIC-themed landing page**

The landing page (`frontend/app/page.tsx`) is the first thing judges see. MOSAIC ideas:

- **Mosaic assembly animation**: Use Framer Motion to show scattered tiles/fragments that fly in and snap into a grid pattern
- **Tagline**: "Enter with fragments. Leave with something whole."
- **Paper sections as mosaic tiles**: When showing "how it works", show paper fragments assembling
- **Color palette**: The existing 3Blue1Brown colors (`--3b1b-blue`, `--3b1b-gold`, `--3b1b-brown`) work perfectly as mosaic tile colors
- Use existing `ui/` components (sparkles, background-beams, card-hover-effect)

**Hour 5–6: MOSAIC processing animation**

On the paper processing page (`frontend/app/abs/[...id]/page.tsx`, around line 561):
- Instead of just a progress bar, show a **mosaic being built tile by tile**
- Each tile represents a section being processed
- Tiles snap into place as processing progresses
- Final state: completed mosaic reveals "Your paper is ready"

---

### PHASE 2: Integration (Hours 6–10)

#### Ajith + Raj (Hours 6–8): Backend handshake
- Ajith verifies Raj's API serves the demo paper correctly
- Test the full flow: ingestion → pipeline → rendering → API
- If live pipeline for new papers works: great (stretch goal)
- If not: the hardcoded Transformer demo is the show

#### Nikhil (Hours 6–8): Connect to real backend
- Set `NEXT_PUBLIC_USE_MOCK=false` and `NEXT_PUBLIC_API_URL=http://localhost:8000`
- Test: enter `1706.03762` → see real paper data → watch real videos
- Debug any display issues with real data

#### All Three (Hours 8–10): Integration testing
Run the full demo 3 times end-to-end:
1. Land on homepage
2. Enter `1706.03762` (or click example button)
3. See paper load (instantly from pre-built content)
4. Read through sections with MOSAIC navigation
5. Watch handcrafted Manim visualizations
6. Everything works smoothly

Fix any bugs found.

---

### PHASE 3: Merge + Polish (Hours 10–14)

**Hour 10–11**: Merge branches to main
- Order: Raj first → Ajith second → Nikhil last
- No conflicts expected since files don't overlap

**Hour 11–13**: Polish
- Ajith: Optimize pipeline speed, try a second paper
- Raj: Ensure API handles edge cases
- Nikhil: Final UI polish, responsive check, smooth animations

**Hour 13–14**: Demo rehearsal
- Practice the pitch 2–3 times
- Aim for 3–5 minute demo
- Have a backup plan if anything fails live

---

### PHASE 4: Stretch Goals (Hours 14–17, pick 1-2)

1. **Live processing of a second paper** (Ajith): Process a NEW paper in real-time during demo
2. **Mosaic View Mode** (Nikhil): Grid view where sections appear as clickable mosaic tiles
3. **Voiceover** (Raj + Ajith): If ElevenLabs key works, render videos with AI narration
4. **Speed optimization** (Ajith): Faster pipeline via caching, parallel execution, or smaller model

---

## The MOSAIC Pitch (For Judges)

**Opening**: "Every research paper arrives as a monolith — dense, opaque, intimidating. But within it lies a mosaic of brilliant ideas waiting to be seen."

**Demo flow**:
1. "We take any arXiv paper..." (paste URL)
2. "...and decompose it into fragments." (show sections being extracted)
3. "Each fragment is analyzed by AI to find the visual story within." (show processing with mosaic animation)
4. "Then we reassemble those fragments into something new — animated visual explanations in the style of 3Blue1Brown." (play Manim videos)
5. "From scattered tiles of text to a mosaic of understanding."

**Technical hook**: "Under the hood, a 5-agent AI pipeline analyzes sections, plans storyboards, generates Manim code, validates through 4 quality gates — syntax, spatial, voiceover, and runtime — then renders and serves it."

---

## Sponsor Track Integrations

### Dedalus: Best Use of Tool Calling ✅
**Status**: IMPLEMENTED

**What we did**: Integrated Dedalus as an MCP (Model Context Protocol) gateway to orchestrate Context7 documentation retrieval for live, up-to-date Manim API references.

**How it works**:
1. Before generating Manim code, the `ManimGenerator` agent calls `get_manim_docs()`
2. This makes a Dedalus API call (OpenAI-compatible, using a cheap Haiku model)
3. Dedalus orchestrates two Context7 MCP tool calls:
   - `resolve_library_id("manim community")` → finds the Manim Community library (860k tokens of docs!)
   - `get_library_docs(libraryId, query)` → fetches relevant, live documentation with code examples
4. The live docs are injected into the ManimGenerator's system prompt alongside the static reference
5. The actual code generation uses Martian/Opus (our unlimited credits model)

**Key files**:
- `backend/agents/context7_docs.py` — Dedalus + Context7 integration module
- `backend/agents/manim_generator.py` — Modified to fetch live docs before generation

**Why it's great**:
- Context7 returns REAL, current Manim documentation with working code examples
- Dedalus handles the MCP tool orchestration (resolve → fetch → return)
- Only uses 1 cheap Dedalus API call per generation (Haiku model for orchestration)
- All heavy lifting (code generation) uses Martian/Opus with unlimited credits
- Graceful fallback chain: Dedalus+Context7 → Direct Context7 → Static docs

**Environment variable**: `DEDALUS_API_KEY` in `backend/.env`

### CodeRabbit: Most Fun Use ✅
**Status**: IN USE — CodeRabbit reviews all PRs in the repo.

---

## Risk Fallbacks

| Risk | Fallback |
|------|----------|
| Manim won't install | Use existing `backend/test.mp4` / `backend/modal_test_output.mp4` as demo videos |
| Pipeline API calls fail | Ajith's handcrafted Manim code doesn't need LLM API — render directly |
| Ingestion fails | Demo paper is hardcoded — only affects "new paper" flow |
| Frontend-backend breaks | Keep `NEXT_PUBLIC_USE_MOCK=true` for demo |
| Videos don't play in browser | Serve from `public/` folder in Next.js instead of API |

---

## Critical Files Quick Reference

| File | What It Does | Owner |
|------|-------------|-------|
| `backend/ingestion/__init__.py` | `ingest_paper()` entry point | Ajith |
| `backend/agents/pipeline.py` | `generate_visualizations()` orchestrator | Ajith |
| `backend/run_demo.py` | Demo script, generates Manim code | Ajith |
| `backend/main.py` | FastAPI entry, startup, CORS | Raj |
| `backend/api/routes.py` | All REST endpoints | Raj |
| `backend/api/schemas.py` | API response/request schemas | Raj |
| `backend/db/queries.py` (lines 224-344) | `seed_mock_paper()` + all CRUD | Raj |
| `backend/rendering/__init__.py` | `process_visualization()` render pipeline | Raj |
| `backend/rendering/local_runner.py` | `render_manim_local()` subprocess | Raj |
| `backend/rendering/storage.py` | `save_video()`, `get_video_path()` | Raj |
| `backend/jobs/worker.py` | Background job processing | Raj |
| `frontend/lib/api.ts` | API client (**HAS 2 BUGS — fix first!**) | Nikhil |
| `frontend/app/page.tsx` | Landing page (MOSAIC theme here) | Nikhil |
| `frontend/app/abs/[...id]/page.tsx` | Paper viewing page | Nikhil |

---

## Verification Checklist (Before Demo)

- [ ] `curl http://localhost:8000/api/paper/1706.03762` returns paper JSON with sections and video URLs
- [ ] `curl http://localhost:8000/api/video/viz_001 -o test.mp4 && open test.mp4` plays a Manim animation
- [ ] `http://localhost:3000/abs/1706.03762` shows paper with playable embedded videos
- [ ] Full flow: Homepage → enter paper ID → paper loads → sections display → videos play
- [ ] MOSAIC theme is visible on landing page
- [ ] Demo runs smoothly 3 times in a row
