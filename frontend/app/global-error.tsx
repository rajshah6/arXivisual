"use client";

/**
 * Last-resort boundary for failures in the root layout itself. Must render
 * its own <html>/<body>; keeps the background black so a crash never
 * flashes a white page.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#000", color: "rgba(255,255,255,0.8)", fontFamily: "system-ui, sans-serif" }}>
        <div style={{ maxWidth: 560, margin: "0 auto", padding: "96px 24px" }}>
          <h1 style={{ fontSize: 22, fontWeight: 500 }}>arXivisual hit an error.</h1>
          <p style={{ opacity: 0.6, fontSize: 14, lineHeight: 1.6 }}>{error.message}</p>
          <button
            type="button"
            onClick={reset}
            style={{ marginTop: 24, padding: "10px 20px", borderRadius: 12, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.08)", color: "#fff", cursor: "pointer" }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
