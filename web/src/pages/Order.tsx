import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { PencilRing, PencilTick } from "../components/Marks";
import { Explained } from "../components/Explained";
import { PdfView, type Box } from "../components/PdfView";
import { api, ApiError, type Role } from "../lib/api";
import { nextStep } from "../lib/nextStep";
import { formatDate, formatMoney, days } from "../lib/format";
import {
  DOC_KIND,
  PROBLEM_TITLE,
  SEVERITY_WORDS,
  problemOwner,
  type Cell,
  type GridRow,
  type OrderDetail,
  type Problem,
} from "../lib/order";
import { ROLE_NAME, useRole } from "../lib/role";

type Load = { state: "loading"; slow: boolean } | { state: "error"; error: ApiError | Error } | { state: "ready"; data: OrderDetail };

function useOrder(id: string) {
  const [load, setLoad] = useState<Load>({ state: "loading", slow: false });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let live = true;
    const slow = window.setTimeout(() => live && setLoad((l) => (l.state === "loading" ? { ...l, slow: true } : l)), 700);
    api
      .get<OrderDetail>(`/api/orders/${id}`)
      .then((data) => live && setLoad({ state: "ready", data }))
      .catch((error: Error) => live && setLoad({ state: "error", error }))
      .finally(() => window.clearTimeout(slow));
    return () => {
      live = false;
      window.clearTimeout(slow);
    };
  }, [id, version]);
  return { load, reload: () => setVersion((v) => v + 1) };
}

// ------------------------------------------------------------------ next step

function NextStep({ d, onDone }: { d: OrderDetail; onDone: () => void }) {
  const { role } = useRole();
  const step = nextStep(d);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [distributors, setDistributors] = useState<{ id: number; name: string }[]>([]);
  const [distributor, setDistributor] = useState("");

  useEffect(() => {
    if (step.action !== "place-po") return;
    api.get<{ parties: { id: number; name: string }[] }>("/api/parties?kind=distributor").then((r) => {
      setDistributors(r.parties);
      setDistributor(String(r.parties[0]?.id ?? ""));
    });
  }, [step.action]);

  const run = async (path: string, body?: unknown) => {
    setBusy(true);
    setError(null);
    try {
      await api.post(path, role, body);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="next" aria-labelledby="next-h">
      <h2 id="next-h">Next step</h2>
      {step.who && (
        <p className="next-who">
          <span className="stamp">{ROLE_NAME[step.who]}</span>
          {step.who === role ? <span>Your turn</span> : <span className="quiet">You are working as {ROLE_NAME[role]}</span>}
        </p>
      )}
      <p className="next-text">
        <Explained text={step.text} />
      </p>
      {step.action === "place-po" && (
        <div className="next-actions">
          <label className="select">
            <span>Distributor</span>
            <select value={distributor} onChange={(e) => setDistributor(e.target.value)}>
              {distributors.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="button primary" disabled={busy || !distributor}
            onClick={() => run(`/api/orders/${d.order.id}/place-po`, { distributor_id: Number(distributor) })}>
            Place our PO
          </button>
        </div>
      )}
      {step.action === "deliver" && (
        <div className="next-actions">
          <button type="button" className="button primary" disabled={busy} onClick={() => run(`/api/orders/${d.order.id}/deliver`)}>
            Deliver to the customer
          </button>
        </div>
      )}
      {step.action === "hand-to-finance" && (
        <div className="next-actions">
          <button type="button" className="button primary" disabled={busy}
            onClick={() => run(`/api/orders/${d.order.id}/hand-to-finance`)}>
            Hand to finance
          </button>
        </div>
      )}
      {step.action === "settle" && (
        <div className="next-actions">
          <a className="button" href="#problems">
            Go to the problem
          </a>
        </div>
      )}
      {step.intake && (
        <div className="next-actions">
          <Link className="button primary" to={`/intake?order=${d.order.id}&kind=${step.intake.kind}`}>
            {step.intake.label}
          </Link>
        </div>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ chain

function Chain({ d }: { d: OrderDetail }) {
  const held = d.order.problems > 0;
  const whoDid = useMemo(() => {
    const by: Record<string, string> = {};
    for (const e of d.events) {
      if (e.table === "customer_order" && e.text.startsWith("Customer PO")) by.po_received = e.role;
      if (e.table === "purchase_order") by.po_sent = e.role;
      if (e.table === "vendor_confirmation") by.confirmed = e.role;
      if (e.text.startsWith("Goods booked in")) by.received = e.role;
      if (e.text.startsWith("Delivered")) by.delivered = e.role;
      if (e.text.startsWith("Handed to finance")) by.ready_to_invoice = e.role;
    }
    return by;
  }, [d.events]);
  return (
    <ol className="chain" aria-label="Where the order is">
      {d.chain.map((s, i) => (
        <li key={s.key} className={`chain-step ${s.state}${s.state === "current" && held ? " held" : ""}`}>
          <span className="chain-mark" aria-hidden="true">
            {s.state === "current" && held && <PencilRing variant={1} />}
          </span>
          <span className="chain-n">{i + 1}</span>
          <span className="chain-name">{s.name}</span>
          <span className="chain-when">
            {s.at ? (
              <>
                {formatDate(s.at)}
                {whoDid[s.key] && whoDid[s.key] !== "system" ? `, ${ROLE_NAME[whoDid[s.key] as Role]}` : ""}
              </>
            ) : s.state === "current" ? (
              "now"
            ) : (
              ""
            )}
          </span>
          <span className="visually-hidden">
            {s.state === "done" ? "done" : s.state === "current" ? (held ? "current step, held by a problem" : "current step") : "not reached"}
          </span>
        </li>
      ))}
    </ol>
  );
}

// ------------------------------------------------------------------ match grid

const COLUMNS = [
  { key: "customer", label: "Customer PO", money: true },
  { key: "ours", label: "Our PO", money: true },
  { key: "confirmed", label: "Confirmed", money: true },
  { key: "received", label: "Goods in", money: false },
  { key: "delivered", label: "Delivered", money: false },
] as const;

function CellView({ cell, money, open, resolved, notYet }: { cell: Cell | null; money: boolean; open: boolean; resolved: boolean; notYet: boolean }) {
  if (!cell) {
    if (open) {
      return (
        <span className="ringed missing">
          <PencilRing />
          <strong>missing</strong>
        </span>
      );
    }
    return <span className="quiet">{notYet ? "not yet" : "not listed"}</span>;
  }
  const value = (
    <span className="cell-value">
      {cell.qty}
      {money && cell.price !== undefined && <span className="times"> x {formatMoney(cell.price)}</span>}
    </span>
  );
  return (
    <span className={`cell ${open ? "differs" : "agrees"}`}>
      {open ? (
        <span className="ringed">
          <PencilRing variant={cell.qty} />
          {value}
        </span>
      ) : (
        <>
          {value}
          {!resolved && <PencilTick />}
        </>
      )}
      {cell.substitutes && <span className="sub mono">as {cell.part_number}</span>}
      {resolved && <span className="sub">settled</span>}
    </span>
  );
}

function MatchGrid({ d }: { d: OrderDetail }) {
  const byId = useMemo(() => Object.fromEntries(d.problems.map((p) => [p.id, p])), [d.problems]);
  const reached = d.order.stage_no;
  const notYet = { customer: false, ours: reached < 2, confirmed: reached < 3, received: reached < 4, delivered: reached < 5 };
  const orderLevel = d.problems.filter((p) => !p.part_number && ["VAT_MATH", "TOTAL_MATH"].includes(p.code));
  const vatOpen = orderLevel.some((p) => p.code === "VAT_MATH" && p.status === "open");
  const totalOpen = orderLevel.some((p) => p.code === "TOTAL_MATH" && p.status === "open");
  return (
    <div className="grid-wrap">
      <table className="pad match">
        <caption className="visually-hidden">
          Each part across the documents. Values that agree are ticked; a value that does not is ringed and explained below the row.
        </caption>
        <thead>
          <tr>
            <th scope="col">Part</th>
            {COLUMNS.map((c) => (
              <th scope="col" key={c.key}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {d.grid.map((row: GridRow) => {
            const rowProblems = Object.values(row.issues)
              .flat()
              .map((id) => byId[id as number])
              .filter((p): p is Problem => Boolean(p) && p.status === "open" && p.severity !== "info");
            return [
              <tr key={row.part_number} className={rowProblems.length ? "has-problem" : ""}>
                <th scope="row">
                  <span className="mono part">{row.part_number}</span>
                  <span className="sub">{row.description}</span>
                </th>
                {COLUMNS.map((c) => {
                  const ids = row.issues[c.key] ?? [];
                  const ps = ids.map((id) => byId[id]).filter(Boolean);
                  const open = ps.some((p) => p.status === "open" && p.severity !== "info");
                  const resolved = !open && ps.some((p) => p.status !== "open");
                  return (
                    <td key={c.key} className={open ? "differs" : ""}>
                      <span className="mobile-cell-label" aria-hidden="true">{c.label}</span>
                      <CellView cell={row[c.key]} money={c.money} open={open} resolved={resolved} notYet={notYet[c.key] && !row[c.key]} />
                    </td>
                  );
                })}
              </tr>,
              ...rowProblems.map((p) => (
                <tr key={`${row.part_number}-${p.id}`} className="explain">
                  <td colSpan={6}>
                    <a href={`#problem-${p.id}`}>
                      <Explained text={p.explanation} />
                    </a>
                  </td>
                </tr>
              )),
            ];
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Customer PO totals</th>
            <td colSpan={5}>
              <span className="totals">
                <span>
                  Subtotal <strong>{formatMoney(d.order.subtotal)}</strong>
                </span>
                <span className={vatOpen ? "ringed" : ""}>
                  {vatOpen && <PencilRing />}
                  VAT {Math.round(Number(d.order.vat_rate) * 100)}% <strong>{formatMoney(d.order.vat_amount)}</strong>
                </span>
                <span className={totalOpen ? "ringed" : ""}>
                  {totalOpen && <PencilRing variant={1} />}
                  Total {d.order.currency} <strong>{formatMoney(d.order.total)}</strong>
                </span>
              </span>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ problems

function ProblemItem({ p, n, onDone }: { p: Problem; n: number; onDone: () => void }) {
  const { role } = useRole();
  const [mode, setMode] = useState<"accepted" | "fixed" | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/api/discrepancies/${p.id}`, role, { status: mode, note });
      setMode(null);
      setNote("");
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const open = p.status === "open";
  return (
    <li id={`problem-${p.id}`} className={`problem-item ${p.status} ${p.severity}`}>
      <span className="problem-mark" aria-hidden="true">
        {open && p.severity !== "info" ? <PencilRing variant={p.id}>{n}</PencilRing> : open ? <span className="note-mark">i</span> : <PencilTick />}
      </span>
      <div className="problem-body">
        <p className="problem-title">
          <strong>{PROBLEM_TITLE[p.code] ?? p.code}</strong>
          <span className="quiet">
            {open ? `${SEVERITY_WORDS[p.severity]}. For ${ROLE_NAME[problemOwner(p.code)]}` : `${p.status === "fixed" ? "Fixed" : "Accepted"} by ${p.resolved_by_role ? ROLE_NAME[p.resolved_by_role] : ""}, ${formatDate(p.resolved_at)}`}
          </span>
        </p>
        <p className={open ? "" : "struck"}>
          <Explained text={p.explanation} />
        </p>
        {!open && p.resolution_note && <p className="resolution">"{p.resolution_note}"</p>}
        {open && p.severity !== "info" && mode === null && (
          <div className="problem-actions">
            <button type="button" className="button" onClick={() => setMode("fixed")}>
              Mark fixed
            </button>
            <button type="button" className="button" onClick={() => setMode("accepted")}>
              Accept with a note
            </button>
          </div>
        )}
        {mode && (
          <form
            className="settle"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <label>
              {mode === "fixed" ? "What was fixed?" : "Why are you accepting this?"} <span className="quiet">Kept in the order's history.</span>
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={500} autoFocus required minLength={3} />
            </label>
            <div className="problem-actions">
              <button type="submit" className="button primary" disabled={busy || note.trim().length < 3}>
                {mode === "fixed" ? "Mark fixed" : "Accept"} as {ROLE_NAME[role]}
              </button>
              <button type="button" className="button" onClick={() => setMode(null)}>
                Cancel
              </button>
            </div>
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </form>
        )}
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ documents

interface DocumentFull {
  document: { id: number; kind: string; filename: string; mime: string; extracted: { fields: Record<string, { value: unknown; page?: number; bbox?: [number, number, number, number] }>; text?: string } };
}

function DocumentViewer({ id, onClose }: { id: number; onClose: () => void }) {
  const [doc, setDoc] = useState<DocumentFull["document"] | null>(null);
  useEffect(() => {
    api.get<DocumentFull>(`/api/documents/${id}`).then((r) => setDoc(r.document));
  }, [id]);
  if (!doc) return <p className="quiet">Opening the document.</p>;
  const boxes: Box[] = Object.entries(doc.extracted.fields)
    .filter(([, f]) => f.bbox && f.page !== undefined)
    .map(([name, f]) => ({ id: name, page: f.page as number, bbox: f.bbox as Box["bbox"] }));
  return (
    <div className="viewer">
      <div className="viewer-head">
        <span>
          <strong>{DOC_KIND[doc.kind]}</strong> <span className="mono">{doc.filename}</span>
        </span>
        <span>
          <a className="link" href={`/api/documents/${id}/file`} target="_blank" rel="noreferrer">
            Open the file
          </a>{" "}
          <button type="button" className="link" onClick={onClose}>
            Close
          </button>
        </span>
      </div>
      {doc.mime === "application/pdf" ? (
        <>
          <p className="quiet small">Blue boxes show where each header value was read.</p>
          <PdfView source={`/api/documents/${id}/file`} boxes={boxes} label={doc.filename} />
        </>
      ) : (
        <pre className="email">{doc.extracted.text}</pre>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ page

export function Order() {
  const { id = "" } = useParams();
  const { load, reload } = useOrder(id);
  const [viewing, setViewing] = useState<number | null>(null);
  const refresh = useCallback(() => reload(), [reload]);

  useEffect(() => {
    if (load.state === "ready") document.title = `${load.data.order.po_number}: Order Desk`;
  }, [load]);

  if (load.state === "loading") {
    return (
      <div className="page">
        <Link to="/" className="back">
          Order board
        </Link>
        <p className="quiet" role="status">{load.slow ? "Still loading the order. The database may need a moment to wake up." : "Loading the order."}</p>
      </div>
    );
  }
  if (load.state === "error") {
    const missing = load.error instanceof ApiError && load.error.status === 404;
    return (
      <div className="page">
        <Link to="/" className="back">
          Order board
        </Link>
        <h1 className="h-page">{missing ? "No such order" : "The order did not load"}</h1>
        <p>{missing ? "Search the board by PO, tracking or serial number." : load.error.message}</p>
        {!missing && (
          <button type="button" className="button" onClick={reload}>
            Try again
          </button>
        )}
      </div>
    );
  }

  const d = load.data;
  const o = d.order;
  const openProblems = d.problems.filter((p) => p.status === "open");
  const settled = d.problems.filter((p) => p.status !== "open");
  const inbound = d.shipments.filter((s) => s.direction === "inbound");
  const serials = d.grid.filter((r) => r.serials.length);

  return (
    <div className="page order-page">
      <Link to="/" className="back">
        Order board
      </Link>
      <div className="order-top">
        <div className="waybill">
          <p className="caption">Customer PO</p>
          <h1 className="po-big mono">{o.po_number}</h1>
          <dl className="boxes">
            <div>
              <dt>Customer</dt>
              <dd>{o.customer_name}</dd>
            </div>
            <div>
              <dt>Our PO</dt>
              <dd className="mono">{o.our_po_number ?? <span className="quiet">not sent</span>}</dd>
            </div>
            <div>
              <dt>Distributor</dt>
              <dd>{o.distributor_name ?? <span className="quiet">none yet</span>}</dd>
            </div>
            <div>
              <dt>PO date</dt>
              <dd>{formatDate(o.po_date)}</dd>
            </div>
            <div>
              <dt>Needed by</dt>
              <dd>{formatDate(o.required_by)}</dd>
            </div>
            <div>
              <dt>Value {o.currency}</dt>
              <dd className="num-left">{formatMoney(o.total)}</dd>
            </div>
          </dl>
          {o.whose_turn && (
            <p className="waiting-line">
              With <strong>{ROLE_NAME[o.whose_turn]}</strong> {o.days_in_stage > 0 ? `for ${days(o.days_in_stage)}` : "since today"}.
            </p>
          )}
        </div>
        <NextStep d={d} onDone={refresh} />
      </div>

      <Chain d={d} />

      <section aria-labelledby="match-h">
        <h2 id="match-h" className="h-section">
          Line by line
        </h2>
        <MatchGrid d={d} />
      </section>

      <div className="order-bottom">
        <section id="problems" aria-labelledby="problems-h">
          <h2 id="problems-h" className="h-section">
            Problems{" "}
            <span className="count">
              {openProblems.length ? `${openProblems.filter((p) => p.severity !== "info").length} open` : "none open"}
            </span>
          </h2>
          {d.problems.length === 0 ? (
            <p className="quiet">The checks found nothing to question on this order.</p>
          ) : (
            <ul className="problems">
              {[...openProblems, ...settled].map((p, i) => (
                <ProblemItem key={p.id} p={p} n={i + 1} onDone={refresh} />
              ))}
            </ul>
          )}
        </section>
        <aside aria-labelledby="docs-h">
          <h2 id="docs-h" className="h-section">
            Documents
          </h2>
          <ul className="docs">
            {d.documents.map((doc) => (
              <li key={doc.id}>
                <button type="button" className="doc" aria-pressed={viewing === doc.id} onClick={() => setViewing(viewing === doc.id ? null : doc.id)}>
                  <span className="doc-kind">{DOC_KIND[doc.kind]}</span>
                  <span className="mono doc-name">{doc.filename}</span>
                  <span className="quiet doc-when">
                    {formatDate(doc.uploaded_at)}, {doc.uploaded_by_role === "system" ? "system" : ROLE_NAME[doc.uploaded_by_role]}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {inbound.length > 0 && (
            <>
              <h3 className="h-sub">Goods in</h3>
              <ul className="ships">
                {inbound.map((s) => (
                  <li key={s.id}>
                    <span className="mono">{s.delivery_note_no}</span>
                    {s.tracking_number && <span className="mono quiet"> {s.tracking_number}</span>}
                    {s.marked_partial && <span className="quiet"> part delivery</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {serials.length > 0 && (
            <>
              <h3 className="h-sub">Serial numbers</h3>
              <dl className="serials">
                {serials.map((r) => (
                  <div key={r.part_number}>
                    <dt className="mono">{r.part_number}</dt>
                    <dd className="mono">{r.serials.join(" ")}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </aside>
      </div>

      {viewing !== null && (
        <section aria-label="Document" className="viewer-section">
          <DocumentViewer id={viewing} onClose={() => setViewing(null)} />
        </section>
      )}

      <section aria-labelledby="history-h">
        <h2 id="history-h" className="h-section">
          History
        </h2>
        <ol className="history">
          {d.events.map((e, i) => (
            <li key={i}>
              <time dateTime={e.at}>{formatDate(e.at)}</time>
              <span className="history-role">{e.role === "system" ? "System" : ROLE_NAME[e.role]}</span>
              <span>
                <Explained text={e.text} />
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
