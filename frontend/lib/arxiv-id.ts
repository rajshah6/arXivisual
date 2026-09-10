/**
 * arXiv id helpers shared by the server page (metadata) and the client
 * reader of /abs/[...id].
 */

const NEW_STYLE = /^\d{4}\.\d{4,5}(v\d+)?$/i; // 1706.03762, 2301.00002v3
const OLD_STYLE = /^[a-z-]+(\.[a-z]{2})?\/\d{7}(v\d+)?$/i; // hep-th/9901001

/**
 * Turn the catch-all route segments of /abs/[...id] back into an arXiv id.
 * Old-style ids contain a slash (hep-th/9901001), so the route is a catch-all
 * and the segments are re-joined; percent-encoding from the URL is undone.
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

/** Syntactically an arXiv id (new or old style, optional version suffix). */
export function isArxivId(id: string): boolean {
  return NEW_STYLE.test(id) || OLD_STYLE.test(id);
}

/** The id without a trailing version: the backend stores and serves papers
 *  under the base id, so every version of a URL is the same page. */
export function baseArxivId(id: string): string {
  return id.replace(/v\d+$/i, "");
}
