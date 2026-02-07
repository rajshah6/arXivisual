"use client";

type LoadingStateProps = {
  message?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
};

const sizeClasses = {
  sm: { spinner: "h-8 w-8", text: "text-xs" },
  md: { spinner: "h-12 w-12", text: "text-sm" },
  lg: { spinner: "h-16 w-16", text: "text-base" },
};

export function LoadingState({
  message = "Loading...",
  size = "md",
  className = "",
}: LoadingStateProps) {
  const { spinner, text } = sizeClasses[size];

  return (
    <div
      className={`flex flex-col items-center justify-center py-20 ${className}`}
    >
      <div
        className={`${spinner} animate-spin rounded-full border-4 border-white/[0.08] border-t-white/60`}
      />
      <p className={`mt-4 ${text} text-white/40`}>{message}</p>
    </div>
  );
}

/**
 * Inline loading spinner for use within other components.
 */
export function LoadingSpinner({
  size = "md",
  className = "",
}: {
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const { spinner } = sizeClasses[size];

  return (
    <div
      className={`${spinner} animate-spin rounded-full border-4 border-white/[0.08] border-t-white/60 ${className}`}
    />
  );
}

/**
 * Skeleton loader for text content.
 */
export function TextSkeleton({
  lines = 3,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-3 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-4 animate-pulse rounded bg-white/[0.06]"
          style={{ width: `${Math.random() * 40 + 60}%` }}
        />
      ))}
    </div>
  );
}

/**
 * Card-style loading placeholder.
 */
export function CardSkeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`rounded-2xl bg-white/[0.04] p-6 border border-white/[0.06] ${className}`}
    >
      <div className="h-6 w-1/3 animate-pulse rounded bg-white/[0.06]" />
      <div className="mt-4 space-y-3">
        <div className="h-4 w-full animate-pulse rounded bg-white/[0.06]" />
        <div className="h-4 w-4/5 animate-pulse rounded bg-white/[0.06]" />
        <div className="h-4 w-3/5 animate-pulse rounded bg-white/[0.06]" />
      </div>
    </div>
  );
}
