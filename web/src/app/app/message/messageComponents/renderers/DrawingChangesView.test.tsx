import { render, screen, setupUser } from "@tests/setup/test-utils";
import {
  DrawingChangesView,
  drawingChangeIssues,
} from "@/app/app/message/messageComponents/renderers/DrawingChangesView";
import { resolvedAnchor } from "@/lib/pdf-review/anchors";
import type { CommentReviewDelta } from "@/app/app/services/streamingModels";

const review: CommentReviewDelta = {
  type: "comment_review_delta",
  status: "Done",
  comments: [],
  extra_issues: [],
  commented_page_count: 1,
  revised_page_count: 1,
  commented_sheet_file_id: "before",
  revised_sheet_file_id: "after",
  commented_sheet_filename: "before.pdf",
  revised_sheet_filename: "after.pdf",
  drawing_changes: {
    status: "partial",
    compared_pages: [1],
    warnings: ["One region needs inspection."],
    changes: [
      {
        id: "dc1",
        page: 1,
        kind: "text_changed",
        before_text: "R42",
        after_text: "R37",
        possible_comment_ids: [],
        vision_validation: "confirmed",
        original_box: { x: 0.1, y: 0.2, width: 0.1, height: 0.04 },
        revised_box: { x: 0.2, y: 0.3, width: 0.1, height: 0.04 },
      },
      {
        id: "dc2",
        page: 1,
        kind: "text_added",
        before_text: "",
        after_text: "0.04",
        possible_comment_ids: ["c1"],
        vision_validation: "confirmed",
        original_box: null,
        revised_box: null,
      },
    ],
  },
};

it("keeps unlinked changes separate and navigates to source evidence", async () => {
  const user = setupUser();
  const show = jest.fn();
  render(<DrawingChangesView review={review} onShow={show} />);
  expect(screen.getByText("Printed text changes (2)")).toBeInTheDocument();
  expect(screen.getByText("One region needs inspection.")).toBeInTheDocument();
  const revisedButtons = screen.getAllByRole("button", {
    name: "Show in revised",
  });
  const firstButton = revisedButtons[0];
  if (!firstButton) throw new Error("Expected evidence navigation");
  await user.click(firstButton);
  expect(show).toHaveBeenCalledWith(
    expect.objectContaining({ id: "dc1" }),
    "after",
    1
  );
  await user.click(
    screen.getByRole("button", { name: "Without a possible comment link" })
  );
  expect(
    screen.queryByText("New or unmatched text: 0.04")
  ).not.toBeInTheDocument();
  expect(screen.getByText("Printed text: R42 → R37")).toBeInTheDocument();
});

it("retains old and new locations without claiming feature confirmation", () => {
  const issue = drawingChangeIssues(review)[0];
  if (!issue) throw new Error("Expected a comparison region");
  expect(issue.anchors.before?.quality).toBe("located_difference");
  expect(resolvedAnchor(undefined, "before", issue)).toEqual({
    page: 1,
    x: 0.1,
    y: 0.2,
    width: 0.1,
    height: 0.04,
  });
  expect(resolvedAnchor(undefined, "after", issue)).toEqual({
    page: 1,
    x: 0.2,
    y: 0.3,
    width: 0.1,
    height: 0.04,
  });
});

it("separates raw visual candidates from the printed-text count", async () => {
  const user = setupUser();
  const audit = review.drawing_changes;
  if (!audit) throw new Error("Expected comparison fixture");
  render(
    <DrawingChangesView
      review={{
        ...review,
        drawing_changes: {
          ...audit,
          changes: [
            ...audit.changes,
            {
              id: "dc3",
              page: 1,
              kind: "visual",
              vision_validation: "confirmed",
              vision_explanation: "A hole was added to the side plate.",
              before_text: "",
              after_text: "",
              original_box: null,
              revised_box: null,
              possible_comment_ids: [],
            },
          ],
        },
      }}
      onShow={jest.fn()}
    />
  );
  expect(screen.getByText("Printed text changes (2)")).toBeInTheDocument();
  expect(
    screen.queryByText("A hole was added to the side plate.")
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Other visual differences (1)" })
  );
  expect(
    screen.getByText("A hole was added to the side plate.")
  ).toBeInTheDocument();
});

it("keeps unchecked and unconfirmed printed text out of findings and PDF navigation", () => {
  const audit = review.drawing_changes;
  if (!audit) throw new Error("Expected comparison fixture");
  const gatedReview: CommentReviewDelta = {
    ...review,
    drawing_changes: {
      ...audit,
      changes: audit.changes.map((change, index) => ({
        ...change,
        vision_validation: index === 0 ? "unconfirmed" : null,
      })),
    },
  };
  render(<DrawingChangesView review={gatedReview} onShow={jest.fn()} />);
  expect(screen.getByText("Printed text changes (0)")).toBeInTheDocument();
  expect(screen.queryByText("Printed text: R42 → R37")).not.toBeInTheDocument();
  expect(
    screen.queryByText("New or unmatched text: 0.04")
  ).not.toBeInTheDocument();
  expect(drawingChangeIssues(gatedReview)).toEqual([]);
});

it("shows separate stage coverage and skipped page reasons", () => {
  render(
    <DrawingChangesView
      review={{
        ...review,
        comment_verification_status: "complete",
        comment_verified_pages: [1],
        drawing_changes: {
          status: "partial",
          validation_status: "incomplete",
          compared_pages: [1],
          validated_pages: [1],
          page_pairs: { "1": 2 },
          skipped_original_pages: { "2": "timeout" },
          unmatched_revised_pages: { "3": "Inserted sheet." },
          warnings: [],
          changes: [],
        },
      }}
      onShow={jest.fn()}
    />
  );
  expect(
    screen.getByText("Comment verification: Finished. Before pages: 1.")
  ).toBeInTheDocument();
  expect(
    screen.getByText("Change validation: Incomplete. Before pages: 1.")
  ).toBeInTheDocument();
  expect(screen.getByText("Before page 1 ↔ After page 2")).toBeInTheDocument();
  expect(screen.getByText("Before page 2: timeout")).toBeInTheDocument();
  expect(screen.getByText("After page 3: Inserted sheet.")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Review incomplete. No differences were confirmed in completed checks."
    )
  ).toBeInTheDocument();
});

it("distinguishes a complete review with no confirmed differences", () => {
  render(
    <DrawingChangesView
      review={{
        ...review,
        comment_verification_status: "complete",
        drawing_changes: {
          status: "complete",
          validation_status: "complete",
          compared_pages: [1],
          validated_pages: [1],
          warnings: [],
          changes: [],
        },
      }}
      onShow={jest.fn()}
    />
  );
  expect(screen.getByText("No confirmed differences.")).toBeInTheDocument();
});

it("navigates reordered sheets and avoids a second marker for linked comment evidence", async () => {
  const audit = review.drawing_changes;
  if (!audit) throw new Error("Expected fixture");
  const show = jest.fn();
  const user = setupUser();
  const reordered = {
    ...review,
    drawing_changes: {
      ...audit,
      changes: audit.changes.map((change) => ({ ...change, revised_page: 2 })),
    },
  };
  render(<DrawingChangesView review={reordered} onShow={show} />);
  await user.click(
    screen.getAllByRole("button", { name: "Show in revised" })[0]!
  );
  expect(show).toHaveBeenCalledWith(
    expect.objectContaining({ id: "dc1" }),
    "after",
    2
  );
  expect(drawingChangeIssues(reordered)[0]?.anchors.after?.page).toBe(2);
  const linked = {
    ...reordered,
    comments: [{ id: "c1" } as CommentReviewDelta["comments"][number]],
    drawing_changes: {
      ...reordered.drawing_changes,
      changes: reordered.drawing_changes.changes.map((change) => ({
        ...change,
        verified_comment_ids: ["c1"],
      })),
    },
  };
  expect(drawingChangeIssues(linked)).toEqual([]);
});
