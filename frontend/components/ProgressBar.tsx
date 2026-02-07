"use client";

type ProgressBarProps = {
  /** Progress value between 0 and 1 */
  progress: number;
  /** Optional label to show above the bar */
  label?: string;
  /** Show percentage text */
  showPercent?: boolean;
  /** Size variant */
  size?: "sm" | "md" | "lg";
  /** Color theme */
  theme?: "default" | "success" | "warning" | "error";
  /** Additional className */
  className?: string;
};

const sizeClasses = {
  sm: "h-1.5",
  md: "h-3",
  lg: "h-4",
};

const themeClasses = {
  default: "from-white/40 to-white/20",
  success: "from-[#7dd19b] to-[#7dd19b]/60",
  warning: "from-amber-400/70 to-amber-400/40",
  error: "from-[#f27066] to-[#f27066]/60",
};

export function ProgressBar({
  progress,
  label,
  showPercent = true,
  size = "md",
  theme = "default",
  className = "",
}: ProgressBarProps) {
  // Clamp progress between 0 and 1
  const clampedProgress = Math.max(0, Math.min(1, progress));
  const percent = Math.round(clampedProgress * 100);

  return (
    <div className={className}>
      {(label || showPercent) && (
        <div className="mb-2 flex items-center justify-between text-sm">
          {label && <span className="text-white/55">{label}</span>}
          {showPercent && <span className="text-white/55">{percent}%</span>}
        </div>
      )}
      <div
        className={`${sizeClasses[size]} w-full overflow-hidden rounded-full bg-white/[0.06]`}
      >
        <div
          className={`h-full rounded-full bg-gradient-to-r ${themeClasses[theme]} transition-all duration-500`}
          style={{ width: `${percent}%` }}
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
    </div>
  );
}

/**
 * Segmented progress bar showing completed/total steps.
 */
type SegmentedProgressProps = {
  completed: number;
  total: number;
  label?: string;
  className?: string;
};

export function SegmentedProgress({
  completed,
  total,
  label,
  className = "",
}: SegmentedProgressProps) {
  if (total <= 0) return null;

  return (
    <div className={className}>
      {label && (
        <div className="mb-2 text-sm text-white/55">
          {label}: {completed} / {total}
        </div>
      )}
      <div className="flex gap-1">
        {Array.from({ length: total }).map((_, i) => (
          <div
            key={i}
            className={`h-2 flex-1 rounded-full transition-colors duration-300 ${
              i < completed
                ? "bg-gradient-to-r from-white/40 to-white/20"
                : "bg-white/[0.06]"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Circular progress indicator.
 */
type CircularProgressProps = {
  progress: number;
  size?: number;
  strokeWidth?: number;
  showPercent?: boolean;
  className?: string;
};

export function CircularProgress({
  progress,
  size = 64,
  strokeWidth = 4,
  showPercent = true,
  className = "",
}: CircularProgressProps) {
  const clampedProgress = Math.max(0, Math.min(1, progress));
  const percent = Math.round(clampedProgress * 100);
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - clampedProgress * circumference;

  return (
    <div
      className={`relative inline-flex items-center justify-center ${className}`}
    >
      <svg width={size} height={size} className="-rotate-90">
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-white/[0.06]"
        />
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="url(#progress-gradient)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-500"
        />
        <defs>
          <linearGradient
            id="progress-gradient"
            x1="0%"
            y1="0%"
            x2="100%"
            y2="0%"
          >
            <stop offset="0%" stopColor="rgba(255, 255, 255, 0.5)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 0.2)" />
          </linearGradient>
        </defs>
      </svg>
      {showPercent && (
        <span className="absolute text-sm font-medium text-white/60">
          {percent}%
        </span>
      )}
    </div>
  );
}
