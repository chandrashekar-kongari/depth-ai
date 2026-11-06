"use client";

import "@opal/components/loader/styles.css";
import { cn } from "@opal/utils";
import { useOpalStrings } from "@opal/strings";

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

// Marks render in `currentColor`, so color is applied as a text token.
// Default is the neutral `border-02`. Pass `color` to override, or
// `"inherit"` to set no class and let the ambient text color flow through.
type LoaderColor =
  | "inherit"
  | "border-02"
  | "text-02"
  | "text-03"
  | "text-04"
  | "text-05"
  | "status-error-05"
  | "status-success-05"
  | "status-warning-05";

const COLOR_CLASS: Record<LoaderColor, string> = {
  inherit: "",
  "border-02": "text-border-02",
  "text-02": "text-text-02",
  "text-03": "text-text-03",
  "text-04": "text-text-04",
  "text-05": "text-text-05",
  "status-error-05": "text-status-error-05",
  "status-success-05": "text-status-success-05",
  "status-warning-05": "text-status-warning-05",
};

// ---------------------------------------------------------------------------
// DepthLoader
// ---------------------------------------------------------------------------

interface DepthLoaderProps {
  /** Size of the animated mark, in pixels. @default 64 */
  size?: number;

  /** Mark color token. @default "border-02" */
  color?: LoaderColor;
}

// Geometry matches the @opal/icons `depth-octagon`/`depth-logo` paths. Stroke
// is defined here, not reused from them, so weight can be tuned: ~2.5px at
// the default 64px, scaling with `size`.
const STROKE_WIDTH = 0.625;

const OUTLINE_PATH = "M4 2.5v11M4 2.5c5.5 0 9 2.4 9 5.5s-3.5 5.5-9 5.5";

function svgLayerProps(size: number) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    xmlns: "http://www.w3.org/2000/svg",
  };
}

const MARK_PATHS = [
  "M4 5.5c3.6 0 6 1.4 6 2.5s-2.4 2.5-6 2.5",
  "M4 7.75c1.8 0 3 .6 3 1.25s-1.2 1.25-3 1.25",
];

/**
 * Depth-branded loading mark: rotates a full turn while crossfading between the
 * D outline and the inner depth rings (2s loop), holding the static outline
 * under `prefers-reduced-motion`. Uses `currentColor`, so `color` themes it.
 * For a full-page loading state with a label, use `PageLoader`.
 */
function DepthLoader({ size = 64, color = "border-02" }: DepthLoaderProps) {
  const strings = useOpalStrings();
  return (
    <div
      role="status"
      aria-label={strings.loading}
      className={cn("relative shrink-0", COLOR_CLASS[color])}
      style={{ width: size, height: size }}
    >
      <div className="opal-loader-rotator">
        <svg
          {...svgLayerProps(size)}
          className="opal-loader-layer opal-loader-outline"
        >
          <path
            d={OUTLINE_PATH}
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <svg
          {...svgLayerProps(size)}
          className="opal-loader-layer opal-loader-mark"
        >
          {MARK_PATHS.map((d) => (
            <path
              key={d}
              d={d}
              strokeWidth={STROKE_WIDTH}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
        </svg>
      </div>
    </div>
  );
}

export { DepthLoader, type DepthLoaderProps, type LoaderColor };
