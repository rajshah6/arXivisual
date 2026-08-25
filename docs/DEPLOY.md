# Deploying arXivisual

Production runs in two pieces:

| Part | Stack | Host |
|------|-------|------|
| Backend | FastAPI in Docker ([backend/Dockerfile](../backend/Dockerfile)) | Azure Container Apps (`arxivisual-api` in resource group `arxivisual-rg`) |
| Frontend | Next.js 16 | Vercel, auto-deployed from `main` |

The backend image bundles Manim's system dependencies (FFmpeg, Cairo, Pango, a TeX Live install for `MathTex`), so it is large (~3 GB) and takes several minutes to build.

---

## Backend: Azure Container Apps

### 1. Build the image in ACR

Build remotely in Azure Container Registry — no local Docker needed. From the repo root:

```bash
az acr build -r ca82c08e2eadacr -t arxivisual-api:<tag> backend
```

Use a descriptive, dated tag (e.g. `tts-langfuse-20260825`) so rollbacks are unambiguous. The build context is the `backend/` directory; the Dockerfile installs the exact locked dependency set with `uv sync --frozen`, so a stale `uv.lock` fails the build instead of shipping silently (CI enforces the same invariant).

### 2. Deploy the new image

```bash
az containerapp update \
  -n arxivisual-api \
  -g arxivisual-rg \
  --image ca82c08e2eadacr.azurecr.io/arxivisual-api:<tag>
```

This creates a new revision and shifts traffic to it. The app runs a single always-on replica; a paper job's Manim renders are CPU-bound, so the replica is sized accordingly (2 vCPU / 4 Gi).

### 3. Verify

```bash
curl https://arxivisual-api.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io/api/health
```

`GET /api/health` reports database, Manim, and storage connectivity; expect `"status": "healthy"` with `"database": "connected"`, `"manim": "available (...)"`, and `"storage": "r2: connected"`. Also confirm `POST /api/render` returns 404 (see `RENDER_API_SECRET` below).

### Environment variables and secrets

Set these on the Container App (secrets referenced via `secretref:`; the rest as plain env vars). [backend/.env.example](../backend/.env.example) documents each one.

| Variable | Value / purpose |
|----------|-----------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint (LLM + TTS both route through it) |
| `AZURE_OPENAI_API_KEY` | **secret** — API key for the resource |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name of the pipeline model (production uses `gpt-5-mini`; code defaults to `gpt-5`) |
| `AZURE_OPENAI_REASONING_EFFORT` | `minimal` \| `low` \| `medium` \| `high`; reasoning tokens dominate output cost, so this is the main cost lever |
| `DATABASE_URL` | **secret** — Postgres flexible server URL, `postgresql://...?ssl=require`. Unset falls back to ephemeral SQLite, which is wiped on every redeploy |
| `STORAGE_MODE` | `r2` — videos go to Cloudflare R2 instead of the container filesystem |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_PUBLIC_URL` | R2 credentials (keys as **secrets**) and the public URL videos are served from |
| `RENDER_MODE` | `local` — Manim renders in-container via subprocess (a Modal.com path exists in code but is not used in production) |
| `ENVIRONMENT` | `production` — disables the raw-code `POST /api/render` endpoint unless `RENDER_API_SECRET` is also set |
| `RENDER_API_SECRET` | **secret**, optional — when set, `POST /api/render` accepts requests carrying it in the `X-Render-Secret` header; when unset in production, the endpoint is fully disabled (404) |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | **secrets** — enable LLM tracing when both are present |
| `LANGFUSE_HOST` | Langfuse region host (e.g. `https://us.cloud.langfuse.com`) |
| `LANGFUSE_TRACING_ENVIRONMENT` | `production` — keeps prod traces separate from dev |
| `VOICEOVER_TTS_SERVICE`, `VOICEOVER_VOICE_NAME`, `VOICEOVER_TTS_MODEL` | Optional TTS overrides. Defaults (`openai` / `nova` / `gpt-4o-mini-tts`) reuse the `AZURE_OPENAI_*` credentials at render time — no extra key needed. The TTS model must match an Azure deployment name |

### Rollback

List available tags, newest first:

```bash
az acr repository show-tags -n ca82c08e2eadacr \
  --repository arxivisual-api --orderby time_desc -o table
```

Then redeploy the previous tag with the same `az containerapp update ... --image` command. Environment variables and secrets live on the app, not the image, so no reconfiguration is needed. Alternatively, reactivate a prior revision directly:

```bash
az containerapp revision list -n arxivisual-api -g arxivisual-rg -o table
az containerapp revision activate -n arxivisual-api -g arxivisual-rg --revision <name>
```

### ACR housekeeping

The registry is **Basic tier (10 GB)** and each image is ~3 GB (TeX Live), so it fills up after a few deploys. Periodically delete superseded tags, always keeping the live tag plus one rollback tag:

```bash
az acr repository delete -n ca82c08e2eadacr --image arxivisual-api:<old-tag>
```

---

## Frontend: Vercel

The Vercel project builds from the `frontend/` directory and auto-deploys on every push to `main`; pull requests get preview deployments (the backend's CORS policy allows `arxivisual.org`, this project's `ar-xivisual-*.vercel.app` previews, and `localhost:3000`).

One environment variable matters:

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | The backend URL (the Azure Container Apps URL above) |

`NEXT_PUBLIC_*` variables are baked in at build time — redeploy the frontend after changing it. As a safety net, production builds fall back to the Azure backend URL when the variable is unset (see [frontend/lib/api.ts](../frontend/lib/api.ts)); dev builds fall back to `http://localhost:8000`.

---

## CI

[.github/workflows/ci.yml](../.github/workflows/ci.yml) runs on every push and PR: backend pytest on Python 3.11 and 3.13 (offline, dummy provider credentials), frontend typecheck + build (lint is advisory), and a Docker image build gated on changes to the Dockerfile, `pyproject.toml`, or `uv.lock`. Deploys are manual via the `az` commands above — CI validates that the image still builds but does not push it.
