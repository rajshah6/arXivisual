# arXivisual frontend

Next.js 16 (App Router, React 19, Tailwind 4). The production target is a
Node server — `output: "standalone"` — inside a Docker image on Azure
Container Apps (`arxivisual-web`), next to the FastAPI backend. There is no
static export.

> **Status as of 2026-09-18 — the move off Vercel is not finished.**
> `arxivisual-web` is live only at its `azurecontainerapps.io` address.
> `arxivisual.org` and `www` still resolve to the old Vercel project, which
> builds and deploys every push to `main` on its own and reads its **own**
> environment variables: the `NEXT_PUBLIC_*` GitHub repository variables
> that `deploy-frontend.yml` builds with never reach it, which is why the
> public site has had no PostHog since 2026-09-10.
> Until the [cut-over](../docs/DEPLOY.md#5-cut-over-vercel--azure) is done,
> merging to `main` is a production deploy. Delete this note afterwards.

## Develop

Node 20.9+ (the image builds on Node 22).

```bash
npm ci
npm run dev        # http://localhost:3000, expects the backend on :8000
```

Environment (all optional, `.env.local` is git-ignored):

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Backend origin. Unset: production builds fall back to the Azure API URL, dev builds to `http://localhost:8000` ([lib/api.ts](lib/api.ts)) |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | Cloudflare Turnstile site key; unset = no widget |
| `NEXT_PUBLIC_POSTHOG_KEY` | PostHog project token (`phc_…`); unset = analytics off (no init, no `/ingest` proxy) |
| `NEXT_PUBLIC_POSTHOG_HOST` | PostHog UI host, `https://us.posthog.com` (default) or `https://eu.posthog.com`; picks the ingest region |
| `NEXT_PUBLIC_CLARITY_PROJECT_ID` | Microsoft Clarity project id; unset = no Clarity and no cookie consent bar |
| `NEXT_PUBLIC_USE_MOCK` | `true` to serve the bundled demo paper instead of calling the API |

`NEXT_PUBLIC_*` values are inlined into the bundles by `next build`; changing
one means rebuilding.

Analytics wiring: [instrumentation-client.ts](instrumentation-client.ts)
(PostHog cookieless init + Clarity init, only with the variables above),
[lib/analytics.ts](lib/analytics.ts) (`track()`, a no-op until PostHog is
up — call it from client components only), [lib/clarity-consent.ts](lib/clarity-consent.ts)
and [components/ConsentBar.tsx](components/ConsentBar.tsx) (Clarity cookie
notice). What is collected and the PostHog/Clarity project settings:
[docs/DEPLOY.md → Analytics](../docs/DEPLOY.md#analytics).

## Check

```bash
npx tsc --noEmit && npm run lint && npm run build
```

All three are hard CI gates.

## Build the production image

```bash
docker build -t arxivisual-web:local \
  --build-arg NEXT_PUBLIC_API_URL=https://arxivisual-api.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io \
  --build-arg APP_COMMIT_SHA=$(git rev-parse HEAD) \
  .
docker run --rm -p 3000:3000 arxivisual-web:local
curl -s localhost:3000/healthz     # {"status":"ok","commit":"<sha>",...}
```

[Dockerfile](Dockerfile) is a three-stage build (deps → `next build` →
runtime) that ships only the traced standalone server, `.next/static` and
`public/`, running as a non-root user on port 3000.

## Routes worth knowing

- `/abs/[...id]` — the reader. [`page.tsx`](app/abs/[...id]/page.tsx) is a
  server component that resolves per-paper `<title>`/OpenGraph metadata from
  the API ([lib/paper-metadata.ts](lib/paper-metadata.ts), fail-safe, cached
  10 min) and renders the client reader in `PaperPage.tsx`.
- `/healthz` — liveness/readiness for Container Apps; reports the image's
  commit so a deploy can wait for the new revision.

Deployment, DNS and rollback: [docs/DEPLOY.md](../docs/DEPLOY.md).
