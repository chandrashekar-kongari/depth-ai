import { render, screen, setupUser } from "@tests/setup/test-utils";
import { CommentReviewRenderer } from "@/app/app/message/messageComponents/renderers/CommentReviewRenderer";
import { RenderType } from "@/app/app/message/messageComponents/types";
import { CommentReviewView } from "@/app/app/message/messageComponents/renderers/CommentReviewView";
import {
  DrawingReviewLayoutProvider,
  useDrawingReviewLayout,
} from "@/app/app/message/messageComponents/renderers/drawingReviewLayout";
import type { CommentReviewDelta } from "@/app/app/services/streamingModels";
jest.mock("@/lib/pdf-review/PdfReviewWorkspace", () => ({
  PdfReviewWorkspace: () => null,
}));
const review: CommentReviewDelta = {
  type: "comment_review_delta",
  commented_page_count: 3,
  revised_page_count: 3,
  status: "completed",
  commented_sheet_file_id: "original",
  commented_sheet_filename: "a.pdf",
  revised_sheet_file_id: "revised",
  revised_sheet_filename: "b.pdf",
  comments: [
    {
      id: "C1",
      page: 1,
      text: "Bore tolerance",
      request: "Add H7",
      evidence: "H7 exists",
      remaining: "",
      verdict: "solved_correct",
      box: null,
      page_level: true,
      span_id: null,
      revised_page: 3,
      revised_box: null,
      revised_page_level: true,
      revised_span_id: null,
    },
  ],
  extra_issues: [
    {
      id: "E1",
      page: 2,
      title: "Missing datum",
      detail: "Add datum",
      box: null,
      page_level: true,
      span_id: null,
    },
  ],
};
function FocusState() {
  const { focusRequest } = useDrawingReviewLayout();
  return (
    <output aria-label="Navigation target">
      {JSON.stringify(focusRequest)}
    </output>
  );
}
it("shows unrequested changes without counting them as defects", async () => {
  const user = setupUser();
  render(
    <CommentReviewView
      review={{
        ...review,
        extra_issues: [
          {
            id: "change1",
            page: 1,
            title: "Finish changed",
            detail: "No linked request.",
            kind: "change",
            before_evidence: "PAINT",
            after_evidence: "ANODIZE",
            box: null,
            page_level: true,
            span_id: null,
          },
        ],
      }}
      part="queue"
    />
  );
  expect(screen.getByText("Change without a linked request")).toBeVisible();
  expect(screen.getByText("Before: PAINT. After: ANODIZE.")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Needs attention (0)" }));
  expect(screen.queryByText("Finish changed")).not.toBeInTheDocument();
});
it("gives each finding two revision buttons and creates a fresh navigation request on every click", async () => {
  const user = setupUser();
  render(
    <DrawingReviewLayoutProvider active mode="comments" reviewKey="review">
      <CommentReviewView review={review} part="queue" />
      <FocusState />
    </DrawingReviewLayoutProvider>
  );
  expect(
    screen.getAllByRole("button", { name: "Show in original" })
  ).toHaveLength(2);
  const [firstRevised, secondRevised] = screen.getAllByRole("button", {
    name: "Show in revised",
  });
  const [firstOriginal] = screen.getAllByRole("button", {
    name: "Show in original",
  });
  if (!firstRevised || !secondRevised || !firstOriginal)
    throw new Error("Missing navigation controls");
  await user.click(firstRevised);
  const first = screen.getByLabelText("Navigation target").textContent;
  expect(JSON.parse(first ?? "null")).toMatchObject({
    issueId: "C1",
    documentId: "revised",
    page: 3,
  });
  await user.click(firstRevised);
  expect(screen.getByLabelText("Navigation target").textContent).not.toBe(
    first
  );
  await user.click(firstOriginal);
  expect(
    JSON.parse(screen.getByLabelText("Navigation target").textContent ?? "null")
  ).toMatchObject({ issueId: "C1", documentId: "original", page: 1 });
  await user.click(secondRevised);
  expect(
    JSON.parse(screen.getByLabelText("Navigation target").textContent ?? "null")
  ).toMatchObject({ issueId: "E1", documentId: "revised", page: 2 });
});

it("filters results without changing coverage or losing evidence and revision navigation", async () => {
  const user = setupUser();
  render(<CommentReviewView review={review} part="queue" />);
  expect(screen.queryByText(/H7 exists/)).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Details for finding 1" })
  );
  expect(screen.getByText(/H7 exists/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Needs attention (1)" }));
  expect(screen.queryByText("Bore tolerance")).not.toBeInTheDocument();
  expect(screen.getByText("Missing datum")).toBeVisible();
  expect(screen.getByText("2 findings · 0 need review")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Addressed (1)" }));
  expect(screen.getByText("Bore tolerance")).toBeVisible();
  expect(screen.queryByText("Missing datum")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Show in revised" })).toBeEnabled();
});

it("searches evidence while retaining the original finding number", async () => {
  const user = setupUser();
  render(<CommentReviewView review={review} part="queue" />);
  await user.type(
    screen.getByRole("textbox", { name: "Search findings" }),
    "H7"
  );
  expect(
    screen.getByRole("button", { name: "Details for finding 1" })
  ).toBeVisible();
  expect(screen.queryByText("Missing datum")).not.toBeInTheDocument();
});

it("shows the latest findings before the tool section ends", () => {
  const onComplete = jest.fn();
  const placement = { turn_index: 0, tab_index: 0 };
  render(
    <CommentReviewRenderer
      state={{}}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen={false}
      onComplete={onComplete}
      packets={[
        { placement, obj: { type: "comment_review_start" } },
        { placement, obj: { ...review, comments: [], extra_issues: [] } },
        { placement, obj: review },
      ]}
    >
      {(steps) => <>{steps[0]?.content}</>}
    </CommentReviewRenderer>
  );
  expect(screen.getByText("Bore tolerance")).toBeInTheDocument();
  expect(onComplete).not.toHaveBeenCalled();
});
