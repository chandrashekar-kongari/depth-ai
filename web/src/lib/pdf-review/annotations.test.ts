import {
  commitAnnotations,
  emptyHistory,
  normalizedPoint,
  redoAnnotations,
  undoAnnotations,
  type ReviewAnnotation,
} from "@/lib/pdf-review/annotations";
const highlight: ReviewAnnotation = {
  id: "a",
  page: 1,
  kind: "highlight",
  points: [
    { x: 0.1, y: 0.2 },
    { x: 0.3, y: 0.4 },
  ],
  text: "",
};
const note: ReviewAnnotation = {
  id: "b",
  page: 2,
  kind: "note",
  points: [{ x: 0.5, y: 0.6 }],
  text: "Check tolerance",
};
it("undoes and redoes edits across pages without mutating earlier snapshots", () => {
  const first = commitAnnotations(emptyHistory(), [highlight]);
  const second = commitAnnotations(first, [highlight, note]);
  expect(undoAnnotations(second).present).toEqual([highlight]);
  expect(redoAnnotations(undoAnnotations(second)).present).toEqual([
    highlight,
    note,
  ]);
  expect(first.present).toEqual([highlight]);
});
it("invalidates redo after a new edit and bounds undo snapshots", () => {
  const undone = undoAnnotations(
    commitAnnotations(commitAnnotations(emptyHistory(), [highlight]), [
      highlight,
      note,
    ])
  );
  expect(commitAnnotations(undone, [note]).future).toEqual([]);
  let history = emptyHistory();
  for (let index = 0; index < 130; index++)
    history = commitAnnotations(history, [highlight]);
  expect(history.past).toHaveLength(100);
});
it("maps zoomed pointer coordinates to stable page coordinates and clamps outside drags", () => {
  expect(normalizedPoint(100, 150, 1000, 500)).toEqual(
    normalizedPoint(200, 300, 2000, 1000)
  );
  expect(normalizedPoint(-10, 510, 1000, 500)).toEqual({ x: 0, y: 1 });
});
