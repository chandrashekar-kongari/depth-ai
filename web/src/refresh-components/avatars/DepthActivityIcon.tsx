"use client";

import { motion, useReducedMotion } from "motion/react";
import useOnMount from "@opal/hooks/useOnMount";
import SvgDepthLogo, {
  DEPTH_INNER_PATH,
  DEPTH_OUTER_PATH,
} from "@opal/logos/depth-logo";

interface DepthActivityIconProps {
  active: boolean;
  size?: number;
}

/** The outer mark stays fixed; only its inner shape moves while work is active. */
export function DepthActivityIcon({
  active,
  size = 24,
}: DepthActivityIconProps) {
  const reducedMotion = useReducedMotion();
  const mounted = useOnMount();
  if (!mounted || !active || reducedMotion !== false) {
    return (
      <SvgDepthLogo
        size={size}
        width={size}
        className="shrink-0"
        aria-hidden="true"
        focusable="false"
        data-depth-activity={active ? "working" : "idle"}
      />
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      className="shrink-0"
      aria-hidden="true"
      focusable="false"
      data-depth-activity="working"
    >
      <path
        fill="var(--theme-primary-05)"
        fillRule="evenodd"
        d={DEPTH_OUTER_PATH}
      />
      <motion.path
        data-depth-pulse
        fill="var(--theme-primary-05)"
        d={DEPTH_INNER_PATH}
        style={{ transformBox: "fill-box", transformOrigin: "center" }}
        initial={{ x: 0, scale: 1, opacity: 0.65 }}
        animate={{
          x: [0, 2, 0],
          scale: [1, 1.18, 1],
          opacity: [0.65, 1, 0.65],
        }}
        transition={{ duration: 1.8, ease: "easeInOut", repeat: Infinity }}
      />
    </svg>
  );
}
