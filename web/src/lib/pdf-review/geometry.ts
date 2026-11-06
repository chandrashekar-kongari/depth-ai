import type { Rect, Size } from "@embedpdf/models";
import { anchorSchema, type ReviewAnchor } from "@/lib/pdf-review/types";

/** EmbedPDF's normalized document pages use top-left points at scale 1. */
export function anchorRect(anchor: ReviewAnchor, size: Size): Rect {
  return {
    origin: { x: anchor.x * size.width, y: anchor.y * size.height },
    size: {
      width: anchor.width * size.width,
      height: anchor.height * size.height,
    },
  };
}
export function rectAnchor(
  rect: Rect,
  size: Size,
  page: number
): ReviewAnchor | null {
  if (size.width <= 0 || size.height <= 0) return null;
  const result = anchorSchema.safeParse({
    page,
    x: rect.origin.x / size.width,
    y: rect.origin.y / size.height,
    width: rect.size.width / size.width,
    height: rect.size.height / size.height,
  });
  return result.success ? result.data : null;
}
