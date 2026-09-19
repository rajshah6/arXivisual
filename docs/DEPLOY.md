# Deploying arXivisual

Production runs in two pieces, both in the same Azure Container Apps environment (`arxivisual-api-env`, resource group `arxivisual-rg`, Terraform in [infra/](../infra/)):

| Part | Stack | Host |
|------|-------|------|
| Backend | FastAPI in Docker ([backend/Dockerfile](../backend/Dockerfile)) | Container Apps `arxivisual-api` (admits jobs, serves reads) and `arxivisual-worker` (same image, runs the pipeline), plus `arxivisual-temporal` |
| Frontend | Next.js 16 server (SSR, `output: "standalone"`) in Docker ([frontend/Dockerfile](../frontend/Dockerfile)) | Container App `arxivisual-web`; `arxivisual.org` and `www` are its custom domains once the [cut-over](#5-cut-over-vercel--azure) is applied |

Azure deploys are manual GitHub Actions runs (nothing in this repository deploys on push): `deploy-backend.yml` and `deploy-frontend.yml`, both authenticating to Azure with OIDC.

The backend image bundles Manim's system dependencies (FFmpeg, Cairo, Pango, a TeX Live install for `MathTex`), so it is large (~3 GB) and takes several minutes to build.

---

## Backend: Azure Container Apps

One image, two apps. `arxivisual-api` runs uvicorn; with `USE_TEMPORAL=1` (production) it only admits jobs and serves reads. `arxivisual-worker` runs `python /app/temporal_app/worker.py` from the **same image** and executes everything else: ingest, generation, renders, visual QA, repair, finalize. A backend deploy is therefore always two rolls — a worker left on an older image keeps running the old pipeline no matter what the API was rolled to.

### 1. Deploy with the workflow

```bash
gh workflow run deploy-backend.yml           # from main
gh run watch
```

[.github/workflows/deploy-backend.yml](../.github/workflows/deploy-backend.yml), in order:

1. refuses to run unless CI is green for the commit;
2. builds `backend/` in ACR as `arxivisual-api:gh-<sha>`, baking the commit in as `APP_COMMIT_SHA`;
3. rolls `arxivisual-api` and polls `GET /api/health` until its `commit` equals the sha — in single-revision mode the old revision keeps answering until the new one passes its probes, so a plain 200 proves nothing;
4. only then rolls `arxivisual-worker` to the same image and checks that its new revision is `Healthy` / `Running` (the worker has no ingress, so there is no URL to poll).

**Roll in the quiet window (19:00–24:00 UTC), with no paper in flight.** Only generation heartbeats (and resumes from per-visualization checkpoints). Ingest, render, repair and the repair re-render have no heartbeat: when a roll replaces the worker under one of them, Temporal notices only when that activity's start-to-close timeout expires — 15 minutes for an ingest, 25 for a render, 18 for a repair — so every interrupted activity can stall its job for up to that long. Ingest and render are then retried once; an interrupted repair is not, and the original video stays ([backend/temporal_app/workflows.py](../backend/temporal_app/workflows.py)).

The count that matters is job rows still `queued` or `processing` — the query the worker's KEDA scale rule already runs ([infra/container_apps.tf](../infra/container_apps.tf)), against the `arxiviz` database:

```sql
SELECT COUNT(*) FROM processing_jobs WHERE status IN ('queued','processing');   -- want 0
```

The Postgres firewall admits Azure-hosted clients only ([infra/database.tf](../infra/database.tf)), so it has to be run from inside Azure (Cloud Shell, for one) — a laptop is refused. It errs on the safe side: a job stranded by an earlier interruption keeps counting until the reaper fails it (two hours old, on the next `POST /api/process`).

From a laptop there is only a lower bound:

```bash
API=https://arxivisual-api.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io
curl -s $API/api/papers | jq '[.papers[] | select(.status == "processing")] | length'
```

Anything above 0 means wait. **0 is not a green light:** a paper reads `ready` as soon as it has one finished video (from this run or an earlier one), while its other renders and the whole repair pass are still running, and a job whose ingest has not stored the paper yet is not in the list at all.

### 2. Deploy by hand (what the workflow automates)

Build remotely in Azure Container Registry — no local Docker needed. From the repo root:

```bash
az acr build -r ca82c08e2eadacr -t arxivisual-api:<tag> \
  --build-arg APP_COMMIT_SHA=$(git rev-parse HEAD) backend
```

Use a descriptive, dated tag (e.g. `tts-langfuse-20260825`) so rollbacks are unambiguous. The build context is the `backend/` directory minus [backend/.dockerignore](../backend/.dockerignore) (tests, evals, tools and videos stay out of the image); the Dockerfile installs the exact locked dependency set with `uv sync --frozen`, so a stale `uv.lock` fails the build instead of shipping silently (CI enforces the same invariant).

Then roll **both** apps, API first:

```bash
IMAGE=ca82c08e2eadacr.azurecr.io/arxivisual-api:<tag>
az containerapp update -n arxivisual-api    -g arxivisual-rg --image $IMAGE
# wait until /api/health reports the new commit (step 3), then:
az containerapp update -n arxivisual-worker -g arxivisual-rg --image $IMAGE
```

Each update creates a new revision and shifts traffic to it. The API scales between 1 and 2 replicas (one is always warm); the worker between 1 and 3 on a KEDA rule that counts queued and processing jobs. Every replica is 2 vCPU / 4 Gi because Manim renders are CPU-bound ([infra/container_apps.tf](../infra/container_apps.tf)).

### 3. Verify

```bash
curl -s $API/api/health
az containerapp revision list -n arxivisual-worker -g arxivisual-rg \
  --query "[?properties.active].{revision:name, image:properties.template.containers[0].image, health:properties.healthState, state:properties.runningState}" -o table
```

The health path is `GET /api/health` — there is no `/health` (it answers 404). It reports the deployed `commit` plus database, Manim, and storage connectivity; expect `"status": "healthy"` with `"database": "connected"`, `"manim": "available (...)"`, and `"storage": "r2: connected"`. The worker's active revision must show the same image tag as the API, `Healthy` and `Running`. Also confirm `POST /api/render` returns 404 (see `RENDER_API_SECRET` below).

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
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | **secret** (Terraform writes it from `azurerm_application_insights.main`, [infra/insights.tf](../infra/insights.tf)) — turns on Azure Application Insights for the API and worker via the Azure Monitor OpenTelemetry distro (requests, outbound HTTP dependencies, exceptions, logs). Unset = off. Langfuse keeps its own tracer provider, so its LLM traces never reach App Insights and are never sampled by it ([backend/telemetry.py](../backend/telemetry.py)) |
| `OTEL_LOGS_EXPORTER` | `none` — app logs already reach the workspace as Container Apps console logs; without this the distro ships every INFO record a second time (unsampled) |
| `OTEL_TRACES_SAMPLER`, `OTEL_TRACES_SAMPLER_ARG` | `microsoft.fixed_percentage` / `0.2` — keep 20% of App Insights request traces. Set both: with the sampler name absent the distro defaults to rate limiting and reads the argument as traces *per second* |
| `POSTHOG_API_KEY` | **secret**, optional (`posthog_api_key` in Terraform) — PostHog project token; enables the server-side product events `paper_accepted` (API, distinct_id = the pseudonymous client fingerprint), `paper_completed` and `paper_failed_server` (whichever process finishes the job — the worker on the Temporal path, the API on the in-process fallback; distinct_id = job id, no person profile). Unset = no events, no client started |
| `POSTHOG_HOST` | PostHog ingestion host; default `https://us.i.posthog.com` (EU: `https://eu.i.posthog.com`). Only set alongside the token |
| `VOICEOVER_TTS_SERVICE`, `VOICEOVER_VOICE_NAME`, `VOICEOVER_TTS_MODEL` | Optional TTS overrides. Defaults (`openai` / `nova` / `gpt-4o-mini-tts`) reuse the `AZURE_OPENAI_*` credentials at render time — no extra key needed. The TTS model must match an Azure deployment name |

### Rollback

List available tags, newest first:

```bash
az acr repository show-tags -n ca82c08e2eadacr \
  --repository arxivisual-api --orderby time_desc -o table
```

Then put **both** apps back on the previous tag — rolling back only the API leaves the worker running the code you are backing out of:

```bash
IMAGE=ca82c08e2eadacr.azurecr.io/arxivisual-api:<previous-tag>
az containerapp update -n arxivisual-api    -g arxivisual-rg --image $IMAGE
az containerapp update -n arxivisual-worker -g arxivisual-rg --image $IMAGE
```

Environment variables and secrets live on the apps, not the image, so no reconfiguration is needed. Alternatively, reactivate a prior revision directly, once per app:

```bash
az containerapp revision list -n arxivisual-api -g arxivisual-rg -o table
az containerapp revision activate -n arxivisual-api -g arxivisual-rg --revision <name>
az containerapp revision list -n arxivisual-worker -g arxivisual-rg -o table
az containerapp revision activate -n arxivisual-worker -g arxivisual-rg --revision <name>
```

The same quiet-window rule applies: a rollback replaces the worker too.

### Monitoring and alerts

- **Production monitor** (scheduled GitHub Actions workflow) checks that the site and `GET /api/health` answer, fails when a certificate is less than 21 days from expiry, and flags deploy drift: API and worker on different images, or `main` ahead of the deployed sha for more than 24 hours.
- **Azure Monitor alerts** (`infra/alerts.tf`) email on Postgres, replica, Temporal-fallback and 5xx conditions. A Temporal fallback means the API could not start a workflow and logged `Temporal unavailable — falling back to in-process pipeline`: the job still runs, but inside the API container and without durability.
- `security.yml` (gitleaks, blocking; npm/pip audits, advisory) runs on pull requests, on every push to `main`, and weekly.

### ACR housekeeping

The registry is **Basic tier**. Its 10 GiB is *included* storage, not a ceiling: Basic keeps accepting pushes up to 40 TiB and bills every GiB above the included 10 at a daily rate. Each backend image is ~3 GB (TeX Live) and nothing prunes them, so the registry stood at **~43 GB on 2026-09-18** — a standing overage charge, not a full disk. Check with `az acr show-usage -n ca82c08e2eadacr -o table`.

Deletion is by manifest, not by tag: `az acr repository delete --image <repo>:<tag>` removes the manifest that tag points at **and every other tag on it**. List tags with their digests first — equal digests share one manifest:

```bash
az acr repository show-tags -n ca82c08e2eadacr --repository arxivisual-api \
  --detail --orderby time_desc --query "[].{tag:name, digest:digest}" -o table
```

These must survive every prune (none of them may share a digest with a tag you delete):

| Keep | How to find it |
|------|----------------|
| the live API tag | `az containerapp show -n arxivisual-api -g arxivisual-rg --query "properties.template.containers[0].image" -o tsv` |
| the live worker tag (differs from the API's whenever a roll was skipped) | same command with `-n arxivisual-worker` |
| the tag Terraform names | `local.app_image` in [infra/container_apps.tf](../infra/container_apps.tf) — only read when Terraform creates or replaces an app, which is exactly when a missing image hurts |
| one rollback tag | the newest tag older than the live one that you would actually roll back to |
| `arxivisual-web:latest` and the live `arxivisual-web` tag | `latest` normally shares its manifest with the newest `gh-<sha>`; Terraform creates the web app from it ([Frontend → Rollback](#3-rollback)) |

Then delete the rest, one tag per manifest:

```bash
az acr repository delete -n ca82c08e2eadacr --image arxivisual-api:<old-tag>
```

To drop a single tag while keeping its manifest, use `az acr repository untag` instead.

---

## Frontend: Azure Container Apps

> **Status as of 2026-09-18 — between hosts.** Everything below this note describes the end state; delete the note when [section 5](#5-cut-over-vercel--azure) is finished, soak period included.
>
> - `arxivisual-web` runs on Azure Container Apps and is reachable **only** at `https://arxivisual-web.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io`.
> - `arxivisual.org` (`A 216.198.79.1`) and `www.arxivisual.org` (`CNAME 7d386a74595ad41d.vercel-dns-017.com`) still resolve to the old Vercel project. Its git integration builds and deploys **every push to `main`** to production, and a preview for every pull request — so a merge is a production frontend deploy, whether or not `deploy-frontend.yml` ran.
> - That build reads **Vercel's own** environment variables. The GitHub repository variables in the table below reach only the Azure image, which is why the public site has had no PostHog since 2026-09-10: `/ingest/static/array.js` is a 404 on `www.arxivisual.org` and a 200 on the Azure address.
> - Still to do: the Porkbun records and the second Terraform apply (`web_custom_domains_enabled = true`).

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
| `NEXT_PUBLIC_POSTHOG_KEY` | PostHog project token (`phc_…`, public). Unset = no product analytics and no `/ingest` proxy (see [Analytics](#analytics)) |
| `NEXT_PUBLIC_POSTHOG_HOST` | PostHog UI host: `https://us.posthog.com` (default when unset) or `https://eu.posthog.com`; also selects the ingest region the proxy forwards to |
| `NEXT_PUBLIC_CLARITY_PROJECT_ID` | Microsoft Clarity project id (public). Unset = no Clarity tag and no cookie consent bar |

The image also bakes in `APP_COMMIT_SHA` (reported by `/healthz`). Nothing else is configurable at runtime; the container listens on `:3000` as a non-root user. The app sends `Strict-Transport-Security` and the basic security headers itself — Container Apps ingress adds none, and nothing else sits in front of it.

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

or `az containerapp revision activate` as for the backend. Images are ~400 MB on disk (~120 MB compressed in ACR; the Node base image is most of it). Prune *older* `arxivisual-web` tags with `az acr repository delete --image arxivisual-web:<old-tag>` — never the newest one: it shares its manifest with `latest`, which Terraform creates or replaces the app from, and deleting a tag deletes the manifest and every tag on it.

### 4. Custom domain and DNS (Porkbun)

[infra/frontend.tf](../infra/frontend.tf) binds `arxivisual.org` and `www.arxivisual.org` to `arxivisual-web` as custom domains with free Azure-managed (DigiCert) certificates, behind the `web_custom_domains_enabled` flag (default `false`; the apply that turns it on is step 3 of [section 5](#5-cut-over-vercel--azure)). Container Apps validates ownership through DNS, so the records must resolve **before** that apply — every phase fails without them, the certificate one only after a 30-minute wait. At Porkbun (DNS → arxivisual.org):

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

Rules that matter: the `www` CNAME must point *directly* at the app FQDN (an intermediate CNAME or ALIAS blocks issuance and renewal); the apex must be an `A` record, not an ALIAS; if the zone ever gets a `CAA` record, add `0 issue digicert.com` next to it (as of the migration the zone has none — do not add one). The `A` and `CNAME` rows **replace** Vercel's records for the same hosts (edit them in place; do not add a second answer) — a hostname resolving to two places validates nowhere. The two `asuid` TXT rows carry no traffic and can be created days ahead. Certificates are issued a few minutes after validation and renew automatically as long as the records and public HTTP ingress stay in place.

### 5. Cut-over (Vercel → Azure)

**There is an outage window, and it cannot be engineered away.** The managed certificates are validated over HTTP (apex) and by CNAME (`www`): DigiCert has to reach each hostname *on Azure*, so they can only be issued **after** DNS points at Container Apps. From the moment a resolver hands out the new records until the certificates are issued and bound (`SniEnabled`), the Container Apps ingress has no certificate for the two hostnames and resets the TLS handshake. Returning visitors cannot click through or fall back to `http://`: Vercel has been sending `Strict-Transport-Security: max-age=63072000` (two years), and a browser holding that pin refuses any downgrade. Expect both hosts to hard-fail for roughly **5–30 minutes** (hostname registration, issuance, bind), plus resolver caches on either side — Porkbun's minimum TTL is 600 s, so dropping it to 60 s beforehand is not an option.

What shortens it:

- Create the two `asuid` TXT records in advance. They carry no traffic, and they are the half of the DNS work that can be wrong without anyone noticing.
- Flip in the quietest hours, 19:00–24:00 UTC.
- Have the apply ready (`web_custom_domains_enabled = true`, plan already reviewed) and run it the minute `dig` shows the new records; do not wait for "full propagation".
- If `main` has moved since the last `deploy-frontend.yml` run, deploy the frontend **first**. At the flip the public site jumps from Vercel's build of `main` to whatever image `arxivisual-web` is running (`curl -s $WEB/healthz` shows its commit).

**Before the day**

1. *Bootstrap (a fresh environment only).* Run `deploy-frontend.yml` with `roll=false`, then `terraform apply` with the defaults (`web_image_tag = "latest"`, `web_custom_domains_enabled = false`): this creates `arxivisual-web` and sets `CORS_EXTRA_ORIGINS` + `TURNSTILE_ALLOWED_HOSTNAMES` on the API app so the new host may call it. Verify on the `azurecontainerapps.io` URL ([step 2](#2-verify)).
2. *Turnstile hostnames.* In the Cloudflare dashboard, the widget's hostname list must contain all three: `arxivisual.org`, `www.arxivisual.org` and `arxivisual-web.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io`. A host missing there cannot mint a token, and every Start click on it ends in a 403.
3. *Smoke test from the Azure address.* Open `$WEB`, start one paper that is **not** already in Explore, and follow it through to playable videos. One uncached paper exercises Turnstile on the new hostname, CORS from the new origin, the API, Temporal, the worker and R2; a cached paper proves none of it. It counts against the daily cap and spends real LLM budget like any other new paper.
4. *`asuid` TXT records* created, and answering: `dig +short TXT asuid.arxivisual.org` and `dig +short TXT asuid.www.arxivisual.org` both print the verification id.
5. *Canonical host — open decision.* Today Vercel answers the apex with a 307 to `www`, while `metadataBase` and every canonical tag name the apex ([frontend/app/layout.tsx](../frontend/app/layout.tsx), [frontend/lib/paper-metadata.ts](../frontend/lib/paper-metadata.ts)). After the cut-over nothing redirects: both hosts answer 200 with the same pages. Pick the canonical host and add the redirect **after** the cut-over. A `www → apex` redirect in app code merged before it would also deploy to Vercel, meet Vercel's own apex → `www` redirect, and loop.

**The day**

1. At Porkbun, replace the apex `A` and the `www` `CNAME` with the values from `terraform output web_dns_records` ([section 4](#4-custom-domain-and-dns-porkbun)).
2. Wait until `dig +short arxivisual.org` answers with the static IP and `dig +short www.arxivisual.org` with the app FQDN.
3. Apply with `web_custom_domains_enabled = true` immediately (issuance takes a few minutes; the apply waits), then confirm `az containerapp hostname list -n arxivisual-web -g arxivisual-rg -o table` shows `SniEnabled` for both names.
4. `curl -sI https://www.arxivisual.org` and `https://arxivisual.org` return 200 with a valid certificate, `curl -s https://arxivisual.org/healthz` reports the commit you deployed, and Start works on the public domain.

**Rollback** is the DNS change in reverse. Vercel's records, verbatim — they are written down nowhere else:

| Type | Host | Answer |
|------|------|--------|
| `A` | *(blank / apex)* | `216.198.79.1` |
| `CNAME` | `www` | `7d386a74595ad41d.vercel-dns-017.com` |

It takes one TTL (600 s) plus resolver caches, and it only works while the Vercel project still has the domains attached. Removing a bound domain from Terraform afterwards needs a manual unbind first (`az containerapp hostname delete`): the azapi binding step has no delete behaviour.

**Soak: 7 days.** Leave the Vercel project exactly as it is — domains attached, git integration on — for seven days after the first 200. It keeps building `main`, so it stays a warm fallback that the two records above switch back to. It does not keep forever: Vercel cannot renew its certificates while DNS points at Azure (the current ones run to 12–13 November 2026).

**Decommission (after the soak)**

1. Remove `arxivisual.org` and `www.arxivisual.org` from the Vercel project's domains.
2. Disconnect the Vercel GitHub integration from this repository. Left connected, its deployment check goes red on every pull request once the project stops building.
3. Delete the leftover `Preview` and `Production` GitHub environments (Settings → Environments); `vercel[bot]` created them and nothing else uses them.
4. Delete the Vercel project.
5. Delete the dated status notes: the one at the top of this section, and those in [README.md](../README.md#deployment), [CONTRIBUTING.md](../CONTRIBUTING.md) and [frontend/README.md](../frontend/README.md).

### 6. Local production image

```bash
docker build -t arxivisual-web:local --build-arg NEXT_PUBLIC_API_URL=<api url> frontend
docker run --rm -p 3000:3000 arxivisual-web:local
```

---

## Analytics

Two client-side tools, each compiled in only when its repository variable (table above) is set. Local dev and CI run without either: no init code runs, no `/ingest` rewrite exists, and no request ever leaves for `*.posthog.com` or `clarity.ms`.

**PostHog — product analytics, cookieless.** [frontend/instrumentation-client.ts](../frontend/instrumentation-client.ts) initialises `posthog-js` with `cookieless_mode: "always"` and `person_profiles: "never"`: no cookies, no local/session storage, no person profiles — a visitor is a privacy-preserving hash computed on PostHog's servers, so PostHog needs no cookie notice. Autocapture is off. Collected: pageviews and pageleaves (one per App Router navigation, via the dated `defaults`), web vitals, and four product events fired from client components through [frontend/lib/analytics.ts](../frontend/lib/analytics.ts):

| Event | Fired when | Properties |
|-------|------------|------------|
| `paper_start` | Start clicked on an unprocessed paper (`processArxivPaper` called) | `arxiv_id` |
| `paper_ready` | the status poll reaches `completed` | `arxiv_id`, `videos` (sections with a playable video) |
| `paper_failed` | the poll reaches `failed` (or `completed` with no paper) | `arxiv_id`, `reason`, `partial` (text survived, only videos failed) |
| `paper_open` | a gallery card is clicked on `/explore` | `arxiv_id`, `position` |

The backend emits server-side counterparts (`paper_accepted`, `paper_completed`, `paper_failed_server`). Browser traffic goes to `/ingest/*` on our own origin; [frontend/next.config.ts](../frontend/next.config.ts) rewrites it to PostHog's US ingest/assets hosts, or the EU ones when `NEXT_PUBLIC_POSTHOG_HOST` contains `eu.` (`skipTrailingSlashRedirect` is on because the SDK posts to `/ingest/e/`). Two project toggles must be ON in the PostHog UI, otherwise cookieless events are dropped at ingestion / vitals never arrive: **Settings → Web analytics → Cookieless server hash mode** and **Settings → Autocapture → Web vitals**. Dashboards live in that PostHog project (`NEXT_PUBLIC_POSTHOG_HOST`): Web analytics for traffic, Product analytics for the events above.

**Microsoft Clarity — session replays and heatmaps, with consent.** Initialised from the same file via `@microsoft/clarity`. Clarity *does* set cookies (first-party `_clck`, `_clsk`), but only after consent: [frontend/components/ConsentBar.tsx](../frontend/components/ConsentBar.tsx) is the notice — a small bar at the bottom of every page until the visitor picks Accept or Decline, remembered in `localStorage`, never blocking the page. Accept calls Clarity's `consentV2` with `analytics_Storage: "granted"` and `ad_Storage: "denied"` (ads are never granted); Decline sends both denied, so Clarity keeps running cookieless (one id per page view, no cross-page replays); a remembered answer is replayed on every load before Clarity could set anything. Clarity's Consent Mode is on by default for EEA/UK/CH visitors only — enable it for the whole project in the Clarity project settings so every visitor is cookieless until they accept. Dashboard: https://clarity.microsoft.com → the project.

Checking a deployed build: with the key set, `curl -sI $WEB/ingest/static/array.js` (`$WEB` as in [Verify](#2-verify)) answers with a PostHog response, not a Next 404; with neither variable set, the served pages make no analytics request at all. Run it against the public domain too — a 404 there means the domain is being served by a build that never saw the repository variables.

## CI

[.github/workflows/ci.yml](../.github/workflows/ci.yml) runs on every pull request and every push to `main`: backend ruff + pytest on Python 3.11 and 3.13 (offline, dummy provider credentials), frontend typecheck + lint + build (all hard gates), and Docker image builds for both halves gated on changes to their build inputs (backend: Dockerfile, `pyproject.toml`, `uv.lock`; frontend: Dockerfile, `.dockerignore`, `package*.json`, `next.config.ts`). Deploys are the manual workflows above — CI validates that the images still build but does not push them.

## Turnstile rollout order (matters)

1. Set the `NEXT_PUBLIC_TURNSTILE_SITE_KEY` repository variable and run `deploy-frontend.yml` — the widget appears and sends
   tokens; the backend ignores them while it has no secret (harmless).
2. Confirm the deployed bundle contains the widget (search for "Verifying you're human").
3. Only then set `turnstile_secret_key` (Terraform) / the `turnstile-secret-key` Container App secret.
   Doing this first turns every Start click into a 403 for humans.
