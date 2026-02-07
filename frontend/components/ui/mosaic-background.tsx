"use client";

import { useEffect, useRef, useCallback } from "react";

interface MosaicBackgroundProps {
  className?: string;
  /** When true, renders the arXiv logo as colored mosaic fragments */
  showLogo?: boolean;
}

// ---------------------------------------------------------------------------
// Seeded PRNG — deterministic output for consistent renders
// ---------------------------------------------------------------------------
function createRng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 16807 + 0) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const CELL_SIZE = 18;
const JITTER = 6;
const SEED = 42;

// arXiv brand colors
const ARXIV_GRAY = { r: 154, g: 140, b: 127 }; // #9a8c7f — ar, iv, back-stroke of X
const ARXIV_RED = { r: 179, g: 27, b: 27 }; // #b31b1b — front diagonal of X

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export function MosaicBackground({
  className = "",
  showLogo = false,
}: MosaicBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const parent = canvas.parentElement;
    if (!parent) return;

    const dpr = window.devicePixelRatio || 1;
    const w = parent.clientWidth;
    const h = parent.clientHeight;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    const rand = createRng(SEED);

    // ------------------------------------------------------------------
    // Step 1: Generate jittered point grid
    // ------------------------------------------------------------------
    const cols = Math.ceil(w / CELL_SIZE) + 1;
    const rows = Math.ceil(h / CELL_SIZE) + 1;

    // points[row][col] = [x, y]
    const points: [number, number][][] = [];
    for (let r = 0; r <= rows; r++) {
      points[r] = [];
      for (let c = 0; c <= cols; c++) {
        let px = c * CELL_SIZE;
        let py = r * CELL_SIZE;
        // Jitter interior points for organic feel
        if (r > 0 && r < rows && c > 0 && c < cols) {
          px += (rand() - 0.5) * 2 * JITTER;
          py += (rand() - 0.5) * 2 * JITTER;
        }
        points[r][c] = [px, py];
      }
    }

    // ------------------------------------------------------------------
    // Step 2: Render arXiv logo to offscreen canvas for pixel sampling
    // ------------------------------------------------------------------
    let logoData: ImageData | null = null;

    if (showLogo) {
      const offscreen = document.createElement("canvas");
      offscreen.width = w;
      offscreen.height = h;
      const offCtx = offscreen.getContext("2d");

      if (offCtx) {
        // Font size scales with viewport width (~12%)
        const fontSize = Math.max(101, Math.round(w * 0.203));
        offCtx.font = `900 ${fontSize}px "Arial Black", "Impact", "Helvetica Neue", Arial, sans-serif`;
        offCtx.textAlign = "center";
        offCtx.textBaseline = "middle";

        const logoX = w / 2;
        const logoY = h * 0.22; // high in the clear area, above the subtitle text

        // Measure text segments to locate the X character boundaries
        const fullWidth = offCtx.measureText("arXiv").width;
        const arWidth = offCtx.measureText("ar").width;
        const arXWidth = offCtx.measureText("arX").width;
        const ivWidth = offCtx.measureText("iv").width;

        const textLeft = logoX - fullWidth / 2;
        const xLeft = textLeft + arWidth;
        const xRight = textLeft + arXWidth;
        const xCenter = (xLeft + xRight) / 2;
        const xHalfW = (xRight - xLeft) / 2;

        // Pass 1: Draw "ar" in gray (left of X)
        offCtx.fillStyle = `rgb(${ARXIV_GRAY.r}, ${ARXIV_GRAY.g}, ${ARXIV_GRAY.b})`;
        offCtx.textAlign = "right";
        offCtx.fillText("ar", xLeft, logoY);

        // Pass 2: Draw "iv" in gray (right of X)
        offCtx.textAlign = "left";
        offCtx.fillText("iv", xRight, logoY);

        // Pass 3: Draw the X as two thick line strokes
        const strokeHalfH = fontSize * 0.50;
        const strokeLineW = fontSize * 0.18;
        offCtx.lineWidth = strokeLineW;
        offCtx.lineCap = "round";

        // Gray "\" stroke (upper-left → lower-right) — back stroke
        offCtx.strokeStyle = `rgb(${ARXIV_GRAY.r}, ${ARXIV_GRAY.g}, ${ARXIV_GRAY.b})`;
        offCtx.beginPath();
        offCtx.moveTo(xCenter - xHalfW * 0.85, logoY - strokeHalfH);
        offCtx.lineTo(xCenter + xHalfW * 0.85, logoY + strokeHalfH);
        offCtx.stroke();

        // Red "/" stroke (lower-left → upper-right) — front stroke, drawn ON TOP
        offCtx.strokeStyle = `rgb(${ARXIV_RED.r}, ${ARXIV_RED.g}, ${ARXIV_RED.b})`;
        offCtx.beginPath();
        offCtx.moveTo(xCenter - xHalfW * 0.85, logoY + strokeHalfH);
        offCtx.lineTo(xCenter + xHalfW * 0.85, logoY - strokeHalfH);
        offCtx.stroke();

        logoData = offCtx.getImageData(0, 0, w, h);
      }
    }

    // ------------------------------------------------------------------
    // Step 3: Draw triangulated mosaic
    // ------------------------------------------------------------------
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const p00 = points[r][c];
        const p10 = points[r][c + 1];
        const p01 = points[r + 1][c];
        const p11 = points[r + 1][c + 1];

        // Alternate diagonal direction per cell for variety
        const alt = (r + c) % 2 === 0;
        const tris: [number, number][][] = alt
          ? [
              [p00, p10, p01],
              [p10, p11, p01],
            ]
          : [
              [p00, p10, p11],
              [p00, p11, p01],
            ];

        for (const tri of tris) {
          // Centroid for logo sampling
          const cx = (tri[0][0] + tri[1][0] + tri[2][0]) / 3;
          const cy = (tri[0][1] + tri[1][1] + tri[2][1]) / 3;

          let fillColor: string;
          let strokeColor: string;

          // Sample the offscreen logo canvas at the centroid
          let isLogoFragment = false;
          if (logoData) {
            const px = Math.round(cx);
            const py = Math.round(cy);
            if (px >= 0 && px < w && py >= 0 && py < h) {
              const idx = (py * w + px) * 4;
              const pr = logoData.data[idx];
              const pg = logoData.data[idx + 1];
              const pb = logoData.data[idx + 2];
              const pa = logoData.data[idx + 3];

              if (pa > 10) {
                isLogoFragment = true;
                const brightnessShift = 0.85 + rand() * 0.30; // 0.85-1.15

                // Distinguish red vs gray by checking red channel dominance
                if (pr > 150 && pg < 80 && pb < 80) {
                  // Red zone (the "/" stroke of X)
                  const opacity = (0.25 + rand() * 0.10) * brightnessShift;
                  fillColor = `rgba(${ARXIV_RED.r}, ${ARXIV_RED.g}, ${ARXIV_RED.b}, ${opacity.toFixed(3)})`;
                  strokeColor = `rgba(255, 255, 255, ${(0.12 + rand() * 0.06).toFixed(3)})`;
                } else {
                  // Gray zone (ar, iv, gray stroke of X)
                  const opacity = (0.20 + rand() * 0.10) * brightnessShift;
                  fillColor = `rgba(${ARXIV_GRAY.r}, ${ARXIV_GRAY.g}, ${ARXIV_GRAY.b}, ${opacity.toFixed(3)})`;
                  strokeColor = `rgba(255, 255, 255, ${(0.12 + rand() * 0.06).toFixed(3)})`;
                }
              }
            }
          }

          // Background fragment (not part of logo)
          if (!isLogoFragment) {
            const opacity = 0.008 + rand() * 0.010; // 0.008-0.018
            fillColor = `rgba(255, 255, 255, ${opacity.toFixed(4)})`;
            strokeColor = `rgba(255, 255, 255, ${(0.025 + rand() * 0.015).toFixed(3)})`;
          }

          // Draw triangle
          ctx.beginPath();
          ctx.moveTo(tri[0][0], tri[0][1]);
          ctx.lineTo(tri[1][0], tri[1][1]);
          ctx.lineTo(tri[2][0], tri[2][1]);
          ctx.closePath();

          ctx.fillStyle = fillColor!;
          ctx.fill();

          ctx.strokeStyle = strokeColor!;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
    }
  }, [showLogo]);

  useEffect(() => {
    render();

    let timeout: ReturnType<typeof setTimeout>;
    const handleResize = () => {
      clearTimeout(timeout);
      timeout = setTimeout(render, 200);
    };

    window.addEventListener("resize", handleResize);
    return () => {
      clearTimeout(timeout);
      window.removeEventListener("resize", handleResize);
    };
  }, [render]);

  return (
    <div
      className={`absolute inset-0 overflow-hidden pointer-events-none ${className}`}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />

      {/* Subtle radial gradient for depth */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 60% 50% at 50% 40%, rgba(255,255,255,0.015), transparent)",
        }}
      />
    </div>
  );
}
