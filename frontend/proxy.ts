import { NextResponse, type NextRequest } from "next/server";

/**
 * Trailing-slash redirect, restored. next.config.ts sets
 * `skipTrailingSlashRedirect` because PostHog's SDK posts to `/ingest/e/`
 * (with a slash) and a 308 before the rewrite would break capture. That
 * flag is global, so this proxy puts the redirect back for every other path:
 * `/explore/` → `/explore` (308), `/abs/<id>/` → `/abs/<id>`, keeping one
 * canonical URL per page. `/ingest/*` is excluded by the matcher, as
 * PostHog's proxy docs require.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname.length > 1 && pathname.endsWith("/")) {
    // A plain URL, not request.nextUrl.clone(): NextURL re-applies its own
    // trailing-slash normalisation to the pathname and would put the slash
    // back on the redirect target.
    const url = new URL(request.url);
    url.pathname = pathname.replace(/\/+$/, "");
    return NextResponse.redirect(url, 308);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except Next internals, the PostHog proxy, and static files.
  matcher: ["/((?!_next/|ingest/|.*\\.[a-zA-Z0-9]+$).*)"],
};
