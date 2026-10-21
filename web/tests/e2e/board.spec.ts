import { expect, test } from "@playwright/test";
import { expectAccessible, expectNoSidewaysScroll, workAs } from "./helpers";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Order board" })).toBeVisible();
  await expect(page.locator("tr.order").first()).toBeVisible();
});

test("the board says what is open and whose turn it is", async ({ page }) => {
  await workAs(page, "Ops");
  await expect(page.locator(".lede")).toContainText(/\d+ orders? open\. \d+ (is|are) with Ops now\./);
  await expect(page.locator(".band.mine")).toContainText("With Ops now");
});

test("switching role puts that role's orders first", async ({ page }) => {
  await workAs(page, "Sales");
  await expect(page.locator(".band.mine")).toContainText("With Sales now");
  await workAs(page, "Finance");
  await expect(page.locator(".band.mine")).toContainText("With Finance now");
});

test("search finds an order by a serial number on its delivery note", async ({ page }) => {
  // Every row lists its customer PO; take a serial from an order that has goods in, through the API.
  const board = await (await page.request.get("/api/board?stage=received")).json();
  const detail = await (await page.request.get(`/api/orders/${board.orders[0].id}`)).json();
  const serial = detail.grid.find((r: { serials: string[] }) => r.serials.length).serials[0];
  await page.getByRole("searchbox").fill(serial);
  await expect(page.locator("tr.order")).toHaveCount(1);
  await expect(page.locator("tr.order a.po")).toHaveText(board.orders[0].po_number);
});

test("keyboard: slash to search, j to move, Enter to open", async ({ page }) => {
  await page.keyboard.press("/");
  await expect(page.getByRole("searchbox")).toBeFocused();
  await page.keyboard.press("Escape");
  await page.keyboard.press("j");
  const second = await page.locator("tr.order.selected a.po").textContent();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/orders\/\d+/);
  await expect(page.locator("h1")).toHaveText(second ?? "");
});

test("only orders with a problem", async ({ page }) => {
  // The box follows the address bar, so it is ticked once the filter is in the URL.
  await page.getByLabel("Only orders with a problem").click();
  await expect(page).toHaveURL(/problems=1/);
  await expect(page.getByLabel("Only orders with a problem")).toBeChecked();
  // Clean orders (a tick in the margin) leave the list; every row left carries a problem ring.
  await expect(page.locator("tr.order td.margin .tick")).toHaveCount(0);
  await expect(page.locator("tr.order td.margin .ring").first()).toBeVisible();
  expect(await page.locator("tr.order td.margin .ring").count()).toBe(await page.locator("tr.order").count());
});

test("board is accessible in both themes", async ({ page }) => {
  await expectAccessible(page);
});

test("phone: one block per order and no sideways scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("tr.order").first()).toBeVisible();
  await expectNoSidewaysScroll(page);
});
