import { render, screen, setupUser } from "@tests/setup/test-utils";
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
