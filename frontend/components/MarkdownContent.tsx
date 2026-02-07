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
            <p className="mb-4 last:mb-0">{children}</p>
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
            <pre className="mb-4 overflow-x-auto rounded-xl bg-white/[0.02] border border-white/[0.06]">
              {children}
            </pre>
          ),
          ul: ({ children }) => (
            <ul className="mb-4 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-4 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="text-white/70">{children}</li>
          ),
          h1: ({ children }) => (
            <h1 className="mb-3 text-xl font-semibold text-white">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-3 text-lg font-semibold text-white">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-2 text-base font-semibold text-white">{children}</h3>
          ),
          blockquote: ({ children }) => (
            <blockquote className="mb-4 border-l-2 border-white/[0.15] pl-4 italic text-white/50 last:mb-0">
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
  let processed = content;
  processed = processed.replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => `$${math}$`);
  processed = processed.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => `$$${math}$$`);
  if (!processed.includes('$')) {
    processed = wrapLatexPatterns(processed);
  }
  return processed;
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
