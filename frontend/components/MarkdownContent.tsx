"use client";

import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

type MarkdownContentProps = {
  content: string;
  className?: string;
};

export function MarkdownContent({ content, className = "" }: MarkdownContentProps) {
  const processedContent = preprocessLatex(content);

  return (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
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
        }}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  );
}

function preprocessLatex(content: string): string {
  let processed = normalizeBrokenSmallCaps(content);
  processed = processed.replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => `$${math}$`);
  processed = processed.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => `$$${math}$$`);
  if (!processed.includes('$')) {
    processed = wrapLatexPatterns(processed);
  }
  return processed;
}

function normalizeBrokenSmallCaps(content: string): string {
  // Remove zero-width characters often introduced by PDF/LLM formatting.
  const cleaned = content.replace(/[\u200B-\u200D\uFEFF]/g, "");
  const lines = cleaned.split("\n");
  const out: string[] = [];

  let i = 0;
  while (i < lines.length) {
    const raw = lines[i] ?? "";
    const line = raw.trim();

    // Handle "\textsc" markers and inline variants like "\textscBASE".
    const textscMatch = line.match(/^\\textsc\b\s*([A-Za-z]+)?$/);
    if (textscMatch) {
      const inlineWord = textscMatch[1];
      if (inlineWord) out.push(inlineWord.toUpperCase());
      i += 1;
      continue;
    }

    // Collapse letter-per-line blocks:
    // L\nA\nR\nG\nE -> LARGE
    if (/^[A-Z]$/.test(line)) {
      const letters: string[] = [];
      let j = i;
      while (j < lines.length && /^[A-Z]$/.test((lines[j] ?? "").trim())) {
        letters.push((lines[j] ?? "").trim());
        j += 1;
      }

      if (letters.length >= 2) {
        const word = letters.join("");
        const next = (lines[j] ?? "").trim().toUpperCase();
        // If the next line already contains the collapsed word, skip duplicate.
        if (next === word) {
          j += 1;
        }
        out.push(word);
        i = j;
        continue;
      }
    }

    out.push(raw);
    i += 1;
  }

  // Collapse excessive blank lines introduced by cleanup.
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}

function wrapLatexPatterns(content: string): string {
  let result = content;
  const latexCommandPattern = /\\(?:text|frac|sqrt|sum|prod|int|lim|log|ln|sin|cos|tan|exp|max|min|sup|inf|mathbb|mathcal|mathbf|mathrm|left|right|cdot|times|div|pm|mp|leq|geq|neq|approx|equiv|subset|supset|in|notin|forall|exists|partial|nabla|infty|alpha|beta|gamma|delta|epsilon|theta|lambda|mu|sigma|omega|phi|psi|pi|rho|tau|chi|eta|zeta|xi|kappa|nu|vec|hat|bar|tilde|dot|ddot|overline|underline)(?:\{[^}]*\}|\b)/g;
  const hasLatexCommands = latexCommandPattern.test(result);
  if (hasLatexCommands) {
    result = result.replace(
      /([A-Za-z0-9\s]*\\[a-z]+(?:\{[^}]*\}|\[[^\]]*\])*[A-Za-z0-9_^{}\s\\]*)+/g,
      (match) => {
        if (match.startsWith('$') || match.startsWith('\\(')) {
          return match;
        }
        const isDisplayMath = /[=<>]/.test(match) && match.length > 20;
        return isDisplayMath ? `\n\n$$${match.trim()}$$\n\n` : `$${match.trim()}$`;
      }
    );
  }
  return result;
}
