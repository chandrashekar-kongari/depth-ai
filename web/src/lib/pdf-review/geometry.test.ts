import { anchorRect, rectAnchor } from "@/lib/pdf-review/geometry";
it.each([
  { width: 600, height: 400 },
  { width: 400, height: 600 },
  { width: 2384, height: 1684 },
])("round trips native page geometry for %o without display scale", (size) => {
  const anchor = { page: 2, x: 0.125, y: 0.25, width: 0.25, height: 0.125 };
  expect(rectAnchor(anchorRect(anchor, size), size, 2)).toEqual(anchor);
});
it("rejects invalid geometry instead of clamping it into a plausible location", () => {
  expect(
    rectAnchor(
      { origin: { x: -5, y: 0 }, size: { width: 20, height: 20 } },
      { width: 100, height: 100 },
      1
    )
  ).toBeNull();
  expect(
    rectAnchor(
      { origin: { x: 95, y: 0 }, size: { width: 20, height: 20 } },
      { width: 100, height: 100 },
      1
    )
  ).toBeNull();
});
