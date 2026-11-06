import { render, screen, setupUser } from "@tests/setup/test-utils";
import { InputTypeIn } from "@opal/components";
import { ChatWorkspace } from "@/lib/chat-workspace/ChatWorkspace";

const originalObserver = global.ResizeObserver;
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {
      /* Layout measurement is not available in jsdom. */
    }
    unobserve() {
      /* No observation resources. */
    }
    disconnect() {
      /* No observation resources. */
    }
  };
});
afterAll(() => {
  global.ResizeObserver = originalObserver;
});

it("retains a typed draft when the document pane opens and closes", async () => {
  const user = setupUser();
  const input = <InputTypeIn aria-label="Draft" />;
  const { rerender } = render(
    <ChatWorkspace document={null}>{input}</ChatWorkspace>
  );
  await user.type(
    screen.getByRole("textbox", { name: "Draft" }),
    "Unsaved engineering note"
  );
  rerender(
    <ChatWorkspace document={<article>Drawing</article>}>{input}</ChatWorkspace>
  );
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue(
    "Unsaved engineering note"
  );
  rerender(<ChatWorkspace document={null}>{input}</ChatWorkspace>);
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue(
    "Unsaved engineering note"
  );
});
