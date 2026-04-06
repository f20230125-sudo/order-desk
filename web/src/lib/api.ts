// A thin client for the Flask API. Every write says who is acting (X-Role); errors come back in one shape.

export type Role = "sales" | "ops" | "finance";

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init: RequestInit = {}, role?: Role): Promise<T> {
  const headers = new Headers(init.headers);
  if (role) headers.set("X-Role", role);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "offline", "The server did not answer. Check the connection and try again.");
  }
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const e = body?.error ?? {};
    throw new ApiError(res.status, e.code ?? "http_error", e.message ?? `Request failed (${res.status})`, e.details);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, role: Role, body?: unknown) =>
    request<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }, role),
  patch: <T>(path: string, role: Role, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }, role),
};

export type Stage = "po_received" | "po_sent" | "confirmed" | "received" | "delivered" | "ready_to_invoice";

export interface BoardOrder {
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
  notes: number;
  first_problem: string | null;
  total: string | null;
  currency: string;
  required_by: string | null;
  eta: string | null;
  eta_after_required: boolean | null;
}

export interface BoardResponse {
  orders: BoardOrder[];
  summary: { open: number; sales: number; ops: number; finance: number; with_problems: number; total: number };
}
