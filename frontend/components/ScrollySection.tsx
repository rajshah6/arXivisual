"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useMotionValue, useMotionTemplate } from "framer-motion";
import { VideoPlayer } from "@/components/VideoPlayer";
import { MarkdownContent } from "@/components/MarkdownContent";
import { cn } from "@/lib/utils";

export type ScrollySectionModel = {
  id: string;
  title: string;
  content: string;
  level?: 1 | 2 | 3;
  equations?: string[];
  videoUrl?: string;
};

function mergeContentWithEquations(content: string, equations?: string[]): string {
  if (!equations || equations.length === 0) {
    return content;
  }

  let result = content;
  const equationsToAppend: string[] = [];

  for (const eq of equations) {
    const normalizedEq = eq.replace(/\s+/g, '');
    const normalizedContent = result.replace(/\s+/g, '');

    const alreadyPresent =
      normalizedContent.includes(normalizedEq) ||
      normalizedContent.includes(`$${normalizedEq}$`) ||
      normalizedContent.includes(`$$${normalizedEq}$$`);

    if (!alreadyPresent) {
      equationsToAppend.push(eq);
    }
  }

  if (equationsToAppend.length > 0) {
    const equationBlocks = equationsToAppend.map(eq => {
      const trimmed = eq.trim();
      if (trimmed.startsWith('$$') && trimmed.endsWith('$$')) {
        return trimmed;
      }
      if (trimmed.startsWith('$') && trimmed.endsWith('$') && !trimmed.startsWith('$$')) {
        return `$${trimmed}$`;
      }
      return `$$${trimmed}$$`;
    }).join('\n\n');

    result = `${result}\n\n${equationBlocks}`;
  }

  return result;
}

export function ScrollySection({
  section,
  index,
  onActiveChange,
}: {
  section: ScrollySectionModel;
  index?: number;
  onActiveChange?: (sectionId: string, isActive: boolean) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  const [hasEntered, setHasEntered] = useState(false);
  const [isActive, setIsActive] = useState(false);
  const activeRef = useRef(false);

  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  function handleMouseMove({
    currentTarget,
    clientX,
    clientY,
  }: React.MouseEvent<HTMLElement>) {
    const { left, top } = currentTarget.getBoundingClientRect();
    mouseX.set(clientX - left);
    mouseY.set(clientY - top);
  }

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

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (!entry) return;

        if (entry.isIntersecting) setHasEntered(true);
        // Activate if >=30% visible OR if the section top is near the viewport top
        // (handles sections taller than viewport that never reach 0.55 ratio)
        const rect = entry.boundingClientRect;
        const topNearViewport = rect.top >= 0 && rect.top < window.innerHeight * 0.4;
        const nextActive =
          entry.isIntersecting && (entry.intersectionRatio >= 0.3 || topNearViewport);

        if (activeRef.current !== nextActive) {
          activeRef.current = nextActive;
          setIsActive(nextActive);
          onActiveChange?.(section.id, nextActive);
        }
      },
      {
        threshold: [0.1, 0.2, 0.3, 0.5, 0.75],
        rootMargin: "0px 0px -25% 0px",
      }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [onActiveChange, section.id]);

  return (
    <motion.section
      ref={ref}
      data-section-id={section.id}
      initial={{ opacity: 0, y: 30 }}
      animate={{
        opacity: hasEntered ? 1 : 0,
        y: hasEntered ? 0 : 30,
      }}
      transition={{ duration: 0.6, ease: "easeOut" }}
      onMouseMove={handleMouseMove}
      className={cn(
        "group relative rounded-2xl border backdrop-blur-sm overflow-hidden scroll-mt-8",
        isActive
          ? "bg-white/[0.06] border-white/[0.15]"
          : "bg-white/[0.03] border-white/[0.06]",
        "transition-all duration-500 ease-out"
      )}
    >
      {/* Spotlight gradient overlay */}
      <motion.div
        className="pointer-events-none absolute -inset-px rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500"
        style={{
          background: useMotionTemplate`
            radial-gradient(
              500px circle at ${mouseX}px ${mouseY}px,
              ${isActive ? "rgba(255, 255, 255, 0.06)" : "rgba(255, 255, 255, 0.04)"},
              transparent 40%
            )
          `,
        }}
      />

      {/* Active indicator bar */}
      <motion.div
        className="absolute left-0 top-0 bottom-0 w-1 rounded-l-2xl bg-gradient-to-b from-white/40 to-white/10"
        initial={{ scaleY: 0 }}
        animate={{ scaleY: isActive ? 1 : 0 }}
        transition={{ duration: 0.3 }}
        style={{ transformOrigin: "top" }}
      />

      <div className="relative px-6 py-6 sm:px-8 sm:py-8">
        <div className="flex items-start gap-4 sm:gap-5">
          {/* Section number badge */}
          <motion.div
            whileHover={{ scale: 1.1 }}
            className={cn(
              "mt-1 grid h-10 w-10 shrink-0 place-items-center rounded-xl border transition-all duration-300",
              isActive
                ? "bg-white/[0.10] border-white/[0.15]"
                : "bg-white/[0.04] border-white/[0.06]"
            )}
          >
            <span
              className={cn(
                "text-sm font-semibold transition-colors duration-300",
                isActive ? "text-white/80" : "text-white/40"
              )}
            >
              {(index ?? 0) + 1}
            </span>
          </motion.div>

          <div className="min-w-0 flex-1">
            {/* Section title */}
            <motion.h2
              className={cn(
                "text-balance font-semibold tracking-tight transition-colors duration-300",
                headingClass,
                isActive ? "text-white" : "text-white/90"
              )}
              layout
            >
              {section.title}
            </motion.h2>

            {/* Section content */}
            <div className="mt-6 text-base leading-[1.9] text-white/55 sm:text-[17px] sm:leading-[2]">
              <MarkdownContent content={unifiedContent} />
            </div>

            {/* Video player */}
            {section.videoUrl && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2, duration: 0.4 }}
                className="mt-6"
              >
                <div className="rounded-xl overflow-hidden border border-white/[0.06] bg-black/30">
                  <VideoPlayer
                    src={section.videoUrl}
                    title="Visualization"
                    pauseWhenInactive={!isActive}
                  />
                </div>
              </motion.div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom gradient for depth */}
      <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
    </motion.section>
  );
}
