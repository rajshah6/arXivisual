# Security Policy

## Reporting a Vulnerability

Please report vulnerabilities privately — do not open a public issue.

- **Preferred:** [GitHub Security Advisories](https://github.com/rajshah6/arXivisual/security/advisories/new) ("Report a vulnerability" on this repository)
- **Alternatively:** contact a maintainer directly (see the Creators section of the [README](README.md))

Include steps to reproduce and the impact you believe the issue has. We'll acknowledge reports as quickly as we can and keep you updated while we work on a fix. Please give us reasonable time to remediate before any public disclosure.

## Scope

- The backend API (`arxivisual-api` on Azure Container Apps, `https://arxivisual-api.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io`)
- The frontend at [arxivisual.org](https://www.arxivisual.org) and `www.arxivisual.org`
- The frontend Container App at its own public address, `https://arxivisual-web.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io`. It serves the same application, is allowed by the API's CORS and Turnstile hostname lists, and is in scope exactly like the domain.

Out of scope: denial of service via volume alone (processing papers is intentionally expensive), and issues in the third-party services we depend on — report those upstream:

- arXiv (paper source)
- Microsoft Azure: Container Apps, Azure OpenAI, PostgreSQL, Application Insights / Log Analytics
- Cloudflare: R2 (video storage) and Turnstile
- Langfuse (LLM traces)
- PostHog (product analytics)
- Microsoft Clarity (session replay; wired into the frontend but not enabled — no project id is configured)
- Vercel, which still serves `arxivisual.org` until the DNS cut-over described in [docs/DEPLOY.md](docs/DEPLOY.md#5-cut-over-vercel--azure) is complete

## Notes for Researchers

- `POST /api/render` executes caller-supplied Manim/Python code by design, for development only. In production it is disabled entirely unless the operator configures `RENDER_API_SECRET` and the caller presents it via the `X-Render-Secret` header; it returns 404 either way. Confirming that 404 is fine; attempting to bypass it on the production deployment is in scope to report, not to exploit further.
- **The pipeline executes LLM-generated Python on the server.** Every animation is Manim code written by a model from the text of an arXiv paper, so paper content is untrusted input to a code generator. That code runs twice, both times in a subprocess and never inside the API or worker process: once in the dry-run validation gate and once in the real render. Before either, a static gate rejects generated code that imports `os`, `subprocess`, `socket`, HTTP clients and similar modules or calls `eval` / `exec` / `open` (`backend/agents/code_validator.py`). Both subprocesses start from one deny-list scrub of the parent environment (`backend/rendering/sandbox_env.py`): every `AZURE_*`, `S3_*`, `LANGFUSE_*`, `POSTHOG_*`, `APPLICATIONINSIGHTS_*`, `TURNSTILE_*`, `IP_HASH_*`, `TEMPORAL_*`, `IDENTITY_*` / `MSI_*` variable, `DATABASE_URL`, and any name containing `KEY`, `SECRET`, `TOKEN`, `PASSWORD` or `CONNECTION_STRING` is removed. One credential is deliberately put back for the real render: narration synthesis needs an Azure OpenAI key, passed as `OPENAI_API_KEY` (`backend/rendering/local_runner.py`), and that key is scoped to the whole Azure OpenAI account, not to the speech deployment. Neither subprocess is a sandbox — the child runs as the same user in the same container, with no syscall or network isolation. A way to make generated code read a secret, reach the database or the video bucket, or persist beyond its render is squarely in scope.
- Please don't test against production data beyond what's needed to demonstrate an issue.

## Bounty

This is a small open-source project — we do not offer a bug bounty. We will gladly credit reporters in the fix's release notes if desired.

## Abuse Controls (cost-bounded admission)

`POST /api/process` spends real money per accepted paper, and this repository is public, so the
limits are designed to hold even when the attacker has read them:

1. **Proof-of-humanity** — Cloudflare Turnstile, verified server-side (browser → API → siteverify).
   Direct API scripts never pass; verification fails closed if Cloudflare is unreachable. Every token
   is minted with the action `start-paper` and the paper's id as `cData`, and the API refuses a token
   carrying any other action, any other paper, or a hostname outside its allow-list — one solved
   challenge starts exactly one paper and cannot be replayed across ids or lifted from another site.
2. **Durable daily cap** — `DAILY_NEW_PAPER_CAP` new-paper jobs per UTC day, counted from Postgres so
   it survives restarts and replicas. Already-visualized papers are always served for free.
3. **Sliding windows** — per-IP hourly and per-IP daily in memory; the global window is counted from the jobs table so every replica enforces the same number. Client identity is the rightmost
   `X-Forwarded-For` hop (appended by the ingress); client-supplied prefixes are ignored.

The cap and the global window are checked before Turnstile, so a day that is already full does not
burn a visitor's single-use token.

Need bulk or programmatic access? Open an issue — that is a conversation, not a rate-limit race.

## What Leaves the Service About a Visitor

- **Logs** carry a pseudonymous client fingerprint — HMAC-SHA256 of the client IP under a server-side
  secret, truncated to 12 hex characters — plus user agent, `Accept-Language`, Referer host and
  Origin, for abuse forensics. Raw IPs are never written.
- **Cloudflare (Turnstile siteverify)** receives the Turnstile token and the **raw client IP** as
  `remoteip` on every `POST /api/process` that reaches verification. Cloudflare already saw that
  address when the browser solved the challenge.
- **PostHog, server-side** receives a `paper_accepted` event whose `distinct_id` is that same
  **hashed fingerprint**, with the arXiv id and job id. Completion and failure events use the job id
  as `distinct_id`. Person profiles and GeoIP are turned off for all of them.
- **PostHog, browser-side** runs cookieless (no cookies, no local storage, no person profiles) through
  a same-origin `/ingest` proxy. **Microsoft Clarity** is wired in behind a consent bar but is not
  enabled. Details: [docs/DEPLOY.md → Analytics](docs/DEPLOY.md#analytics).
- **Application Insights** receives request and dependency telemetry from the API and worker, sampled
  at 20%. LLM prompts and completions go to **Langfuse** only; they are deliberately kept out of
  Application Insights (`backend/telemetry.py`).
