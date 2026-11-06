import { revealIssue } from "@/lib/pdf-review/revealIssue";
import type { ScrollCapability, ScrollScope } from "@embedpdf/plugin-scroll";
function harness(initiallyReady = false) {
  let laidOut = initiallyReady;
  const listeners = new Set<Parameters<ScrollCapability["onLayoutReady"]>[0]>();
  const ready: ScrollCapability["onLayoutReady"] = (
    listener: Parameters<ScrollCapability["onLayoutReady"]>[0]
  ) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  };
  const scroll = {
    getLayout: () => ({
      virtualItems: laidOut ? [{ pageLayouts: [{ pageNumber: 2 }] }] : [],
    }),
    scrollToPage: jest.fn(),
  } as unknown as Pick<ScrollScope, "getLayout" | "scrollToPage">;
  return {
    ready,
    scroll,
    fire: (documentId: string) => {
      laidOut = true;
      for (const listener of listeners)
        listener({ documentId, isInitial: true, pageNumber: 2, totalPages: 3 });
    },
  };
}
it("waits for the target document layout, centers without any zoom call and reveals only once", () => {
  const h = harness();
  const revealed = jest.fn();
  const cancel = revealIssue({
    ...h,
    documentId: "revised",
    target: {
      page: 2,
      rect: { origin: { x: 60, y: 80 }, size: { width: 20, height: 10 } },
    },
    onReveal: revealed,
  });
  expect(h.scroll.scrollToPage).not.toHaveBeenCalled();
  h.fire("original");
  expect(revealed).not.toHaveBeenCalled();
  h.fire("revised");
  h.fire("revised");
  expect(h.scroll.scrollToPage).toHaveBeenCalledTimes(1);
  expect(h.scroll.scrollToPage).toHaveBeenCalledWith({
    pageNumber: 2,
    behavior: "instant",
    alignX: 50,
    alignY: 50,
    pageCoordinates: { x: 70, y: 85 },
  });
  cancel();
});
it("cancels stale requests before a delayed layout arrives", () => {
  const h = harness();
  const revealed = jest.fn();
  const cancel = revealIssue({
    ...h,
    documentId: "revised",
    target: { page: 2, rect: null },
    onReveal: revealed,
  });
  cancel();
  h.fire("revised");
  expect(h.scroll.scrollToPage).not.toHaveBeenCalled();
});
it("opens unconfirmed findings at page level with no guessed coordinate", () => {
  const h = harness(true);
  revealIssue({
    ...h,
    documentId: "revised",
    target: { page: 2, rect: null },
    onReveal: jest.fn(),
  });
  expect(h.scroll.scrollToPage).toHaveBeenCalledWith({
    pageNumber: 2,
    behavior: "instant",
    alignX: 50,
    alignY: 50,
  });
});

it("does not consume a request while the viewport has no measurable size", () => {
  const h = harness(true);
  let visible = false;
  const revealed = jest.fn();
  revealIssue({
    ...h,
    documentId: "revised",
    target: { page: 2, rect: null },
    canReveal: () => visible,
    onReveal: revealed,
  });
  expect(revealed).not.toHaveBeenCalled();
  visible = true;
  h.fire("revised");
  expect(revealed).toHaveBeenCalledTimes(1);
});

it("does not finish before the destination is visible", () => {
  const h = harness(true);
  let visible = false;
  let scrollListener: (() => void) | undefined;
  const revealed = jest.fn();
  const changed: ScrollScope["onScroll"] = (
    callback: Parameters<ScrollScope["onScroll"]>[0]
  ) => {
    scrollListener = () => callback({} as Parameters<typeof callback>[0]);
    return () => {
      scrollListener = undefined;
    };
  };
  const cancel = revealIssue({
    ...h,
    documentId: "revised",
    target: { page: 2, rect: null },
    changed,
    isVisible: () => visible,
    onReveal: revealed,
  });
  expect(revealed).not.toHaveBeenCalled();
  visible = true;
  scrollListener?.();
  expect(revealed).toHaveBeenCalledTimes(1);
  cancel();
});
