# Security Policy

## Reporting a Vulnerability

Please report vulnerabilities privately — do not open a public issue.

- **Preferred:** [GitHub Security Advisories](https://github.com/rajshah6/arXivisual/security/advisories/new) ("Report a vulnerability" on this repository)
- **Alternatively:** contact a maintainer directly (see the Creators section of the [README](README.md))

Include steps to reproduce and the impact you believe the issue has. We'll acknowledge reports as quickly as we can and keep you updated while we work on a fix. Please give us reasonable time to remediate before any public disclosure.

## Scope

- The backend API (the arXivisual API deployed on Azure Container Apps)
- The frontend at [arxivisual.org](https://www.arxivisual.org)

Out of scope: denial of service via volume alone (processing papers is intentionally expensive), and issues in third-party services we depend on (arXiv, Azure, Vercel, Cloudflare, Langfuse) — report those upstream.

## Notes for Researchers

- `POST /api/render` executes caller-supplied Manim/Python code by design, for development only. In production it is disabled entirely unless the operator configures `RENDER_API_SECRET` and the caller presents it via the `X-Render-Secret` header; it returns 404 either way. Confirming that 404 is fine; attempting to bypass it on the production deployment is in scope to report, not to exploit further.
- Please don't test against production data beyond what's needed to demonstrate an issue.

## Bounty

This is a small open-source project — we do not offer a bug bounty. We will gladly credit reporters in the fix's release notes if desired.
