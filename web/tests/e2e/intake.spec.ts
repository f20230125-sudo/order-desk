import { expect, test } from "@playwright/test";
import { expectAccessible, workAs, writesAllowed } from "./helpers";

test.beforeEach(async ({ page }) => {
  await page.goto("/intake");
  await expect(page.getByRole("heading", { name: "Add from a document" })).toBeVisible();
});

test("the tray offers the sample documents and is accessible", async ({ page }) => {
  await expect(page.locator("button.sample")).toHaveCount(6);
  await expectAccessible(page);
});

test("an unfamiliar layout marks the values to check and boxes their source", async ({ page }) => {
  test.skip(!writesAllowed, "keeps an upload waiting");
  await page.getByRole("button", { name: /unfamiliar layout/ }).click();
  await expect(page.locator(".pdf-page canvas").first()).toBeVisible();
  await expect(page.locator(".read-summary")).toContainText("to check before you confirm");
  await expect(page.locator(".check-word").first()).toBeVisible();
  await page.locator("#f-po_date").focus();
  await expect(page.locator(".src-box.active")).toBeVisible();
  await expectAccessible(page);
});

test("a confirmation one unit short becomes a problem on its order", async ({ page }) => {
  test.skip(!writesAllowed, "changes data");
  await workAs(page, "Ops");
  await page.getByRole("button", { name: /Confirmation for PO-2026-0102/ }).click();
  await expect(page.locator(".read select")).not.toHaveValue("");
  await page.getByRole("button", { name: "Confirm and add to the board" }).click();
  await expect(page).toHaveURL(/\/orders\/\d+/);
  await expect(page.locator(".problem-item.open").first()).toContainText("Short quantity");
  await expect(page.locator(".next")).toContainText("Short 1");
});

test("the same file twice is refused with a link to its order", async ({ page }) => {
  test.skip(!writesAllowed, "changes data");
  // Uses the confirmation added by the previous test.
  await page.getByRole("button", { name: /Confirmation for PO-2026-0102/ }).click();
  await expect(page.getByRole("alert")).toContainText("already added");
  await expect(page.getByRole("link", { name: "Open that order" })).toBeVisible();
});
