"use client";

import { useState, useSyncExternalStore } from "react";
import { sendVideoFeedback } from "@/lib/api";

const DOWN_REASONS = [
  "Overlapping text",
  "Elements cut off",
  "Audio issue",
  "Wrong concept",
];

type Stage = "vote" | "reason" | "done";

/**
 * Thumbs verdict on one rendered visualization. Every vote is labeled ground
 * truth for the backend's visual-QA loop, so keep friction minimal: one tap
 * for 👍, one tap + optional reason chip for 👎. A localStorage guard keeps
 * repeat votes from the same browser out of the dataset.
 */
export function VideoFeedback({ vizId }: { vizId: string }) {
  const storageKey = `arxivisual-fb-${vizId}`;
  const [stage, setStage] = useState<Stage>("vote");
  const [thanked, setThanked] = useState(false);
  // SSR renders the buttons (server snapshot false); after hydration the
  // client snapshot hides them if this browser already voted. localStorage
  // never changes behind our back, so subscribe is a no-op.
  const alreadyVoted = useSyncExternalStore(
    () => () => {},
    () => {
      try {
        return localStorage.getItem(storageKey) !== null;
      } catch {
        return false; // storage unavailable — backend rate limit caps abuse
      }
    },
    () => false
  );

  function submitVote(v: "up" | "down", reason?: string) {
    // Exactly ONE row per user action: a bare 👎 only opens the reason stage,
    // and the POST fires when that stage resolves (chip or Skip). Sending on
    // the initial 👎 too would double-count downvotes in the labeled dataset.
    // Fire-and-forget: a lost vote is not worth interrupting reading for.
    sendVideoFeedback(vizId, v, reason).catch(() => {});
    try {
      localStorage.setItem(storageKey, "1");
    } catch {
      // Storage unavailable (private mode) — the vote still counted.
    }
    setThanked(true);
    setStage("done");
  }

  if (alreadyVoted && stage === "vote") return null;

  if (stage === "done") {
    return thanked ? (
      <p className="mt-2 text-[11px] text-white/30">
        Thanks — this helps improve future renders.
      </p>
    ) : null;
  }

  if (stage === "reason") {
    return (
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-white/30">What went wrong?</span>
        {DOWN_REASONS.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => submitVote("down", r)}
            className="rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[11px] text-white/50 transition hover:bg-white/[0.08] hover:text-white/80"
          >
            {r}
          </button>
        ))}
        <button
          type="button"
          onClick={() => submitVote("down")}
          className="px-1.5 py-1 text-[11px] text-white/25 transition hover:text-white/50"
        >
          Skip
        </button>
      </div>
    );
  }

  return (
    <div className="mt-2 flex items-center gap-2">
      <span className="text-[11px] text-white/30">Was this visualization helpful?</span>
      <button
        type="button"
        aria-label="Yes, helpful"
        onClick={() => submitVote("up")}
        className="rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-[12px] text-white/50 transition hover:bg-white/[0.08] hover:text-white/80"
      >
        👍
      </button>
      <button
        type="button"
        aria-label="No, something is off"
        onClick={() => setStage("reason")}
        className="rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-[12px] text-white/50 transition hover:bg-white/[0.08] hover:text-white/80"
      >
        👎
      </button>
    </div>
  );
}
