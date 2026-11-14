import { fireEvent, waitFor } from "@testing-library/react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { PdfCanvas } from "@/lib/pdf-review/PdfCanvas";
import type { PdfReviewWorkspaceProps } from "@/lib/pdf-review/types";
import type { RenderPageOptions } from "@embedpdf/plugin-render";

const mockActivate = jest.fn();
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

it("renders at Retina density through the full canvas zoom range", async () => {
  jest.replaceProperty(window, "devicePixelRatio", 2);
  render(<PdfCanvas {...props} editor={null} />);
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
  const { container, rerender } = render(
    <PdfCanvas {...props} editor={null} />
  );
  expect(
    container.querySelectorAll('[data-pdf-document="original"]')
  ).toHaveLength(2);
  expect(
    container.querySelectorAll('[data-pdf-document="revised"]')
  ).toHaveLength(2);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Zoom in" }));
  const surface =
    container.querySelector("[data-pdf-canvas]")?.firstElementChild;
  const before = surface?.getAttribute("style")?.match(/scale\(([^)]+)\)/)?.[1];
  const request = {
    id: "click1",
    issueId: "C1",
    documentId: "revised",
    page: 2,
  };
  rerender(<PdfCanvas {...props} focusRequest={request} editor={null} />);
  await waitFor(() => expect(mockActivate).toHaveBeenCalledWith("revised"));
  expect(props.onPageChange).toHaveBeenCalledWith(2);
  expect(screen.getByTestId("pdf-attention-ring")).toBeInTheDocument();
  expect(surface?.getAttribute("style")).toContain(`scale(${before})`);
  fireEvent.wheel(screen.getByRole("application"), { deltaX: 120, deltaY: 50 });
  const panned = surface?.getAttribute("style");
  rerender(
    <PdfCanvas
      {...props}
      focusRequest={{ ...request, id: "click2" }}
      editor={null}
    />
  );
  await waitFor(() => expect(surface?.getAttribute("style")).not.toBe(panned));
  expect(surface?.getAttribute("style")).toContain(`scale(${before})`);
});

it("opens uncertain findings at page level and returns from annotation mode", async () => {
  render(
    <PdfCanvas
      {...props}
      focusRequest={{
        id: "unknown",
        issueId: "missing",
        documentId: "original",
        page: 1,
      }}
      editor={<div>Editor fixture</div>}
    />
  );
  await waitFor(() => expect(mockActivate).toHaveBeenCalledWith("original"));
  expect(screen.queryByTestId("pdf-attention-ring")).not.toBeInTheDocument();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Annotate" }));
  expect(screen.getByText("Editor fixture")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Back to canvas" }));
  expect(screen.getByRole("application")).toBeVisible();
});
