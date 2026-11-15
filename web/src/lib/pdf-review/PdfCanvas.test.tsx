import type { HTMLAttributes } from "react";
import { act, fireEvent, waitFor } from "@testing-library/react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { PdfCanvas } from "@/lib/pdf-review/PdfCanvas";
import type { PdfReviewWorkspaceProps } from "@/lib/pdf-review/types";
import type { RenderPageOptions } from "@embedpdf/plugin-render";

const mockActivate = jest.fn();
const mockAnnotation = {
  setActiveTool: jest.fn(),
  deselectAnnotation: jest.fn(),
};
const mockAnnotationState = { selectedUid: null, byUid: {} };
jest.mock("@embedpdf/plugin-annotation/react", () => ({
  useAnnotation: () => ({
    provides: mockAnnotation,
    state: mockAnnotationState,
  }),
  AnnotationLayer: () => <div data-testid="native-annotations" />,
}));
jest.mock("@embedpdf/plugin-export/react", () => ({
  useExportCapability: () => ({ provides: null }),
}));
jest.mock("@embedpdf/plugin-print/react", () => ({
  usePrintCapability: () => ({ provides: null }),
}));
jest.mock("@embedpdf/plugin-selection/react", () => ({
  SelectionLayer: () => null,
}));
jest.mock("@embedpdf/plugin-interaction-manager/react", () => ({
  PagePointerProvider: ({
    children,
    style,
    inert,
  }: HTMLAttributes<HTMLDivElement>) => (
    <div style={style} inert={inert}>
      {children}
    </div>
  ),
}));
jest.mock("@/lib/pdf-review/useDocumentAnnotations", () => ({
  useDocumentAnnotations: () => ({
    annotation: mockAnnotation,
    state: mockAnnotationState,
    ready: true,
    error: false,
  }),
}));
const mockRenderPage = jest.fn((_options: RenderPageOptions) => ({
  wait: jest.fn(),
  abort: jest.fn(),
}));
const mockRenderCapability = {
  forDocument: () => ({ renderPage: mockRenderPage }),
};
const mockPdf = {
  pageCount: 2,
  pages: [
    { size: { width: 600, height: 400 } },
    { size: { width: 400, height: 600 } },
  ],
};
jest.mock("@embedpdf/core/react", () => ({
  useDocumentState: () => ({ status: "loaded", document: mockPdf }),
}));
jest.mock("@embedpdf/plugin-document-manager/react", () => ({
  useDocumentManagerCapability: () => ({
    provides: { setActiveDocument: mockActivate },
  }),
}));
jest.mock("@embedpdf/plugin-render/react", () => ({
  useRenderCapability: () => ({ provides: mockRenderCapability }),
}));
jest.mock("@/lib/pdf-review/hooks", () => ({
  useDrawingWorkspace: () => ({ snapshot: undefined, reload: jest.fn() }),
}));
jest.mock("@/lib/pdf-review/useTextLocations", () => ({
  useTextLocations: (_snapshot: unknown, _id: string, issues: unknown) => ({
    issues,
    isLoading: false,
  }),
}));
jest.mock("@/lib/pdf-review/ReviewStatusMarkers", () => ({
  ReviewStatusMarkers: () => null,
}));

const props: PdfReviewWorkspaceProps = {
  documents: [
    { id: "original", url: "/a.pdf", filename: "a.pdf", label: "Original" },
    { id: "revised", url: "/b.pdf", filename: "b.pdf", label: "Revised" },
  ],
  pageNumber: 1,
  onPageChange: jest.fn(),
  issues: [
    {
      id: "C1",
      title: "Width",
      request: "Correct width",
      evidence: "",
      remaining: "",
      anchors: {
        revised: {
          page: 2,
          quality: "confirmed",
          pageLevel: false,
          box: { x: 0.1, y: 0.2, width: 0.1, height: 0.1 },
        },
      },
    },
  ],
};

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(globalThis, "ResizeObserver").mockImplementation((callback) => ({
    observe: () =>
      callback(
        [{ contentRect: { width: 900, height: 700 } } as ResizeObserverEntry],
        {} as ResizeObserver
      ),
    unobserve: jest.fn(),
    disconnect: jest.fn(),
  }));
});
afterEach(() => jest.restoreAllMocks());

it("keeps the floating dock outside camera gestures and opens compact controls", async () => {
  const user = setupUser();
  const { container } = render(<PdfCanvas {...props} />);
  const toolbar = screen.getByRole("toolbar", { name: "Drawing workspace" });
  const canvas = screen.getByRole("application");
  expect(canvas).not.toContainElement(toolbar);
  const surface =
    container.querySelector("[data-pdf-canvas]")?.firstElementChild;
  const before = surface?.getAttribute("style");
  fireEvent.wheel(toolbar, { deltaY: 120, ctrlKey: true });
  expect(surface?.getAttribute("style")).toBe(before);
  await user.click(screen.getByRole("button", { name: "Zoom in" }));
  const zoomedIn = surface?.getAttribute("style");
  expect(zoomedIn).not.toBe(before);
  await user.click(screen.getByRole("button", { name: "Zoom out" }));
  expect(surface?.getAttribute("style")).not.toBe(zoomedIn);
  await user.click(screen.getByRole("button", { name: "Zoom controls" }));
  expect(screen.getByRole("button", { name: "Fit page" })).toBeVisible();
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Documents and pages" }));
  await user.click(screen.getByRole("button", { name: "Revised" }));
  expect(mockActivate).toHaveBeenCalledWith("revised");
  expect(screen.getByRole("spinbutton", { name: "Page" })).toBeInTheDocument();
  await user.keyboard("{Escape}");
  act(() => screen.getByRole("button", { name: "Select" }).focus());
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("button", { name: "Pan" })).toHaveFocus();
});

it("renders at Retina density through the full canvas zoom range", async () => {
  jest.replaceProperty(window, "devicePixelRatio", 2);
  render(<PdfCanvas {...props} />);
  await waitFor(() =>
    expect(mockRenderPage).toHaveBeenCalledWith(
      expect.objectContaining({ options: expect.objectContaining({ dpr: 2 }) })
    )
  );
  const user = setupUser();
  for (let step = 0; step < 18; step++) {
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
  }
  await waitFor(() =>
    expect(
      mockRenderPage.mock.calls.some(
        ([options]) =>
          options.pageIndex === 0 &&
          options.options.dpr === 2 &&
          (options.options.scaleFactor ?? 0) >= (4 * 1000) / 600
      )
    ).toBe(true)
  );
});

it("keeps both revisions on one camera and repeated card requests preserve zoom", async () => {
  const { container, rerender } = render(<PdfCanvas {...props} />);
  expect(
    container.querySelectorAll('[data-pdf-document="original"]')
  ).toHaveLength(2);
  expect(
    container.querySelectorAll('[data-pdf-document="revised"]')
  ).toHaveLength(2);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Zoom in" }));
  await user.keyboard("{Escape}");
  const surface =
    container.querySelector("[data-pdf-canvas]")?.firstElementChild;
  const before = surface?.getAttribute("style")?.match(/scale\(([^)]+)\)/)?.[1];
  const request = {
    id: "click1",
    issueId: "C1",
    documentId: "revised",
    page: 2,
  };
  rerender(<PdfCanvas {...props} focusRequest={request} />);
  await waitFor(() => expect(mockActivate).toHaveBeenCalledWith("revised"));
  expect(props.onPageChange).toHaveBeenCalledWith(2);
  expect(screen.getByTestId("pdf-attention-ring")).toBeInTheDocument();
  expect(surface?.getAttribute("style")).toContain(`scale(${before})`);
  fireEvent.wheel(screen.getByRole("application"), { deltaX: 120, deltaY: 50 });
  const panned = surface?.getAttribute("style");
  rerender(
    <PdfCanvas {...props} focusRequest={{ ...request, id: "click2" }} />
  );
  await waitFor(() => expect(surface?.getAttribute("style")).not.toBe(panned));
  expect(surface?.getAttribute("style")).toContain(`scale(${before})`);
});

it("opens uncertain findings at page level and edits without replacing the canvas", async () => {
  render(
    <PdfCanvas
      {...props}
      focusRequest={{
        id: "unknown",
        issueId: "missing",
        documentId: "original",
        page: 1,
      }}
    />
  );
  await waitFor(() => expect(mockActivate).toHaveBeenCalledWith("original"));
  expect(screen.queryByTestId("pdf-attention-ring")).not.toBeInTheDocument();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Annotate" }));
  expect(
    screen.queryByRole("button", { name: "Back to canvas" })
  ).not.toBeInTheDocument();
  expect(screen.getAllByTestId("native-annotations").length).toBeGreaterThan(0);
  await user.keyboard("{Escape}");
  expect(screen.getByRole("application")).toBeVisible();
});
