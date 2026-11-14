import { fireEvent, render, screen, setupUser } from "@tests/setup/test-utils";
import { Button } from "@opal/components";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";

jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({ allRecentFiles: [] }),
}));

afterEach(() => jest.restoreAllMocks());

it("opens the native device picker directly from the upload row", async () => {
  const user = setupUser();
  const showPicker = jest.fn();
  const { container } = render(
    <FilePickerPopover
      handleUploadChange={jest.fn()}
      trigger={<Button>Attach files</Button>}
    />
  );
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("Missing device upload input");
  Object.defineProperty(input, "showPicker", {
    configurable: true,
    value: showPicker,
  });
  await user.click(screen.getByRole("button", { name: "Attach files" }));
  await user.click(screen.getByText("Upload a file from your device"));
  expect(showPicker).toHaveBeenCalledTimes(1);
});

it("keeps the fallback input click away from parent handlers and delivers selected files", async () => {
  const user = setupUser();
  const parentClick = jest.fn();
  const onChange = jest.fn();
  const { container } = render(
    <div
      aria-label="Parent control"
      role="button"
      tabIndex={0}
      onKeyDown={parentClick}
      onClick={parentClick}
    >
      <FilePickerPopover
        handleUploadChange={onChange}
        trigger={<Button>Attach files</Button>}
      />
    </div>
  );
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("Missing device upload input");
  Object.defineProperty(input, "showPicker", {
    configurable: true,
    value: undefined,
  });
  await user.click(screen.getByRole("button", { name: "Attach files" }));
  parentClick.mockClear();
  await user.click(screen.getByText("Upload a file from your device"));
  expect(parentClick).not.toHaveBeenCalled();
  const file = new File(["drawing"], "drawing.pdf", {
    type: "application/pdf",
  });
  fireEvent.change(input, { target: { files: [file] } });
  expect(onChange).toHaveBeenCalledTimes(1);
});
