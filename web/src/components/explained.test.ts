import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Explained } from "./Explained";

const html = (text: string) => renderToStaticMarkup(createElement(Explained, { text }));

describe("identifiers inside sentences", () => {
  it("sets part numbers, PO numbers, serials and delivery notes in the identifier face", () => {
    const out = html("Serial KR3QK3R (SFP28-SR-25G) is already booked in on DN-FVD-45510.");
    expect(out).toContain('<span class="mono ident">KR3QK3R</span>');
    expect(out).toContain('<span class="mono ident">SFP28-SR-25G</span>');
    expect(out).toContain('<span class="mono ident">DN-FVD-45510</span>');
  });
  it("leaves words and plain numbers alone", () => {
    const out = html("Short 2: we ordered 10, the distributor confirmed 8.");
    expect(out).not.toContain("ident");
    expect(html("VAT at 5% of 1,000.00 is 50.00")).not.toContain("ident");
  });
  it("keeps the text unchanged", () => {
    const text = "Our PO PO-2026-0104 sent to the distributor";
    expect(html(text).replace(/<[^>]+>/g, "")).toBe(text);
  });
});
