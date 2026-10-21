import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export interface Box {
  id: string;
  page: number;
  bbox: [number, number, number, number]; // PDF points from the top-left corner: x0, top, x1, bottom
  active?: boolean;
}

// Renders every page of a PDF to canvas at the width of its column, and draws boxes over it where values
// were read. The page stays white in dark mode: it is a document.
export function PdfView({
  source,
  boxes = [],
  label,
  onBoxClick,
}: {
  source: string | ArrayBuffer;
  boxes?: Box[];
  label: string;
  onBoxClick?: (id: string) => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [pages, setPages] = useState<{ width: number; height: number; scale: number }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const canvases = useRef<(HTMLCanvasElement | null)[]>([]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setPages([]);
    const task = pdfjs.getDocument(
      typeof source === "string" ? { url: source } : { data: new Uint8Array(source.slice(0)) },
    );
    task.promise
      .then(async (d) => {
        const width = Math.max(320, (holder.current?.clientWidth ?? 640) - 2);
        const sizes = [];
        for (let n = 1; n <= d.numPages; n++) {
          const page = await d.getPage(n);
          const base = page.getViewport({ scale: 1 });
          const scale = width / base.width;
          sizes.push({ width, height: base.height * scale, scale });
        }
        if (cancelled) return;
        setPages(sizes);
        const ratio = window.devicePixelRatio || 1;
        for (let n = 1; n <= d.numPages; n++) {
          const canvas = canvases.current[n - 1];
          if (!canvas) continue;
          const page = await d.getPage(n);
          const viewport = page.getViewport({ scale: sizes[n - 1].scale * ratio });
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          await page.render({ canvas, viewport }).promise;
        }
      })
      .catch(() => !cancelled && setError("This PDF could not be shown."));
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [source]);

  useEffect(() => {
    const active = holder.current?.querySelector<HTMLElement>(".src-box.active");
    active?.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [boxes]);

  return (
    <div className="pdf" ref={holder} aria-label={label} role="document">
      {error && <p className="state">{error}</p>}
      {!error && pages.length === 0 && <div className="pdf-page loading" aria-hidden="true" />}
      {pages.map((p, i) => (
        <div key={i} className="pdf-page" style={{ width: p.width, height: p.height }}>
          <canvas ref={(el) => void (canvases.current[i] = el)} style={{ width: p.width, height: p.height }} />
          {boxes
            .filter((b) => b.page === i)
            .map((b) => {
              const [x0, top, x1, bottom] = b.bbox;
              const pad = 3;
              return (
                <button
                  type="button"
                  key={b.id}
                  className={`src-box${b.active ? " active" : ""}`}
                  tabIndex={-1}
                  aria-hidden="true"
                  onClick={() => onBoxClick?.(b.id)}
                  style={{
                    left: x0 * p.scale - pad,
                    top: top * p.scale - pad,
                    width: (x1 - x0) * p.scale + pad * 2,
                    height: (bottom - top) * p.scale + pad * 2,
                  }}
                />
              );
            })}
        </div>
      ))}
    </div>
  );
}
