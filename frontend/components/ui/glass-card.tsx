"use client";

import { motion, useMotionValue, useMotionTemplate } from "framer-motion";
import { cn } from "@/lib/utils";
import React from "react";

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  spotlight?: boolean;
  spotlightColor?: string;
  animate?: boolean;
  delay?: number;
  onClick?: () => void;
}

export function GlassCard({
  children,
  className,
  spotlight = true,
  spotlightColor = "rgba(255, 255, 255, 0.06)",
  animate = true,
  delay = 0,
  onClick,
}: GlassCardProps) {
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const { left, top } = e.currentTarget.getBoundingClientRect();
    mouseX.set(e.clientX - left);
    mouseY.set(e.clientY - top);
  }

  const spotlightBg = useMotionTemplate`
    radial-gradient(
      400px circle at ${mouseX}px ${mouseY}px,
      ${spotlightColor},
      transparent 60%
    )
  `;

  return (
    <motion.div
      initial={animate ? { opacity: 0, y: 16 } : undefined}
      animate={animate ? { opacity: 1, y: 0 } : undefined}
      transition={animate ? { duration: 0.5, delay, ease: "easeOut" } : undefined}
      onMouseMove={spotlight ? handleMouseMove : undefined}
      onClick={onClick}
      className={cn(
        "group relative rounded-2xl",
        "bg-white/[0.04] backdrop-blur-xl",
        "border border-white/[0.08]",
        "transition-colors duration-300",
        "hover:bg-white/[0.07] hover:border-white/[0.14]",
        onClick && "cursor-pointer",
        className
      )}
    >
      {spotlight && (
        <motion.div
          className="pointer-events-none absolute -inset-px rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500"
          style={{ background: spotlightBg }}
        />
      )}
      <div className="relative z-10">{children}</div>
    </motion.div>
  );
}
