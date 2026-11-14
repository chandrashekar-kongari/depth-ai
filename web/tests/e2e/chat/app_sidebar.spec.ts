import { test } from "@playwright/test";
import { AppSidebarPage } from "@tests/e2e/pages/AppSidebarPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";

test("keeps navigation compact when the chat sidebar is open or folded", async ({
  page,
}, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);

  const sidebar = new AppSidebarPage(page);
  await sidebar.goto();
  await sidebar.expectSimplifiedNavigation();
  await sidebar.fold();
  await sidebar.expectSimplifiedNavigation();
});
