"use client";

import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (
        el: HTMLElement,
        opts: {
          sitekey: string;
          callback: (token: string) => void;
          "expired-callback"?: () => void;
          "error-callback"?: () => void;
          appearance?: "always" | "execute" | "interaction-only";
          theme?: "light" | "dark" | "auto";
        }
      ) => string;
      remove: (widgetId: string) => void;
    };
  }
}

const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js";
export const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "";

/** Single source of truth for "is human verification on in this build". */
export function isTurnstileConfigured(): boolean {
  return Boolean(TURNSTILE_SITE_KEY);
}

const LOAD_HINT_MS = 10_000;

/**
 * Cloudflare Turnstile widget. Produces a token the backend verifies before
 * accepting a new-paper request — the verification is server-side, so this
 * only exists to mint the token; a script that skips the widget gets a 403.
 *
 * Renders nothing when no site key is configured (local dev / pre-rollout);
 * the backend skips verification in that case too.
 */
export function TurnstileWidget({
  onToken,
}: {
  onToken: (token: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const onTokenRef = useRef(onToken);
  // If the Turnstile script is blocked (content blockers, strict networks)
  // the button would sit on "Verifying…" forever; after a while say why.
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    onTokenRef.current = onToken;
  }, [onToken]);
  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return;
    const t = setTimeout(() => setSlow(true), LOAD_HINT_MS);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || !containerRef.current) return;
    const container = containerRef.current;
    let widgetId: string | null = null;
    let cancelled = false;

    function render() {
      if (cancelled || !window.turnstile || widgetId !== null) return;
      widgetId = window.turnstile.render(container, {
        sitekey: TURNSTILE_SITE_KEY,
        theme: "dark",
        // interaction-only: invisible for humans, a checkbox only when
        // Cloudflare is unsure — keeps the Start button one tap for readers.
        appearance: "interaction-only",
        callback: (token) => {
          setSlow(false);
          onTokenRef.current(token);
        },
        "expired-callback": () => onTokenRef.current(null),
        "error-callback": () => onTokenRef.current(null),
      });
    }

    if (window.turnstile) {
      render();
    } else {
      let script = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT_SRC}"]`);
      if (!script) {
        script = document.createElement("script");
        script.src = SCRIPT_SRC;
        script.async = true;
        document.head.appendChild(script);
      }
      script.addEventListener("load", render);
    }

    return () => {
      cancelled = true;
      if (widgetId !== null) window.turnstile?.remove(widgetId);
    };
  }, []);

  if (!TURNSTILE_SITE_KEY) return null;
  return (
    <div>
      <div ref={containerRef} className="min-h-[1px]" />
      {slow && (
        <p className="mt-2 text-xs text-white/40">
          Human verification is taking a while to load. If you use a content
          blocker, allow challenges.cloudflare.com and reload.
        </p>
      )}
    </div>
  );
}
