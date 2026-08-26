"use client";

import Link from "next/link";
import { useEffect, useState, useCallback, useMemo, useRef, use } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CardStack } from "@/components/CardStack";
import type { ScrollySectionModel } from "@/components/ScrollySection";
import { GlassCard } from "@/components/ui/glass-card";
import { MosaicBackground } from "@/components/ui/mosaic-background";
import { ShardField } from "@/components/ui/glass-shard";
import type { Paper, ProcessingStatus } from "@/lib/types";
import { DEMO_PAPER_IDS, getDemoPaper } from "@/lib/mock-data";
import {
  getPaper,
  processArxivPaper,
  getProcessingStatus,
  toProcessingStatus,
} from "@/lib/api";

// --- Demo simulation config ---
const DEMO_DURATION_MS = 5000;
const DEMO_TICK_MS = 50;
const DEMO_STEPS = [
  { label: "Fetching paper from arXiv", at: 0 },
  { label: "Parsing sections and equations", at: 0.2 },
  { label: "Analyzing concepts for visualization", at: 0.4 },
  { label: "Generating animations", at: 0.6 },
  { label: "Rendering videos", at: 0.8 },
];

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
  // paperPreview: once the backend has stored the paper text (~30% progress),
  // we show the real reader immediately and let videos pop in as they render.
  | { type: "processing"; status: ProcessingStatus; paperPreview?: Paper | null }
  | { type: "ready"; paper: Paper; notice?: string }
  | { type: "error"; message: string };

/**
 * Completion notifier: a ding + (when the tab is hidden) a browser notification
 * and a title flash, so people can safely tab away during the 3-5 minute wait.
 * Everything is gated behind an explicit button click — the click both resumes
 * the AudioContext (autoplay policy) and triggers the permission prompt.
 */
function useCompletionNotifier() {
  const [enabled, setEnabled] = useState(false);
  const audioCtxRef = useRef<AudioContext | null>(null);

  const enable = useCallback(async () => {
    try {
      audioCtxRef.current = audioCtxRef.current ?? new AudioContext();
      await audioCtxRef.current.resume();
    } catch {
      // no audio — notification/title flash still work
    }
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      try {
        await Notification.requestPermission();
      } catch {
        // denied or unsupported — the ding still works
      }
    }
    setEnabled(true);
  }, []);

  const fire = useCallback(
    (title: string, body: string) => {
      if (!enabled) return;
      const ctx = audioCtxRef.current;
      if (ctx) {
        try {
          // Two-note "ding": E6 then B5, short and gentle.
          [[1318.5, 0], [987.8, 0.18]].forEach(([freq, delay]) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "sine";
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0.0001, ctx.currentTime + delay);
            gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + delay + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + delay + 0.5);
            osc.connect(gain).connect(ctx.destination);
            osc.start(ctx.currentTime + delay);
            osc.stop(ctx.currentTime + delay + 0.55);
          });
        } catch {
          // audio failed — continue with the visual channels
        }
      }
      if (document.hidden) {
        if (typeof Notification !== "undefined" && Notification.permission === "granted") {
          try {
            new Notification(title, { body });
          } catch {
            // notification failed — title flash below still signals
          }
        }
        const originalTitle = document.title;
        document.title = `✅ ${title}`;
        const restore = () => {
          document.title = originalTitle;
          document.removeEventListener("visibilitychange", restore);
        };
        document.addEventListener("visibilitychange", restore);
      }
    },
    [enabled]
  );

  // Stable identity so consumers can use the notifier in effect deps without
  // tearing the effect down on every render.
  return useMemo(() => ({ enabled, enable, fire }), [enabled, enable, fire]);
}

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

  const [state, setState] = useState<PageState>({ type: "loading" });
  const [jobId, setJobId] = useState<string | null>(null);
  const [scrollProgress, setScrollProgress] = useState(0);
  const [startingJob, setStartingJob] = useState(false);
  const demoSimRunning = useRef(false);
  // Live paper preview while processing (sections appear at ~30% progress,
  // videos pop in during the render phase). Ref, not state: the poll effect's
  // closure would otherwise go stale between status ticks.
  const previewRef = useRef<Paper | null>(null);
  const pollTickRef = useRef(0);
  const notifier = useCompletionNotifier();

  // Staged entrance:
  // 0.0s–0.7s  → pure black
  // 0.7s       → background + arXiv logo + shards fade in
  // 2.2s       → UI fades in over 0.6s, loadPaper fires
  //              (logo visible alone for 1.5s: 0.7→2.2)
  const [bgVisible, setBgVisible] = useState(false);
  const [bgReady, setBgReady] = useState(false);
  useEffect(() => {
    const t1 = setTimeout(() => setBgVisible(true), 700);
    const t2 = setTimeout(() => setBgReady(true), 2200);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);

  const loadPaper = useCallback(async () => {
    if (!arxivId) {
      setState({ type: "error", message: "No arXiv ID provided" });
      return;
    }

    // Demo paper: run simulated 5-second processing
    if (DEMO_PAPER_IDS.has(arxivId)) {
      const demoData = getDemoPaper(arxivId);
      const sectionCount = demoData?.sections.length ?? 5;
      demoSimRunning.current = true;
      setState({
        type: "processing",
        status: {
          job_id: "demo",
          status: "processing",
          progress: 0,
          sections_completed: 0,
          sections_total: sectionCount,
          current_step: DEMO_STEPS[0].label,
        },
      });
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
    if (!arxivId || startingJob) return;
    setStartingJob(true);

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
    } finally {
      setStartingJob(false);
    }
  }, [arxivId, startingJob]);

  // Derived before the effect so it can sit in the dependency array
  // (state.status only exists on the "processing" variant).
  const demoSectionsTotal =
    state.type === "processing" ? state.status.sections_total : 0;

  // Demo simulation: animate progress 0→100% over 5 seconds
  useEffect(() => {
    if (state.type !== "processing" || !demoSimRunning.current) return;

    const totalSections = demoSectionsTotal;
    const startTime = Date.now();
    const timer = setInterval(async () => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / DEMO_DURATION_MS, 1);

      // Find current step label
      let currentStep = DEMO_STEPS[0].label;
      for (const step of DEMO_STEPS) {
        if (progress >= step.at) currentStep = step.label;
      }

      if (progress >= 1) {
        clearInterval(timer);
        // Show 100% with all steps "Done" for 800ms before transitioning
        setState({
          type: "processing",
          status: {
            job_id: "demo",
            status: "processing",
            progress: 1,
            sections_completed: totalSections,
            sections_total: totalSections,
            current_step: "Complete",
          },
        });
        setTimeout(async () => {
          demoSimRunning.current = false;
          const paper = await getPaper(arxivId);
          if (paper) {
            setState({ type: "ready", paper });
          }
        }, 800);
        return;
      }

      setState({
        type: "processing",
        status: {
          job_id: "demo",
          status: "processing",
          progress,
          sections_completed: Math.floor(progress * totalSections),
          sections_total: totalSections,
          current_step: currentStep,
        },
      });
    }, DEMO_TICK_MS);

    return () => {
      clearInterval(timer);
      demoSimRunning.current = false;
    };
  }, [state.type, demoSectionsTotal, arxivId]);

  // Real API polling (non-demo papers)
  useEffect(() => {
    if (state.type !== "processing" || !jobId || demoSimRunning.current) return;

    const pollInterval = setInterval(async () => {
      try {
        const response = await getProcessingStatus(jobId);
        const status = toProcessingStatus(response);

        if (response.status === "completed") {
          clearInterval(pollInterval);
          const paper = await getPaper(arxivId);
          if (paper) {
            notifier.fire("Your paper is ready", "The visualizations finished rendering — come take a look.");
            setState({ type: "ready", paper });
          } else {
            setState({ type: "error", message: "Paper processing completed but paper not found" });
          }
        } else if (response.status === "failed") {
          clearInterval(pollInterval);
          // The paper text often survives a failed pipeline (e.g. all renders
          // failed) — show what exists instead of a dead end.
          const paper = await getPaper(arxivId).catch(() => null);
          if (paper) {
            notifier.fire("Paper processed with problems", "The text is readable, but some visualizations failed.");
            setState({
              type: "ready",
              paper,
              notice:
                response.error ||
                "Some visualizations failed to render. The paper text is available below.",
            });
          } else {
            notifier.fire("Processing failed", response.error || "The paper could not be processed.");
            setState({ type: "error", message: response.error || "Processing failed" });
          }
        } else {
          // Progressive reading: once the backend has stored the paper text
          // (~30% progress), fetch it so the reader renders immediately.
          // During the render phase, refetch every other tick (~4s) so each
          // finished video pops into its section live.
          pollTickRef.current += 1;
          const shouldFetchPreview =
            response.progress >= 0.3 &&
            (previewRef.current === null ||
              (response.progress >= 0.75 && pollTickRef.current % 2 === 0));
          if (shouldFetchPreview) {
            const preview = await getPaper(arxivId).catch(() => null);
            if (preview) previewRef.current = preview;
          }
          setState({ type: "processing", status, paperPreview: previewRef.current });
        }
      } catch (err) {
        console.error("Error polling status:", err);
      }
    }, 2000);

    return () => clearInterval(pollInterval);
  }, [state.type, jobId, arxivId, notifier]);

  // Don't start loading until the background has had its moment
  useEffect(() => {
    if (bgReady) loadPaper();
  }, [bgReady, loadPaper]);

  // Refetch while sections still lack videos (late renders trickle in). Keeps
  // polling until EVERY section has its video or the retry budget runs out —
  // the old `some()` stop condition abandoned all but the first-arriving video.
  const missingVideoCount =
    state.type === "ready"
      ? state.paper.sections.filter((s) => !s.video_url).length
      : 0;
  useEffect(() => {
    if (missingVideoCount === 0 || !arxivId) return;
    let retries = 0;
    const maxRetries = 12; // ~2 min
    const refetchInterval = setInterval(async () => {
      retries++;
      if (retries > maxRetries) return clearInterval(refetchInterval);
      const paper = await getPaper(arxivId).catch(() => null);
      if (!paper) return;
      const stillMissing = paper.sections.filter((s) => !s.video_url).length;
      if (stillMissing < missingVideoCount) {
        setState((prev) => ({
          type: "ready",
          paper,
          notice: prev.type === "ready" ? prev.notice : undefined,
        }));
        // missingVideoCount changes -> effect re-runs with a fresh budget,
        // or stops naturally when stillMissing reaches 0.
        clearInterval(refetchInterval);
      }
    }, 10000);
    return () => clearInterval(refetchInterval);
  }, [missingVideoCount, arxivId]);

  const onProgressChange = useCallback((progress: number) => {
    setScrollProgress(progress);
  }, []);

  return (
    <main className="min-h-dvh relative bg-black">
      {/* Background — fades in after 0.7s black */}
      <AnimatePresence>
        {bgVisible && (
          <motion.div
            key="background"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="fixed inset-0 z-0 overflow-hidden"
          >
            <MosaicBackground showLogo logoYFraction={0.28} />
            <ShardField />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Foreground UI — fades in 1.5s after logo appears */}
      <AnimatePresence>
        {bgReady && (
          <motion.div
            key="foreground"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6 }}
            className="relative z-10"
          >
            {/* Minimal progress bar — fixed at top, no nav chrome */}
            {state.type === "ready" && (
              <div className="fixed top-0 left-0 right-0 z-50 h-[3px] bg-white/[0.03]">
                <motion.div
                  className="h-full bg-gradient-to-r from-white/50 to-white/25"
                  animate={{ width: `${scrollProgress * 100}%` }}
                  transition={{ duration: 0.3, ease: "easeOut" }}
                />
              </div>
            )}

            {/* Floating back button — minimal, top-left */}
            <motion.div
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.4, delay: 0.2 }}
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

            {/* Content based on state */}
            <div className="min-h-dvh">
              {state.type === "loading" && <LoadingState message="Loading paper..." />}

              {state.type === "not_found" && (
                <NotFoundState
                  arxivId={state.arxivId}
                  onProcess={startProcessing}
                  starting={startingJob}
                />
              )}

              {state.type === "processing" && !state.paperPreview && (
                <ProcessingState status={state.status} notifier={notifier} />
              )}

              {/* Progressive reading: paper text is in the DB — show the real
                  reader now; videos pop into their sections as renders finish. */}
              {state.type === "processing" && state.paperPreview && (
                <>
                  <ReadyState
                    paper={state.paperPreview}
                    absUrl={absUrl}
                    onProgressChange={onProgressChange}
                  />
                  <ProcessingPill status={state.status} notifier={notifier} />
                </>
              )}

              {state.type === "error" && (
                <ErrorState message={state.message} onRetry={loadPaper} />
              )}

              {state.type === "ready" && (
                <>
                  {state.notice && <NoticeBanner notice={state.notice} />}
                  <ReadyState
                    paper={state.paper}
                    absUrl={absUrl}
                    onProgressChange={onProgressChange}
                  />
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}

// === Scrollytelling Ready State ===
function ReadyState({
  paper,
  absUrl,
  onProgressChange,
}: {
  paper: Paper;
  absUrl: string;
  onProgressChange: (progress: number) => void;
}) {
  const scrollySections: ScrollySectionModel[] = [...paper.sections]
    .sort((a, b) => a.order_index - b.order_index)
    .map((s) => ({
      id: s.id,
      title: s.title,
      content: s.summary || s.content,
      level: clampLevel(s.level),
      equations: s.equations,
      videoUrl: s.video_url,
    }));

  const heroContent = (
    <div className="mb-12">
      {/* Hero section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="space-y-6 pt-8 pb-8"
      >
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/[0.04] border border-white/[0.08]">
          <span className="w-2 h-2 rounded-full bg-white/30" />
          <span className="text-sm text-white/50">Research Paper</span>
        </div>

        <h1 className="text-3xl sm:text-4xl lg:text-5xl font-medium text-white/90 leading-tight tracking-tight">
          {paper.title}
        </h1>

        <p className="text-white/40 max-w-2xl">
          {paper.authors.slice(0, 5).join(", ")}
          {paper.authors.length > 5 && ", et al."}
        </p>
      </motion.div>

      {/* Abstract */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.15 }}
      >
        <div className="rounded-2xl bg-white/[0.04] p-6 sm:p-8 border border-white/[0.08] backdrop-blur-sm">
          <h2 className="text-lg font-medium text-white/80 mb-4 flex items-center gap-3">
            <span className="w-8 h-8 rounded-lg bg-white/[0.06] border border-white/[0.08] flex items-center justify-center text-white/40">
              &there4;
            </span>
            Abstract
          </h2>
          <p className="text-white/50 leading-relaxed text-base sm:text-lg">
            {paper.abstract}
          </p>
        </div>
      </motion.div>

      {/* Scroll hint */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.6 }}
        className="mt-8 flex flex-col items-center gap-2 text-white/25"
      >
        <span className="text-xs tracking-wider uppercase">Scroll to begin reading</span>
        <motion.svg
          animate={{ y: [0, 6, 0] }}
          transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          className="w-5 h-5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
        </motion.svg>
      </motion.div>

      {/* Divider before sections */}
      <div className="mt-10 h-px bg-gradient-to-r from-transparent via-white/[0.08] to-transparent" />
    </div>
  );

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="px-6 py-8"
    >
      <div className="max-w-6xl mx-auto">
        <CardStack
          sections={scrollySections}
          heroContent={heroContent}
          onProgressChange={onProgressChange}
        />

        {/* Footer links */}
        <div className="mt-8 mb-16 flex items-center justify-center gap-4 text-sm">
          <a
            href={absUrl}
            target="_blank"
            rel="noreferrer"
            className="text-white/30 hover:text-white/60 transition-colors"
          >
            View on arXiv
          </a>
          <span className="w-1 h-1 rounded-full bg-white/20" />
          <Link href="/" className="text-white/30 hover:text-white/60 transition-colors">
            Explore another paper
          </Link>
        </div>
      </div>
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
  starting,
}: {
  arxivId: string;
  onProcess: () => void;
  starting: boolean;
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

        <div className="mt-8 rounded-2xl bg-black/90 border border-white/10 p-6 sm:p-8 shadow-xl">
          <h2 className="text-2xl font-medium text-white/90">Paper Not Yet Processed</h2>
          <p className="mt-4 text-white/70 leading-relaxed">
            This paper (<span className="font-mono text-white/80 bg-white/15 px-2 py-0.5 rounded">{arxivId}</span>) hasn&apos;t been visualized yet.
            We&apos;ll parse the content and generate animations for key concepts.
          </p>

          <div className="mt-8 space-y-4">
            <motion.button
              whileHover={{ scale: starting ? 1 : 1.02 }}
              whileTap={{ scale: starting ? 1 : 0.98 }}
              onClick={onProcess}
              disabled={starting}
              className="w-full sm:w-auto rounded-2xl bg-white/[0.08] hover:bg-white/[0.12] px-8 py-4 text-sm font-medium text-white border border-white/[0.15] hover:border-white/[0.25] shadow-xl shadow-white/[0.03] transition-all duration-300 disabled:opacity-50 disabled:cursor-wait"
            >
              {starting ? "Starting…" : "Start Processing"}
            </motion.button>

            <p className="text-xs text-white/40">
              This usually takes 3-5 minutes depending on paper length
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

function formatTimeLeft(seconds: number): string {
  if (seconds <= 0) return "almost done";
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins > 0) return `~${mins}m ${secs}s`;
  return `~${secs}s`;
}

/**
 * Honest pipeline phases, mapped to the progress values the worker actually
 * writes (0.10 fetch, 0.30 stored, 0.50 generation, 0.75+ rendering). The
 * previous five steps used thresholds the backend never emits, so the UI
 * routinely claimed steps were done before they had started.
 */
const PIPELINE_PHASES = [
  { label: "Fetching & parsing the paper", start: 0.0, end: 0.3, icon: "\u222B", estSeconds: 40 },
  { label: "AI designs & writes the animations", start: 0.3, end: 0.75, icon: "\u03BB", estSeconds: 110 },
  { label: "Rendering narrated videos", start: 0.75, end: 1.0, icon: "\u221E", estSeconds: 240 },
] as const;

function estimateSecondsLeft(status: ProcessingStatus): number {
  const p = status.progress;
  let remaining = 0;
  for (const phase of PIPELINE_PHASES) {
    if (p >= phase.end) continue;
    if (p <= phase.start) {
      remaining += phase.estSeconds;
    } else {
      remaining += phase.estSeconds * ((phase.end - p) / (phase.end - phase.start));
    }
  }
  // During rendering the honest signal is the per-video counter.
  if (p >= 0.75 && status.sections_total > 0) {
    const videosLeft = Math.max(0, status.sections_total - status.sections_completed);
    remaining = videosLeft * 55;
  }
  return Math.round(remaining);
}

function NotifyButton({
  notifier,
  compact = false,
}: {
  notifier: ReturnType<typeof useCompletionNotifier>;
  compact?: boolean;
}) {
  if (notifier.enabled) {
    return (
      <span className={`inline-flex items-center gap-2 text-white/40 ${compact ? "text-xs" : "text-sm"}`}>
        <span className="text-[#7dd19b]">&#10003;</span>
        We&apos;ll ding when it&apos;s ready &mdash; feel free to switch tabs
      </span>
    );
  }
  return (
    <button
      onClick={notifier.enable}
      className={`inline-flex items-center gap-2 rounded-full bg-white/[0.06] border border-white/[0.12] text-white/70 transition-all hover:bg-white/[0.10] hover:text-white/90 ${
        compact ? "px-3 py-1.5 text-xs" : "px-4 py-2 text-sm"
      }`}
    >
      <span aria-hidden>&#128276;</span>
      Notify me when it&apos;s ready
    </button>
  );
}

function ProcessingState({
  status,
  notifier,
}: {
  status: ProcessingStatus;
  notifier: ReturnType<typeof useCompletionNotifier>;
}) {
  const progressPercent = Math.round(status.progress * 100);
  const isRendering = status.progress >= 0.75;
  const estimatedSecondsLeft = progressPercent >= 100 ? 0 : estimateSecondsLeft(status);

  return (
    <div className="flex items-center justify-center py-16 px-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
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
              <span className="flex items-center gap-4">
                {progressPercent < 100 && status.job_id !== "demo" && (
                  <span className="text-white/40 font-medium">{formatTimeLeft(estimatedSecondsLeft)} left</span>
                )}
                <span className="font-mono text-white/80 font-medium">{progressPercent}%</span>
              </span>
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

          {/* During the render phase these counts are real per-video progress */}
          {isRendering && status.sections_total > 0 && (
            <div className="mt-4 flex items-center gap-3 text-sm">
              <span className="text-white/30">Videos rendered:</span>
              <span className="font-mono text-white/60 bg-white/[0.06] px-2 py-0.5 rounded">
                {status.sections_completed} / {status.sections_total}
              </span>
            </div>
          )}

          {/* Notify: lets people safely tab away during the wait */}
          {status.job_id !== "demo" && (
            <div className="mt-6">
              <NotifyButton notifier={notifier} />
            </div>
          )}

          {/* Phases — thresholds match what the worker actually writes */}
          <div className="mt-8 rounded-2xl bg-white/[0.03] p-6 border border-white/[0.06]">
            <div className="text-xs font-medium text-white/25 uppercase tracking-wider mb-4">Pipeline Progress</div>
            <ol className="space-y-3">
              {PIPELINE_PHASES.map((phase, i) => {
                const isDone = status.progress >= phase.end;
                const isCurrent =
                  status.progress >= phase.start && status.progress < phase.end;

                return (
                  <motion.li
                    key={i}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.1 }}
                    className="flex items-center gap-4"
                  >
                    <span className={`text-xl transition-all duration-300 ${isDone || isCurrent ? 'text-white/50' : 'text-white/15'}`}>
                      {phase.icon}
                    </span>
                    <span className={`flex-1 text-sm transition-colors duration-300 ${isDone || isCurrent ? 'text-white/60' : 'text-white/20'}`}>
                      {phase.label}
                      {isCurrent && i === 1 && (
                        <span className="block text-xs text-white/30 mt-0.5">
                          The slow part — each concept gets its own storyboard, code, and narration
                        </span>
                      )}
                    </span>
                    {isCurrent && (
                      <span className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-white/40 animate-pulse" />
                        <span className="text-xs text-white/40">In progress</span>
                      </span>
                    )}
                    {isDone && (
                      <span className="text-xs text-[#7dd19b] font-medium">Done</span>
                    )}
                  </motion.li>
                );
              })}
            </ol>
            {/* Once the text is parsed, the reader replaces this card — tell
                people the wait is about the videos, not the words */}
            {status.progress >= 0.3 && (
              <p className="mt-4 text-xs text-white/30">
                Loading the paper text&hellip; it will appear as soon as it&apos;s parsed.
              </p>
            )}
          </div>
        </GlassCard>
      </motion.div>
    </div>
  );
}

/**
 * Compact status pill shown while the reader is already visible (progressive
 * reading) but videos are still rendering. Fixed bottom-center, out of the way.
 */
function ProcessingPill({
  status,
  notifier,
}: {
  status: ProcessingStatus;
  notifier: ReturnType<typeof useCompletionNotifier>;
}) {
  const progressPercent = Math.round(status.progress * 100);
  const isRendering = status.progress >= 0.75;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-full bg-black/80 backdrop-blur-xl border border-white/[0.12] px-5 py-3 shadow-2xl shadow-black/50"
    >
      <span className="relative flex h-3 w-3">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white/30" />
        <span className="relative inline-flex rounded-full h-3 w-3 bg-white/50" />
      </span>
      <span className="text-sm text-white/70 whitespace-nowrap">
        {isRendering && status.sections_total > 0
          ? `Rendering videos ${status.sections_completed}/${status.sections_total} — they'll appear below as they finish`
          : `${status.current_step || "Processing"} · ${progressPercent}%`}
      </span>
      <span className="hidden sm:block">
        <NotifyButton notifier={notifier} compact />
      </span>
    </motion.div>
  );
}

/** Floating notice for partial failures — the paper is readable, but honest. */
function NoticeBanner({ notice }: { notice: string }) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;
  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="fixed top-5 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 max-w-xl rounded-2xl bg-black/85 backdrop-blur-xl border border-[#e0b34e]/30 px-5 py-3 shadow-2xl shadow-black/50"
    >
      <span className="text-[#e0b34e]" aria-hidden>&#9888;</span>
      <span className="text-sm text-white/70">{notice}</span>
      <button
        onClick={() => setDismissed(true)}
        className="ml-1 text-white/40 hover:text-white/80 transition-colors"
        aria-label="Dismiss"
      >
        &times;
      </button>
    </motion.div>
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
