import { describe, expect, it } from "vitest";
import { nextStep } from "./nextStep";
import type { OrderDetail, Problem } from "./order";

function order(stage: OrderDetail["order"]["stage"], problems: Partial<Problem>[] = []): OrderDetail {
  return {
    order: {
      id: 1, po_number: "GCB-PO-1", customer_name: "Gulf Crescent Bank", sector: "bank", our_po_number: "PO-2026-0101",
      distributor_name: "Falcon Value Distribution FZE", stage, stage_no: 1, whose_turn: "ops", days_in_stage: 2, problems: 0,
      total: "100.00", subtotal: "95.24", vat_amount: "4.76", vat_rate: "0.05", currency: "AED", po_date: "2026-10-01",
      required_by: "2026-10-30", eta: "2026-10-20", eta_after_required: false, deliver_to: null, contact_name: null,
      ready_to_invoice_at: stage === "ready_to_invoice" ? "2026-10-21T10:00:00Z" : null,
    },
    chain: [], grid: [], documents: [], shipments: [], events: [],
    problems: problems.map((p, i) => ({
      id: i + 1, code: "QTY_SHORT", severity: "block", stage: "confirmed", part_number: "PER760-XS2", expected: "4", found: "3",
      explanation: "Short 1: we ordered 4 PER760-XS2, the distributor confirmed 3.", status: "open", resolution_note: null,
      resolved_by_role: null, resolved_at: null, ...p,
    })) as Problem[],
  };
}

describe("next step", () => {
  it("follows the chain when nothing blocks it", () => {
    expect(nextStep(order("po_received"))).toMatchObject({ who: "sales", action: "place-po" });
    expect(nextStep(order("po_sent"))).toMatchObject({ who: "ops", intake: { kind: "vendor_confirmation" } });
    expect(nextStep(order("confirmed"))).toMatchObject({ who: "ops", intake: { kind: "delivery_note" } });
    expect(nextStep(order("received"))).toMatchObject({ who: "ops", action: "deliver" });
    expect(nextStep(order("delivered"))).toMatchObject({ who: "finance", action: "hand-to-finance" });
    expect(nextStep(order("ready_to_invoice")).who).toBeNull();
  });

  it("puts a blocking problem first, with the right owner", () => {
    expect(nextStep(order("confirmed", [{}]))).toMatchObject({ who: "ops", action: "settle" });
    expect(nextStep(order("confirmed", [{ code: "PRICE_DIFF", explanation: "Price up 12%." }]))).toMatchObject({ who: "sales" });
  });

  it("ignores problems already settled and warnings", () => {
    expect(nextStep(order("received", [{ status: "accepted" }])).action).toBe("deliver");
    expect(nextStep(order("received", [{ severity: "warn", code: "QTY_OVER" }])).action).toBe("deliver");
  });

  it("counts the problems after the first", () => {
    expect(nextStep(order("confirmed", [{}, { code: "PRICE_DIFF" }])).text).toMatch(/1 more problem after this one/);
  });
});
