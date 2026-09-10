/**
 * Vendor-agnostic product-analytics wrapper (client only).
 *
 * `track()` forwards to whatever `instrumentation-client.ts` registered
 * (PostHog in production). Until that happens — every build without
 * NEXT_PUBLIC_POSTHOG_KEY, and always during SSR — it is a silent no-op, so
 * call sites never need to know whether analytics is on.
 *
 * Never import this from a server component: it only makes sense where a
 * user is clicking, and the registered sink touches `window`.
 */

export type AnalyticsProps = Record<string, unknown>;
type CaptureFn = (event: string, props?: AnalyticsProps) => void;

// Module-level "ready" flag: null until instrumentation-client.ts registers a
// sink, which only happens when the analytics key is configured.
let capture: CaptureFn | null = null;

/** Called once by instrumentation-client.ts after the vendor SDK is initialised. */
export function registerAnalytics(fn: CaptureFn): void {
  capture = fn;
}

export function isAnalyticsReady(): boolean {
  return capture !== null;
}

/**
 * Record a product event. Event names are shared with the backend's
 * server-side counterparts (paper_start ↔ paper_accepted, paper_ready ↔
 * paper_completed, paper_failed ↔ paper_failed_server) — keep them stable.
 */
export function track(event: string, props?: AnalyticsProps): void {
  if (typeof window === "undefined" || capture === null) return;
  try {
    capture(event, props);
  } catch {
    // Analytics must never break the page.
  }
}
