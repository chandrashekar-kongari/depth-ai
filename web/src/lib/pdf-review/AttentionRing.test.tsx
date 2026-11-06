import { render, screen } from "@tests/setup/test-utils";
import {
  AttentionRing,
  scheduleAttentionEnd,
} from "@/lib/pdf-review/AttentionRing";
jest.mock("@embedpdf/plugin-scroll/react", () => ({
  useScroll: () => ({
    provides: {
      getRectPositionForPage: (
        _page: number,
        rect: { size: { width: number } }
      ) =>
        rect.size.width === 600
          ? { origin: { x: 40, y: 80 }, size: { width: 600, height: 400 } }
          : { origin: { x: 140, y: 180 }, size: { width: 20, height: 10 } },
    },
  }),
}));
jest.mock("@embedpdf/core/react", () => ({
  useDocumentState: () => ({
    document: { pages: [{ size: { width: 600, height: 400 } }] },
  }),
}));
it("uses SDK page-relative coordinates for the transient ring", () => {
  render(
    <AttentionRing
      documentId="revised"
      pageIndex={0}
      rect={{ origin: { x: 100, y: 100 }, size: { width: 20, height: 10 } }}
    />
  );
  expect(screen.getByTestId("pdf-attention-ring")).toHaveStyle({
    left: "110px",
    top: "105px",
  });
});
it("ends at two seconds and cancels an old timer on a newer request", () => {
  jest.useFakeTimers();
  const first = jest.fn(),
    second = jest.fn();
  const cancel = scheduleAttentionEnd(first);
  cancel();
  scheduleAttentionEnd(second);
  jest.advanceTimersByTime(1999);
  expect(second).not.toHaveBeenCalled();
  jest.advanceTimersByTime(1);
  expect(second).toHaveBeenCalledTimes(1);
  expect(first).not.toHaveBeenCalled();
  jest.useRealTimers();
});
