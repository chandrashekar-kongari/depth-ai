import { issueFocusTarget } from "@/lib/pdf-review/navigation";
import { locationKey } from "@/lib/pdf-review/anchors";
import type { LinkedIssue, WorkspaceSnapshot } from "@/lib/pdf-review/types";
import type { PdfDocumentObject } from "@embedpdf/models";
const document = {
  pageCount: 3,
  pages: Array.from({ length: 3 }, () => ({
    size: { width: 600, height: 400 },
  })),
} as PdfDocumentObject;
const issue: LinkedIssue = {
  id: "C1",
  title: "Bore",
  request: "Add tolerance",
  evidence: "",
  remaining: "",
  anchors: {
    original: {
      page: 2,
      box: { x: 0.1, y: 0.2, width: 0.1, height: 0.1 },
      pageLevel: false,
      quality: "confirmed",
    },
    revised: { page: 3, box: null, pageLevel: true },
  },
};
it("uses the requested revision's own page and region", () => {
  const request = {
    id: "click1",
    issueId: "C1",
    documentId: "original",
    page: 1,
  };
  const target = issueFocusTarget(request, [issue], document);
  expect(target.page).toBe(2);
  expect(target.rect?.origin.x).toBeCloseTo(60);
  expect(target.rect?.origin.y).toBeCloseTo(80);
  expect(target.rect?.size).toEqual({ width: 60, height: 40 });
  expect(
    issueFocusTarget(
      { ...request, documentId: "revised", page: 3 },
      [issue],
      document
    )
  ).toEqual({ page: 3, rect: null });
});
it("honors a saved location correction and keeps edge regions inside the page", () => {
  const snapshot: WorkspaceSnapshot = {
    id: "w",
    version: 1,
    documents: [],
    can_undo: true,
    can_redo: false,
    state: {
      annotations: {},
      calibrations: {},
      anchors: {
        [`revised:${locationKey(issue)}`]: {
          page: 1,
          x: 0.95,
          y: 0.95,
          width: 0.05,
          height: 0.05,
        },
      },
    },
  };
  expect(
    issueFocusTarget(
      { id: "click2", issueId: "C1", documentId: "revised", page: 3 },
      [issue],
      document,
      snapshot
    )
  ).toEqual({
    page: 1,
    rect: { origin: { x: 570, y: 380 }, size: { width: 30, height: 20 } },
  });
});
