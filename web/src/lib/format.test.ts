import { describe, expect, it } from "vitest";
import { STAGES, days, formatMoney, plural } from "./format";

describe("format", () => {
  it("keeps money exact to two places", () => {
    expect(formatMoney("1434793.5")).toBe("1,434,793.50");
    expect(formatMoney(null)).toBe("");
  });
  it("says days the way a person does", () => {
    expect(days(0)).toBe("today");
    expect(days(1)).toBe("1 day");
    expect(days(5)).toBe("5 days");
    expect(plural(1, "order")).toBe("1 order");
    expect(plural(14, "order")).toBe("14 orders");
  });
  it("has the six steps in the database's order", () => {
    expect(STAGES.map((s) => s.key)).toEqual(["po_received", "po_sent", "confirmed", "received", "delivered", "ready_to_invoice"]);
  });
});
