import { Locator, Page, expect } from "@playwright/test";

export class SidebarChatRow {
  constructor(
    readonly page: Page,
    readonly name: string
  ) {}

  /**
   * The row container. Matched by the visible label, so it matches nothing
   * while the row shows the inline rename editor.
   */
  get root(): Locator {
    return this.page.getByTestId("ChatButton").filter({ hasText: this.name });
  }

  /** The "..." button that opens the row's options popover. */
  get optionsButton(): Locator {
    return this.root.getByTestId("ChatButton/options");
  }

  /** The options menu. Only one row's menu is open at a time. */
  get optionsPopover(): Locator {
    return this.page.getByRole("menu", { name: "Chat options" });
  }

  /**
   * The inline rename editor. The editor replaces the row's label, so this
   * cannot be scoped to the row by name; only one row renames at a time.
   */
  get renameInput(): Locator {
    return this.page.getByTestId("ChatButton").getByRole("textbox");
  }

  /** Reveals the row's actions and opens the options popover. */
  async openOptions(): Promise<void> {
    await this.root.hover();
    await this.optionsButton.click();
    await expect(this.optionsPopover).toBeVisible();
  }

  /** Opens the options popover and clicks "Rename". */
  async startRename(): Promise<void> {
    await this.openOptions();
    await this.optionsPopover.getByRole("menuitem", { name: "Rename" }).click();
  }

  /** Types a new name into the rename editor and submits it. */
  async submitRename(newName: string): Promise<void> {
    await this.renameInput.fill(newName);
    await this.renameInput.press("Enter");
  }
}

/** The main application sidebar. */
export class AppSidebarPage {
  constructor(private readonly page: Page) {}

  /** A chat session row, looked up by its visible name. */
  chatRow(name: string): SidebarChatRow {
    return new SidebarChatRow(this.page, name);
  }

  async goto(): Promise<void> {
    await this.page.goto("/app");
    await this.page.waitForLoadState("networkidle");
  }

  async fold(): Promise<void> {
    const close = this.page.getByLabel("Close Sidebar", { exact: true });
    await close.click();
    await expect(close).toBeHidden();
  }

  async expectSimplifiedNavigation(): Promise<void> {
    await expect(this.page.getByTestId("AppSidebar/new-session")).toBeVisible();
    await expect(this.page.getByTestId("AppSidebar/projects")).toHaveCount(0);
    await expect(this.page.getByTestId("AppSidebar/more-agents")).toHaveCount(
      0
    );
    await expect(
      this.page.getByRole("link", { name: "Plugins", exact: true })
    ).toHaveCount(0);
    await expect(
      this.page.getByRole("button", { name: "New Project", exact: true })
    ).toHaveCount(0);
  }
}
