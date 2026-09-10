# Deploying arXivisual

Production runs in two pieces, both in the same Azure Container Apps environment (`arxivisual-api-env`, resource group `arxivisual-rg`, Terraform in [infra/](../infra/)):

| Part | Stack | Host |
|------|-------|------|
| Backend | FastAPI in Docker ([backend/Dockerfile](../backend/Dockerfile)) | Container App `arxivisual-api` (+ `arxivisual-worker`, `arxivisual-temporal`) |
| Frontend | Next.js 16 server (SSR, `output: "standalone"`) in Docker ([frontend/Dockerfile](../frontend/Dockerfile)) | Container App `arxivisual-web`, serving `arxivisual.org` |

Deploys are manual GitHub Actions runs (no push-to-deploy): `deploy-backend.yml` and `deploy-frontend.yml`, both authenticating to Azure with OIDC.

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
| `TURNSTILE_SECRET_KEY` | **secret** — server-side human verification on `POST /api/process`; fails closed when set |
| `DAILY_NEW_PAPER_CAP`, `RATE_LIMIT_PROCESS_GLOBAL`, `RATE_LIMIT_PROCESS_PER_IP_DAILY`, `IP_HASH_SECRET` | admission control knobs (see `backend/CLAUDE.md`) |
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

## Frontend: Azure Container Apps

### 1. Build and deploy

```bash
gh workflow run deploy-frontend.yml          # from main, once CI is green
gh run watch                                 # ~4 minutes
```

[.github/workflows/deploy-frontend.yml](../.github/workflows/deploy-frontend.yml) builds `frontend/` in ACR as `arxivisual-web:gh-<sha>`, rolls the `arxivisual-web` Container App to it, then polls `/healthz` until the response carries that commit — in single-revision mode the old revision keeps serving until the new one passes its probes, so a plain 200 would prove nothing.

Build-time inputs come from **GitHub repository variables** (`gh variable set NAME --body VALUE`), not container env vars, because `next build` inlines them into the bundles:

| Repository variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | The backend origin (the Azure Container Apps API URL above). Unset: production builds fall back to it anyway ([frontend/lib/api.ts](../frontend/lib/api.ts)) |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | Cloudflare Turnstile site key (public). Unset = no widget, backend must have no secret either |

The image also bakes in `APP_COMMIT_SHA` (reported by `/healthz`). Nothing else is configurable at runtime; the container listens on `:3000` as a non-root user.

First-time bootstrap (the app does not exist yet): run the workflow with `roll=false` so the image exists, then `terraform apply` with `web_image_tag = "gh-<sha>"` (see [infra/README.md](../infra/README.md)); every later deploy is the plain workflow run.

### 2. Verify

```bash
WEB=https://arxivisual-web.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io
curl -s $WEB/healthz                                  # {"status":"ok","commit":"<sha>","uptime_s":N}
curl -s -o /dev/null -w '%{http_code}\n' $WEB/explore   # 200
curl -s $WEB/abs/1706.03762 | grep -o '<title>[^<]*'    # "Attention Is All You Need · arXivisual" (server-rendered)
```

The last line is the SSR payoff: the paper route's server component fetches the paper's title/abstract from the API (3 s timeout, 10 min cache, any failure falls back to a generic title) so links unfurl with the paper, not the site card.

### 3. Rollback

```bash
az acr repository show-tags -n ca82c08e2eadacr --repository arxivisual-web --orderby time_desc -o table
az containerapp update -n arxivisual-web -g arxivisual-rg \
  --image ca82c08e2eadacr.azurecr.io/arxivisual-web:<previous-tag>
```

or `az containerapp revision activate` as for the backend. Images are ~400 MB (the bundled demo media is most of it); prune old `arxivisual-web` tags with the same `az acr repository delete` housekeeping.

### 4. Custom domain and DNS (Porkbun)

`arxivisual.org` and `www.arxivisual.org` are custom domains on `arxivisual-web` with free Azure-managed (DigiCert) certificates ([infra/frontend.tf](../infra/frontend.tf), gated by `web_custom_domains_enabled`). Container Apps validates ownership through DNS, so the records must resolve **before** the apply that enables the domains — every phase fails without them, the certificate one only after a 30-minute wait. At Porkbun (DNS → arxivisual.org):

| Type | Host | Answer | Why |
|------|------|--------|-----|
| `CNAME` | `www` | `arxivisual-web.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io` | routes www to the app |
| `TXT` | `asuid.www` | the environment's custom-domain verification id | proves ownership of www |
| `A` | *(blank / apex)* | `20.10.252.218` (the environment's static IP) | apex cannot be a CNAME |
| `TXT` | `asuid` | the same verification id | proves ownership of the apex |

`terraform output web_dns_records` prints exactly these four rows once the app exists; or read the two values directly:

```bash
az containerapp env show -n arxivisual-api-env -g arxivisual-rg \
  --query '{ip:properties.staticIp, asuid:properties.customDomainConfiguration.customDomainVerificationId}'
```

Rules that matter: the `www` CNAME must point *directly* at the app FQDN (an intermediate CNAME or ALIAS blocks issuance and renewal); the apex must be an `A` record, not an ALIAS; if the zone ever gets a `CAA` record, add `0 issue digicert.com` next to it (as of the migration the zone has none — do not add one). Remove the old `www` CNAME to `vercel-dns` and any apex records Vercel asked for at the same time — a hostname resolving to two places validates nowhere. Certificates are issued a few minutes after validation and renew automatically as long as the records and public HTTP ingress stay in place.

### 5. Cut-over order (Vercel → Azure)

1. Merge, run `deploy-frontend.yml` with `roll=false`, then `terraform apply` with `web_image_tag = "gh-<sha>"` and `web_custom_domains_enabled = false` (creates `arxivisual-web`, and sets `CORS_EXTRA_ORIGINS` + `TURNSTILE_ALLOWED_HOSTNAMES` on the API app so the new host may call it). Verify on the `azurecontainerapps.io` URL (step 2). Add that hostname to the Turnstile widget's allowed hostnames in the Cloudflare dashboard if you want the Start flow to work there too.
2. Create the four Porkbun records from `terraform output web_dns_records`; wait until `dig +short www.arxivisual.org` answers with the app FQDN, `dig +short arxivisual.org` with the static IP, and `dig +short TXT asuid.arxivisual.org` with the verification id. Apply with `web_custom_domains_enabled = true` (issuance takes a few minutes; the apply waits), then confirm `az containerapp hostname list -n arxivisual-web -g arxivisual-rg -o table` shows `SniEnabled` for both names.
3. `curl -sI https://www.arxivisual.org` and `https://arxivisual.org` return 200 with a valid certificate. Only now remove the domain from the Vercel project and delete the project — nothing in the backend references Vercel any more.

Rollback of the cut-over is the DNS change in reverse (point `www` back at `vercel-dns` while the Vercel project still exists). Note that removing a bound domain from Terraform needs a manual unbind first (`az containerapp hostname delete`): the azapi binding step has no delete behaviour.

### 6. Local production image

```bash
docker build -t arxivisual-web:local --build-arg NEXT_PUBLIC_API_URL=<api url> frontend
docker run --rm -p 3000:3000 arxivisual-web:local
```

---

## CI

[.github/workflows/ci.yml](../.github/workflows/ci.yml) runs on every push and PR: backend ruff + pytest on Python 3.11 and 3.13 (offline, dummy provider credentials), frontend typecheck + lint + build (all hard gates), and Docker image builds for both halves gated on changes to their build inputs (backend: Dockerfile, `pyproject.toml`, `uv.lock`; frontend: Dockerfile, `.dockerignore`, `package*.json`, `next.config.ts`). Deploys are the manual workflows above — CI validates that the images still build but does not push them.

## Turnstile rollout order (matters)

1. Set the `NEXT_PUBLIC_TURNSTILE_SITE_KEY` repository variable and run `deploy-frontend.yml` — the widget appears and sends
   tokens; the backend ignores them while it has no secret (harmless).
2. Confirm the deployed bundle contains the widget (search for "Verifying you're human").
3. Only then set `turnstile_secret_key` (Terraform) / the `turnstile-secret-key` Container App secret.
   Doing this first turns every Start click into a 403 for humans.
