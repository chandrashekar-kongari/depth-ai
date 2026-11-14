import type { Rect, Size } from "@embedpdf/models";

export interface CanvasCamera {
  x: number;
  y: number;
  scale: number;
}

export const PAGE_WIDTH = 1000;
export const PAGE_GAP = 64;
export const COLUMN_GAP = 96;
export const HEADER_HEIGHT = 48;

export function zoomCamera(
  camera: CanvasCamera,
  scale: number,
  point: { x: number; y: number }
): CanvasCamera {
  const next = Math.max(0.08, Math.min(4, scale));
  const ratio = next / camera.scale;
  return {
    x: point.x - (point.x - camera.x) * ratio,
    y: point.y - (point.y - camera.y) * ratio,
    scale: next,
  };
}

export function centerCamera(
  camera: CanvasCamera,
  viewport: Size,
  rect: Rect
): CanvasCamera {
  return {
    ...camera,
    x:
      viewport.width / 2 - (rect.origin.x + rect.size.width / 2) * camera.scale,
    y:
      viewport.height / 2 -
      (rect.origin.y + rect.size.height / 2) * camera.scale,
  };
}

export function fitCamera(viewport: Size, rect: Rect): CanvasCamera {
  const scale = Math.max(
    0.08,
    Math.min(
      2,
      (viewport.width - 64) / rect.size.width,
      (viewport.height - 64) / rect.size.height
    )
  );
  return centerCamera({ x: 0, y: 0, scale }, viewport, rect);
}

export function pageFrame(pages: Size[], column: number, index: number): Rect {
  return {
    origin: {
      x: column * (PAGE_WIDTH + COLUMN_GAP),
      y:
        HEADER_HEIGHT +
        pages
          .slice(0, index)
          .reduce(
            (sum, page) =>
              sum + (page.height * PAGE_WIDTH) / page.width + PAGE_GAP,
            0
          ),
    },
    size: {
      width: PAGE_WIDTH,
      height:
        ((pages[index]?.height ?? 1) * PAGE_WIDTH) / (pages[index]?.width ?? 1),
    },
  };
}

export function canvasTarget(
  frame: Rect,
  nativeSize: Size,
  region: Rect | null
): Rect {
  if (!region) return frame;
  const scale = frame.size.width / nativeSize.width;
  return {
    origin: {
      x: frame.origin.x + region.origin.x * scale,
      y: frame.origin.y + region.origin.y * scale,
    },
    size: {
      width: region.size.width * scale,
      height: region.size.height * scale,
    },
  };
}

export function frameVisible(
  camera: CanvasCamera,
  viewport: Size,
  frame: Rect
): boolean {
  const x = camera.x + frame.origin.x * camera.scale;
  const y = camera.y + frame.origin.y * camera.scale;
  return (
    x < viewport.width + 200 &&
    y < viewport.height + 200 &&
    x + frame.size.width * camera.scale > -200 &&
    y + frame.size.height * camera.scale > -200
  );
}
