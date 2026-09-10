import { NextResponse } from "next/server";

/**
 * Liveness/readiness target for Azure Container Apps and the deploy
 * workflow's "is the NEW revision serving yet" check: `commit` is the git
 * SHA baked in at image build time (APP_COMMIT_SHA), so a deploy can wait
 * for the value to match instead of trusting a 200 that the old revision is
 * still serving during a rollout.
 */
export const dynamic = "force-dynamic";

const startedAt = Date.now();

export function GET() {
  return NextResponse.json(
    {
      status: "ok",
      commit: process.env.APP_COMMIT_SHA ?? null,
      uptime_s: Math.round((Date.now() - startedAt) / 1000),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
