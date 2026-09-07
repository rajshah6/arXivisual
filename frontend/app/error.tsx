"use client";

import { useEffect } from "react";
import Link from "next/link";

/**
 * Route-level error boundary for every page under the root layout. Without
 * one, a render-phase throw unmounts the whole tree to Next's white
 * "Application error" screen with nothing to act on.
 */
export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Page crashed:", error);
  }, [error]);

  return (
    <main className="min-h-dvh bg-black text-white/80">
      <div className="mx-auto max-w-xl px-6 py-24">
        <p className="text-sm uppercase tracking-wide text-white/40">Something broke</p>
        <h1 className="mt-3 text-2xl font-medium text-white/90">This page hit an error while rendering.</h1>
        <p className="mt-4 text-sm leading-relaxed text-white/50">
          Your papers and videos are safe — this is a display problem. Try again usually fixes it.
        </p>
        <pre className="mt-6 max-h-40 overflow-auto rounded-lg border border-white/[0.08] bg-white/[0.03] p-3 text-xs text-white/50">
          {error.message}
          {error.digest ? `\n(digest ${error.digest})` : ""}
        </pre>
        <div className="mt-8 flex gap-3">
          <button
            type="button"
            onClick={reset}
            className="rounded-xl border border-white/[0.15] bg-white/[0.08] px-5 py-2.5 text-sm text-white transition hover:bg-white/[0.12]"
          >
            Try again
          </button>
          <Link href="/" className="rounded-xl border border-white/[0.08] px-5 py-2.5 text-sm text-white/60 transition hover:text-white">
            Home
          </Link>
        </div>
      </div>
    </main>
  );
}
