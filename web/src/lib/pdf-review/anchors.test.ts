import { resolvedAnchor, locationKey } from "@/lib/pdf-review/anchors";
import type { LinkedIssue, WorkspaceSnapshot } from "@/lib/pdf-review/types";
const issue: LinkedIssue = {
  id: "c1",
  title: "Bore",
  request: "Add H7",
  evidence: "H7",
  remaining: "",
  anchors: {
    original: {
      page: 1,
      box: { x: 0.1, y: 0.2, width: 0.1, height: 0.1 },
      pageLevel: false,
    },
  },
};
it("does not promote a legacy comment or word rectangle to an exact feature", () => {
  expect(resolvedAnchor(undefined, "original", issue)).toBeNull();
});
it("does not reuse sequential IDs or old corrections across different findings", () => {
  const changed = { ...issue, title: "Plate thickness" };
  expect(locationKey(changed)).not.toBe(locationKey(issue));
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
        "original:c1": { page: 1, x: 0, y: 0, width: 0.1, height: 0.1 },
        [`original:${locationKey(issue)}`]: {
          page: 1,
          x: 0.3,
          y: 0.4,
          width: 0.1,
          height: 0.1,
        },
      },
    },
  };
  expect(resolvedAnchor(snapshot, "original", issue)?.x).toBe(0.3);
  expect(resolvedAnchor(snapshot, "original", changed)).toBeNull();
});
