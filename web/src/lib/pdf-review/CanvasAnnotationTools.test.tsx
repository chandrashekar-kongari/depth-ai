import { render, screen, setupUser } from "@tests/setup/test-utils";
import {
  CanvasAnnotationTools,
  type CanvasAnnotationToolsProps,
} from "@/lib/pdf-review/CanvasAnnotationTools";

const controls: CanvasAnnotationToolsProps = {
  tool: "ink",
  editable: true,
  pending: 0,
  canUndo: false,
  canRedo: false,
  selected: null,
  onToolChange: jest.fn(),
  onUndo: jest.fn(),
  onRedo: jest.fn(),
  onDelete: jest.fn(),
  onNoteChange: jest.fn(),
  onExport: jest.fn(),
  onPrint: jest.fn(),
  status: "All changes saved",
  onRetry: jest.fn(),
  hasError: false,
};
it("shows icon tools with hover labels and the active selection", async () => {
  const user = setupUser();
  render(<CanvasAnnotationTools {...controls} />);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Draw" })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  const rectangle = screen.getByRole("button", { name: "Rectangle" });
  await user.hover(rectangle);
  expect(
    await screen.findByRole("tooltip", { name: "Rectangle" })
  ).toBeInTheDocument();
  await user.click(rectangle);
  expect(controls.onToolChange).toHaveBeenCalledWith("square");
  expect(
    screen.queryByRole("button", { name: "Retry" })
  ).not.toBeInTheDocument();
});
