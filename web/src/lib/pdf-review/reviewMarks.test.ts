import { createReviewMarks } from "@/lib/pdf-review/reviewMarks";
import type { LinkedIssue } from "@/lib/pdf-review/types";
const issue: LinkedIssue = {
  id: "c1",
  title: "Bore fit",
  request: "Add H7",
  evidence: "Ø8 H7",
  remaining: "",
  verdict: "solved_correct",
  anchors: {},
};
const anchor = { page: 2, x: 0.1, y: 0.2, width: 0.3, height: 0.1 };
it("creates printable green region and status annotations for a completed comment", () => {
  const marks = createReviewMarks(
    issue,
    anchor,
    1,
    { width: 600, height: 400 },
    "Solved, correct"
  );
  expect(marks.map((mark) => mark.type)).toEqual([5, 3]);
  expect(marks[0]).toMatchObject({
    pageIndex: 1,
    strokeColor: "#17834b",
    flags: ["print"],
    rect: { origin: { x: 60, y: 80 }, size: { width: 180, height: 40 } },
  });
  expect(marks[1]?.contents).toContain("Solved, correct");
});
it.each(["open", "solved_incorrect"] as const)(
  "marks %s in red with its evidence",
  (verdict) => {
    const marks = createReviewMarks(
      { ...issue, verdict, remaining: "Add the missing fit" },
      anchor,
      0,
      { width: 600, height: 400 },
      verdict
    );
    expect(marks[0]).toMatchObject({ strokeColor: "#c83232" });
    expect(marks[0]?.contents).toContain("Add the missing fit");
  }
);
it("does not add edge placeholders when location is unresolved", () => {
  const marks = createReviewMarks(
    { ...issue, verdict: "unclear" },
    null,
    0,
    { width: 600, height: 400 },
    "Unclear"
  );
  expect(marks).toEqual([]);
});
