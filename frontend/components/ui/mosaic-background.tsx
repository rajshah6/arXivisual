"use client";

interface MosaicBackgroundProps {
  className?: string;
}

export function MosaicBackground({ className = "" }: MosaicBackgroundProps) {
  return (
    <div className={`absolute inset-0 overflow-hidden pointer-events-none ${className}`}>
      {/* Base tessellation pattern via CSS class */}
      <div className="absolute inset-0 mosaic-bg" />

      {/* Larger decorative tessellation lines */}
      <svg
        className="absolute inset-0 w-full h-full"
        xmlns="http://www.w3.org/2000/svg"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="mosaic-grad-1" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="white" stopOpacity="0" />
            <stop offset="50%" stopColor="white" stopOpacity="0.03" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" y1="0" x2="100%" y2="100%" stroke="url(#mosaic-grad-1)" strokeWidth="0.5" />
        <line x1="100%" y1="0" x2="0" y2="100%" stroke="url(#mosaic-grad-1)" strokeWidth="0.5" />
        <line x1="50%" y1="0" x2="100%" y2="50%" stroke="url(#mosaic-grad-1)" strokeWidth="0.5" />
        <line x1="0" y1="50%" x2="50%" y2="100%" stroke="url(#mosaic-grad-1)" strokeWidth="0.5" />
      </svg>

      {/* Subtle radial gradient for depth */}
      <div
        className="absolute inset-0"
        style={{
          background: "radial-gradient(ellipse 60% 50% at 50% 40%, rgba(255,255,255,0.015), transparent)",
        }}
      />
    </div>
  );
}
