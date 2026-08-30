"use client";

import { useState } from "react";
import { sendSiteFeedback } from "@/lib/api";

/**
 * Compact "suggest a feature / report a problem" box for the paper footer.
 * Collapsed to one line of text until the reader opens it.
 */
export function SiteFeedback() {
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");

  async function submit() {
    const trimmed = comment.trim();
    if (!trimmed || state === "sending") return;
    setState("sending");
    try {
      await sendSiteFeedback(trimmed.slice(0, 2000));
      setState("sent");
    } catch {
      setState("error");
    }
  }

  if (state === "sent") {
    return (
      <p className="text-sm text-white/30">
        Thanks — your suggestion landed. It genuinely shapes what gets built next.
      </p>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-sm text-white/30 underline decoration-white/20 underline-offset-4 transition hover:text-white/60"
      >
        Wish this did something it doesn&apos;t? Suggest a feature
      </button>
    );
  }

  return (
    <div className="w-full max-w-md space-y-2">
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={3}
        maxLength={2000}
        placeholder="What should arXivisual do better? A feature, a paper type it struggles with, anything."
        className="w-full resize-none rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2 text-sm text-white/80 placeholder:text-white/25 focus:border-white/[0.2] focus:outline-none"
      />
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={submit}
          disabled={!comment.trim() || state === "sending"}
          className="rounded-lg border border-white/[0.1] bg-white/[0.06] px-3 py-1.5 text-sm text-white/70 transition hover:bg-white/[0.12] disabled:opacity-40"
        >
          {state === "sending" ? "Sending…" : "Send"}
        </button>
        {state === "error" && (
          <span className="text-xs text-[#f27066]">
            Couldn&apos;t send — try again in a moment.
          </span>
        )}
      </div>
    </div>
  );
}
