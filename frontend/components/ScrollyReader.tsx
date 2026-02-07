"use client";

import { useCallback, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { ScrollySection, type ScrollySectionModel } from "./ScrollySection";
import { cn } from "@/lib/utils";

function safeEscapeForAttr(value: string): string {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const css = (globalThis as any).CSS as
    | { escape?: (v: string) => string }
    | undefined;
  if (css?.escape) return css.escape(value);
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

export function ScrollyReader({
  sections,
}: {
  sections: ScrollySectionModel[];
}) {
  const [activeId, setActiveId] = useState<string | null>(
    sections[0]?.id ?? null
  );

  const items = useMemo(
    () =>
      sections.map((s, i) => ({
        id: s.id,
        title: s.title,
        index: i,
        level: s.level ?? 1,
      })),
    [sections]
  );

  const onActiveChange = useCallback((id: string, isActive: boolean) => {
    if (isActive) setActiveId(id);
  }, []);

  const scrollTo = useCallback((id: string) => {
    const escaped = safeEscapeForAttr(id);
    const el = document.querySelector(
      `[data-section-id="${escaped}"]`
    ) as HTMLElement | null;
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const activeIndex = items.findIndex((it) => it.id === activeId);
  const progress = items.length > 1 ? activeIndex / (items.length - 1) : 0;

  return (
    <div className="grid gap-10 lg:grid-cols-12 lg:items-start">
      {/* Sidebar Navigation */}
      <aside className="lg:col-span-4">
        <div className="lg:sticky lg:top-10">
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5 }}
            className="rounded-2xl bg-white/[0.04] p-6 border border-white/[0.08] backdrop-blur-xl"
          >
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-white/80">Outline</div>
              <div className="text-xs text-white/30">
                {activeIndex + 1} / {items.length}
              </div>
            </div>

            {/* Progress bar */}
            <div className="mt-4 h-1 rounded-full bg-white/[0.05] overflow-hidden">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-white/40 to-white/20"
                initial={{ width: 0 }}
                animate={{ width: `${progress * 100}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>

            <p className="mt-4 text-sm leading-6 text-white/35">
              Click to navigate. The active section highlights as you scroll.
            </p>

            <nav className="mt-5">
              <ul className="space-y-1">
                {items.map((it) => {
                  const isActive = activeId === it.id;
                  const indent =
                    it.level === 1 ? "" : it.level === 2 ? "pl-3" : "pl-6";

                  return (
                    <li key={it.id} className={indent}>
                      <motion.button
                        type="button"
                        onClick={() => scrollTo(it.id)}
                        whileHover={{ x: 2 }}
                        whileTap={{ scale: 0.98 }}
                        className={cn(
                          "group w-full rounded-lg px-3 py-2.5 text-left text-sm border transition-all duration-200",
                          isActive
                            ? "bg-white/[0.08] text-white/90 border-white/[0.15]"
                            : "bg-transparent text-white/45 border-transparent hover:bg-white/[0.04] hover:text-white/70 hover:border-white/[0.08]"
                        )}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <span className="min-w-0 truncate font-medium">
                            {it.title}
                          </span>
                          <span
                            className={cn(
                              "shrink-0 rounded-md px-2 py-0.5 text-[10px] font-medium border transition-all duration-200",
                              isActive
                                ? "bg-white/[0.10] text-white/70 border-white/[0.12]"
                                : "bg-white/[0.03] text-white/30 border-white/[0.06] group-hover:text-white/50"
                            )}
                          >
                            {it.index + 1}
                          </span>
                        </div>
                      </motion.button>
                    </li>
                  );
                })}
              </ul>
            </nav>
          </motion.div>

          {/* Tip */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.2 }}
            className="mt-4 rounded-xl bg-white/[0.03] p-4 border border-white/[0.06]"
          >
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-white/30">Tip:</span>
              <span className="text-xs text-white/25">
                Scroll to navigate through sections
              </span>
            </div>
          </motion.div>
        </div>
      </aside>

      {/* Main Content */}
      <div className="lg:col-span-8">
        <div className="space-y-6">
          {sections.map((s, i) => (
            <ScrollySection
              key={s.id}
              section={s}
              index={i}
              onActiveChange={onActiveChange}
            />
          ))}
        </div>

        {/* End of content indicator */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="mt-10 flex items-center justify-center gap-3 text-sm text-white/25"
        >
          <div className="h-px flex-1 bg-gradient-to-r from-transparent to-white/[0.06]" />
          <span>End of paper</span>
          <div className="h-px flex-1 bg-gradient-to-l from-transparent to-white/[0.06]" />
        </motion.div>
      </div>
    </div>
  );
}
