"use client";

import { motion } from "framer-motion";
import { useMemo } from "react";

// ---------------------------------------------------------------------------
// 16 unique irregular shard shapes — jagged, asymmetric broken-glass polygons
// Each has: polygon points, non-square viewBox, and which edges get the bright
// "light catching" highlight stroke.
// ---------------------------------------------------------------------------

type ShardDef = {
  /** SVG polygon points string */
  points: string;
  /** viewBox width & height — allows non-square aspect ratios */
  vb: [number, number];
  /** Pairs of vertex indices whose connecting edge gets a bright highlight.
   *  e.g. [[0,1],[3,4]] means edge from vertex 0→1 and 3→4 get the glow. */
  highlights: [number, number][];
};

// Parse "x1,y1 x2,y2 ..." into [[x1,y1],[x2,y2],...]
function parsePoints(pts: string): [number, number][] {
  return pts.split(/\s+/).map((p) => {
    const [x, y] = p.split(",").map(Number);
    return [x, y] as [number, number];
  });
}

const SHARD_SHAPES: ShardDef[] = [
  // 0 — tall thin sliver
  { points: "5,0 28,3 32,40 30,95 8,100 2,55", vb: [35, 100], highlights: [[0, 1], [3, 4]] },
  // 1 — wide flat chunk
  { points: "0,15 45,0 100,8 95,50 60,55 10,48", vb: [100, 55], highlights: [[1, 2], [4, 5]] },
  // 2 — jagged triangle
  { points: "12,0 95,20 70,100 5,75", vb: [100, 100], highlights: [[0, 1], [2, 3]] },
  // 3 — long diagonal shard
  { points: "0,8 60,0 65,15 10,90 3,85", vb: [68, 92], highlights: [[1, 2]] },
  // 4 — irregular pentagon
  { points: "20,0 80,5 100,45 55,100 0,60", vb: [100, 100], highlights: [[0, 1], [2, 3]] },
  // 5 — small sharp splinter
  { points: "0,0 100,30 85,100 10,80", vb: [100, 100], highlights: [[0, 1]] },
  // 6 — wide trapezoid chunk
  { points: "15,0 90,0 100,35 80,100 0,95 5,30", vb: [100, 100], highlights: [[0, 1], [3, 4]] },
  // 7 — thin needle
  { points: "3,0 18,5 20,50 15,100 0,95 2,45", vb: [22, 100], highlights: [[0, 1], [3, 4]] },
  // 8 — angular flat piece
  { points: "0,10 70,0 100,20 90,60 15,55", vb: [100, 60], highlights: [[1, 2], [3, 4]] },
  // 9 — irregular rhombus
  { points: "30,0 100,30 75,100 0,65", vb: [100, 100], highlights: [[0, 1], [2, 3]] },
  // 10 — short wide fragment
  { points: "5,0 60,5 100,30 95,55 40,60 0,40", vb: [100, 60], highlights: [[2, 3]] },
  // 11 — elongated spike
  { points: "0,5 40,0 45,30 35,100 5,95", vb: [48, 100], highlights: [[1, 2], [4, 0]] },
  // 12 — curved-looking chunk (many vertices)
  { points: "10,0 50,3 90,15 100,50 80,90 30,100 0,70 5,25", vb: [100, 100], highlights: [[2, 3], [5, 6]] },
  // 13 — acute triangle splinter
  { points: "0,0 100,40 15,100", vb: [100, 100], highlights: [[0, 1]] },
  // 14 — flat rectangular-ish piece
  { points: "5,0 95,8 100,40 90,50 8,45 0,30", vb: [100, 50], highlights: [[0, 1], [3, 4]] },
  // 15 — asymmetric kite
  { points: "35,0 100,35 60,100 0,55", vb: [100, 100], highlights: [[0, 1], [1, 2]] },
];

// ---------------------------------------------------------------------------
// GlassShard component
// ---------------------------------------------------------------------------

interface GlassShardProps {
  /** Index into SHARD_SHAPES */
  shardIndex: number;
  /** Scale factor — the longest dimension will be this many px */
  size: number;
  /** CSS position */
  x: string;
  y: string;
  /** Initial rotation in degrees */
  rotate?: number;
  /** Float cycle duration in seconds */
  floatDuration?: number;
  /** Animation start delay in seconds */
  delay?: number;
  /** Highlight brightness 0-1 (mapped to stroke opacity) */
  brightness?: number;
  /** Horizontal wander range in px */
  driftX?: number;
  /** Vertical wander range in px */
  driftY?: number;
  /** Rotation tumble range in degrees */
  rotateRange?: number;
  className?: string;
}

export function GlassShard({
  shardIndex,
  size,
  x,
  y,
  rotate = 0,
  floatDuration = 10,
  delay = 0,
  brightness = 0.5,
  driftX = 30,
  driftY = 25,
  rotateRange = 15,
  className = "",
}: GlassShardProps) {
  const shape = SHARD_SHAPES[shardIndex % SHARD_SHAPES.length];
  const [vbW, vbH] = shape.vb;
  const aspect = vbW / vbH;
  const w = aspect >= 1 ? size : size * aspect;
  const h = aspect >= 1 ? size / aspect : size;

  const vertices = useMemo(() => parsePoints(shape.points), [shape.points]);
  const gradId = `sf-${shardIndex}-${size}`;

  // Compute the gradient angle from the first highlight edge direction
  const gradAngle = useMemo(() => {
    if (shape.highlights.length === 0) return 135;
    const [i, j] = shape.highlights[0];
    const dx = (vertices[j]?.[0] ?? 0) - (vertices[i]?.[0] ?? 0);
    const dy = (vertices[j]?.[1] ?? 0) - (vertices[i]?.[1] ?? 0);
    return (Math.atan2(dy, dx) * 180) / Math.PI + 90;
  }, [shape.highlights, vertices]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{
        x: [0, driftX, -driftX * 0.6, driftX * 0.4, 0],
        y: [0, -driftY, driftY * 0.4, -driftY * 0.7, 0],
        rotate: [
          rotate,
          rotate + rotateRange,
          rotate - rotateRange * 0.6,
          rotate + rotateRange * 0.8,
          rotate,
        ],
        opacity: [0.5, 0.85, 0.6, 1, 0.5],
      }}
      transition={{
        duration: floatDuration,
        delay,
        repeat: Infinity,
        ease: "easeInOut",
      }}
      className={`absolute pointer-events-none select-none ${className}`}
      style={{
        left: x,
        top: y,
        width: w,
        height: h,
        willChange: "transform, opacity",
      }}
    >
      <svg
        viewBox={`0 0 ${vbW} ${vbH}`}
        width={w}
        height={h}
        xmlns="http://www.w3.org/2000/svg"
        className="block"
      >
        <defs>
          <linearGradient
            id={gradId}
            gradientTransform={`rotate(${gradAngle}, 50, 50)`}
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor={`rgba(255,255,255,0.10)`} />
            <stop offset="40%" stopColor={`rgba(255,255,255,0.03)`} />
            <stop offset="100%" stopColor={`rgba(255,255,255,0.07)`} />
          </linearGradient>
        </defs>

        {/* Glass body fill */}
        <polygon points={shape.points} fill={`url(#${gradId})`} />

        {/* Full perimeter — subtle edge definition */}
        <polygon
          points={shape.points}
          fill="none"
          stroke={`rgba(255,255,255,0.14)`}
          strokeWidth="0.7"
          strokeLinejoin="bevel"
        />

        {/* Bright highlight edges — the "light catching on glass" effect */}
        {shape.highlights.map(([i, j], idx) => {
          const a = vertices[i];
          const b = vertices[j];
          if (!a || !b) return null;
          return (
            <line
              key={idx}
              x1={a[0]}
              y1={a[1]}
              x2={b[0]}
              y2={b[1]}
              stroke={`rgba(255,255,255,${brightness})`}
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          );
        })}

        {/* Inner reflection line — subtle diagonal refraction */}
        {vertices.length >= 4 && (
          <line
            x1={vertices[0][0] * 0.7 + vertices[2][0] * 0.3}
            y1={vertices[0][1] * 0.7 + vertices[2][1] * 0.3}
            x2={vertices[1][0] * 0.3 + vertices[3 % vertices.length][0] * 0.7}
            y2={vertices[1][1] * 0.3 + vertices[3 % vertices.length][1] * 0.7}
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="0.5"
          />
        )}
      </svg>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// ShardField — 22 shards (4 large, 8 medium, 10 small)
// ---------------------------------------------------------------------------

export function ShardField({ className = "" }: { className?: string }) {
  const shards = useMemo(
    () => [
      // ── Large shards (200-350px) — slow majestic drift ────────────────
      { shardIndex: 0, size: 320, x: "2%", y: "5%", rotate: 15, floatDuration: 14, delay: 0, brightness: 0.55, driftX: 25, driftY: 20, rotateRange: 12 },
      { shardIndex: 4, size: 280, x: "78%", y: "8%", rotate: -25, floatDuration: 16, delay: 2, brightness: 0.5, driftX: -30, driftY: 25, rotateRange: 15 },
      { shardIndex: 6, size: 300, x: "65%", y: "55%", rotate: 35, floatDuration: 13, delay: 1, brightness: 0.45, driftX: 22, driftY: -30, rotateRange: 10 },
      { shardIndex: 12, size: 260, x: "8%", y: "60%", rotate: -12, floatDuration: 15, delay: 3, brightness: 0.5, driftX: -28, driftY: 22, rotateRange: 18 },

      // ── Medium shards (80-170px) — natural float ──────────────────────
      { shardIndex: 1, size: 170, x: "40%", y: "2%", rotate: 50, floatDuration: 11, delay: 0.5, brightness: 0.55, driftX: 45, driftY: -35, rotateRange: 20 },
      { shardIndex: 3, size: 140, x: "90%", y: "35%", rotate: -40, floatDuration: 9, delay: 1.5, brightness: 0.6, driftX: -40, driftY: 30, rotateRange: 22 },
      { shardIndex: 5, size: 120, x: "25%", y: "40%", rotate: 20, floatDuration: 10, delay: 2.5, brightness: 0.5, driftX: 35, driftY: 40, rotateRange: 18 },
      { shardIndex: 8, size: 150, x: "55%", y: "25%", rotate: -15, floatDuration: 12, delay: 0.8, brightness: 0.45, driftX: -50, driftY: -28, rotateRange: 25 },
      { shardIndex: 9, size: 130, x: "15%", y: "82%", rotate: 65, floatDuration: 11, delay: 3.5, brightness: 0.55, driftX: 38, driftY: -32, rotateRange: 20 },
      { shardIndex: 11, size: 100, x: "72%", y: "78%", rotate: -30, floatDuration: 10, delay: 1.2, brightness: 0.5, driftX: -32, driftY: 45, rotateRange: 24 },
      { shardIndex: 14, size: 160, x: "48%", y: "70%", rotate: 10, floatDuration: 9, delay: 4, brightness: 0.45, driftX: 42, driftY: 35, rotateRange: 16 },
      { shardIndex: 15, size: 110, x: "85%", y: "60%", rotate: -55, floatDuration: 10, delay: 2.8, brightness: 0.6, driftX: -55, driftY: -38, rotateRange: 22 },

      // ── Small shards / splinters (20-60px) — erratic fast tumble ──────
      { shardIndex: 2, size: 55, x: "18%", y: "15%", rotate: 30, floatDuration: 7, delay: 0.3, brightness: 0.7, driftX: 65, driftY: -50, rotateRange: 35 },
      { shardIndex: 7, size: 35, x: "60%", y: "12%", rotate: -70, floatDuration: 6, delay: 1.8, brightness: 0.65, driftX: -55, driftY: 60, rotateRange: 40 },
      { shardIndex: 10, size: 45, x: "35%", y: "55%", rotate: 80, floatDuration: 8, delay: 0.6, brightness: 0.6, driftX: 70, driftY: 45, rotateRange: 30 },
      { shardIndex: 13, size: 30, x: "92%", y: "20%", rotate: -20, floatDuration: 5, delay: 2.2, brightness: 0.75, driftX: -80, driftY: -55, rotateRange: 38 },
      { shardIndex: 5, size: 40, x: "5%", y: "45%", rotate: 45, floatDuration: 7, delay: 3.2, brightness: 0.65, driftX: 60, driftY: -65, rotateRange: 32 },
      { shardIndex: 7, size: 25, x: "50%", y: "88%", rotate: -50, floatDuration: 6, delay: 1, brightness: 0.7, driftX: -70, driftY: 50, rotateRange: 42 },
      { shardIndex: 2, size: 50, x: "80%", y: "48%", rotate: 15, floatDuration: 8, delay: 4.5, brightness: 0.6, driftX: 55, driftY: 60, rotateRange: 28 },
      { shardIndex: 13, size: 28, x: "30%", y: "92%", rotate: -35, floatDuration: 5, delay: 2, brightness: 0.8, driftX: -75, driftY: -48, rotateRange: 36 },
      { shardIndex: 10, size: 38, x: "68%", y: "3%", rotate: 55, floatDuration: 7, delay: 3.8, brightness: 0.65, driftX: 48, driftY: 70, rotateRange: 34 },
      { shardIndex: 11, size: 32, x: "45%", y: "45%", rotate: -60, floatDuration: 6, delay: 0.2, brightness: 0.7, driftX: -60, driftY: -55, rotateRange: 40 },
    ],
    []
  );

  return (
    <div
      className={`absolute inset-0 overflow-hidden pointer-events-none z-[1] ${className}`}
    >
      {shards.map((s, i) => (
        <GlassShard key={i} {...s} />
      ))}
    </div>
  );
}
