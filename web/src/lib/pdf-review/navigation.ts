import type { PdfDocumentObject, Rect } from "@embedpdf/models";
import type {
  LinkedIssue,
  ReviewFocusRequest,
  WorkspaceSnapshot,
} from "@/lib/pdf-review/types";
import { anchorRect } from "@/lib/pdf-review/geometry";
import { resolvedAnchor } from "@/lib/pdf-review/anchors";

export interface IssueFocusTarget {
  page: number;
  rect: Rect | null;
}

export function issueFocusTarget(
  request: ReviewFocusRequest,
  issues: LinkedIssue[],
  document: PdfDocumentObject,
  snapshot?: WorkspaceSnapshot
): IssueFocusTarget {
  const issue = issues.find((item) => item.id === request.issueId);
  const anchor = issue
    ? resolvedAnchor(snapshot, request.documentId, issue)
    : null;
  const page = Math.max(
    1,
    Math.min(anchor?.page ?? request.page, document.pageCount)
  );
  const size = document.pages[page - 1]?.size;
  if (!anchor || !size) return { page, rect: null };
  return { page, rect: anchorRect(anchor, size) };
}
