import type { PdfAnnotationObject, Size } from "@embedpdf/models";
import { anchorRect } from "@/lib/pdf-review/geometry";
import { locationKey } from "@/lib/pdf-review/anchors";
import type { LinkedIssue, ReviewAnchor } from "@/lib/pdf-review/types";

export const reviewStatusStyles = {
  solved_correct: { color: "#17834b", border: "border-status-success-05" },
  open: { color: "#c83232", border: "border-status-error-05" },
  solved_incorrect: { color: "#c83232", border: "border-status-error-05" },
  unclear: { color: "#ad7411", border: "border-status-warning-05" },
};

/** Derived PDF annotations stay separate from the model's persisted verdict. */
export function createReviewMarks(
  issue: LinkedIssue,
  anchor: ReviewAnchor | null,
  pageIndex: number,
  size: Size,
  label: string,
  position = 0
): PdfAnnotationObject[] {
  const style = reviewStatusStyles[issue.verdict ?? "unclear"];
  const contents = [
    label,
    issue.title,
    issue.request,
    issue.evidence,
    issue.remaining,
  ]
    .filter(Boolean)
    .join("\n");
  const prefix = `depth-review:${locationKey(issue)}`;
  if (!anchor) return [];
  const rect = anchorRect(anchor, size);
  return [
    {
      id: `${prefix}:region`,
      type: 5,
      pageIndex,
      rect,
      contents,
      color: "transparent",
      strokeColor: style.color,
      strokeWidth: 1.5,
      strokeStyle: 1,
      opacity: 1,
      flags: ["print"],
    },
    {
      id: `${prefix}:label`,
      type: 3,
      pageIndex,
      rect: {
        origin: {
          x: Math.max(0, Math.min(rect.origin.x, size.width - 160)),
          y: Math.max(0, rect.origin.y - 17),
        },
        size: { width: Math.min(160, size.width), height: 16 },
      },
      contents: `${position + 1} · ${label}`,
      fontFamily: 4,
      fontSize: 10,
      fontColor: style.color,
      textAlign: 0,
      verticalAlign: 0,
      opacity: 1,
      color: "#ffffff",
      flags: ["print"],
    },
  ];
}
