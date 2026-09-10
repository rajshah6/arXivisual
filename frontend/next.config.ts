import type { NextConfig } from "next";

// PostHog reverse proxy. The SDK (instrumentation-client.ts) talks to
// /ingest on our own origin and these rewrites forward it to PostHog, so the
// capture traffic is first-party. Hostnames are the ones in PostHog's Next.js
// proxy docs; the region follows NEXT_PUBLIC_POSTHOG_HOST (the UI host):
// https://eu.posthog.com selects the EU ingest/assets hosts, anything else US.
// Evaluated at `next build` — the build arg must be present then, not at run.
const POSTHOG_ENABLED = Boolean(process.env.NEXT_PUBLIC_POSTHOG_KEY);
const POSTHOG_REGION = (process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "").includes("eu.") ? "eu" : "us";

const nextConfig: NextConfig = {
  // Self-hosted on Azure Container Apps: `next build` emits a minimal Node
  // server plus only the files it traces into .next/standalone, which the
  // Dockerfile copies into a small runtime image (no node_modules, no Vercel).
  output: "standalone",

  // PostHog posts to /ingest/e/ (trailing slash); Next would otherwise 308 it
  // to /ingest/e before the rewrite. Side effect: /explore/ now answers 200
  // instead of redirecting to /explore (the app never links with a slash).
  skipTrailingSlashRedirect: true,

  async rewrites() {
    if (!POSTHOG_ENABLED) return [];
    return [
      {
        source: "/ingest/static/:path*",
        destination: `https://${POSTHOG_REGION}-assets.i.posthog.com/static/:path*`,
      },
      {
        source: "/ingest/array/:path*",
        destination: `https://${POSTHOG_REGION}-assets.i.posthog.com/array/:path*`,
      },
      {
        source: "/ingest/:path*",
        destination: `https://${POSTHOG_REGION}.i.posthog.com/:path*`,
      },
    ];
  },
};

export default nextConfig;
