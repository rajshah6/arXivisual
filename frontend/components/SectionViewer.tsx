"use client";

import { useCallback, useState, useMemo, useEffect } from "react";
import { motion, AnimatePresence, PanInfo } from "framer-motion";
import { VideoPlayer } from "@/components/VideoPlayer";
import { MarkdownContent } from "@/components/MarkdownContent";
import { FloatingDock } from "@/components/ui/floating-dock";
import { cn } from "@/lib/utils";

export type SectionModel = {
  id: string;
  title: string;
  content: string;
  level?: 1 | 2 | 3;
  equations?: string[];
  videoUrl?: string;
};

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

const SectionIcon = ({ index }: { index: number }) => (
  <span className="text-sm font-semibold">{index + 1}</span>
);

export function SectionViewer({ sections }: { sections: SectionModel[] }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const activeSection = sections[activeIndex];

  const unifiedContent = useMemo(
    () =>
      activeSection
        ? mergeContentWithEquations(activeSection.content, activeSection.equations)
        : "",
    [activeSection]
  );

  const goToSection = useCallback(
    (index: number) => {
      if (index >= 0 && index < sections.length) {
        setActiveIndex(index);
      }
    },
    [sections.length]
  );

  const goNext = useCallback(() => {
    if (activeIndex < sections.length - 1) {
      setActiveIndex(activeIndex + 1);
    }
  }, [activeIndex, sections.length]);

  const goPrev = useCallback(() => {
    if (activeIndex > 0) {
      setActiveIndex(activeIndex - 1);
    }
  }, [activeIndex]);

  const dockItems = sections.map((section, idx) => ({
    id: section.id,
    title: section.title,
    icon: <SectionIcon index={idx} />,
  }));

  const progress = sections.length > 1 ? (activeIndex / (sections.length - 1)) * 100 : 100;

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        goNext();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        goPrev();
      } else if (e.key === "Home") {
        e.preventDefault();
        goToSection(0);
      } else if (e.key === "End") {
        e.preventDefault();
        goToSection(sections.length - 1);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [goNext, goPrev, goToSection, sections.length]);

  // Swipe gesture handler
  const handleDragEnd = useCallback(
    (_: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => {
      const threshold = 50;
      if (info.offset.x < -threshold) {
        goNext();
      } else if (info.offset.x > threshold) {
        goPrev();
      }
    },
    [goNext, goPrev]
  );

  if (!activeSection) return null;

  return (
    <div className="relative">
      {/* Progress bar at top */}
      <div className="sticky top-0 z-30 bg-black/80 backdrop-blur-2xl border-b border-white/[0.06]">
        <div className="h-1 bg-white/[0.03]">
          <motion.div
            className="h-full bg-gradient-to-r from-white/40 to-white/20"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.4, ease: "easeOut" }}
          />
        </div>
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-sm text-white/30">Section</span>
            <span className="font-mono text-white/90 font-medium">
              {activeIndex + 1} / {sections.length}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={goPrev}
              disabled={activeIndex === 0}
              className={cn(
                "p-2 rounded-lg border transition-all duration-200",
                activeIndex === 0
                  ? "border-white/[0.04] text-white/15 cursor-not-allowed"
                  : "border-white/[0.08] text-white/50 hover:bg-white/[0.06] hover:text-white/80"
              )}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <button
              onClick={goNext}
              disabled={activeIndex === sections.length - 1}
              className={cn(
                "p-2 rounded-lg border transition-all duration-200",
                activeIndex === sections.length - 1
                  ? "border-white/[0.04] text-white/15 cursor-not-allowed"
                  : "border-white/[0.08] text-white/50 hover:bg-white/[0.06] hover:text-white/80"
              )}
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Main content area */}
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="grid lg:grid-cols-12 gap-8">
          {/* Sidebar with mini-nav */}
          <aside className="lg:col-span-3">
            <div className="lg:sticky lg:top-24">
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="rounded-2xl bg-white/[0.03] p-4 border border-white/[0.06] backdrop-blur-xl"
              >
                <div className="text-xs font-medium text-white/30 uppercase tracking-wider mb-3">
                  Sections
                </div>
                <nav className="space-y-1 max-h-[60vh] overflow-y-auto scrollbar-thin scrollbar-thumb-white/10">
                  {sections.map((section, idx) => {
                    const isActive = idx === activeIndex;
                    return (
                      <button
                        key={section.id}
                        onClick={() => goToSection(idx)}
                        className={cn(
                          "w-full text-left px-3 py-2 rounded-lg text-sm transition-all duration-200 flex items-center gap-2",
                          isActive
                            ? "bg-white/[0.08] text-white/90 border border-white/[0.12]"
                            : "text-white/40 hover:text-white/60 hover:bg-white/[0.03]"
                        )}
                      >
                        <span
                          className={cn(
                            "w-6 h-6 rounded-md flex items-center justify-center text-xs font-medium border shrink-0",
                            isActive
                              ? "bg-white/[0.10] text-white/80 border-white/[0.15]"
                              : "bg-white/[0.03] text-white/30 border-white/[0.06]"
                          )}
                        >
                          {idx + 1}
                        </span>
                        <span className="truncate">{section.title}</span>
                      </button>
                    );
                  })}
                </nav>
              </motion.div>

              {/* Navigation hints */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="mt-4 rounded-xl bg-white/[0.03] p-4 border border-white/[0.06] space-y-4"
              >
                {/* Mobile swipe hint */}
                <div className="lg:hidden">
                  <div className="text-xs font-medium text-white/30 mb-2">Navigation</div>
                  <div className="flex items-center gap-2 text-xs text-white/25">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
                    </svg>
                    <span>Swipe left/right to navigate</span>
                  </div>
                </div>

                {/* Desktop keyboard hints */}
                <div className="hidden lg:block">
                  <div className="text-xs font-medium text-white/30 mb-3">Keyboard Shortcuts</div>
                  <div className="grid grid-cols-2 gap-2 text-xs text-white/25">
                    <div className="flex items-center gap-1.5">
                      <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] font-mono text-[10px] text-white/40">&#8592;</kbd>
                      <span>Previous</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] font-mono text-[10px] text-white/40">&#8594;</kbd>
                      <span>Next</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] font-mono text-[10px] text-white/40">Home</kbd>
                      <span>First</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] font-mono text-[10px] text-white/40">End</kbd>
                      <span>Last</span>
                    </div>
                  </div>
                </div>
              </motion.div>
            </div>
          </aside>

          {/* Main section content */}
          <main className="lg:col-span-9">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeSection.id}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.3, ease: "easeOut" }}
                drag="x"
                dragConstraints={{ left: 0, right: 0 }}
                dragElastic={0.1}
                onDragEnd={handleDragEnd}
                className="space-y-6 cursor-grab active:cursor-grabbing"
              >
                {/* Section header */}
                <div className="rounded-2xl bg-white/[0.04] backdrop-blur-xl border border-white/[0.08] p-6">
                  <div className="flex items-start gap-4">
                    <motion.div
                      initial={{ scale: 0.8 }}
                      animate={{ scale: 1 }}
                      className="h-12 w-12 rounded-xl bg-white/[0.06] border border-white/[0.10] flex items-center justify-center shrink-0"
                    >
                      <span className="text-lg font-bold text-white/70">{activeIndex + 1}</span>
                    </motion.div>
                    <div>
                      <h2 className="text-2xl sm:text-3xl font-medium text-white/90 tracking-tight">
                        {activeSection.title}
                      </h2>
                      <div className="mt-2 flex items-center gap-3 text-sm text-white/30">
                        <span>
                          {activeSection.content.split(/\s+/).length} words
                        </span>
                        {activeSection.videoUrl && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-white/20" />
                            <span className="text-white/50">Has visualization</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Video section */}
                {activeSection.videoUrl && (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.98 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: 0.1 }}
                    className="rounded-2xl overflow-hidden border border-white/[0.08] shadow-2xl shadow-black/40"
                  >
                    <div className="bg-white/[0.03] px-4 py-3 border-b border-white/[0.06]">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-white/20" />
                        <span className="text-xs text-white/40 font-mono tracking-wider uppercase">Visualization</span>
                      </div>
                    </div>
                    <VideoPlayer src={activeSection.videoUrl} title="Concept Visualization" />
                  </motion.div>
                )}

                {/* Content section */}
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.2 }}
                  className="rounded-2xl bg-white/[0.03] p-6 sm:p-8 border border-white/[0.06]"
                >
                  <div className="prose prose-invert prose-lg max-w-none">
                    <div className="text-white/55 leading-relaxed">
                      <MarkdownContent content={unifiedContent} />
                    </div>
                  </div>
                </motion.div>

                {/* Navigation buttons */}
                <div className="flex items-center justify-between pt-4">
                  <button
                    onClick={goPrev}
                    disabled={activeIndex === 0}
                    className={cn(
                      "group flex items-center gap-3 px-5 py-3 rounded-xl transition-all duration-200",
                      activeIndex === 0
                        ? "opacity-40 cursor-not-allowed"
                        : "bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] hover:border-white/[0.12]"
                    )}
                  >
                    <svg
                      className="w-5 h-5 text-white/50 group-hover:-translate-x-1 transition-transform"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    <div className="text-left">
                      <div className="text-xs text-white/30">Previous</div>
                      <div className="text-sm text-white/60 max-w-[150px] truncate">
                        {activeIndex > 0 ? sections[activeIndex - 1].title : "\u2014"}
                      </div>
                    </div>
                  </button>

                  <button
                    onClick={goNext}
                    disabled={activeIndex === sections.length - 1}
                    className={cn(
                      "group flex items-center gap-3 px-5 py-3 rounded-xl transition-all duration-200",
                      activeIndex === sections.length - 1
                        ? "opacity-40 cursor-not-allowed"
                        : "bg-white/[0.05] hover:bg-white/[0.08] border border-white/[0.08] hover:border-white/[0.14]"
                    )}
                  >
                    <div className="text-right">
                      <div className="text-xs text-white/30">Next</div>
                      <div className="text-sm text-white/60 max-w-[150px] truncate">
                        {activeIndex < sections.length - 1 ? sections[activeIndex + 1].title : "\u2014"}
                      </div>
                    </div>
                    <svg
                      className="w-5 h-5 text-white/50 group-hover:translate-x-1 transition-transform"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                </div>
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
      </div>

      {/* Floating dock for quick navigation */}
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
        <FloatingDock
          items={dockItems}
          activeId={activeSection.id}
          onItemClick={(id) => {
            const idx = sections.findIndex((s) => s.id === id);
            if (idx >= 0) goToSection(idx);
          }}
        />
      </div>

      {/* Spacer for floating dock */}
      <div className="h-24" />
    </div>
  );
}
