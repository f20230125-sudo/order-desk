// A sentence from the check engine, with identifiers (part numbers, PO numbers, serials, delivery notes) set
// in the identifier face and kept on one line, so "SVC-INSTALL-D1" never breaks at a hyphen.

const ID = /\b(?=[A-Z0-9./-]*\d)(?=[A-Z0-9./-]*[A-Z])[A-Z0-9][A-Z0-9./-]{3,}[A-Z0-9]\b/g;

export function Explained({ text }: { text: string }) {
  const parts: (string | { id: string })[] = [];
  let last = 0;
  for (const m of text.matchAll(ID)) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push({ id: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return (
    <>
      {parts.map((p, i) =>
        typeof p === "string" ? (
          p
        ) : (
          <span key={i} className="mono ident">
            {p.id}
          </span>
        ),
      )}
    </>
  );
}
