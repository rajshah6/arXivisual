"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { MosaicBackground } from "@/components/ui/mosaic-background";
import { ShardField } from "@/components/ui/glass-shard";
import { GlassCard } from "@/components/ui/glass-card";
import { CardSkeleton } from "@/components/LoadingState";
import { listPapers } from "@/lib/api";
import type { PaperSummary } from "@/lib/types";

type ExploreState =
  | { type: "loading" }
  | { type: "empty" }
  | { type: "ready"; papers: PaperSummary[] }
  | { type: "error"; message: string };

function formatAuthors(authors: string[]): string {
  if (!authors || authors.length === 0) return "Unknown authors";
  if (authors.length <= 3) return authors.join(", ");
  return `${authors.slice(0, 3).join(", ")}, et al.`;
}

function formatDate(iso: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function ExplorePage() {
  const [state, setState] = useState<ExploreState>({ type: "loading" });

  // setState only happens in the fetch's async callbacks, so the mount effect
  // never sets state synchronously (initial state is already "loading").
  const load = useCallback(() => {
    listPapers()
      .then((papers) => {
        if (papers.length === 0) {
          setState({ type: "empty" });
          return;
        }
        setState({ type: "ready", papers });
      })
      .catch((err: unknown) => {
        console.error("Error loading papers:", err);
        setState({
          type: "error",
          message: err instanceof Error ? err.message : "Failed to load papers",
        });
      });
  }, []);

  // Retry from the error card: show the skeleton grid again, then refetch.
  const retry = useCallback(() => {
    setState({ type: "loading" });
    load();
  }, [load]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <main className="min-h-dvh relative overflow-hidden bg-black">
      {/* Mosaic background + floating shards — same ambient treatment as home */}
      <MosaicBackground />
      <ShardField />

      {/* Back to home — floating glass pill, top-left (matches reader) */}
      <motion.div
        initial={{ opacity: 0, x: -10 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.4 }}
        className="fixed top-5 left-5 z-50"
      >
        <Link
          href="/"
          className="group inline-flex items-center gap-2 rounded-full bg-black/60 backdrop-blur-xl px-4 py-2.5 text-sm text-white/50 border border-white/[0.08] transition-all hover:bg-black/80 hover:text-white/80 hover:border-white/[0.15] shadow-lg shadow-black/30"
        >
          <span className="transition-transform group-hover:-translate-x-0.5">&larr;</span>
          <span className="hidden sm:inline">Back</span>
        </Link>
      </motion.div>

      <div className="relative z-10 mx-auto w-full max-w-6xl px-6 pb-24 pt-24 sm:pt-28">
        {/* Header */}
        <motion.header
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="mb-12 text-center"
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/[0.04] border border-white/[0.08]">
            <span className="w-2 h-2 rounded-full bg-white/30" />
            <span className="text-sm text-white/50">The Library</span>
          </div>
          <h1 className="mt-6 text-3xl sm:text-4xl lg:text-5xl font-medium text-white/90 leading-tight tracking-tight">
            Explore Visualized Papers
          </h1>
          <p className="mt-4 text-white/40 max-w-xl mx-auto leading-relaxed font-light">
            Browse papers that have already been turned into{" "}
            <span className="text-white/60 font-medium">visual</span> scrollytelling
            explanations. Pick one to dive in.
          </p>
        </motion.header>

        {/* Content states */}
        {state.type === "loading" && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        )}

        {state.type === "error" && (
          <ExploreMessage
            title="Couldn't load the library"
            body={state.message}
            action={
              <button
                onClick={retry}
                className="rounded-2xl bg-white/[0.06] px-8 py-4 text-sm font-medium text-white/80 border border-white/[0.10] transition hover:bg-white/[0.10]"
              >
                Try Again
              </button>
            }
            accent="error"
          />
        )}

        {state.type === "empty" && (
          <ExploreMessage
            title="No papers yet"
            body="Nothing has been visualized so far. Be the first — paste an arXiv paper and watch it come to life."
            action={
              <Link
                href="/"
                className="rounded-2xl bg-white/[0.08] hover:bg-white/[0.12] px-8 py-4 text-sm font-medium text-white border border-white/[0.15] hover:border-white/[0.25] transition-all"
              >
                Visualize a paper
              </Link>
            }
          />
        )}

        {state.type === "ready" && (
          <>
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4 }}
              className="mb-6 text-sm text-white/30"
            >
              {state.papers.length}{" "}
              {state.papers.length === 1 ? "paper" : "papers"} visualized
            </motion.p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {state.papers.map((paper, i) => (
                <PaperCard key={paper.paper_id} paper={paper} index={i} />
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  );
}

function PaperCard({ paper, index }: { paper: PaperSummary; index: number }) {
  const date = formatDate(paper.processed_at);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: Math.min(index * 0.05, 0.4), ease: "easeOut" }}
    >
      <Link
        href={`/abs/${encodeURIComponent(paper.paper_id)}`}
        className="block h-full"
      >
        <GlassCard animate={false} className="h-full p-6 flex flex-col">
          {/* Top row: viz badge + arxiv id */}
          <div className="flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.06] border border-white/[0.08] px-3 py-1 text-xs text-white/50">
              <span className="text-white/40">&#9671;</span>
              {paper.visualization_count}{" "}
              {paper.visualization_count === 1 ? "visual" : "visuals"}
            </span>
            <span className="font-mono text-xs text-white/25">{paper.paper_id}</span>
          </div>

          {/* Title */}
          <h2 className="mt-5 text-lg font-medium text-white/90 leading-snug tracking-tight line-clamp-3 transition-colors group-hover:text-white">
            {paper.title}
          </h2>

          {/* Authors */}
          <p className="mt-3 text-sm text-white/40 line-clamp-2">
            {formatAuthors(paper.authors)}
          </p>

          {/* Footer */}
          <div className="mt-auto pt-6 flex items-center justify-between text-xs">
            {date ? (
              <span className="text-white/25">{date}</span>
            ) : (
              <span />
            )}
            <span className="inline-flex items-center gap-1 text-white/40 transition-colors group-hover:text-white/70">
              Read
              <span className="transition-transform group-hover:translate-x-0.5">&rarr;</span>
            </span>
          </div>
        </GlassCard>
      </Link>
    </motion.div>
  );
}

function ExploreMessage({
  title,
  body,
  action,
  accent,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
  accent?: "error";
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mx-auto max-w-lg text-center py-16"
    >
      <div className="rounded-2xl bg-white/[0.04] border border-white/[0.08] p-8 backdrop-blur-sm">
        <h2
          className={`text-2xl font-medium ${
            accent === "error" ? "text-[#f27066]" : "text-white/90"
          }`}
        >
          {title}
        </h2>
        <p className="mt-4 text-white/40 leading-relaxed">{body}</p>
        {action && <div className="mt-8 flex justify-center">{action}</div>}
      </div>
    </motion.div>
  );
}
