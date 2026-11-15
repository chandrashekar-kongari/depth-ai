import { renderToString } from "react-dom/server";
import { render } from "@tests/setup/test-utils";
import { useReducedMotion } from "motion/react";
import { DepthActivityIcon } from "@/refresh-components/avatars/DepthActivityIcon";

jest.mock("motion/react", () => ({
  ...jest.requireActual<typeof import("motion/react")>("motion/react"),
  useReducedMotion: jest.fn(),
}));

beforeEach(() => jest.mocked(useReducedMotion).mockReturnValue(false));

test("animates only while active and removes the animation when work ends", () => {
  const { container, rerender } = render(
    <DepthActivityIcon active size={24} />
  );
  expect(container.querySelector("[data-depth-pulse]")).not.toBeNull();
  expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  rerender(<DepthActivityIcon active={false} size={24} />);
  expect(container.querySelector("[data-depth-pulse]")).toBeNull();
  expect(container.querySelector("svg")).toHaveAttribute(
    "data-depth-activity",
    "idle"
  );
  expect(container.querySelector("svg")).toHaveAttribute("width", "24");
});

test.each([true, null])(
  "keeps the mark static when reduced motion is %s",
  (preference) => {
    jest.mocked(useReducedMotion).mockReturnValue(preference);
    const { container } = render(<DepthActivityIcon active />);
    expect(container.querySelector("[data-depth-pulse]")).toBeNull();
    expect(container.querySelector("svg")).toHaveAttribute(
      "data-depth-activity",
      "working"
    );
  }
);

test("server rendering keeps the first frame static for hydration", () => {
  const markup = renderToString(<DepthActivityIcon active />);
  expect(markup).not.toContain("data-depth-pulse");
  expect(markup).toContain('data-depth-activity="working"');
});
