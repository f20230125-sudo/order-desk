import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const writesAllowed = !process.env.BASE_URL || process.env.E2E_WRITES === "1";

export async function expectAccessible(page: Page) {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(results.violations.map((v) => `${scheme}: ${v.id} ${v.nodes.length}`)).toEqual([]);
  }
  await page.emulateMedia({ colorScheme: "light" });
}

export async function expectNoSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

export async function workAs(page: Page, role: "Sales" | "Ops" | "Finance") {
  await page.getByRole("group", { name: "Working as" }).getByRole("button", { name: role }).click();
}
