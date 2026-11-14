import { act, renderHook, waitFor } from "@testing-library/react";
import type { AnnotationEvent } from "@embedpdf/plugin-annotation";
import type { PdfDocumentObject } from "@embedpdf/models";
import { useDocumentAnnotations } from "@/lib/pdf-review/useDocumentAnnotations";
import {
  annotationSchema,
  type LinkedIssue,
  type WorkspaceSnapshot,
} from "@/lib/pdf-review/types";

const mockListeners = new Set<(event: AnnotationEvent) => void>();
const mockScope = {
  setLocked: jest.fn(),
  setActiveTool: jest.fn(),
  deleteAnnotation: jest.fn(),
  getAnnotationById: jest.fn(),
  onAnnotationEvent: (listener: (event: AnnotationEvent) => void) => {
    mockListeners.add(listener);
    return () => {
      mockListeners.delete(listener);
    };
  },
};
const mockCapability = { forDocument: () => mockScope };
const mockReconcile = jest.fn<Promise<void>, unknown[]>();
jest.mock("@embedpdf/plugin-annotation/react", () => ({
  useAnnotationCapability: () => ({ provides: mockCapability }),
}));
jest.mock("@/lib/pdf-review/embedpdf/adapter", () => ({
  reconcileAnnotations: (...args: unknown[]) => mockReconcile(...args),
}));
const document = {
  pages: [{ index: 0, size: { width: 600, height: 400 } }],
} as unknown as PdfDocumentObject;
const snapshot: WorkspaceSnapshot = {
  id: "w",
  version: 1,
  can_undo: false,
  can_redo: false,
  documents: [],
  state: { annotations: {}, anchors: {}, calibrations: {} },
};
const annotation = annotationSchema.parse({
  id: "mark",
  type: 4,
  pageIndex: 0,
  rect: { origin: { x: 60, y: 80 }, size: { width: 120, height: 40 } },
});
const options = {
  documentId: "revised",
  document,
  snapshot,
  pending: 0,
  enabled: true,
  active: true,
  tool: "square",
  correction: null,
  submit: jest.fn(),
  onCorrected: jest.fn(),
  retryToken: 0,
};
function emit(event: AnnotationEvent) {
  act(() => {
    for (const listener of mockListeners) listener(event);
  });
}
beforeEach(() => {
  jest.clearAllMocks();
  mockListeners.clear();
  mockReconcile.mockResolvedValue(undefined);
});

it("persists user edits under the correct document and ignores committed SDK replays", async () => {
  const { result } = renderHook(() => useDocumentAnnotations(options));
  await waitFor(() => expect(result.current.ready).toBe(true));
  emit({
    type: "create",
    documentId: "revised",
    annotation,
    pageIndex: 0,
    committed: true,
  });
  expect(options.submit).not.toHaveBeenCalled();
  emit({
    type: "create",
    documentId: "revised",
    annotation,
    pageIndex: 0,
    committed: false,
  });
  expect(options.submit).toHaveBeenCalledWith({
    action: "upsert_annotation",
    document_id: "revised",
    annotation,
  });
});

it("saves a corrected location in normalized PDF coordinates without keeping its temporary rectangle", async () => {
  const correction: LinkedIssue = {
    id: "C1",
    locationIdentity: "stable-issue",
    title: "Bore",
    request: "Fix bore",
    evidence: "",
    remaining: "",
    anchors: {},
  };
  const { result } = renderHook(() =>
    useDocumentAnnotations({ ...options, correction })
  );
  await waitFor(() => expect(result.current.ready).toBe(true));
  emit({
    type: "create",
    documentId: "revised",
    annotation,
    pageIndex: 0,
    committed: false,
  });
  emit({
    type: "delete",
    documentId: "revised",
    annotation,
    pageIndex: 0,
    committed: false,
  });
  expect(options.submit).toHaveBeenCalledTimes(1);
  expect(options.submit).toHaveBeenCalledWith({
    action: "set_anchor",
    document_id: "revised",
    issue_id: "stable-issue",
    anchor: { page: 1, x: 0.1, y: 0.2, width: 0.2, height: 0.1 },
  });
  expect(mockScope.deleteAnnotation).toHaveBeenCalledWith(0, "mark");
  expect(options.onCorrected).toHaveBeenCalledTimes(1);
});

it("saves the updated position when the SDK event carries the previous annotation", async () => {
  const { result } = renderHook(() => useDocumentAnnotations(options));
  await waitFor(() => expect(result.current.ready).toBe(true));
  const rect = { ...annotation.rect, origin: { x: 140, y: 110 } };
  mockScope.getAnnotationById.mockReturnValue({
    object: { ...annotation, rect },
  });
  emit({
    type: "update",
    documentId: "revised",
    annotation,
    pageIndex: 0,
    patch: { rect },
    committed: false,
  });
  expect(options.submit).toHaveBeenCalledWith({
    action: "upsert_annotation",
    document_id: "revised",
    annotation: { ...annotation, rect },
  });
});

it("keeps failed hydration read-only and can retry the same workspace version", async () => {
  mockReconcile.mockRejectedValueOnce(new Error("Unavailable"));
  const { result, rerender } = renderHook(
    ({ retryToken }) => useDocumentAnnotations({ ...options, retryToken }),
    { initialProps: { retryToken: 0 } }
  );
  await waitFor(() => expect(result.current.error).toBe(true));
  expect(result.current.ready).toBe(false);
  rerender({ retryToken: 1 });
  await waitFor(() => expect(result.current.ready).toBe(true));
  expect(result.current.error).toBe(false);
});

it("keeps the current selection editable when a saved version is reconciled", async () => {
  const { result, rerender } = renderHook(
    ({ version }) =>
      useDocumentAnnotations({
        ...options,
        snapshot: { ...snapshot, version },
      }),
    { initialProps: { version: 1 } }
  );
  await waitFor(() => expect(result.current.ready).toBe(true));
  mockScope.setLocked.mockClear();
  rerender({ version: 2 });
  await waitFor(() => expect(mockReconcile).toHaveBeenCalledTimes(2));
  expect(mockScope.setLocked).not.toHaveBeenCalledWith({ type: "all" });
  expect(result.current.ready).toBe(true);
});
