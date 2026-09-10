"use client";

import { useSyncExternalStore } from "react";
import { motion } from "framer-motion";
import { getStoredConsent, setClarityConsent, type ConsentChoice } from "@/lib/clarity-consent";

/**
 * Cookie notice for Microsoft Clarity (session replays + heatmaps). Rendered
 * by app/layout.tsx only when NEXT_PUBLIC_CLARITY_PROJECT_ID is set.
 *
 * Clarity runs cookieless until the visitor accepts; Decline keeps it that
 * way. Either answer is remembered in localStorage and the bar stays hidden.
 * PostHog is cookieless by construction and needs no notice.
 *
 * Never blocks the page: a fixed strip at the bottom, no overlay, no focus
 * trap. Visibility comes through useSyncExternalStore so the server renders
 * nothing (no hydration mismatch) and no state is set inside an effect.
 */

// Tiny external store: "has the visitor answered?" lives in localStorage.
const listeners = new Set<() => void>();
function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
function readOpen(): boolean {
  return getStoredConsent() === null;
}
function readServerOpen(): boolean {
  return false;
}

export function ConsentBar() {
  const open = useSyncExternalStore(subscribe, readOpen, readServerOpen);
  if (!open) return null;

  function choose(choice: ConsentChoice) {
    setClarityConsent(choice);
    listeners.forEach((listener) => listener());
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.8, ease: "easeOut" }}
      role="region"
      aria-label="Cookie notice"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-center px-4 pb-4 sm:pb-6"
    >
      <div className="pointer-events-auto flex w-full max-w-2xl flex-col gap-3 rounded-2xl border border-white/[0.08] bg-black/70 p-4 shadow-lg shadow-black/30 backdrop-blur-xl sm:flex-row sm:items-center sm:gap-5 sm:px-5">
        <p className="text-sm leading-relaxed text-white/50">
          We use Microsoft Clarity to see how the site is used (session replays,
          heatmaps). It sets cookies only if you accept.{" "}
          <a
            href="https://learn.microsoft.com/clarity/setup-and-installation/clarity-cookies"
            target="_blank"
            rel="noopener noreferrer"
            className="text-white/70 underline decoration-white/20 underline-offset-4 transition-colors hover:text-white"
          >
            What it stores
          </a>
        </p>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => choose("denied")}
            className="rounded-full border border-white/[0.08] px-4 py-2 text-sm text-white/50 transition-colors hover:bg-white/[0.06] hover:text-white/80"
          >
            Decline
          </button>
          <button
            type="button"
            onClick={() => choose("granted")}
            className="rounded-full border border-white/[0.15] bg-white/[0.10] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/[0.16]"
          >
            Accept
          </button>
        </div>
      </div>
    </motion.div>
  );
}
