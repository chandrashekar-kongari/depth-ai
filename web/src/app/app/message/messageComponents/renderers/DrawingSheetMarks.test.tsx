import type { ReactNode } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { DrawingSheetMarks } from "@/app/app/message/messageComponents/renderers/DrawingSheetMarks";
import type { DrawingFinding } from "@/app/app/services/streamingModels";

jest.mock("react-pdf", () => ({
  pdfjs: { version: "test", GlobalWorkerOptions: {} },
  Document: ({ children }: { children: ReactNode; file: Blob }) => (
    <div data-testid="pdf-document">{children}</div>
  ),
  Page: ({ pageNumber }: { pageNumber: number }) => (
    <div data-testid="pdf-page" data-page={pageNumber} />
  ),
}));

const findings: DrawingFinding[] = [
  {
    id: "f1",
    category: "title_block",
    status: "fail",
    page: 1,
    title: "Revision is missing",
    detail: "The revision field is blank.",
    evidence: "visible text: none",
    source: "observed",
    span_id: "p1s0",
    box: { x: 0.1, y: 0.1, width: 0.2, height: 0.05 },
    page_level: false,
    standard_citation: "No company standard was used.",
  },
  {
    id: "f2",
    category: "dimensions",
    status: "needs_review",
    page: 2,
    title: "Angular tolerance conflicts",
    detail: "Sheet 2 does not match sheet 1.",
    evidence: "visible text: 0.5",
    source: "observed",
    span_id: "p2s1",
    box: { x: 0.4, y: 0.4, width: 0.2, height: 0.05 },
    page_level: false,
    standard_citation: "No company standard was used.",
  },
  {
    id: "f3",
    category: "views",
    status: "pass",
    page: 1,
    title: "Units are stated",
    detail: "The units note is on the sheet.",
    evidence: "visible text: mm",
    source: "observed",
    span_id: null,
    box: null,
    page_level: false,
    standard_citation: null,
  },
];

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    blob: async () => new Blob(["%PDF"], { type: "application/pdf" }),
  }) as typeof fetch;
});

it("selects the finding box and its page", async () => {
  const user = setupUser();
  render(
    <DrawingSheetMarks
      sheetFileId="sheet-1"
      sheetFilename="sheet.pdf"
      pageCount={2}
      findings={findings}
    />
  );

  expect(await screen.findByTestId("pdf-page")).toHaveAttribute(
    "data-page",
    "1"
  );
  expect(
    screen.getByRole("button", { name: "Dimensions and tolerances" })
  ).toHaveAttribute("aria-expanded", "true");
  expect(screen.queryByRole("button", { name: "Units are stated" })).toBeNull();
  expect(screen.getByText("Views and notes")).toBeInTheDocument();

  await user.click(
    screen.getByRole("button", { name: "Angular tolerance conflicts" })
  );

  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "2");
  const mark = screen.getByRole("button", {
    name: "Mark: Angular tolerance conflicts",
  });
  expect(mark).toHaveAttribute("aria-pressed", "true");
  expect(mark.closest("[data-finding-id='f2']")).toHaveAttribute(
    "data-selected",
    "true"
  );

  await user.click(mark);
  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "2");
  expect(
    screen.getByRole("button", { name: "Revision is missing" })
  ).toHaveAttribute("aria-pressed", "false");
});
