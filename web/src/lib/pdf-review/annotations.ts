export interface Point {
  x: number;
  y: number;
}
export interface ReviewAnnotation {
  id: string;
  page: number;
  kind: "highlight" | "ink" | "note";
  points: Point[];
  text: string;
}
export interface AnnotationHistory {
  past: ReviewAnnotation[][];
  present: ReviewAnnotation[];
  future: ReviewAnnotation[][];
}
export function emptyHistory(): AnnotationHistory {
  return { past: [], present: [], future: [] };
}
export function commitAnnotations(
  history: AnnotationHistory,
  present: ReviewAnnotation[]
): AnnotationHistory {
  return {
    past: [...history.past.slice(-99), history.present],
    present,
    future: [],
  };
}
export function undoAnnotations(history: AnnotationHistory): AnnotationHistory {
  const previous = history.past.at(-1);
  return previous
    ? {
        past: history.past.slice(0, -1),
        present: previous,
        future: [history.present, ...history.future],
      }
    : history;
}
export function redoAnnotations(history: AnnotationHistory): AnnotationHistory {
  const next = history.future[0];
  return next
    ? {
        past: [...history.past, history.present],
        present: next,
        future: history.future.slice(1),
      }
    : history;
}
export function normalizedPoint(
  x: number,
  y: number,
  width: number,
  height: number
): Point {
  return {
    x: Math.max(0, Math.min(1, x / width)),
    y: Math.max(0, Math.min(1, y / height)),
  };
}
