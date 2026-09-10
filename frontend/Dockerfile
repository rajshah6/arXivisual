# ── arXivisual Frontend ─────────────────────────────────────
# Next.js 16 server (SSR) for Azure Container Apps. Three stages:
#   deps    — exact locked dependency set (npm ci)
#   builder — `next build` with output: "standalone"
#   runner  — only the traced server + static assets, non-root (~400 MB on
#             disk, ~120 MB compressed in ACR; the Node base is most of it)
#
# NEXT_PUBLIC_* values are inlined into the JS bundles at BUILD time, so they
# must arrive as build args (see .github/workflows/deploy-frontend.yml);
# setting them on the running container has no effect.
# ─────────────────────────────────────────────────────────────

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# --frozen equivalent: npm ci refuses to run if package-lock.json is out of
# sync with package.json, so a stale lockfile fails here, not in production.
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_TURNSTILE_SITE_KEY
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_TURNSTILE_SITE_KEY=${NEXT_PUBLIC_TURNSTILE_SITE_KEY} \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app

# Surfaced by GET /healthz so a deploy can confirm the new revision is live.
ARG APP_COMMIT_SHA=unknown
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    APP_COMMIT_SHA=${APP_COMMIT_SHA}

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# The standalone tracer emits server.js + a pruned node_modules, but by design
# leaves out `public/` and `.next/static` (they are meant for a CDN); copy
# them in explicitly so the Node server serves them itself.
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
