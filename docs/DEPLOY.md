# Deploy ArXivisual (Frontend + Backend) — Free Tier

Step-by-step guide to deploy the **Next.js frontend** and **FastAPI backend** for free.

---

## Overview

| Part      | Stack           | Free host   | Notes                          |
|-----------|------------------|------------|--------------------------------|
| Frontend  | Next.js 16       | **Vercel** | Best fit for Next.js           |
| Backend   | FastAPI (Python) | **Render** | Free web service (sleeps ~15 min idle) |

You’ll deploy the **backend first**, then the frontend (so you can set the API URL).

---

## Prerequisites

- GitHub repo with this project pushed
- Accounts (free): [GitHub](https://github.com), [Vercel](https://vercel.com), [Render](https://render.com)
- Backend API keys in `.env`: `DEDALUS_API_KEY`, `ELEVEN_API_KEY` (you already have these locally)

---

## Part 1: Deploy the backend (Render)

### 1.1 Push code to GitHub

```bash
cd /Users/rajshah/Documents/Projects/Hackathons/TartanHacks/arXivisual
git add .
git commit -m "Prepare for deployment"
git push origin main
```

(Use your branch name if not `main`.)

### 1.2 Create a Render account and new Web Service

1. Go to [render.com](https://render.com) and sign up (e.g. with GitHub).
2. **Dashboard** → **New** → **Web Service**.
3. Connect your GitHub account if needed, then select the **arXivisual** repo.
4. Use these settings:

| Field | Value |
|-------|--------|
| **Name** | `arxivisual-api` (or any name) |
| **Region** | Oregon (or nearest) |
| **Branch** | `main` |
| **Root Directory** | `backend` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |

5. Click **Advanced** and add **Environment Variables**:

| Key | Value | Notes |
|-----|--------|--------|
| `DEDALUS_API_KEY` | (your key from `.env`) | Required for LLM |
| `ELEVEN_API_KEY` | (your key from `.env`) | Required for voiceover |

Do **not** commit your real keys to git; only add them in Render’s UI.

6. Click **Create Web Service**. Render will build and deploy. The first build can take several minutes (installing Manim etc.).

### 1.3 Get your backend URL

When the service is live, you’ll see a URL like:

```text
https://arxivisual-api.onrender.com
```

Use this as `NEXT_PUBLIC_API_URL` when deploying the frontend. Test it:

```bash
curl https://YOUR-RENDER-URL.onrender.com/api/health
```

You should get a JSON health response.

### 1.4 Render free tier notes

- Service **sleeps** after ~15 minutes of no traffic; first request after sleep can take 30–60 seconds.
- **SQLite** is used by default; data is lost on redeploy (no persistent disk on free tier). Fine for a demo/hackathon.
- If the build fails (e.g. out of memory), see “Backend build issues” at the end.

---

## Part 2: Deploy the frontend (Vercel)

### 2.1 Create a Vercel project from GitHub

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub.
2. **Add New** → **Project**.
3. Import your **arXivisual** repo.
4. Set **Root Directory**: click **Edit** and set to `frontend`.
5. **Framework Preset** should be **Next.js** (auto-detected). Leave **Build Command** and **Output Directory** as default.

### 2.2 Set environment variable for the API

1. In the project settings, open **Environment Variables**.
2. Add:

| Name | Value |
|------|--------|
| `NEXT_PUBLIC_API_URL` | `https://arxivisual-api.onrender.com` |

Use the **exact** backend URL from Render (no trailing slash).

3. (Optional) To use mock data instead of the real API:  
   `NEXT_PUBLIC_USE_MOCK` = `true`.

### 2.3 Deploy

Click **Deploy**. Vercel will build and deploy the Next.js app. When it’s done, you get a URL like:

```text
https://arxivisual-xxx.vercel.app
```

Open that URL; the app will call your Render backend using `NEXT_PUBLIC_API_URL`.

---

## Part 3: CORS and security (already set)

- The backend already allows all origins in CORS (for the hackathon). For production you’d set `allow_origins` to your Vercel domain(s).
- API keys are only in Render’s environment (and your local `.env`), not in the frontend.

---

## Quick reference

### Backend (Render)

- **Build**: `pip install -r requirements.txt` (root = `backend`)
- **Start**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Env vars**: `DEDALUS_API_KEY`, `ELEVEN_API_KEY`

### Frontend (Vercel)

- **Root**: `frontend`
- **Env**: `NEXT_PUBLIC_API_URL` = your Render backend URL

### Optional: run backend locally with same PORT behavior

The backend already supports both `PORT` (Render/Railway) and `API_PORT` (local). To run locally:

```bash
cd backend
uv run uvicorn main:app --reload --port 8000
```

---

## Troubleshooting

### Backend build fails on Render (out of memory / timeout)

- **Option A**: On Render free tier, try reducing dependencies (e.g. comment out or make optional heavy packages like `manim` if you only need the API to return cached/demo data).
- **Option B**: Deploy backend to **Railway** instead: [railway.app](https://railway.app) → New Project → Deploy from GitHub, set root to `backend`, add the same env vars, and use `uvicorn main:app --host 0.0.0.0 --port $PORT`. Railway gives a small free monthly credit.

### Frontend shows “Failed to fetch” or network errors

- Confirm `NEXT_PUBLIC_API_URL` in Vercel matches the Render URL exactly (https, no trailing slash).
- Redeploy the frontend after changing env vars (Vercel uses env at build time for `NEXT_PUBLIC_*`).
- If the backend is sleeping, the first request may take 30–60 seconds; try again.

### Health check works but `/api/process` or paper endpoints fail

- Ensure `DEDALUS_API_KEY` and `ELEVEN_API_KEY` are set in Render.
- Check Render **Logs** for Python tracebacks.

---

## Summary

1. **Backend**: Render → New Web Service → repo root `backend`, build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`, add `DEDALUS_API_KEY` and `ELEVEN_API_KEY`.
2. **Frontend**: Vercel → Import repo → root `frontend`, add `NEXT_PUBLIC_API_URL` = Render URL, deploy.
3. Open the Vercel URL and use the app; the frontend will talk to the backend on Render.

All steps use free tiers of Render and Vercel.
