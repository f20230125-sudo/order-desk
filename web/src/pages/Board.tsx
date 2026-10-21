import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { PencilRing, PencilTick } from "../components/Marks";
import { RouteLine } from "../components/RouteLine";
import { api, type BoardOrder, type BoardResponse, type Role } from "../lib/api";
import { STAGES, days, formatMoney, plural } from "../lib/format";
import { ROLE_NAME, useRole } from "../lib/role";

type Load = { state: "loading"; slow: boolean } | { state: "error"; message: string } | { state: "ready"; data: BoardResponse };

function useBoard(query: string) {
  const [load, setLoad] = useState<Load>({ state: "loading", slow: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setLoad((l) => (l.state === "ready" ? l : { state: "loading", slow: false }));
    const slow = window.setTimeout(() => live && setLoad((l) => (l.state === "loading" ? { ...l, slow: true } : l)), 700);
    api
      .get<BoardResponse>(`/api/board${query}`)
      .then((data) => live && setLoad({ state: "ready", data }))
      .catch((e: Error) => live && setLoad({ state: "error", message: e.message }))
      .finally(() => window.clearTimeout(slow));
    return () => {
      live = false;
      window.clearTimeout(slow);
    };
  }, [query, attempt]);
  return { load, retry: () => setAttempt((n) => n + 1) };
}

function Sentence({ data, role }: { data: BoardResponse; role: Role }) {
  const s = data.summary;
  return (
    <p className="lede">
      {plural(s.open, "order")} open. {s[role] === 0 ? `Nothing is waiting for ${ROLE_NAME[role]}.` : `${s[role]} ${s[role] === 1 ? "is" : "are"} with ${ROLE_NAME[role]} now.`}{" "}
      {s.with_problems === 0 ? "No open problems." : `${plural(s.with_problems, "order")} ${s.with_problems === 1 ? "has" : "have"} a problem.`}
    </p>
  );
}

function Row({ o, role, selected, onSelect }: { o: BoardOrder; role: Role; selected: boolean; onSelect: () => void }) {
  const navigate = useNavigate();
  const stage = STAGES[o.stage_no - 1];
  const open = () => navigate(`/orders/${o.id}`);
  return (
    <tr
      className={`order${selected ? " selected" : ""}`}
      aria-selected={selected}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a")) return;
        onSelect();
        open();
      }}
    >
      <td className="margin">
        {o.problems > 0 ? (
          <PencilRing filled variant={o.id} label={plural(o.problems, "open problem")}>
            {o.problems}
          </PencilRing>
        ) : (
          <PencilTick label="No open problems" />
        )}
      </td>
      <th scope="row" className="ids">
        <Link to={`/orders/${o.id}`} className="po" tabIndex={selected ? 0 : -1}>
          {o.po_number}
        </Link>
        {o.our_po_number ? <span className="sub mono">{o.our_po_number}</span> : <span className="sub">Our PO not sent</span>}
      </th>
      <td className="customer">
        {o.customer_name}
        <span className="sub">{o.distributor_name ?? "No distributor yet"}</span>
      </td>
      <td className="where">
        <RouteLine stageNo={o.stage_no} problem={o.problems > 0} />
        <span className="stage">{stage.short}</span>
      </td>
      <td className="turn">
        {o.whose_turn === role ? (
          // the band heading already says it is yours; a stamp on every row would only repeat it
          <span className="visually-hidden">With {ROLE_NAME[role]}</span>
        ) : o.whose_turn ? (
          <span className="stamp">{ROLE_NAME[o.whose_turn]}</span>
        ) : (
          <span className="quiet">Handed over</span>
        )}
      </td>
      <td className={`waiting num${o.days_in_stage >= 5 && o.whose_turn ? " long" : ""}`}>
        {o.whose_turn ? days(o.days_in_stage) : ""}
      </td>
      <td className="problem">
        {o.first_problem ? (
          <span className="pencil-text">{o.first_problem}</span>
        ) : o.notes > 0 ? (
          <span className="quiet">Note: part delivery, balance to follow.</span>
        ) : (
          <span className="quiet">None</span>
        )}
      </td>
      <td className="value num">{formatMoney(o.total)}</td>
    </tr>
  );
}

const COLS = 8;

export function Board() {
  const { role } = useRole();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const stage = params.get("stage") ?? "";
  const problems = params.get("problems") === "1";
  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (stage) p.set("stage", stage);
    if (problems) p.set("problems", "1");
    const s = p.toString();
    return s ? `?${s}` : "";
  }, [q, stage, problems]);
  const { load, retry } = useBoard(query);
  const [showDone, setShowDone] = useState(false);
  const [selected, setSelected] = useState(0);
  const search = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const bands = useMemo(() => {
    const orders = load.state === "ready" ? load.data.orders : [];
    const mine = orders.filter((o) => o.whose_turn === role);
    const others = orders.filter((o) => o.whose_turn && o.whose_turn !== role);
    const done = orders.filter((o) => !o.whose_turn);
    return { mine, others, done };
  }, [load, role]);
  const visible = useMemo(
    () => [...bands.mine, ...bands.others, ...(showDone ? bands.done : [])],
    [bands, showDone],
  );

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input, textarea, select");
      if (e.key === "/" && !typing) {
        e.preventDefault();
        search.current?.focus();
      } else if (!typing && (e.key === "j" || e.key === "k")) {
        setSelected((i) => Math.max(0, Math.min(visible.length - 1, i + (e.key === "j" ? 1 : -1))));
      } else if (!typing && e.key === "Enter" && visible[selected]) {
        navigate(`/orders/${visible[selected].id}`);
      } else if (!typing && e.key.toLowerCase() === "n" && !e.metaKey && !e.ctrlKey) {
        navigate("/intake");
      } else if (e.key === "Escape" && typing) {
        (e.target as HTMLElement).blur();
      }
    },
    [visible, selected, navigate],
  );
  useEffect(() => {
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onKey]);
  useEffect(() => {
    document.title = "Order board · Order Desk";
  }, []);
  useEffect(() => setSelected(0), [query, role]);
  useEffect(() => {
    document.querySelector<HTMLElement>("tr.order.selected a.po")?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const filtered = Boolean(q || stage || problems);
  let index = -1;
  const rows = (list: BoardOrder[]) =>
    list.map((o) => {
      index += 1;
      const i = index;
      return <Row key={o.id} o={o} role={role} selected={i === selected} onSelect={() => setSelected(i)} />;
    });

  return (
    <div className="page board">
      <div className="board-head">
        <h1>Order board</h1>
        {load.state === "ready" ? <Sentence data={load.data} role={role} /> : <p className="lede quiet">Counting orders.</p>}
      </div>

      <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
        <label className="search">
          <span className="visually-hidden">Find an order</span>
          <kbd aria-hidden="true">/</kbd>
          <input
            ref={search}
            type="search"
            value={q}
            onChange={(e) => set("q", e.target.value)}
            placeholder="Find a PO, tracking or serial number"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="select">
          <span>Stage</span>
          <select value={stage} onChange={(e) => set("stage", e.target.value)}>
            <option value="">All stages</option>
            {STAGES.map((s) => (
              <option key={s.key} value={s.key}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={problems} onChange={(e) => set("problems", e.target.checked ? "1" : "")} />
          Only orders with a problem
        </label>
      </form>

      {load.state === "error" ? (
        <div className="state error" role="alert">
          <p>{load.message}</p>
          <button type="button" className="button" onClick={retry}>
            Try again
          </button>
        </div>
      ) : (
        <table className="pad" aria-busy={load.state === "loading"}>
          <caption className="visually-hidden">
            Orders, yours first. Columns: problems, order, customer, where it is, whose turn, waiting, first problem,
            value.
          </caption>
          <colgroup>
            <col className="c-margin" />
            <col className="c-ids" />
            <col className="c-customer" />
            <col className="c-where" />
            <col className="c-turn" />
            <col className="c-waiting" />
            <col className="c-problem" />
            <col className="c-value" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">
                <span className="visually-hidden">Problems</span>
              </th>
              <th scope="col">Customer PO</th>
              <th scope="col">Customer</th>
              <th scope="col">Where it is</th>
              <th scope="col">Turn</th>
              <th scope="col" className="num">
                Waiting
              </th>
              <th scope="col">First problem</th>
              <th scope="col" className="num">
                Value AED
              </th>
            </tr>
          </thead>
          {load.state === "loading" ? (
            <tbody>
              <tr className="band">
                <th scope="rowgroup" colSpan={COLS}>
                  {load.slow ? "Waking the database. This usually takes a few seconds." : "Loading orders."}
                </th>
              </tr>
              {Array.from({ length: 8 }, (_, i) => (
                <tr key={i} className="ghost">
                  <td colSpan={COLS} />
                </tr>
              ))}
            </tbody>
          ) : visible.length === 0 && bands.done.length === 0 ? (
            <tbody>
              <tr className="band">
                <th scope="rowgroup" colSpan={COLS}>
                  {filtered ? (
                    <>
                      No orders match these filters.{" "}
                      <button type="button" className="link" onClick={() => setParams({}, { replace: true })}>
                        Clear filters
                      </button>
                    </>
                  ) : (
                    "No orders yet. Add one from a document."
                  )}
                </th>
              </tr>
            </tbody>
          ) : (
            <>
              <tbody>
                <tr className="band mine">
                  <th scope="rowgroup" colSpan={COLS}>
                    With {ROLE_NAME[role]} now <span className="count">{bands.mine.length}</span>
                  </th>
                </tr>
                {bands.mine.length ? (
                  rows(bands.mine)
                ) : (
                  <tr className="empty">
                    <td colSpan={COLS}>Nothing is waiting for {ROLE_NAME[role]}.</td>
                  </tr>
                )}
              </tbody>
              {bands.others.length > 0 && (
                <tbody>
                  <tr className="band">
                    <th scope="rowgroup" colSpan={COLS}>
                      With {(["sales", "ops", "finance"] as Role[]).filter((r) => r !== role).map((r) => ROLE_NAME[r]).join(" and ")}{" "}
                      <span className="count">{bands.others.length}</span>
                    </th>
                  </tr>
                  {rows(bands.others)}
                </tbody>
              )}
              {bands.done.length > 0 && (
                <tbody>
                  <tr className="band">
                    <th scope="rowgroup" colSpan={COLS}>
                      Handed to finance <span className="count">{bands.done.length}</span>{" "}
                      <button type="button" className="link" aria-expanded={showDone} onClick={() => setShowDone((s) => !s)}>
                        {showDone ? "Hide" : "Show"}
                      </button>
                    </th>
                  </tr>
                  {showDone && rows(bands.done)}
                </tbody>
              )}
            </>
          )}
        </table>
      )}
      <p className="keys" aria-hidden="true">
        <kbd>/</kbd> search <kbd>j</kbd> <kbd>k</kbd> move <kbd>Enter</kbd> open <kbd>N</kbd> add from a document
      </p>
    </div>
  );
}
