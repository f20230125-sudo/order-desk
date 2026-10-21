import type { Role } from "./api";
import { formatDate, plural } from "./format";
import { problemOwner, type OrderDetail } from "./order";

// What happens next on an order, in one sentence, and which action the page offers for it.

export interface Step {
  who: Role | null;
  text: string;
  action?: "place-po" | "deliver" | "hand-to-finance" | "settle";
  intake?: { kind: string; label: string };
}

export function nextStep(d: OrderDetail): Step {
  const o = d.order;
  const blocking = d.problems.filter((p) => p.status === "open" && p.severity === "block");
  if (blocking.length) {
    const p = blocking[0];
    const who = problemOwner(p.code);
    const more = blocking.length > 1 ? ` ${plural(blocking.length - 1, "more problem")} after this one.` : "";
    return { who, text: `${p.explanation} Settle it before the order moves on.${more}`, action: "settle" };
  }
  switch (o.stage) {
    case "po_received":
      return { who: "sales", text: "The customer's PO is booked. Place our PO with a distributor to order the goods.", action: "place-po" };
    case "po_sent":
      return {
        who: "ops",
        text: `Waiting for ${o.distributor_name ?? "the distributor"} to confirm ${o.our_po_number}. Add their confirmation when it arrives.`,
        intake: { kind: "vendor_confirmation", label: "Add the confirmation" },
      };
    case "confirmed":
      return {
        who: "ops",
        text: `Goods ${o.eta ? `expected ${formatDate(o.eta)}` : "on the way"}. Book them in from the delivery note or the dispatch email.`,
        intake: { kind: "delivery_note", label: "Book in goods" },
      };
    case "received":
      return { who: "ops", text: `All goods are in. Deliver to ${o.customer_name}.`, action: "deliver" };
    case "delivered":
      return { who: "finance", text: "The customer signed for the goods. Hand the order to finance for invoicing.", action: "hand-to-finance" };
    default:
      return { who: null, text: `Handed to finance on ${formatDate(o.ready_to_invoice_at)}. Nothing left to do here.` };
  }
}

