import {
  canvasTarget,
  centerCamera,
  fitCamera,
  frameVisible,
  pageFrame,
  zoomCamera,
} from "@/lib/pdf-review/camera";

it("keeps the world point under the pointer fixed when zoom reaches either limit", () => {
  const camera = { x: -200, y: 40, scale: 0.5 };
  const pointer = { x: 350, y: 240 };
  for (const scale of [0.001, 1.2, 100]) {
    const next = zoomCamera(camera, scale, pointer);
    expect((pointer.x - next.x) / next.scale).toBeCloseTo(
      (pointer.x - camera.x) / camera.scale
    );
    expect((pointer.y - next.y) / next.scale).toBeCloseTo(
      (pointer.y - camera.y) / camera.scale
    );
  }
});

it("centers a finding on the second revision's second page without changing zoom", () => {
  const pages = [
    { width: 600, height: 400 },
    { width: 400, height: 600 },
  ];
  const frame = pageFrame(pages, 1, 1);
  const nativeSize = pages[1];
  if (!nativeSize) throw new Error("Missing page");
  const target = canvasTarget(frame, nativeSize, {
    origin: { x: 100, y: 300 },
    size: { width: 80, height: 60 },
  });
  const camera = centerCamera(
    { x: 0, y: 0, scale: 1.25 },
    { width: 900, height: 700 },
    target
  );
  expect(camera.scale).toBe(1.25);
  expect(
    camera.x + (target.origin.x + target.size.width / 2) * camera.scale
  ).toBeCloseTo(450);
  expect(
    camera.y + (target.origin.y + target.size.height / 2) * camera.scale
  ).toBeCloseTo(350);
  expect(canvasTarget(frame, nativeSize, null)).toEqual(frame);
});

it("fits paired sheets and only renders pages near the visible camera area", () => {
  const bounds = { origin: { x: 0, y: 0 }, size: { width: 2096, height: 800 } };
  const viewport = { width: 900, height: 700 };
  const camera = fitCamera(viewport, bounds);
  expect(bounds.size.width * camera.scale).toBeLessThanOrEqual(836);
  expect(frameVisible(camera, viewport, bounds)).toBe(true);
  expect(
    frameVisible(camera, viewport, { ...bounds, origin: { x: 0, y: 20000 } })
  ).toBe(false);
});
