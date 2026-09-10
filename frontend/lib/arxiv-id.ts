/**
 * Turn the catch-all route segments of /abs/[...id] back into an arXiv id.
 * Old-style ids contain a slash (hep-th/9901001), so the route is a catch-all
 * and the segments are re-joined; percent-encoding from the URL is undone.
 * Shared by the server page (metadata) and the client reader.
 */
export function normalizeArxivId(segments: string[] | undefined): string {
  if (!segments || segments.length === 0) return "";
  const joined = segments.join("/");
  try {
    return decodeURIComponent(joined);
  } catch {
    return joined;
  }
}
