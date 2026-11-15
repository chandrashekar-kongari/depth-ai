import { fireEvent, render, screen, setupUser } from "@tests/setup/test-utils";
import { Button } from "@opal/components";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";

import { ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { ChatFileType } from "@/app/app/types";

const mockRecentFiles: ProjectFile[] = ["original", "revised"].map((id) => ({
  id,
  name: `${id}.pdf`,
  project_id: null,
  user_id: null,
  file_id: id,
  created_at: "2026-11-15T00:00:00Z",
  status: UserFileStatus.COMPLETED,
  file_type: "application/pdf",
  last_accessed_at: "2026-11-15T00:00:00Z",
  chat_file_type: ChatFileType.DOCUMENT,
  token_count: null,
  chunk_count: null,
}));

jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({ allRecentFiles: mockRecentFiles }),
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

it("keeps recent files open while attaching and removing files", async () => {
  const user = setupUser();
  const onPickRecent = jest.fn();
  const onUnpickRecent = jest.fn();
  const props = {
    handleUploadChange: jest.fn(),
    onPickRecent,
    onUnpickRecent,
    trigger: <Button>Attach files</Button>,
  };
  const { rerender } = render(<FilePickerPopover {...props} />);
  await user.click(screen.getByRole("button", { name: "Attach files" }));
  await user.click(screen.getByText("original.pdf"));
  expect(onPickRecent).toHaveBeenLastCalledWith(mockRecentFiles[0]);
  expect(screen.getByText("revised.pdf")).toBeVisible();

  rerender(<FilePickerPopover {...props} selectedFileIds={["original"]} />);
  await user.click(screen.getByText("revised.pdf"));
  expect(onPickRecent).toHaveBeenLastCalledWith(mockRecentFiles[1]);
  await user.click(screen.getByText("original.pdf"));
  expect(onUnpickRecent).toHaveBeenCalledWith(mockRecentFiles[0]);
  expect(screen.getByText("revised.pdf")).toBeVisible();

  await user.keyboard("{Escape}");
  expect(screen.getByRole("button", { name: "Attach files" })).toHaveAttribute(
    "aria-expanded",
    "false"
  );
});
