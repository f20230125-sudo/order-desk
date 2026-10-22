import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { PdfView, type Box } from "../components/PdfView";
import { api, ApiError, type BoardResponse } from "../lib/api";
import { DOC_KIND } from "../lib/order";
import { ROLE_NAME, useRole } from "../lib/role";

// ------------------------------------------------------------------ what the API returns

type Bbox = [number, number, number, number];
interface Read<T = unknown> {
  value: T;
  confidence: number;
  rule: string;
  page?: number;
  bbox?: Bbox;
  span?: [number, number];
}
interface ReadLine {
  part_number?: Read<string>;
  description?: Read<string>;
  qty?: Read<number>;
  unit_price?: Read<string>;
  serials?: Read<string[]>;
  substitutes_part?: Read<string>;
}
interface Extracted {
  kind: string;
  fields: Record<string, Read>;
  lines: ReadLine[];
  warnings: string[];
  text?: string;
  attachments?: string[];
}
interface Upload {
  pending_id: string;
  kind: string;
  mime: string;
  filename: string;
  extracted: Extracted;
  suggestion: { customer?: { id: number; name: string } | null; order?: { id: number; po_number: string; our_po_number: string } | null };
}
interface Sample {
  file: string;
  title: string;
  shows: string;
}

// ------------------------------------------------------------------ the form's own state

interface Line {
  part_number: string;
  description: string;
  qty: string;
  unit_price: string;
  serials: string;
  substitutes_part: string;
  confidence: number;
}
interface Form {
  fields: Record<string, string>;
  lines: Line[];
}

const CHECK_BELOW = 0.8;

const FIELDS: Record<string, { key: string; label: string; type?: string }[]> = {
  customer_po: [
    { key: "po_number", label: "PO number" },
    { key: "po_date", label: "PO date", type: "date" },
    { key: "required_by", label: "Needed by", type: "date" },
    { key: "subtotal", label: "Subtotal" },
    { key: "vat_amount", label: "VAT" },
    { key: "total", label: "Total" },
  ],
  vendor_confirmation: [
    { key: "confirmation_no", label: "Confirmation number" },
    { key: "referenced_po", label: "Our PO number it quotes" },
    { key: "eta", label: "Expected delivery", type: "date" },
  ],
  delivery_note: [
    { key: "delivery_note_no", label: "Delivery note number" },
    { key: "tracking_number", label: "Tracking number" },
  ],
  shipment_email: [
    { key: "delivery_note_no", label: "Delivery note number" },
    { key: "tracking_number", label: "Tracking number" },
  ],
};

function toForm(u: Upload): Form {
  const f = u.extracted.fields;
  const fields: Record<string, string> = {};
  for (const { key } of FIELDS[u.kind]) fields[key] = f[key]?.value == null ? "" : String(f[key].value);
  if (u.kind === "delivery_note" || u.kind === "shipment_email") fields.marked_partial = f.marked_partial?.value ? "1" : "";
  fields.customer_id = u.suggestion.customer ? String(u.suggestion.customer.id) : "";
  fields.order_id = u.suggestion.order ? String(u.suggestion.order.id) : "";
  const lines = u.extracted.lines.map((ln) => ({
    part_number: ln.part_number?.value ?? "",
    description: ln.description?.value ?? "",
    qty: ln.qty?.value == null ? "" : String(ln.qty.value),
    unit_price: ln.unit_price?.value == null ? "" : String(ln.unit_price.value),
    serials: (ln.serials?.value ?? []).join(" "),
    substitutes_part: ln.substitutes_part?.value ?? "",
    confidence: Math.min(...[ln.part_number, ln.qty, ln.unit_price].filter(Boolean).map((r) => (r as Read).confidence), 1),
  }));
  return { fields, lines };
}

function payload(kind: string, form: Form) {
  const f = form.fields;
  const blank = (s: string) => (s.trim() === "" ? null : s.trim());
  if (kind === "customer_po") {
    return {
      customer_id: Number(f.customer_id) || null, po_number: f.po_number, po_date: f.po_date, required_by: blank(f.required_by),
      subtotal: blank(f.subtotal), vat_amount: blank(f.vat_amount), total: blank(f.total),
      lines: form.lines.map((l) => ({ part_number: l.part_number, description: l.description, qty: Number(l.qty), unit_price: l.unit_price })),
    };
  }
  if (kind === "vendor_confirmation") {
    return {
      order_id: Number(f.order_id) || null, confirmation_no: f.confirmation_no, referenced_po: f.referenced_po, eta: blank(f.eta),
      lines: form.lines.map((l) => ({
        part_number: l.part_number, description: l.description, qty: Number(l.qty), unit_price: l.unit_price || "0",
        substitutes_part: blank(l.substitutes_part),
      })),
    };
  }
  return {
    order_id: Number(f.order_id) || null, delivery_note_no: f.delivery_note_no, tracking_number: blank(f.tracking_number),
    marked_partial: f.marked_partial === "1",
    lines: form.lines.map((l) => ({ part_number: l.part_number, qty: Number(l.qty), serials: l.serials.split(/[\s,]+/).filter(Boolean) })),
  };
}

// ------------------------------------------------------------------ the tray (before a file is chosen)

function Tray({ onFile, busy }: { onFile: (file: File) => void; busy: boolean }) {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    fetch("/samples/samples.json")
      .then((r) => (r.ok ? r.json() : []))
      .then(setSamples)
      .catch(() => setSamples([]));
  }, []);
  const take = async (s: Sample) => {
    const r = await fetch(`/samples/${s.file}`);
    const blob = await r.blob();
    onFile(new File([blob], s.file, { type: blob.type }));
  };
  return (
    <div className="intake-empty">
      <div
        className={`tray${over ? " over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const file = e.dataTransfer.files[0];
          if (file) onFile(file);
        }}
      >
        <p className="tray-title">Drop a PDF or an email (.eml) here</p>
        <p className="quiet">A customer PO, a distributor confirmation, a delivery note or a dispatch email. Up to 2 MB.</p>
        <button type="button" className="button primary" disabled={busy} onClick={() => input.current?.click()}>
          Choose a file
        </button>
        <input
          ref={input}
          type="file"
          aria-label="Choose a PDF or .eml file"
          accept=".pdf,.eml,application/pdf,message/rfc822"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onFile(file);
            e.target.value = "";
          }}
        />
      </div>
      {samples.length > 0 && (
        <section className="samples" aria-labelledby="samples-h">
          <h2 id="samples-h" className="h-sub">
            Or try a sample document
          </h2>
          <p className="quiet small">Made-up documents that fit the orders on the board. Try them in this order.</p>
          <ol>
            {samples.map((s) => (
              <li key={s.file}>
                <button type="button" className="sample" disabled={busy} onClick={() => void take(s)}>
                  <span className="sample-title">{s.title}</span>
                  <span className="quiet">{s.shows}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ the email view (no page to draw on)

function EmailView({ text, spans, active }: { text: string; spans: { id: string; span: [number, number] }[]; active: string | null }) {
  const sorted = [...spans].sort((a, b) => a.span[0] - b.span[0]);
  const out: React.ReactNode[] = [];
  let at = 0;
  for (const s of sorted) {
    if (s.span[0] < at) continue;
    out.push(text.slice(at, s.span[0]));
    out.push(
      <mark key={s.id} className={s.id === active ? "active" : ""}>
        {text.slice(s.span[0], s.span[1])}
      </mark>,
    );
    at = s.span[1];
  }
  out.push(text.slice(at));
  return <pre className="email">{out}</pre>;
}

// ------------------------------------------------------------------ page

export function Intake() {
  const { role } = useRole();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [upload, setUpload] = useState<Upload | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileData, setFileData] = useState<ArrayBuffer | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; orderId?: number } | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [active, setActive] = useState<string | null>(null);
  const [customers, setCustomers] = useState<{ id: number; name: string }[]>([]);
  const [orders, setOrders] = useState<{ id: number; label: string }[]>([]);

  useEffect(() => {
    document.title = "Add from a document: Order Desk";
    api.get<{ parties: { id: number; name: string }[] }>("/api/parties?kind=customer").then((r) => setCustomers(r.parties)).catch(() => {});
    api
      .get<BoardResponse>("/api/board")
      .then((r) =>
        setOrders(
          r.orders
            .filter((o) => o.our_po_number)
            .map((o) => ({ id: o.id, label: `${o.our_po_number} (customer PO ${o.po_number}, ${o.customer_name})` }))
            .sort((a, b) => a.label.localeCompare(b.label)),
        ),
      )
      .catch(() => {});
  }, []);

  const choose = useCallback(
    async (f: File) => {
      setBusy(true);
      setError(null);
      setFieldErrors({});
      try {
        const body = new FormData();
        body.append("file", f);
        const kind = params.get("kind");
        if (kind && f.name.toLowerCase().endsWith(".pdf")) body.append("kind", kind);
        const u = await api.post<Upload>("/api/intake", role, body);
        const preset = params.get("order");
        const next = toForm(u);
        if (preset && !next.fields.order_id) next.fields.order_id = preset;
        setFile(f);
        setFileData(await f.arrayBuffer());
        setUpload(u);
        setForm(next);
        setActive(null);
      } catch (e) {
        const err = e as ApiError;
        const details = err.details as { order_id?: number } | undefined;
        setError({ message: err.message, orderId: details?.order_id ?? undefined });
      } finally {
        setBusy(false);
      }
    },
    [params, role],
  );

  const confirm = async () => {
    if (!upload || !form) return;
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      const r = await api.post<{ order_id: number }>(`/api/intake/${upload.pending_id}/confirm`, role, payload(upload.kind, form));
      navigate(`/orders/${r.order_id}`);
    } catch (e) {
      const err = e as ApiError;
      if (Array.isArray(err.details)) {
        const map: Record<string, string> = {};
        for (const d of err.details as { field: string; message: string }[]) map[d.field] = d.message.replace(/^Value error, /, "");
        setFieldErrors(map);
      }
      setError({ message: err.message });
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setUpload(null);
    setForm(null);
    setFile(null);
    setFileData(null);
    setError(null);
    setFieldErrors({});
  };

  // Boxes on the PDF for every value read; the focused field's box is the active one.
  const boxes: Box[] = useMemo(() => {
    if (!upload) return [];
    const out: Box[] = [];
    for (const [key, r] of Object.entries(upload.extracted.fields)) {
      if (r.bbox && r.page !== undefined) out.push({ id: key, page: r.page, bbox: r.bbox, active: active === key });
    }
    upload.extracted.lines.forEach((ln, i) => {
      for (const [key, r] of Object.entries(ln)) {
        if (r && (r as Read).bbox && (r as Read).page !== undefined) {
          const id = `line${i}.${key}`;
          out.push({ id, page: (r as Read).page as number, bbox: (r as Read).bbox as Bbox, active: active === id });
        }
      }
    });
    return out;
  }, [upload, active]);

  const spans = useMemo(() => {
    if (!upload) return [];
    const out: { id: string; span: [number, number] }[] = [];
    for (const [key, r] of Object.entries(upload.extracted.fields)) if (r.span) out.push({ id: key, span: r.span });
    upload.extracted.lines.forEach((ln, i) => {
      for (const [key, r] of Object.entries(ln)) if (r && (r as Read).span) out.push({ id: `line${i}.${key}`, span: (r as Read).span as [number, number] });
    });
    return out;
  }, [upload]);

  if (!upload || !form) {
    return (
      <div className="page intake">
        <Link to="/" className="back">
          Order board
        </Link>
        <h1 className="h-page">Add from a document</h1>
        <p className="lede">The values are read for you, each with the place on the page it came from. Nothing is saved until you confirm.</p>
        {error && (
          <p className="form-error" role="alert">
            {error.message} {error.orderId && <Link to={`/orders/${error.orderId}`}>Open that order</Link>}
          </p>
        )}
        {busy && <p className="quiet" role="status">Reading the document.</p>}
        <Tray onFile={(f) => void choose(f)} busy={busy} />
      </div>
    );
  }

  const kind = upload.kind;
  const fields = FIELDS[kind];
  const conf = (key: string) => upload.extracted.fields[key]?.confidence ?? 0;
  const toCheck =
    fields.filter((f) => conf(f.key) < CHECK_BELOW && f.key !== "required_by" && f.key !== "tracking_number").length +
    form.lines.filter((l) => l.confidence < CHECK_BELOW).length;
  const setField = (key: string, value: string) => setForm({ ...form, fields: { ...form.fields, [key]: value } });
  const setLine = (i: number, key: keyof Line, value: string) =>
    setForm({ ...form, lines: form.lines.map((l, j) => (j === i ? { ...l, [key]: value } : l)) });
  const priced = kind === "customer_po" || kind === "vendor_confirmation";
  const goods = kind === "delivery_note" || kind === "shipment_email";

  return (
    <div className="page intake">
      <Link to="/" className="back">
        Order board
      </Link>
      <h1 className="h-page">Add from a document</h1>
      <div className="intake-grid">
        <section className="source" aria-label="The document">
          <p className="source-head">
            <strong>{DOC_KIND[kind]}</strong> <span className="mono">{file?.name}</span>
          </p>
          {upload.mime === "application/pdf" && fileData ? (
            <PdfView source={fileData} boxes={boxes} label={file?.name ?? "document"} onBoxClick={(id) => document.getElementById(`f-${id}`)?.focus()} />
          ) : (
            <EmailView text={upload.extracted.text ?? ""} spans={spans} active={active} />
          )}
          {upload.extracted.attachments && upload.extracted.attachments.length > 0 && (
            <p className="quiet small">Attached: {upload.extracted.attachments.join(", ")}</p>
          )}
        </section>

        <form
          className="read"
          onSubmit={(e) => {
            e.preventDefault();
            void confirm();
          }}
        >
          <p className="read-summary">
            {toCheck === 0 ? "Everything was read with confidence. Look it over, then confirm." : `${toCheck} ${toCheck === 1 ? "value" : "values"} to check before you confirm.`}
          </p>
          {upload.extracted.warnings.length > 0 && <p className="quiet small">{upload.extracted.warnings.join(". ")}.</p>}

          {kind === "customer_po" ? (
            <label className="field">
              <span>Customer {upload.suggestion.customer && <span className="quiet">(matched by their tax number)</span>}</span>
              <select value={form.fields.customer_id} onChange={(e) => setField("customer_id", e.target.value)} required>
                <option value="">Choose the customer</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {fieldErrors.customer_id && <span className="field-error">{fieldErrors.customer_id}</span>}
            </label>
          ) : (
            <label className="field">
              <span>
                Order {upload.suggestion.order ? <span className="quiet">(matched by the PO number it quotes)</span> : <span className="check-word">Check</span>}
              </span>
              <select value={form.fields.order_id} onChange={(e) => setField("order_id", e.target.value)} required
                className={upload.suggestion.order ? "" : "to-check"}>
                <option value="">Choose the order this belongs to</option>
                {orders.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
              {!upload.suggestion.order && (
                <span className="field-help">No order on the board has the PO number this document quotes. Choose it by hand; the check will flag the wrong number.</span>
              )}
            </label>
          )}

          <div className="field-grid">
            {fields.map((f) => {
              const low = conf(f.key) < CHECK_BELOW;
              const r = upload.extracted.fields[f.key];
              const err = fieldErrors[f.key];
              return (
                <label key={f.key} className="field">
                  <span>
                    {f.label} {low && r && <span className="check-word">Check</span>} {!r && <span className="quiet">(not found)</span>}
                  </span>
                  <input
                    id={`f-${f.key}`}
                    type={f.type ?? "text"}
                    value={form.fields[f.key] ?? ""}
                    className={`${low ? "to-check" : ""}${f.key.includes("number") || f.key.includes("_no") || f.key === "referenced_po" ? " mono" : ""}`}
                    onChange={(e) => setField(f.key, e.target.value)}
                    onFocus={() => setActive(f.key)}
                    aria-describedby={r ? `how-${f.key}` : undefined}
                    aria-invalid={Boolean(err)}
                  />
                  {r && (
                    <span id={`how-${f.key}`} className="visually-hidden">
                      Read by rule: {r.rule}. Confidence {Math.round(r.confidence * 100)}%.
                    </span>
                  )}
                  {err && <span className="field-error">{err}</span>}
                </label>
              );
            })}
            {goods && (
              <label className="field check-field">
                <input type="checkbox" checked={form.fields.marked_partial === "1"} onChange={(e) => setField("marked_partial", e.target.checked ? "1" : "")} />
                <span>Part delivery, balance to follow</span>
              </label>
            )}
          </div>

          <fieldset className="lines">
            <legend>Lines</legend>
            <table className="lines-table">
              <thead>
                <tr>
                  <th scope="col">Part</th>
                  {priced && <th scope="col">Description</th>}
                  <th scope="col" className="num">
                    Qty
                  </th>
                  {priced && (
                    <th scope="col" className="num">
                      Unit price
                    </th>
                  )}
                  {kind === "vendor_confirmation" && <th scope="col">Replaces</th>}
                  {goods && <th scope="col">Serial numbers</th>}
                  <th scope="col">
                    <span className="visually-hidden">Remove</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {form.lines.map((l, i) => {
                  const low = l.confidence < CHECK_BELOW;
                  const err = (k: string) => fieldErrors[`lines.${i}.${k}`];
                  return (
                    <tr key={i} className={low ? "to-check" : ""}>
                      <td data-label="Part number">
                        <input id={`f-line${i}.part_number`} className="mono" value={l.part_number} aria-label={`Line ${i + 1} part number`}
                          onFocus={() => setActive(`line${i}.part_number`)} onChange={(e) => setLine(i, "part_number", e.target.value.toUpperCase())}
                          aria-invalid={Boolean(err("part_number"))} />
                        {err("part_number") && <span className="field-error">{err("part_number")}</span>}
                      </td>
                      {priced && (
                        <td data-label="Description">
                          <input value={l.description} aria-label={`Line ${i + 1} description`} onFocus={() => setActive(`line${i}.description`)}
                            onChange={(e) => setLine(i, "description", e.target.value)} />
                        </td>
                      )}
                      <td className="num" data-label="Quantity">
                        <input id={`f-line${i}.qty`} inputMode="numeric" value={l.qty} aria-label={`Line ${i + 1} quantity`}
                          onFocus={() => setActive(`line${i}.qty`)} onChange={(e) => setLine(i, "qty", e.target.value)} aria-invalid={Boolean(err("qty"))} />
                        {err("qty") && <span className="field-error">{err("qty")}</span>}
                      </td>
                      {priced && (
                        <td className="num" data-label="Unit price">
                          <input id={`f-line${i}.unit_price`} inputMode="decimal" value={l.unit_price} aria-label={`Line ${i + 1} unit price`}
                            onFocus={() => setActive(`line${i}.unit_price`)} onChange={(e) => setLine(i, "unit_price", e.target.value)}
                            aria-invalid={Boolean(err("unit_price"))} />
                          {err("unit_price") && <span className="field-error">{err("unit_price")}</span>}
                        </td>
                      )}
                      {kind === "vendor_confirmation" && (
                        <td data-label="Replaces part">
                          <input className="mono" value={l.substitutes_part} aria-label={`Line ${i + 1} replaces part`}
                            onChange={(e) => setLine(i, "substitutes_part", e.target.value.toUpperCase())} />
                        </td>
                      )}
                      {goods && (
                        <td data-label="Serial numbers">
                          <input className="mono" value={l.serials} aria-label={`Line ${i + 1} serial numbers`}
                            onFocus={() => setActive(`line${i}.serials`)} onChange={(e) => setLine(i, "serials", e.target.value.toUpperCase())} />
                        </td>
                      )}
                      <td>
                        <button type="button" className="link" aria-label={`Remove line ${i + 1}`}
                          onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <button type="button" className="link add-line"
              onClick={() => setForm({ ...form, lines: [...form.lines, { part_number: "", description: "", qty: "", unit_price: "", serials: "", substitutes_part: "", confidence: 0 }] })}>
              Add a line
            </button>
          </fieldset>

          <div className="confirm-bar">
            <button type="submit" className="button primary" disabled={busy || form.lines.length === 0}>
              Confirm and add to the board
            </button>
            <button type="button" className="button" onClick={reset}>
              Discard
            </button>
            <span className="quiet small">Saved as {ROLE_NAME[role]}. The checks run as soon as it is saved.</span>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error.message}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
