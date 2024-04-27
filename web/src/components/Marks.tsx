// The only drawn marks on the site (DESIGN.md section 0.4): a graphite pencil tick for "agrees" and a red pencil
// ring for "does not". Hand-drawn feel from fixed paths (two variants), so a render is stable and testable.

const RINGS = [
  "M29.5 5.2C36.8 7.4 38.6 18.6 28.9 23.3C19.4 27.8 4.6 25.6 2.9 16.4C1.5 8.6 11.1 2.6 21.4 3.1C27.3 3.4 32.6 5.6 34.4 9.1",
  "M8.2 6.4C15.7 1.9 33.9 2.3 36.6 11.8C39 20.4 27.6 25.6 18.1 25.1C8.7 24.6 2.4 19.9 3.2 13.2C3.8 8.5 9.4 4.9 15.9 4.1",
];

export function PencilRing({
  children,
  variant = 0,
  filled = false,
  label,
}: {
  children?: React.ReactNode;
  variant?: number;
  filled?: boolean;
  label?: string;
}) {
  return (
    <span className={`ring${filled ? " ring-filled" : ""}`} role={label ? "img" : undefined} aria-label={label}>
      {/* stretches to whatever it circles; the stroke keeps its weight */}
      <svg viewBox="0 0 40 28" preserveAspectRatio="none" aria-hidden="true" focusable="false">
        <path d={RINGS[Math.abs(variant) % RINGS.length]} vectorEffect="non-scaling-stroke" />
      </svg>
      {children !== undefined && <span className="ring-text">{children}</span>}
    </span>
  );
}

export function PencilTick({ label }: { label?: string }) {
  return (
    <span className="tick" role={label ? "img" : undefined} aria-label={label}>
      <svg viewBox="0 0 24 20" aria-hidden="true" focusable="false">
        <path d="M3.2 11.6C5.1 12.4 6.8 14.6 8.1 17.4C10.9 10.6 15.2 5.4 21.1 2.3" />
      </svg>
    </span>
  );
}
