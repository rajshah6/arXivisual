"use client";

import { useMemo, useRef, useEffect, useCallback } from "react";
import { motion, type MotionValue, useMotionValue, useMotionTemplate } from "framer-motion";
import { VideoFeedback } from "@/components/VideoFeedback";
import { VideoPlayer } from "@/components/VideoPlayer";
import { MarkdownContent } from "@/components/MarkdownContent";
import { cn } from "@/lib/utils";

// Re-export the model type so page.tsx can import from here
export type { ScrollySectionModel } from "@/components/ScrollySection";

// Reuse the equation-merging logic from ScrollySection
function mergeContentWithEquations(content: string, equations?: string[]): string {
  if (!equations || equations.length === 0) return content;

  let result = content;
  const equationsToAppend: string[] = [];

  for (const eq of equations) {
    const normalizedEq = eq.replace(/\s+/g, "");
    const normalizedContent = result.replace(/\s+/g, "");

    const alreadyPresent =
      normalizedContent.includes(normalizedEq) ||
      normalizedContent.includes(`$${normalizedEq}$`) ||
      normalizedContent.includes(`$$${normalizedEq}$$`);

    if (!alreadyPresent) {
      equationsToAppend.push(eq);
    }
  }

  if (equationsToAppend.length > 0) {
    const equationBlocks = equationsToAppend
      .map((eq) => {
        const trimmed = eq.trim();
        if (trimmed.startsWith("$$") && trimmed.endsWith("$$")) return trimmed;
        if (trimmed.startsWith("$") && trimmed.endsWith("$") && !trimmed.startsWith("$$")) {
          return `$${trimmed}$`;
        }
        return `$$${trimmed}$$`;
      })
      .join("\n\n");

    result = `${result}\n\n${equationBlocks}`;
  }

  return result;
}

interface StackCardProps {
  section: {
    id: string;
    title: string;
    content: string;
    level?: 1 | 2 | 3;
    equations?: string[];
    videoUrl?: string;
    vizId?: string;
  };
  index: number;
  totalSections: number;
  isActive: boolean;
  cardX: MotionValue<number>;
  cardOpacity: MotionValue<number>;
  contentY: MotionValue<number>;
  zIndex: number;
  onContentHeight?: (index: number, height: number) => void;
}

export function StackCard({
  section,
  index,
  totalSections,
  isActive,
  cardX,
  cardOpacity,
  contentY,
  zIndex,
  onContentHeight,
}: StackCardProps) {
  const contentRef = useRef<HTMLDivElement>(null);

  // Mouse spotlight
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const { left, top } = e.currentTarget.getBoundingClientRect();
    mouseX.set(e.clientX - left);
    mouseY.set(e.clientY - top);
  }

  const spotlightBg = useMotionTemplate`
    radial-gradient(
      600px circle at ${mouseX}px ${mouseY}px,
      rgba(255, 255, 255, 0.05),
      transparent 40%
    )
  `;

  const headingClass = useMemo(() => {
    const level = section.level ?? 1;
    if (level === 1) return "text-2xl sm:text-3xl";
    if (level === 2) return "text-xl sm:text-2xl";
    return "text-lg sm:text-xl";
  }, [section.level]);

  const unifiedContent = useMemo(
    () => mergeContentWithEquations(section.content, section.equations),
    [section.content, section.equations]
  );

  // Report content height for scroll calculation
  const reportHeight = useCallback(() => {
    if (contentRef.current && onContentHeight) {
      onContentHeight(index, contentRef.current.scrollHeight);
    }
  }, [index, onContentHeight]);

  useEffect(() => {
    reportHeight();

    const el = contentRef.current;
    if (!el) return;

    const observer = new ResizeObserver(() => reportHeight());
    observer.observe(el);
    return () => observer.disconnect();
  }, [reportHeight]);

  const sectionNumber = String(index + 1).padStart(2, "0");

  return (
    <motion.section
      data-card-index={index}
      aria-hidden={!isActive}
      onMouseMove={isActive ? handleMouseMove : undefined}
      className={cn(
        "absolute inset-x-4 top-4 bottom-4 sm:inset-x-6 sm:top-6 sm:bottom-6",
        "rounded-3xl border backdrop-blur-xl overflow-hidden",
        "will-change-transform",
        isActive
          ? "bg-white/[0.06] border-white/[0.18] shadow-2xl shadow-black/50"
          : "bg-white/[0.04] border-white/[0.10] shadow-xl shadow-black/30"
      )}
      style={{
        x: cardX,
        opacity: cardOpacity,
        zIndex,
        pointerEvents: isActive ? "auto" : "none",
      }}
    >
      {/* Spotlight gradient overlay */}
      {isActive && (
        <motion.div
          className="pointer-events-none absolute -inset-px rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-500"
          style={{ background: spotlightBg }}
        />
      )}

      {/* Content area */}
      <div className="relative h-full overflow-hidden">
        <motion.div
          ref={contentRef}
          style={{ y: contentY }}
          className="px-6 pt-6 pb-8 sm:px-10 sm:pt-8 sm:pb-10"
        >
          {/* Section number */}
          <div className="mb-4 flex items-center gap-3">
            <span className="text-xs font-mono text-white/20 tracking-wider">
              {sectionNumber}
            </span>
            <span className="text-white/10">|</span>
            <span className="text-xs text-white/15 tracking-wider uppercase">
              Section {index + 1} of {totalSections}
            </span>
          </div>

          {/* Section title */}
          <h2
            className={cn(
              "text-balance font-semibold tracking-tight text-white",
              headingClass
            )}
          >
            {section.title}
          </h2>

          {/* Section content */}
          <div className="mt-6 text-base leading-[1.9] text-white/55 sm:text-[17px] sm:leading-[2]">
            <MarkdownContent content={unifiedContent} />
          </div>

          {/* Video player */}
          {section.videoUrl && (
            <div className="mt-8">
              <div className="rounded-xl overflow-hidden border border-white/[0.06] bg-black/30">
                <VideoPlayer src={section.videoUrl} title="Visualization" />
                {section.vizId && <VideoFeedback vizId={section.vizId} />}
              </div>
            </div>
          )}
        </motion.div>
      </div>

      {/* Bottom gradient fade for depth */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-black/40 to-transparent" />

      {/* Top edge highlight */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/[0.12] to-transparent" />
    </motion.section>
  );
}
