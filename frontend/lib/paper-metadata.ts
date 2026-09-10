import "server-only";

import type { Metadata } from "next";
import { API_BASE } from "./api";

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
 */

const SITE_URL = "https://arxivisual.org";
const DESCRIPTION_MAX = 160;
const FETCH_TIMEOUT_MS = 3000;
// Titles and abstracts never change once processed; a paper that is still
// processing turns into a real one within minutes, hence a short window.
const REVALIDATE_SECONDS = 600;

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

export async function paperMetadata(arxivId: string): Promise<Metadata> {
  if (!arxivId) return {};

  const canonical = `${SITE_URL}/abs/${arxivId}`;
  const paper = await fetchPaperMeta(arxivId);

  if (!paper) {
    // Unknown, stale, or unreachable: a generic but still paper-specific
    // title. The client reader shows the "Start" flow for these.
    return {
      title: `arXiv:${arxivId}`,
      description: `Visualize arXiv paper ${arxivId} as an interactive scrollytelling explainer with AI-generated Manim animations.`,
      alternates: { canonical },
    };
  }

  const title = `${paper.title} · arXivisual`;
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
    authors: paper.authors.map((name) => ({ name })),
    openGraph: {
      type: "article",
      url: canonical,
      siteName: "arXivisual",
      title,
      description,
      images: [
        {
          url: "/landing.jpeg",
          width: 1200,
          height: 630,
          alt: `${paper.title} — visualized on arXivisual`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: ["/landing.jpeg"],
    },
  };
}
