"use client";

import Link from "next/link";
import { useEffect, useState, useCallback, use } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { SectionViewer, type SectionModel } from "@/components/SectionViewer";
import { GlassCard } from "@/components/ui/glass-card";
import { MosaicBackground } from "@/components/ui/mosaic-background";
import { ShardField } from "@/components/ui/glass-shard";
import type { Paper, ProcessingStatus } from "@/lib/types";
import {
  getPaper,
  processArxivPaper,
  getProcessingStatus,
  toProcessingStatus,
} from "@/lib/api";

function normalizeArxivId(segments: string[] | undefined): string {
  if (!segments || segments.length === 0) return "";
  const joined = segments.join("/");
  try {
    return decodeURIComponent(joined);
  } catch {
    return joined;
  }
}

type PageState =
  | { type: "loading" }
  | { type: "not_found"; arxivId: string }
  | { type: "processing"; status: ProcessingStatus }
  | { type: "ready"; paper: Paper }
  | { type: "error"; message: string };

function clampLevel(level: number): 1 | 2 | 3 {
  if (level <= 1) return 1;
  if (level === 2) return 2;
  return 3;
}

export default function PaperPage({
  params,
}: {
  params: Promise<{ id?: string[] }>;
}) {
  const resolvedParams = use(params);
  const arxivId = normalizeArxivId(resolvedParams.id);
  const absUrl = arxivId ? `https://arxiv.org/abs/${arxivId}` : "https://arxiv.org";
  const pdfUrl = arxivId ? `https://arxiv.org/pdf/${arxivId}.pdf` : "https://arxiv.org";

  const [state, setState] = useState<PageState>({ type: "loading" });
  const [jobId, setJobId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"overview" | "reader">("overview");

  const loadPaper = useCallback(async () => {
    if (!arxivId) {
      setState({ type: "error", message: "No arXiv ID provided" });
      return;
    }

    try {
      const paper = await getPaper(arxivId);
      if (paper) {
        setState({ type: "ready", paper });
        return;
      }
      setState({ type: "not_found", arxivId });
    } catch (err) {
      console.error("Error loading paper:", err);
      setState({
        type: "error",
        message: err instanceof Error ? err.message : "Failed to load paper",
      });
    }
  }, [arxivId]);

  const startProcessing = useCallback(async () => {
    if (!arxivId) return;

    try {
      const response = await processArxivPaper(arxivId);
      setJobId(response.job_id);
      setState({
        type: "processing",
        status: {
          job_id: response.job_id,
          status: response.status,
          progress: 0,
          sections_completed: 0,
          sections_total: 0,
          current_step: "Starting...",
        },
      });
    } catch (err) {
      console.error("Error starting processing:", err);
      setState({
        type: "error",
        message: err instanceof Error ? err.message : "Failed to start processing",
      });
    }
  }, [arxivId]);

  useEffect(() => {
    if (state.type !== "processing" || !jobId) return;

    const pollInterval = setInterval(async () => {
      try {
        const response = await getProcessingStatus(jobId);
        const status = toProcessingStatus(response);

        if (response.status === "completed") {
          clearInterval(pollInterval);
          const paper = await getPaper(arxivId);
          if (paper) {
            setState({ type: "ready", paper });
          } else {
            setState({ type: "error", message: "Paper processing completed but paper not found" });
          }
        } else if (response.status === "failed") {
          clearInterval(pollInterval);
          setState({
            type: "error",
            message: response.error || "Processing failed",
          });
        } else {
          setState({ type: "processing", status });
        }
      } catch (err) {
        console.error("Error polling status:", err);
      }
    }, 2000);

    return () => clearInterval(pollInterval);
  }, [state.type, jobId, arxivId]);

  useEffect(() => {
    loadPaper();
  }, [loadPaper]);

  return (
    <main className="min-h-dvh relative overflow-hidden bg-black">
      <MosaicBackground />
      <ShardField />

      <div className="relative z-10">
        {/* Fixed Header */}
        <motion.header
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="sticky top-0 z-40 bg-black/80 backdrop-blur-2xl border-b border-white/[0.06]"
        >
          <div className="mx-auto w-full max-w-7xl px-6 py-4">
            <div className="flex items-center justify-between gap-4">
              <Link
                href="/"
                className="group inline-flex items-center gap-2 rounded-xl bg-white/[0.04] px-4 py-2.5 text-sm text-white/60 border border-white/[0.08] transition-all hover:bg-white/[0.07] hover:border-white/[0.12]"
              >
                <motion.span
                  aria-hidden
                  className="transition-transform group-hover:-translate-x-1 text-white/50"
                >
                  &larr;
                </motion.span>
                Back
              </Link>

              <div className="flex-1 flex items-center justify-center">
                <div className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-white/[0.04] border border-white/[0.08]">
                  <div className="w-2 h-2 rounded-full bg-white/30 animate-pulse" />
                  <span className="text-sm font-mono text-white/50">{arxivId || "Loading..."}</span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <motion.a
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  href={absUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-xl bg-white/[0.04] px-4 py-2.5 text-sm text-white/60 border border-white/[0.08] transition hover:bg-white/[0.07]"
                >
                  arXiv
                </motion.a>
                <motion.a
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  href={pdfUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-xl bg-white/[0.06] px-4 py-2.5 text-sm text-white/60 border border-white/[0.10] transition hover:bg-white/[0.09]"
                >
                  PDF
                </motion.a>
              </div>
            </div>
          </div>
        </motion.header>

        {/* Content based on state */}
        <div className="min-h-[calc(100dvh-80px)]">
          {state.type === "loading" && <LoadingState message="Loading paper..." />}

          {state.type === "not_found" && (
            <NotFoundState arxivId={state.arxivId} onProcess={startProcessing} />
          )}

          {state.type === "processing" && <ProcessingState status={state.status} />}

          {state.type === "error" && (
            <ErrorState message={state.message} onRetry={loadPaper} />
          )}

          {state.type === "ready" && (
            <AnimatePresence mode="wait">
              {viewMode === "overview" ? (
                <OverviewMode
                  key="overview"
                  paper={state.paper}
                  onStartReading={() => setViewMode("reader")}
                />
              ) : (
                <ReaderMode
                  key="reader"
                  paper={state.paper}
                  onBack={() => setViewMode("overview")}
                />
              )}
            </AnimatePresence>
          )}
        </div>
      </div>
    </main>
  );
}

// === Overview Mode ===
function OverviewMode({
  paper,
  onStartReading,
}: {
  paper: Paper;
  onStartReading: () => void;
}) {
  const sectionsWithVideo = paper.sections.filter((s) => s.video_url);
  const totalEquations = paper.sections.reduce(
    (acc, s) => acc + (s.equations?.length || 0),
    0
  );

  const stats = [
    {
      title: "Sections",
      description: `${paper.sections.length} sections to explore`,
      icon: <span className="text-2xl text-white/50">&sect;</span>,
    },
    {
      title: "Visualizations",
      description: `${sectionsWithVideo.length} animated explanations`,
      icon: <span className="text-2xl text-white/50">&#9654;</span>,
    },
    {
      title: "Equations",
      description: `${totalEquations} mathematical expressions`,
      icon: <span className="text-2xl text-white/50">&sum;</span>,
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.5 }}
      className="px-6 py-12"
    >
      <div className="max-w-6xl mx-auto space-y-12">
        {/* Hero section */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="text-center space-y-6"
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/[0.04] border border-white/[0.08]">
            <span className="w-2 h-2 rounded-full bg-white/30" />
            <span className="text-sm text-white/50">Research Paper</span>
          </div>

          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-medium text-white/90 leading-tight tracking-tight max-w-4xl mx-auto">
            {paper.title}
          </h1>

          <p className="text-white/40 max-w-2xl mx-auto">
            {paper.authors.slice(0, 5).join(", ")}
            {paper.authors.length > 5 && ", et al."}
          </p>

          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={onStartReading}
            className="mt-4 inline-flex items-center gap-3 px-8 py-4 rounded-2xl bg-white/[0.08] hover:bg-white/[0.12] text-white font-medium border border-white/[0.15] hover:border-white/[0.25] backdrop-blur-xl shadow-xl shadow-white/[0.03] transition-all duration-300"
          >
            Start Reading
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </motion.button>
        </motion.div>

        {/* Stats cards */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="grid grid-cols-1 md:grid-cols-3 gap-4"
        >
          {stats.map((stat, i) => (
            <GlassCard key={i} delay={0.2 + i * 0.1} className="p-6">
              <div className="flex items-start gap-4">
                <div className="h-10 w-10 rounded-xl bg-white/[0.06] border border-white/[0.08] flex items-center justify-center">
                  {stat.icon}
                </div>
                <div>
                  <h4 className="text-white/90 font-medium">{stat.title}</h4>
                  <p className="mt-1 text-sm text-white/40">{stat.description}</p>
                </div>
              </div>
            </GlassCard>
          ))}
        </motion.div>

        {/* Abstract section */}
        <GlassCard delay={0.3} className="p-8">
          <h2 className="text-lg font-medium text-white/80 mb-4 flex items-center gap-3">
            <span className="w-8 h-8 rounded-lg bg-white/[0.06] border border-white/[0.08] flex items-center justify-center text-white/40">
              &there4;
            </span>
            Abstract
          </h2>
          <p className="text-white/50 leading-relaxed text-lg">
            {paper.abstract}
          </p>
        </GlassCard>

        {/* Table of contents */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          <h2 className="text-lg font-medium text-white/80 mb-6 flex items-center gap-3">
            <span className="w-8 h-8 rounded-lg bg-white/[0.06] border border-white/[0.08] flex items-center justify-center text-white/40">
              &equiv;
            </span>
            Table of Contents
          </h2>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {[...paper.sections]
              .sort((a, b) => a.order_index - b.order_index)
              .map((section, idx) => (
                <motion.button
                  key={section.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.4 + idx * 0.05 }}
                  onClick={onStartReading}
                  className="group relative text-left p-4 rounded-xl bg-white/[0.03] border border-white/[0.06] hover:border-white/[0.12] hover:bg-white/[0.05] transition-all duration-200"
                >
                  <div className="flex items-start gap-3">
                    <span className="w-7 h-7 rounded-lg bg-white/[0.06] border border-white/[0.08] flex items-center justify-center text-sm font-semibold text-white/50 shrink-0">
                      {idx + 1}
                    </span>
                    <div className="min-w-0">
                      <h3 className="font-medium text-white/60 group-hover:text-white/80 transition-colors truncate">
                        {section.title}
                      </h3>
                      <div className="mt-1 flex items-center gap-2 text-xs text-white/25">
                        {section.video_url && (
                          <span className="flex items-center gap-1 text-white/40">
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                              <path d="M8 5v14l11-7z" />
                            </svg>
                            Video
                          </span>
                        )}
                        {section.equations && section.equations.length > 0 && (
                          <span>{section.equations.length} equations</span>
                        )}
                      </div>
                    </div>
                  </div>
                </motion.button>
              ))}
          </div>
        </motion.div>

        {/* Quick start CTA */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="text-center py-8"
        >
          <GlassCard className="inline-flex flex-col items-center gap-4 p-8">
            <div className="text-4xl text-white/30" style={{ clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)" }}>
              <div className="w-12 h-12 bg-white/[0.06] border border-white/[0.10]" />
            </div>
            <h3 className="text-xl font-medium text-white/80">Ready to dive in?</h3>
            <p className="text-white/40 max-w-md">
              Navigate through sections seamlessly with our interactive reader, complete with visualizations and equations.
            </p>
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={onStartReading}
              className="mt-2 px-6 py-3 rounded-xl bg-white/[0.06] text-white/80 font-medium border border-white/[0.10] hover:bg-white/[0.10] transition-all"
            >
              Begin Reading Experience
            </motion.button>
          </GlassCard>
        </motion.div>
      </div>
    </motion.div>
  );
}

// === Reader Mode ===
function ReaderMode({
  paper,
  onBack,
}: {
  paper: Paper;
  onBack: () => void;
}) {
  const sections: SectionModel[] = [...paper.sections]
    .sort((a, b) => a.order_index - b.order_index)
    .map((s) => ({
      id: s.id,
      title: s.title,
      content: s.summary || s.content,
      level: clampLevel(s.level),
      equations: s.equations,
      videoUrl: s.video_url,
    }));

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
    >
      {/* Back to overview button */}
      <div className="sticky top-[73px] z-30 bg-black/80 backdrop-blur-2xl border-b border-white/[0.04]">
        <div className="max-w-6xl mx-auto px-6 py-2 flex items-center justify-between">
          <button
            onClick={onBack}
            className="group flex items-center gap-2 text-sm text-white/40 hover:text-white/70 transition-colors"
          >
            <svg
              className="w-4 h-4 group-hover:-translate-x-1 transition-transform"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Back to Overview
          </button>
          <h2 className="text-sm font-medium text-white/50 truncate max-w-md">
            {paper.title}
          </h2>
        </div>
      </div>

      <SectionViewer sections={sections} />
    </motion.div>
  );
}

// === State Components ===

function LoadingState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-32 px-6">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        className="relative"
      >
        <div className="h-20 w-20 rounded-2xl bg-white/[0.05] border border-white/[0.10] backdrop-blur-xl" />
        <div className="absolute inset-0 h-20 w-20 animate-spin rounded-2xl border-2 border-transparent border-t-white/30" style={{ animationDuration: '2s' }} />
      </motion.div>
      <motion.p
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mt-8 text-white/40"
      >
        {message}
      </motion.p>
    </div>
  );
}

function NotFoundState({
  arxivId,
  onProcess,
}: {
  arxivId: string;
  onProcess: () => void;
}) {
  return (
    <div className="flex items-center justify-center py-20 px-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-lg text-center"
      >
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ delay: 0.2, type: "spring", stiffness: 200 }}
          className="mx-auto h-24 w-24 grid place-items-center"
          style={{ clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)" }}
        >
          <div className="w-full h-full bg-white/[0.05] border border-white/[0.10] grid place-items-center">
            <span className="text-3xl text-white/40">&int;</span>
          </div>
        </motion.div>

        <h2 className="mt-8 text-2xl font-medium text-white/80">Paper Not Yet Processed</h2>
        <p className="mt-4 text-white/40 leading-relaxed">
          This paper (<span className="font-mono text-white/60 bg-white/[0.06] px-2 py-0.5 rounded">{arxivId}</span>) hasn&apos;t been visualized yet.
          We&apos;ll parse the content and generate Manim animations for key concepts.
        </p>

        <div className="mt-8 space-y-4">
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={onProcess}
            className="w-full sm:w-auto rounded-2xl bg-white/[0.08] hover:bg-white/[0.12] px-8 py-4 text-sm font-medium text-white border border-white/[0.15] hover:border-white/[0.25] shadow-xl shadow-white/[0.03] transition-all duration-300"
          >
            Start Processing
          </motion.button>

          <p className="text-xs text-white/20">
            This usually takes 1-3 minutes depending on paper length
          </p>
        </div>
      </motion.div>
    </div>
  );
}

function ProcessingState({ status }: { status: ProcessingStatus }) {
  const progressPercent = Math.round(status.progress * 100);

  const steps = [
    { label: "Fetching paper from arXiv", threshold: 10, icon: "\u222B" },
    { label: "Parsing sections and content", threshold: 30, icon: "\u2202" },
    { label: "Analyzing concepts for visualization", threshold: 50, icon: "\u2207" },
    { label: "Generating Manim animations", threshold: 70, icon: "\u03BB" },
    { label: "Rendering videos", threshold: 90, icon: "\u221E" },
  ];

  return (
    <div className="flex items-center justify-center py-16 px-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-2xl"
      >
        <GlassCard animate={false} className="p-8">
          {/* Header */}
          <div className="flex items-center gap-5">
            <div className="relative">
              <div className="h-16 w-16 rounded-2xl bg-white/[0.05] border border-white/[0.10]" />
              <div className="absolute inset-0 h-16 w-16 animate-spin rounded-2xl border-2 border-transparent border-t-white/30" style={{ animationDuration: '2s' }} />
            </div>
            <div>
              <h2 className="text-2xl font-medium text-white/90">Processing Paper</h2>
              <p className="mt-1 text-white/40">{status.current_step || "Preparing..."}</p>
            </div>
          </div>

          {/* Progress */}
          <div className="mt-8">
            <div className="flex items-center justify-between text-sm mb-3">
              <span className="text-white/30">Overall Progress</span>
              <span className="font-mono text-white/80 font-medium">{progressPercent}%</span>
            </div>
            <div className="h-3 rounded-full bg-white/[0.05] overflow-hidden border border-white/[0.06]">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-white/40 to-white/20"
                initial={{ width: 0 }}
                animate={{ width: `${progressPercent}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
          </div>

          {/* Sections */}
          {status.sections_total > 0 && (
            <div className="mt-4 flex items-center gap-3 text-sm">
              <span className="text-white/30">Sections processed:</span>
              <span className="font-mono text-white/60 bg-white/[0.06] px-2 py-0.5 rounded">
                {status.sections_completed} / {status.sections_total}
              </span>
            </div>
          )}

          {/* Steps */}
          <div className="mt-8 rounded-2xl bg-white/[0.03] p-6 border border-white/[0.06]">
            <div className="text-xs font-medium text-white/25 uppercase tracking-wider mb-4">Pipeline Progress</div>
            <ol className="space-y-3">
              {steps.map((step, i) => {
                const isActive = progressPercent >= step.threshold;
                const isCurrent = progressPercent >= step.threshold && (i === steps.length - 1 || progressPercent < steps[i + 1].threshold);

                return (
                  <motion.li
                    key={i}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.1 }}
                    className="flex items-center gap-4"
                  >
                    <span className={`text-xl transition-all duration-300 ${isActive ? 'text-white/50' : 'text-white/15'}`}>
                      {step.icon}
                    </span>
                    <span className={`flex-1 text-sm transition-colors duration-300 ${isActive ? 'text-white/60' : 'text-white/20'}`}>
                      {step.label}
                    </span>
                    {isCurrent && (
                      <span className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-white/40 animate-pulse" />
                        <span className="text-xs text-white/40">In progress</span>
                      </span>
                    )}
                    {isActive && !isCurrent && (
                      <span className="text-white/50">&check;</span>
                    )}
                  </motion.li>
                );
              })}
            </ol>
          </div>
        </GlassCard>
      </motion.div>
    </div>
  );
}

function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex items-center justify-center py-20 px-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-lg text-center"
      >
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 200 }}
          className="mx-auto h-24 w-24 rounded-3xl bg-white/[0.04] border border-[#f27066]/20 grid place-items-center"
        >
          <span className="text-4xl text-[#f27066]">!</span>
        </motion.div>

        <h2 className="mt-8 text-2xl font-medium text-[#f27066]">Something Went Wrong</h2>
        <p className="mt-4 text-white/40 leading-relaxed">{message}</p>

        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={onRetry}
          className="mt-8 rounded-2xl bg-white/[0.06] px-8 py-4 text-sm font-medium text-white/80 border border-white/[0.10] transition hover:bg-white/[0.10]"
        >
          Try Again
        </motion.button>
      </motion.div>
    </div>
  );
}
