"use client";

import { cn } from "@/lib/utils";
import {
  AnimatePresence,
  MotionValue,
  motion,
  useMotionValue,
  useSpring,
  useTransform,
} from "framer-motion";
import { useRef, useState } from "react";

export const FloatingDock = ({
  items,
  activeId,
  onItemClick,
  className,
}: {
  items: { id: string; title: string; icon: React.ReactNode }[];
  activeId?: string;
  onItemClick?: (id: string) => void;
  className?: string;
}) => {
  const mouseX = useMotionValue(Infinity);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      onMouseMove={(e) => mouseX.set(e.pageX)}
      onMouseLeave={() => mouseX.set(Infinity)}
      className={cn(
        "mx-auto flex h-16 gap-4 items-end rounded-2xl bg-black/80 backdrop-blur-2xl px-4 pb-3 border border-white/[0.08]",
        className
      )}
    >
      {items.map((item) => (
        <IconContainer
          key={item.id}
          mouseX={mouseX}
          {...item}
          isActive={activeId === item.id}
          onClick={() => onItemClick?.(item.id)}
        />
      ))}
    </motion.div>
  );
};

function IconContainer({
  mouseX,
  title,
  icon,
  isActive,
  onClick,
}: {
  mouseX: MotionValue;
  title: string;
  icon: React.ReactNode;
  isActive?: boolean;
  onClick?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState(false);

  const distance = useTransform(mouseX, (val) => {
    const bounds = ref.current?.getBoundingClientRect() ?? { x: 0, width: 0 };
    return val - bounds.x - bounds.width / 2;
  });

  const widthTransform = useTransform(distance, [-150, 0, 150], [40, 60, 40]);
  const heightTransform = useTransform(distance, [-150, 0, 150], [40, 60, 40]);

  const width = useSpring(widthTransform, {
    mass: 0.1,
    stiffness: 150,
    damping: 12,
  });
  const height = useSpring(heightTransform, {
    mass: 0.1,
    stiffness: 150,
    damping: 12,
  });

  return (
    <motion.div
      ref={ref}
      style={{ width, height }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
      className={cn(
        "aspect-square rounded-xl flex items-center justify-center cursor-pointer relative transition-colors duration-200",
        isActive
          ? "bg-white/[0.12] border-2 border-white/[0.20]"
          : "bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.06]"
      )}
    >
      <AnimatePresence>
        {hovered && (
          <motion.div
            initial={{ opacity: 0, y: 10, x: "-50%" }}
            animate={{ opacity: 1, y: 0, x: "-50%" }}
            exit={{ opacity: 0, y: 2, x: "-50%" }}
            className="px-3 py-1.5 whitespace-pre rounded-lg bg-black/90 backdrop-blur-xl border border-white/[0.10] text-white/80 text-xs absolute left-1/2 -top-10"
          >
            {title}
          </motion.div>
        )}
      </AnimatePresence>
      <div className={cn(
        "transition-colors duration-200",
        isActive ? "text-white/90" : "text-white/40"
      )}>
        {icon}
      </div>
    </motion.div>
  );
}
