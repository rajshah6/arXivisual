"use client";

import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  motion,
  useScroll,
  useTransform,
  useMotionValueEvent,
  type MotionValue,
} from "framer-motion";
import { StackCard } from "@/components/StackCard";
import type { ScrollySectionModel } from "@/components/ScrollySection";
import { cn } from "@/lib/utils";

// --- Layout constants ---
const SCROLL_PER_SECTION = 2; // 200vh scroll per section
const EXIT_FRACTION = 0.25; // last 25% of each segment = exit/enter phase
const CONTENT_FRACTION = 1 - EXIT_FRACTION; // first 75% = content scroll phase

/**
 * SlideCard — creates 3 motion values per card (vs old CardSlot's 8 hooks).
 * Handles horizontal slide transitions: exit left, enter from right.
 */
function SlideCard({
  section,
  index,
  totalSections,
  scrollYProgress,
  isActive,
  contentHeightsRef,
  onContentHeight,
}: {
  section: ScrollySectionModel;
  index: number;
  totalSections: number;
  scrollYProgress: MotionValue<number>;
  isActive: boolean;
  contentHeightsRef: React.RefObject<number[]>;
  onContentHeight: (index: number, height: number) => void;
}) {
  const N = totalSections;
  const segStart = index / N;
  const segEnd = (index + 1) / N;
  const segLen = segEnd - segStart;
  const contentEnd = segStart + segLen * CONTENT_FRACTION;

  // Previous card's exit phase = this card's enter phase
  const prevSegStart = (index - 1) / N;
  const prevSegLen = 1 / N;
  const prevExitStart = prevSegStart + prevSegLen * CONTENT_FRACTION;

  // --- slideX: horizontal position ---
  const slideX = useTransform(scrollYProgress, (v) => {
    const vw = typeof window !== "undefined" ? window.innerWidth : 1000;

    // Before this card's enter phase: offscreen right
    if (index > 0 && v < prevExitStart) return vw;

    // First card is always at x=0 until its exit
    if (index === 0 && v < contentEnd) return 0;

    // Enter phase (slides in from right) — during previous card's exit
    if (index > 0 && v >= prevExitStart && v < segStart) {
      const enterProgress = (v - prevExitStart) / (segStart - prevExitStart);
      return vw * (1 - enterProgress);
    }

    // Content phase: card is centered
    if (v >= segStart && v < contentEnd) return 0;

    // Exit phase: slide left
    if (v >= contentEnd && v < segEnd) {
      const exitProgress = (v - contentEnd) / (segEnd - contentEnd);
      return -vw * exitProgress;
    }

    // After segment: offscreen left
    if (v >= segEnd) return -vw;

    return 0;
  });

  // --- slideOpacity ---
  const slideOpacity = useTransform(scrollYProgress, (v) => {
    // Before enter: hidden
    if (index > 0 && v < prevExitStart) return 0;

    // First card: visible from start
    if (index === 0 && v < contentEnd) return 1;

    // Enter phase: fade in
    if (index > 0 && v >= prevExitStart && v < segStart) {
      const enterProgress = (v - prevExitStart) / (segStart - prevExitStart);
      return enterProgress;
    }

    // Content phase: fully visible
    if (v >= segStart && v < contentEnd) return 1;

    // Exit phase: fade out
    if (v >= contentEnd && v < segEnd) {
      const exitProgress = (v - contentEnd) / (segEnd - contentEnd);
      return 1 - exitProgress;
    }

    // After: hidden
    if (v >= segEnd) return 0;

    return 1;
  });

  // --- contentY: scroll content within the card during content phase ---
  const contentY = useTransform(scrollYProgress, (v) => {
    const contentHeight = contentHeightsRef.current?.[index] || 0;
    const cardViewportHeight =
      typeof window !== "undefined" ? window.innerHeight - 96 : 600;
    const maxScroll = Math.max(0, contentHeight - cardViewportHeight);

    // Before this card's segment: content at top
    if (v < segStart) return 0;

    // Content phase: scroll from 0 to -maxScroll
    if (v >= segStart && v < contentEnd) {
      const contentPhaseProgress = (v - segStart) / (contentEnd - segStart);
      return -contentPhaseProgress * maxScroll;
    }

    // Exit phase + after: stay at bottom so scrolling back doesn't snap
    return -maxScroll;
  });

  // z-index: computed inline, no useState
  const zIndex = useMemo(() => {
    if (isActive) return N + 1;
    return N - Math.abs(index);
  }, [isActive, N, index]);

  return (
    <StackCard
      section={section}
      index={index}
      totalSections={N}
      isActive={isActive}
      cardX={slideX}
      cardOpacity={slideOpacity}
      contentY={contentY}
      zIndex={zIndex}
      onContentHeight={onContentHeight}
    />
  );
}

export function CardStack({
  sections,
  heroContent,
  onProgressChange,
}: {
  sections: ScrollySectionModel[];
  heroContent?: ReactNode;
  onProgressChange?: (progress: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const N = sections.length;
  const totalScrollVh = N * SCROLL_PER_SECTION * 100;

  const contentHeightsRef = useRef<number[]>(new Array(N).fill(0));

  const handleContentHeight = useCallback(
    (index: number, height: number) => {
      contentHeightsRef.current[index] = height;
    },
    []
  );

  const { scrollYProgress } = useScroll({
    target: trackRef,
    offset: ["start start", "end end"],
  });

  // No useSpring — raw scroll progress for responsive feel

  const [activeIndex, setActiveIndex] = useState(0);

  useMotionValueEvent(scrollYProgress, "change", (latest) => {
    const newActive = Math.min(Math.floor(latest * N), N - 1);
    if (newActive >= 0 && newActive !== activeIndex) {
      setActiveIndex(newActive);
    }
  });

  useEffect(() => {
    if (onProgressChange && N > 1) {
      onProgressChange(activeIndex / (N - 1));
    }
  }, [activeIndex, N, onProgressChange]);

  // Virtualize: only render cards near the active one (max 3 in DOM)
  const visibleIndices = useMemo(() => {
    const indices: number[] = [];
    for (let i = activeIndex - 1; i <= activeIndex + 1; i++) {
      if (i >= 0 && i < N) indices.push(i);
    }
    return indices;
  }, [activeIndex, N]);

  const indicatorOpacity = useTransform(
    scrollYProgress,
    [0, 0.95, 1],
    [1, 1, 0]
  );

  return (
    <div>
      {heroContent}

      {/* Scroll track */}
      <div
        ref={trackRef}
        style={{ height: `${totalScrollVh}vh` }}
        className="relative"
      >
        {/* Sticky viewport — holds visible cards, clips transitions */}
        <div className="sticky top-0 h-screen overflow-hidden">
          {visibleIndices.map((i) => (
            <SlideCard
              key={sections[i].id}
              section={sections[i]}
              index={i}
              totalSections={N}
              scrollYProgress={scrollYProgress}
              isActive={i === activeIndex}
              contentHeightsRef={contentHeightsRef}
              onContentHeight={handleContentHeight}
            />
          ))}

          {/* Section counter indicator */}
          <motion.div
            className="absolute bottom-3 left-1/2 -translate-x-1/2 z-[100]"
            style={{ opacity: indicatorOpacity }}
          >
            <div className="flex items-center gap-2.5 rounded-full bg-black/60 backdrop-blur-xl px-4 py-2 border border-white/[0.08]">
              <span className="text-xs font-mono text-white/40">
                {activeIndex + 1} / {N}
              </span>
              <div className="flex gap-1">
                {sections.map((_, i) => (
                  <div
                    key={i}
                    className={cn(
                      "h-1 rounded-full transition-all duration-300",
                      i === activeIndex
                        ? "w-4 bg-white/50"
                        : i < activeIndex
                          ? "w-1 bg-white/20"
                          : "w-1.5 bg-white/10"
                    )}
                  />
                ))}
              </div>
            </div>
          </motion.div>
        </div>
      </div>

      {/* End of content */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5 }}
        className="mt-16 flex flex-col items-center gap-4 py-8"
      >
        <div className="flex items-center gap-3 w-full max-w-3xl mx-auto text-sm text-white/25 px-6">
          <div className="h-px flex-1 bg-gradient-to-r from-transparent to-white/[0.06]" />
          <span>End of paper</span>
          <div className="h-px flex-1 bg-gradient-to-l from-transparent to-white/[0.06]" />
        </div>

        <button
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          className="mt-2 text-xs text-white/30 hover:text-white/60 transition-colors"
        >
          Back to top
        </button>
      </motion.div>
    </div>
  );
}
