import "server-only";

import type { Metadata } from "next";
import { API_BASE } from "./api";
import { baseArxivId, isArxivId } from "./arxiv-id";
import { getDemoPaper } from "./mock-data";

/**
 * Per-paper <title> / description / OpenGraph for /abs/[...id].
 *
 * This is the one thing the SSR deployment does that a static export could
 * not: a link to a paper unfurls with the paper's title and abstract instead
 * of the generic site card, and search engines index a real title. It is
 * deliberately fail-safe — any API error, timeout, 404 (unknown or stale
 * paper) or malformed body falls back to a generic title, so the reader
 * (which fetches client-side and offers "Start" for unknown papers) is never
 * blocked on this request.
 *
 * Only pages that show a processed paper are indexable: a syntactically valid
 * but unprocessed id is a soft 404 (the reader offers "Start"), and anything
 * that is not an arXiv id at all gets a fixed title — otherwise /abs/<any
 * text> would be an unbounded set of indexable pages with a caller-chosen
 * title and a self-referential canonical.
 */

const SITE_URL = "https://arxivisual.org";
const DESCRIPTION_MAX = 160;
const MAX_AUTHOR_TAGS = 10; // collaboration papers list thousands of authors
const FETCH_TIMEOUT_MS = 3000;
// Titles and abstracts never change once processed; a paper that is still
// processing turns into a real one within minutes, hence a short window.
const REVALIDATE_SECONDS = 600;

// Mirrors the layout's openGraph/twitter blocks: page-level metadata
// replaces those objects wholesale (Next merges per top-level key), so the
// site/creator/locale/image fields have to be restated here.
const OG_IMAGE = { url: "/landing.jpeg", width: 1200, height: 630 };
const TWITTER_HANDLE = "@armaangupt0";

type PaperMeta = { title: string; abstract: string; authors: string[] };

async function fetchPaperMeta(arxivId: string): Promise<PaperMeta | null> {
  try {
    const res = await fetch(`${API_BASE}/api/paper/${encodeURIComponent(arxivId)}`, {
      next: { revalidate: REVALIDATE_SECONDS },
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      headers: { accept: "application/json" },
    });
    if (!res.ok) return null;
    const body: unknown = await res.json();
    if (typeof body !== "object" || body === null) return null;
    const data = body as Record<string, unknown>;
    if (typeof data.title !== "string" || !data.title.trim()) return null;
    return {
      title: data.title.replace(/\s+/g, " ").trim(),
      abstract: typeof data.abstract === "string" ? data.abstract : "",
      authors: Array.isArray(data.authors)
        ? data.authors.filter((a): a is string => typeof a === "string" && a.trim() !== "")
        : [],
    };
  } catch {
    return null;
  }
}

function truncate(text: string, max: number): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max - 1);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > max / 2 ? cut.slice(0, lastSpace) : cut).replace(/[,;:.]+$/, "")}…`;
}

function formatAuthors(authors: string[]): string {
  if (authors.length <= 3) return authors.join(", ");
  return `${authors.slice(0, 3).join(", ")} et al.`;
}

function socialCards(title: string, description: string, url: string, imageAlt: string): Metadata {
  return {
    openGraph: {
      type: "article",
      url,
      siteName: "arXivisual",
      locale: "en_US",
      title,
      description,
      images: [{ ...OG_IMAGE, alt: imageAlt }],
    },
    twitter: {
      card: "summary_large_image",
      site: TWITTER_HANDLE,
      creator: TWITTER_HANDLE,
      title,
      description,
      images: [OG_IMAGE.url],
    },
  };
}

export async function paperMetadata(rawId: string): Promise<Metadata> {
  if (!rawId || !isArxivId(rawId)) {
    // Not an arXiv id: never reflect the path into the title, never index.
    return {
      title: "Paper not found",
      description: "arXivisual visualizes arXiv papers; this address is not an arXiv identifier.",
      robots: { index: false, follow: false },
    };
  }

  // Every version of an id is the same page (the backend strips the suffix),
  // so all of them share one canonical URL and one cache entry.
  const arxivId = baseArxivId(rawId);
  const canonical = `${SITE_URL}/abs/${arxivId}`;

  const demo = getDemoPaper(arxivId);
  const paper: PaperMeta | null = demo
    ? { title: demo.title, abstract: demo.abstract, authors: demo.authors }
    : await fetchPaperMeta(arxivId);

  if (!paper) {
    // Unknown, stale, or unreachable: a paper-specific title so a shared link
    // still reads sensibly, but a soft 404 for search engines. The client
    // reader shows the "Start" flow for these.
    const title = `arXiv:${arxivId}`;
    const description = `Visualize arXiv paper ${arxivId} as an interactive scrollytelling explainer with AI-generated Manim animations.`;
    return {
      title,
      description,
      alternates: { canonical },
      robots: { index: false, follow: true },
      ...socialCards(`${title} · arXivisual`, description, canonical, "arXivisual — arXiv papers, visualized"),
    };
  }

  const fullTitle = `${paper.title} · arXivisual`;
  const description = truncate(
    paper.abstract ||
      `${paper.title}${paper.authors.length ? ` by ${formatAuthors(paper.authors)}` : ""}, visualized with AI-generated Manim animations.`,
    DESCRIPTION_MAX,
  );

  return {
    // The layout's `%s · arXivisual` template appends the site name.
    title: paper.title,
    description,
    alternates: { canonical },
    authors: paper.authors.slice(0, MAX_AUTHOR_TAGS).map((name) => ({ name })),
    ...socialCards(fullTitle, description, canonical, `${paper.title} — visualized on arXivisual`),
  };
}
