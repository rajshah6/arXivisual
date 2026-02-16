"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MarkdownContent } from "@/components/MarkdownContent";
import { MOCK_PAPER } from "@/lib/mock-data";
import type { ProcessingStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Per-section accent colors: emerald, purple, amber, blue, rose
// ---------------------------------------------------------------------------
const SECTION_COLORS = ["#34d399", "#a78bfa", "#fbbf24", "#60a5fa", "#fb7185"];

// ---------------------------------------------------------------------------
// Actual paper text excerpts from "Attention Is All You Need" (1706.03762)
// Taken directly from the PDF — trimmed for readability but authentic content.
// ---------------------------------------------------------------------------
const PAPER_SECTIONS = [
  {
    heading: "3  Model Architecture",
    body: `Most competitive neural sequence transduction models have an encoder-decoder structure. Here, the encoder maps an input sequence of symbol representations (x₁, ..., xₙ) to a sequence of continuous representations z = (z₁, ..., zₙ). Given z, the decoder then generates an output sequence (y₁, ..., yₘ) of symbols one element at a time.

The Transformer follows this overall architecture using stacked self-attention and point-wise, fully connected layers for both the encoder and decoder, shown in the left and right halves of Figure 1, respectively.`,
    subheading: "3.1  Encoder and Decoder Stacks",
    subbody: `**Encoder:** The encoder is composed of a stack of N = 6 identical layers. Each layer has two sub-layers. The first is a multi-head self-attention mechanism, and the second is a simple, position-wise fully connected feed-forward network. We employ a residual connection around each of the two sub-layers, followed by layer normalization. That is, the output of each sub-layer is LayerNorm(x + Sublayer(x)).

**Decoder:** The decoder is also composed of a stack of N = 6 identical layers. In addition to the two sub-layers in each encoder layer, the decoder inserts a third sub-layer, which performs multi-head attention over the output of the encoder stack.`,
  },
  {
    heading: "3.2  Attention",
    body: `An attention function can be described as mapping a query and a set of key-value pairs to an output, where the query, keys, values, and output are all vectors. The output is computed as a weighted sum of the values, where the weight assigned to each value is computed by a compatibility function of the query with the corresponding key.`,
    subheading: "3.2.1  Scaled Dot-Product Attention",
    subbody: `We call our particular attention "Scaled Dot-Product Attention". The input consists of queries and keys of dimension dₖ, and values of dimension dᵥ. We compute the dot products of the query with all keys, divide each by √dₖ, and apply a softmax function to obtain the weights on the values.`,
    equation: `$$\\text{Attention}(Q, K, V) = \\text{softmax}\\!\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V$$`,
  },
  {
    heading: "3.2.2  Multi-Head Attention",
    body: `Instead of performing a single attention function with dₘₒdₑₗ-dimensional keys, values and queries, we found it beneficial to linearly project the queries, keys and values h times with different, learned linear projections to dₖ, dₖ and dᵥ dimensions, respectively. On each of these projected versions of queries, keys and values we then perform the attention function in parallel, yielding dᵥ-dimensional output values. These are concatenated and once again projected, resulting in the final values.`,
    equation: `$$\\text{MultiHead}(Q,K,V) = \\text{Concat}(\\text{head}_1, \\dots, \\text{head}_h)\\,W^O$$

$$\\text{where } \\text{head}_i = \\text{Attention}(QW_i^Q,\\; KW_i^K,\\; VW_i^V)$$`,
    subbody: `In this work we employ h = 8 parallel attention layers, or heads. For each of these we use dₖ = dᵥ = dₘₒdₑₗ/h = 64. Due to the reduced dimension of each head, the total computational cost is similar to that of single-head attention with full dimensionality.`,
  },
  {
    heading: "3.5  Positional Encoding",
    body: `Since our model contains no recurrence and no convolution, in order for the model to make use of the order of the sequence, we must inject some information about the relative or absolute position of the tokens in the sequence. To this end, we add "positional encodings" to the input embeddings at the bottoms of the encoder and decoder stacks. The positional encodings have the same dimension dₘₒdₑₗ as the embeddings, so that the two can be summed.

In this work, we use sine and cosine functions of different frequencies:`,
    equation: `$$PE_{(pos,\\,2i)} = \\sin\\!\\left(\\frac{pos}{10000^{\\,2i/d_{\\text{model}}}}\\right)$$

$$PE_{(pos,\\,2i+1)} = \\cos\\!\\left(\\frac{pos}{10000^{\\,2i/d_{\\text{model}}}}\\right)$$`,
    subbody: `We chose this function because we hypothesized it would allow the model to easily learn to attend by relative positions, since for any fixed offset k, PE_pos+k can be represented as a linear function of PE_pos.`,
  },
  {
    heading: "4  Why Self-Attention",
    body: `In this section we compare various aspects of self-attention layers to the recurrent and convolutional layers commonly used for mapping one variable-length sequence of symbol representations (x₁, ..., xₙ) to another sequence of equal length (z₁, ..., zₙ), with xᵢ, zᵢ ∈ ℝᵈ.

One is the total computational complexity per layer. Another is the amount of computation that can be parallelized, as measured by the minimum number of sequential operations required.

The third is the path length between long-range dependencies in the network. Learning long-range dependencies is a key challenge in many sequence transduction tasks. One key factor affecting the ability to learn such dependencies is the length of the paths forward and backward signals have to traverse in the network. The shorter these paths between any combination of positions in the input and output sequences, the easier it is to learn long-range dependencies.`,
    subbody: `As side benefit, self-attention could yield more interpretable models. We inspect attention distributions from our models and present and discuss examples in the appendix. Not only do individual attention heads clearly learn to perform different tasks, many appear to exhibit behavior related to the syntactic and semantic structure of the sentences.`,
  },
];

// ---------------------------------------------------------------------------

interface SplitScreenDemoProps {
  status: ProcessingStatus;
}

export function SplitScreenDemo({ status }: SplitScreenDemoProps) {
  const progress = status.progress;
  const activeIndex = Math.min(Math.floor(progress * 5), 4);
  const sectionProgress = Math.max(
    0,
    Math.min(1, (progress - activeIndex * 0.2) / 0.2)
  );
  const progressPercent = Math.round(progress * 100);
  const activeColor = SECTION_COLORS[activeIndex];

  const mockSections = MOCK_PAPER.sections;
  const activeSection = mockSections[activeIndex];

  return (
    <div className="flex items-center justify-center min-h-[80vh] py-8 px-4 sm:px-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
        className="w-full max-w-7xl"
      >
        {/* Top bar: progress + step label */}
        <div className="mb-5">
          <div className="flex items-center justify-between mb-2.5">
            <div className="flex items-center gap-3">
              <div className="relative">
                <div className="h-5 w-5 rounded-md bg-white/[0.05] border border-white/[0.10]" />
                <div
                  className="absolute inset-0 h-5 w-5 animate-spin rounded-md border border-transparent"
                  style={{ animationDuration: "2s", borderTopColor: `${activeColor}80` }}
                />
              </div>
              <span className="text-sm text-white/40">
                {status.current_step || "Preparing..."}
              </span>
            </div>
            <span className="font-mono text-sm text-white/60">
              {progressPercent}%
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-white/[0.05] overflow-hidden border border-white/[0.06]">
            <motion.div
              className="h-full rounded-full"
              style={{
                background: `linear-gradient(to right, ${activeColor}, ${activeColor}80)`,
              }}
              initial={{ width: 0 }}
              animate={{ width: `${progressPercent}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>

        {/* Paper title + authors */}
        <div className="mb-5">
          <h2 className="text-xl sm:text-2xl font-medium text-white/90 tracking-tight">
            {MOCK_PAPER.title}
          </h2>
          <p className="mt-1.5 text-sm text-white/30">
            {MOCK_PAPER.authors.slice(0, 5).join(", ")}
            {MOCK_PAPER.authors.length > 5 && ", et al."}
          </p>
        </div>

        {/* Split screen */}
        <div className="flex flex-col md:flex-row items-stretch gap-3 md:gap-0">
          {/* Left: The Paper */}
          <div className="w-full md:w-[calc(50%-56px)] shrink-0">
            <PaperPanel
              activeIndex={activeIndex}
              sectionProgress={sectionProgress}
            />
          </div>

          {/* Center: Transformation Arrow (desktop) */}
          <div className="hidden md:flex items-center justify-center w-28 shrink-0">
            <div className="flex flex-col items-center gap-4">
              <div className="w-px h-24 bg-gradient-to-b from-transparent via-white/[0.2] to-white/[0.15]" />
              <motion.div
                animate={{
                  scale: [1, 1.15, 1],
                  opacity: [0.7, 1, 0.7],
                }}
                transition={{
                  duration: 2,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
                className="w-16 h-16 rounded-full border-2 border-white/[0.25] bg-white/[0.08] backdrop-blur-sm flex items-center justify-center shadow-lg shadow-white/[0.05]"
              >
                <svg
                  className="w-8 h-8 text-white/80"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3"
                  />
                </svg>
              </motion.div>
              <div className="w-px h-24 bg-gradient-to-t from-transparent via-white/[0.2] to-white/[0.15]" />
            </div>
          </div>

          {/* Center: Transformation Arrow (mobile) */}
          <div className="flex md:hidden items-center justify-center py-2">
            <motion.div
              animate={{ opacity: [0.5, 0.9, 0.5] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
              className="w-12 h-12 rounded-full border-2 border-white/[0.2] bg-white/[0.06] backdrop-blur-sm flex items-center justify-center"
            >
              <svg
                className="w-7 h-7 text-white/70 rotate-90"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2.5}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
              </svg>
            </motion.div>
          </div>

          {/* Right: ArXivisual Output */}
          <div className="w-full md:w-[calc(50%-56px)]">
            <VisualizationPanel
              section={activeSection}
              index={activeIndex}
              sectionProgress={sectionProgress}
              color={activeColor}
            />
          </div>
        </div>
      </motion.div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Left panel: actual paper content with colored scanning highlight
// ---------------------------------------------------------------------------

function PaperPanel({
  activeIndex,
  sectionProgress,
}: {
  activeIndex: number;
  sectionProgress: number;
}) {
  const sectionRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const el = sectionRefs.current[activeIndex];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [activeIndex]);

  return (
    <div className="rounded-2xl bg-white/[0.06] backdrop-blur-sm border border-white/[0.08] overflow-hidden flex flex-col">
      {/* Header */}
      <div className="px-5 pt-4 pb-3 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <svg className="w-4 h-4 text-white/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
          </svg>
          <span className="text-sm font-medium text-white/70 tracking-wide">
            Original Paper
          </span>
        </div>
        <span className="text-[11px] text-white/30 font-mono">
          arXiv:1706.03762
        </span>
      </div>

      {/* Scrollable paper content */}
      <div className="overflow-y-auto max-h-[65vh] p-5 space-y-0 scroll-smooth custom-scrollbar">
        {PAPER_SECTIONS.map((section, i) => {
          const isActive = i === activeIndex;
          const isCompleted = i < activeIndex;
          const isPending = i > activeIndex;
          const color = SECTION_COLORS[i];

          return (
            <div
              key={i}
              ref={(el) => {
                sectionRefs.current[i] = el;
              }}
              className="relative"
            >
              {/* Divider between sections */}
              {i > 0 && (
                <div className="h-px bg-white/[0.06] my-5" />
              )}

              {/* Section content wrapper */}
              <div
                className={cn(
                  "relative rounded-xl px-4 py-3 transition-all duration-500",
                  isPending && "opacity-40 border-l-2 border-l-transparent"
                )}
                style={
                  isActive
                    ? {
                        borderLeft: `2px solid ${color}`,
                        backgroundColor: `${color}10`,
                      }
                    : isCompleted
                      ? { borderLeft: `2px solid ${color}30` }
                      : undefined
                }
              >
                {/* Scan line — sweeps top to bottom on active section */}
                {isActive && (
                  <div
                    className="absolute left-0 right-0 h-10 pointer-events-none z-10 transition-[top] duration-300 ease-linear"
                    style={{ top: `${sectionProgress * 85}%` }}
                  >
                    <div
                      className="w-full h-full"
                      style={{
                        background: `linear-gradient(to bottom, transparent, ${color}20, transparent)`,
                      }}
                    />
                  </div>
                )}

                {/* Heading */}
                <h3
                  className={cn(
                    "font-serif text-base font-bold mb-2 transition-colors duration-500",
                    isActive
                      ? "text-white/90"
                      : isCompleted
                        ? "text-white/70"
                        : "text-white/40"
                  )}
                >
                  {section.heading}
                </h3>

                {/* Body text */}
                <div
                  className={cn(
                    "font-serif text-[13px] leading-[1.8] whitespace-pre-line transition-colors duration-500",
                    isActive
                      ? "text-white/60"
                      : isCompleted
                        ? "text-white/45"
                        : "text-white/25"
                  )}
                >
                  {section.body}
                </div>

                {/* Subheading */}
                {section.subheading && (
                  <h4
                    className={cn(
                      "font-serif text-sm font-bold mt-3 mb-1.5 transition-colors duration-500",
                      isActive
                        ? "text-white/80"
                        : isCompleted
                          ? "text-white/60"
                          : "text-white/30"
                    )}
                  >
                    {section.subheading}
                  </h4>
                )}

                {/* Sub-body text */}
                {section.subbody && (
                  <div
                    className={cn(
                      "font-serif text-[13px] leading-[1.8] whitespace-pre-line transition-colors duration-500",
                      isActive
                        ? "text-white/60"
                        : isCompleted
                          ? "text-white/45"
                          : "text-white/25"
                    )}
                  >
                    {section.subbody}
                  </div>
                )}

                {/* Equation */}
                {section.equation && (
                  <div
                    className={cn(
                      "my-3 transition-opacity duration-500",
                      isActive
                        ? "opacity-100"
                        : isCompleted
                          ? "opacity-60"
                          : "opacity-30"
                    )}
                  >
                    <MarkdownContent
                      content={section.equation}
                      className="text-center"
                    />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Right panel: LLM-style streaming text (ArXivisual output)
// ---------------------------------------------------------------------------

function VisualizationPanel({
  section,
  index,
  sectionProgress,
  color,
}: {
  section: (typeof MOCK_PAPER.sections)[number];
  index: number;
  sectionProgress: number;
  color: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // Reveal characters based on section progress
  const content = section.content;
  const revealedLength = Math.floor(content.length * sectionProgress);
  const visibleText = content.slice(0, revealedLength);
  const isStreaming = sectionProgress < 1;

  // Auto-scroll to bottom as text streams in
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [revealedLength]);

  return (
    <div className="rounded-2xl bg-white/[0.07] backdrop-blur-sm border border-white/[0.08] overflow-hidden flex flex-col">
      {/* Header */}
      <div className="px-5 pt-4 pb-3 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <svg className="w-4 h-4 text-white/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />
          </svg>
          <span className="text-sm font-medium text-white/70 tracking-wide">
            ArXivisual Output
          </span>
        </div>
        <span className="flex items-center gap-2 text-[11px] text-white/40">
          <span
            className="w-1.5 h-1.5 rounded-full animate-pulse"
            style={{ backgroundColor: color }}
          />
          Generating
        </span>
      </div>

      {/* Content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={section.id}
          initial={{ opacity: 0, x: 30 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -30 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
          className="flex flex-col"
        >
          {/* Section info */}
          <div className="px-5 pt-5 pb-0">
            <div className="text-[11px] font-mono text-white/20 tracking-wider mb-2">
              Section {index + 1} of 5
            </div>

            <h3 className="text-lg font-semibold text-white/90 tracking-tight">
              {section.title}
            </h3>

            {/* Color accent bar */}
            <div
              className="mt-2 h-0.5 w-16 rounded-full"
              style={{ backgroundColor: color }}
            />
          </div>

          {/* Streaming text area */}
          <div
            ref={scrollRef}
            className="px-5 pt-4 pb-5 overflow-y-auto max-h-[50vh] custom-scrollbar"
          >
            <div className="text-sm leading-relaxed text-white/55">
              <MarkdownContent content={visibleText} />
              {isStreaming && (
                <span
                  className="inline-block w-2 h-4 ml-0.5 align-middle animate-pulse rounded-sm"
                  style={{ backgroundColor: color }}
                />
              )}
            </div>
            <div ref={endRef} />
          </div>

          {/* Video placeholder */}
          <VideoPlaceholder
            sectionProgress={sectionProgress}
            color={color}
          />
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Video placeholder — black box with play button to show video generation
// ---------------------------------------------------------------------------

function VideoPlaceholder({
  sectionProgress,
  color,
}: {
  sectionProgress: number;
  color: string;
}) {
  const visible = sectionProgress > 0.3;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
          className="mx-5 mb-5 mt-2"
        >
          {/* Label */}
          <div className="flex items-center gap-2 mb-2.5">
            <svg className="w-3.5 h-3.5 text-white/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z" />
            </svg>
            <span className="text-[11px] text-white/35 font-medium tracking-wide">
              Manim Visualization
            </span>
          </div>

          {/* Black video placeholder box */}
          <div className="relative aspect-video rounded-xl bg-black border border-white/[0.08] overflow-hidden">
            {/* Subtle shimmer */}
            <div
              className="absolute inset-0 opacity-30 animate-shimmer"
              style={{
                background: `linear-gradient(135deg, transparent 40%, ${color}15 50%, transparent 60%)`,
                backgroundSize: "200% 200%",
              }}
            />

            {/* Center play button */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="h-12 w-12 rounded-full border border-white/[0.15] bg-white/[0.06] flex items-center justify-center backdrop-blur-sm">
                <svg
                  viewBox="0 0 24 24"
                  className="h-5 w-5 text-white/40 translate-x-[1px]"
                  fill="currentColor"
                >
                  <path d="M8 5v14l11-7z" />
                </svg>
              </div>
            </div>

            {/* Bottom label */}
            <div className="absolute bottom-0 inset-x-0 p-3 bg-gradient-to-t from-black/60 to-transparent">
              <div className="flex items-center gap-2">
                <span
                  className="w-1.5 h-1.5 rounded-full animate-pulse"
                  style={{ backgroundColor: color }}
                />
                <span className="text-[11px] text-white/35">
                  {sectionProgress < 0.8 ? "Rendering animation..." : "Finalizing video..."}
                </span>
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
