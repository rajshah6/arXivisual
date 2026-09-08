"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

// All display normalization (small-caps repair, TeX wrapping, fence repair,
// currency escaping, \[ \] / \( \) delimiters) happens in the backend at
// ingest AND read time (ingestion/text_normalize.py) — one owner, no drift.
type MarkdownContentProps = {
  content: string;
  className?: string;
};

// Hoisted: a new object literal per render defeated react-markdown's own
// memoisation, and this component used to re-run the whole
// remark → rehype → KaTeX pipeline on every unrelated state change (the 2s
// status poll re-parsed every mounted card while the reader scrolled).
const MARKDOWN_COMPONENTS: Components = {
          p: ({ children }) => (
            <p className="mb-6 last:mb-0 leading-[1.9]">{children}</p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-white">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="italic text-white/90">{children}</em>
          ),
          code: ({ children, className }) => {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              return (
                <code className="block overflow-x-auto rounded-lg bg-white/[0.03] border border-white/[0.05] px-4 py-3 text-sm text-white/70">
                  {children}
                </code>
              );
            }
            return (
              <code className="rounded bg-white/[0.06] px-1.5 py-0.5 text-sm text-white/70">
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="mb-6 overflow-x-auto rounded-xl bg-white/[0.02] border border-white/[0.06]">
              {children}
            </pre>
          ),
          ul: ({ children }) => (
            <ul className="mb-6 ml-5 list-disc space-y-2 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-6 ml-5 list-decimal space-y-2 last:mb-0">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="text-white/70 leading-[1.8] pl-1">{children}</li>
          ),
          h1: ({ children }) => (
            <h1 className="mt-8 mb-4 text-xl font-semibold text-white">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mt-6 mb-4 text-lg font-semibold text-white">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mt-5 mb-3 text-base font-semibold text-white">{children}</h3>
          ),
          blockquote: ({ children }) => (
            <blockquote className="mb-6 border-l-2 border-white/[0.15] pl-5 italic text-white/50 last:mb-0">
              {children}
            </blockquote>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              className="text-white/70 underline decoration-white/20 hover:text-white hover:decoration-white/50"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          ),
};

export const MarkdownContent = memo(function MarkdownContent({
  content,
  className = "",
}: MarkdownContentProps) {

  return (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={MARKDOWN_COMPONENTS}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});
