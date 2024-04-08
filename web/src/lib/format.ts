import type { Stage } from "./api";

export const STAGES: { key: Stage; name: string; short: string }[] = [
  { key: "po_received", name: "Customer PO received", short: "PO received" },
  { key: "po_sent", name: "Our PO sent to the distributor", short: "PO sent" },
  { key: "confirmed", name: "Distributor confirmed", short: "Confirmed" },
  { key: "received", name: "Goods received", short: "Goods in" },
  { key: "delivered", name: "Delivered to the customer", short: "Delivered" },
  { key: "ready_to_invoice", name: "Ready to invoice", short: "To invoice" },
];

const money = new Intl.NumberFormat("en-AE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  return money.format(Number(value));
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function days(n: number): string {
  return n === 1 ? "1 day" : `${n} days`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
