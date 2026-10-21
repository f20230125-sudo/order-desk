import type { Role, Stage } from "./api";

export interface Problem {
  id: number;
  code: string;
  severity: "block" | "warn" | "info";
  stage: Stage;
  part_number: string | null;
  expected: string | null;
  found: string | null;
  explanation: string;
  status: "open" | "accepted" | "fixed";
  resolution_note: string | null;
  resolved_by_role: Role | null;
  resolved_at: string | null;
}

export interface Cell {
  qty: number;
  price?: string;
  part_number?: string;
  substitutes?: string | null;
}

export interface GridRow {
  part_number: string;
  description: string;
  customer: Cell | null;
  ours: Cell | null;
  confirmed: Cell | null;
  received: Cell | null;
  delivered: Cell | null;
  serials: string[];
  issues: Partial<Record<"customer" | "ours" | "confirmed" | "received" | "delivered", number[]>>;
}

export interface OrderDetail {
  order: {
    id: number;
    po_number: string;
    customer_name: string;
    sector: string;
    our_po_number: string | null;
    distributor_name: string | null;
    stage: Stage;
    stage_no: number;
    whose_turn: Role | null;
    days_in_stage: number;
    problems: number;
    total: string | null;
    subtotal: string | null;
    vat_amount: string | null;
    vat_rate: string;
    currency: string;
    po_date: string;
    required_by: string | null;
    eta: string | null;
    eta_after_required: boolean | null;
    deliver_to: string | null;
    contact_name: string | null;
    ready_to_invoice_at: string | null;
  };
  chain: { key: Stage; name: string; state: "done" | "current" | "todo"; at: string | null }[];
  grid: GridRow[];
  problems: Problem[];
  documents: {
    id: number;
    kind: string;
    filename: string;
    mime: string;
    size_bytes: number;
    uploaded_by_role: Role | "system";
    uploaded_at: string;
    warnings: number;
  }[];
  shipments: {
    id: number;
    direction: "inbound" | "outbound";
    tracking_number: string | null;
    delivery_note_no: string | null;
    received_at: string | null;
    marked_partial: boolean;
    carrier: string | null;
  }[];
  events: { at: string; role: Role | "system"; text: string; table: string }[];
}

export const PROBLEM_TITLE: Record<string, string> = {
  QTY_SHORT: "Short quantity",
  QTY_OVER: "More than ordered",
  PART_MISMATCH: "Wrong part on our PO",
  SUBSTITUTION: "Substitute part",
  PRICE_DIFF: "Price changed",
  MISSING_LINE: "Line missing",
  EXTRA_LINE: "Extra line",
  SERIAL_COUNT: "Serial numbers do not match the count",
  DUPLICATE_SERIAL: "Serial already booked in",
  VAT_MATH: "VAT does not add up",
  TOTAL_MATH: "Total does not add up",
  PO_REF: "Confirmation quotes another PO",
  ETA_LATE: "Arrives after the date needed",
  PARTIAL_SHIPMENT: "Part delivery",
};

export const SEVERITY_WORDS = { block: "Holds the order", warn: "Warning", info: "Note" } as const;

export const DOC_KIND: Record<string, string> = {
  customer_po: "Customer PO",
  vendor_confirmation: "Distributor confirmation",
  delivery_note: "Delivery note",
  shipment_email: "Dispatch email",
};

// Who acts on a problem: the same split as the database's blocking_issue_owner().
export function problemOwner(code: string): Role {
  return ["VAT_MATH", "TOTAL_MATH", "PRICE_DIFF", "SUBSTITUTION"].includes(code) ? "sales" : "ops";
}
