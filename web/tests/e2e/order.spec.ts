import { expect, test } from "@playwright/test";
import { expectAccessible, expectNoSidewaysScroll, workAs, writesAllowed } from "./helpers";

async function openOrderWithProblem(page: import("@playwright/test").Page) {
  const board = await (await page.request.get("/api/board?problems=1")).json();
  const target = board.orders[0];
  await page.goto(`/orders/${target.id}`);
  await expect(page.locator("h1")).toHaveText(target.po_number);
  return target;
}

test("the order shows its chain, the line-by-line check and what to do next", async ({ page }) => {
  await openOrderWithProblem(page);
  await expect(page.getByRole("heading", { name: "Next step" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Where the order is" }).locator("li")).toHaveCount(6);
  await expect(page.locator("table.match td.differs").first()).toBeVisible();
  await expect(page.locator("tr.explain").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
});

test("a document opens with the boxes where values were read", async ({ page }) => {
  await openOrderWithProblem(page);
  await page.locator("button.doc").first().click();
  await expect(page.locator(".pdf-page canvas").first()).toBeVisible();
  await expect(page.locator(".src-box").first()).toBeVisible();
});

test("settling a problem needs a note and lands in the history", async ({ page }) => {
  test.skip(!writesAllowed, "changes data");
  const target = await openOrderWithProblem(page);
  await workAs(page, "Ops");
  const item = page.locator(".problem-item.open").first();
  await item.getByRole("button", { name: "Accept with a note" }).click();
  const save = item.getByRole("button", { name: /^Accept as Ops/ });
  await expect(save).toBeDisabled();
  await item.getByRole("textbox").fill("Agreed with the distributor by phone.");
  await save.click();
  await expect(page.locator(".history li").last()).toContainText("Marked accepted: Agreed with the distributor by phone.");
  const after = await (await page.request.get(`/api/board`)).json();
  const row = after.orders.find((o: { id: number }) => o.id === target.id);
  expect(row.problems).toBe(target.problems - 1);
});

test("an unknown order and an unknown page say so", async ({ page }) => {
  await page.goto("/orders/999999");
  await expect(page.getByRole("heading", { name: "No such order" })).toBeVisible();
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Nothing at this address" })).toBeVisible();
});

test("order page is accessible in both themes, and fits a phone", async ({ page }) => {
  await openOrderWithProblem(page);
  await expectAccessible(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoSidewaysScroll(page);
});
