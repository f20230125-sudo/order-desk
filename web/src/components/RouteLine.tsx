import { STAGES } from "../lib/format";

// The six steps as stations on a line (DESIGN.md section 0.3): solid up to where the order is, dotted after.
// The station where the order stands gets an ink ring; with an open problem, a red pencil ring around it.

const GAP = 25;
const X0 = 8;
const H = 20;
const Y = H / 2;

export function RouteLine({ stageNo, problem }: { stageNo: number; problem: boolean }) {
  const current = stageNo - 1;
  const xs = STAGES.map((_, i) => X0 + i * GAP);
  const last = xs[xs.length - 1];
  const cx = xs[current];
  const label = `Step ${stageNo} of 6, ${STAGES[current].name.toLowerCase()}${problem ? ", held by a problem" : ""}`;
  const finished = current === 5;
  return (
    <svg className="route" viewBox={`0 0 ${last + X0} ${H}`} width={last + X0} height={H} role="img" aria-label={label}>
      <line className="route-done" x1={X0} y1={Y} x2={cx} y2={Y} />
      {!finished && <line className="route-todo" x1={cx} y1={Y} x2={last} y2={Y} />}
      {xs.map((x, i) =>
        i < current ? (
          <circle key={i} className="station-done" cx={x} cy={Y} r={3.2} />
        ) : i > current ? (
          <circle key={i} className="station-todo" cx={x} cy={Y} r={2.9} />
        ) : null,
      )}
      {finished ? (
        <circle className="station-done" cx={cx} cy={Y} r={4.2} />
      ) : (
        <circle className="station-current" cx={cx} cy={Y} r={5.6} />
      )}
      {problem && (
        <path
          className="station-problem"
          transform={`translate(${cx - 11} 0)`}
          d="M16.6 2.4C21.6 3.9 22.9 12 16.2 15.6C9.4 19 0.9 16.9 0.8 10.4C0.7 4.8 6.8 1.2 13.2 1.6C16.6 1.8 19.6 3.3 20.6 5.5"
        />
      )}
    </svg>
  );
}
