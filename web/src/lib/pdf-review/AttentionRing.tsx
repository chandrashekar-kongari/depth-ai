"use client";
import { useScroll } from "@embedpdf/plugin-scroll/react";
import { useDocumentState } from "@embedpdf/core/react";
import type { Rect } from "@embedpdf/models";

/** A temporary view decoration. It never enters the PDF annotation store. */
export function AttentionRing({
  documentId,
  pageIndex,
  rect,
}: {
  documentId: string;
  pageIndex: number;
  rect: Rect;
}) {
  const { provides: scroll } = useScroll(documentId);
  const state = useDocumentState(documentId);
  const size = state?.document?.pages[pageIndex]?.size;
  const target = scroll?.getRectPositionForPage(pageIndex, rect);
  const page = size
    ? scroll?.getRectPositionForPage(pageIndex, {
        origin: { x: 0, y: 0 },
        size,
      })
    : null;
  if (!target || !page) return null;
  return (
    <div
      aria-hidden="true"
      data-testid="pdf-attention-ring"
      className="pointer-events-none absolute z-50 h-12 w-12 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-status-info-05 bg-action-selection-02"
      style={{
        left: target.origin.x - page.origin.x + target.size.width / 2,
        top: target.origin.y - page.origin.y + target.size.height / 2,
      }}
    >
      <div className="absolute inset-0 rounded-full border-2 border-status-info-05 motion-safe:animate-ping" />
    </div>
  );
}

export function scheduleAttentionEnd(onEnd: () => void): () => void {
  const timer = setTimeout(onEnd, 2000);
  return () => clearTimeout(timer);
}
