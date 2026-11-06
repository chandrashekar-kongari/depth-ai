import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";

const SvgDepthWordmark = ({ size, className }: IconProps) => (
  <span
    role="img"
    aria-label="Depth"
    className={cn(
      "inline-flex items-center font-semibold tracking-tight",
      className,
    )}
    style={{
      height: size,
      fontSize: size ? size * 0.82 : undefined,
      color: "var(--theme-primary-05)",
      lineHeight: 1,
    }}
  >
    Depth
  </span>
);

export default SvgDepthWordmark;
