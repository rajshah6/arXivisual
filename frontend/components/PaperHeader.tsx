"use client";

import type { Paper } from "@/lib/types";

type PaperHeaderProps = {
  paper: Paper;
  /** Show the full abstract (default: true) */
  showAbstract?: boolean;
  /** Truncate abstract after this many characters (0 = no truncation) */
  abstractMaxLength?: number;
  /** Additional className */
  className?: string;
};

export function PaperHeader({
  paper,
  showAbstract = true,
  abstractMaxLength = 0,
  className = "",
}: PaperHeaderProps) {
  const arxivUrl = `https://arxiv.org/abs/${paper.paper_id}`;
  const pdfUrl = paper.pdf_url || `https://arxiv.org/pdf/${paper.paper_id}.pdf`;

  const displayAbstract =
    abstractMaxLength > 0 && paper.abstract.length > abstractMaxLength
      ? paper.abstract.slice(0, abstractMaxLength) + "..."
      : paper.abstract;

  return (
    <header className={`space-y-4 ${className}`}>
      {/* Title */}
      <h1 className="text-balance text-2xl font-semibold tracking-tight text-white/90 sm:text-3xl lg:text-4xl">
        {paper.title}
      </h1>

      {/* Authors */}
      <div className="flex flex-wrap items-center gap-2">
        {paper.authors.slice(0, 5).map((author, i) => (
          <span
            key={i}
            className="rounded-full bg-white/[0.04] px-3 py-1 text-sm text-white/55 border border-white/[0.06]"
          >
            {author}
          </span>
        ))}
        {paper.authors.length > 5 && (
          <span className="rounded-full bg-white/[0.04] px-3 py-1 text-sm text-white/40 italic border border-white/[0.06]">
            et al.
          </span>
        )}
      </div>

      {/* Paper ID and links */}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="rounded-lg bg-white/[0.04] px-3 py-1.5 font-mono text-white/50 border border-white/[0.06]">
          arXiv:{paper.paper_id}
        </span>
        <a
          href={arxivUrl}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg bg-white/[0.04] px-3 py-1.5 text-white/55 border border-white/[0.06] transition hover:bg-white/[0.07] hover:text-white/80 hover:border-white/[0.12]"
        >
          View on arXiv
        </a>
        <a
          href={pdfUrl}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg bg-white/[0.04] px-3 py-1.5 text-white/55 border border-white/[0.06] transition hover:bg-white/[0.07] hover:text-white/80 hover:border-white/[0.12]"
        >
          Download PDF
        </a>
        {paper.html_url && (
          <a
            href={paper.html_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg bg-white/[0.04] px-3 py-1.5 text-white/55 border border-white/[0.06] transition hover:bg-white/[0.07] hover:text-white/80 hover:border-white/[0.12]"
          >
            HTML Version
          </a>
        )}
      </div>

      {/* Abstract */}
      {showAbstract && paper.abstract && (
        <div className="rounded-xl bg-white/[0.04] p-5 border border-white/[0.06]">
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-white/30">
            Abstract
          </div>
          <p className="text-sm leading-7 text-white/55 sm:text-base">
            {displayAbstract}
          </p>
        </div>
      )}
    </header>
  );
}

/**
 * Compact version of the paper header for use in lists or sidebars.
 */
type CompactPaperHeaderProps = {
  paper: Paper;
  onClick?: () => void;
  className?: string;
};

export function CompactPaperHeader({
  paper,
  onClick,
  className = "",
}: CompactPaperHeaderProps) {
  const Wrapper = onClick ? "button" : "div";

  return (
    <Wrapper
      onClick={onClick}
      className={`w-full text-left rounded-xl bg-white/[0.04] p-4 border border-white/[0.06] transition ${
        onClick ? "hover:bg-white/[0.07] hover:border-white/[0.12] cursor-pointer" : ""
      } ${className}`}
    >
      <div className="text-xs text-white/30 font-mono">
        arXiv:{paper.paper_id}
      </div>
      <h3 className="mt-1 text-sm font-medium text-white/80 line-clamp-2">
        {paper.title}
      </h3>
      <div className="mt-2 text-xs text-white/40 line-clamp-1">
        {paper.authors.slice(0, 3).join(", ")}
        {paper.authors.length > 3 && ` +${paper.authors.length - 3} more`}
      </div>
    </Wrapper>
  );
}

/**
 * Paper metadata stats (section count, equation count, etc.)
 */
type PaperStatsProps = {
  paper: Paper;
  className?: string;
};

export function PaperStats({ paper, className = "" }: PaperStatsProps) {
  const sectionCount = paper.sections.length;
  const equationCount = paper.sections.reduce(
    (acc, s) => acc + (s.equations?.length || 0),
    0
  );
  const videoCount = paper.sections.filter((s) => s.video_url).length;

  return (
    <div className={`flex flex-wrap gap-4 ${className}`}>
      <div className="rounded-lg bg-white/[0.04] px-3 py-2 border border-white/[0.06]">
        <div className="text-lg font-semibold text-white/90">{sectionCount}</div>
        <div className="text-xs text-white/40">Sections</div>
      </div>
      <div className="rounded-lg bg-white/[0.04] px-3 py-2 border border-white/[0.06]">
        <div className="text-lg font-semibold text-white/90">{equationCount}</div>
        <div className="text-xs text-white/40">Equations</div>
      </div>
      <div className="rounded-lg bg-white/[0.04] px-3 py-2 border border-white/[0.06]">
        <div className="text-lg font-semibold text-white/90">{videoCount}</div>
        <div className="text-xs text-white/40">Visualizations</div>
      </div>
    </div>
  );
}
