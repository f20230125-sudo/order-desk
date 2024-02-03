"""Write every synthetic document to synth/out/ and the ground truth to synth/ground_truth.json.

    python -m synth.generate

Ground truth holds, for each document, the exact values printed on it (what a perfect extractor returns),
and for each order the problems that were planted (what a perfect check engine reports).
"""

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from synth.render_eml import dispatch_email
from synth.render_pdf import CONFIRMATION, CUSTOMER_PO, delivery_note
from synth.scenario import SynthOrder, build, planted_summary

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
GROUND_TRUTH = HERE / "ground_truth.json"


def _lines(lines) -> list[dict]:
    return [
        {
            "line_no": x.line_no,
            "part_number": x.part_number,
            "qty": x.qty,
            "unit_price": str(x.unit_price),
            **({"substitutes_part": x.substitutes_part} if x.substitutes_part else {}),
        }
        for x in lines
    ]


def documents_for(o: SynthOrder, held_out: bool = False) -> list[tuple[str, bytes, dict]]:
    """(filename, bytes, truth) for each document of the order. held_out adds the L5 rendering of its PO."""
    po = o.customer_po
    docs = []
    po_truth = {
        "kind": "customer_po",
        "layout": o.customer_layout,
        "order": o.key,
        "fields": {
            "po_number": po.po_number,
            "po_date": po.po_date.isoformat(),
            "required_by": po.required_by.isoformat(),
            "buyer_trn": o.customer.trn,
            "subtotal": str(po.subtotal),
            "vat_amount": str(po.vat_amount),
            "total": str(po.total),
        },
        "lines": _lines(po.lines),
    }
    docs.append((f"{o.key}-customer-po-{o.customer_layout}.pdf", CUSTOMER_PO[o.customer_layout](o), po_truth))
    if held_out:
        docs.append((f"{o.key}-customer-po-L5.pdf", CUSTOMER_PO["L5"](o), {**po_truth, "layout": "L5"}))
    if o.confirmation:
        c = o.confirmation
        docs.append(
            (
                f"{o.key}-confirmation-{o.confirmation_layout}.pdf",
                CONFIRMATION[o.confirmation_layout](o),
                {
                    "kind": "vendor_confirmation",
                    "layout": o.confirmation_layout,
                    "order": o.key,
                    "fields": {
                        "confirmation_no": c.confirmation_no,
                        "referenced_po": c.referenced_po,
                        "eta": c.eta.isoformat(),
                    },
                    "lines": _lines(c.lines),
                },
            )
        )
    for k, ship in enumerate(o.inbound):
        ship_truth = {
            "delivery_note_no": ship.reference,
            "referenced_po": o.our_po.our_po_number,
            "tracking_number": o.tracking[ship.reference],
            "marked_partial": ship.marked_partial,
        }
        ship_lines = [
            {"part_number": sl.part_number, "qty": sl.qty, "serials": sl.serials} for sl in ship.lines
        ]
        docs.append(
            (
                f"{o.key}-delivery-note-{k + 1}.pdf",
                delivery_note(o, k),
                {
                    "kind": "delivery_note",
                    "layout": "DN",
                    "order": o.key,
                    "fields": ship_truth,
                    "lines": ship_lines,
                },
            )
        )
        docs.append(
            (
                f"{o.key}-dispatch-{k + 1}.eml",
                dispatch_email(o, k),
                {
                    "kind": "shipment_email",
                    "layout": "CSV" if o.carrier.short_code == "AAF" else "BODY",
                    "order": o.key,
                    "fields": {k2: v for k2, v in ship_truth.items() if k2 != "marked_partial"},
                    "lines": ship_lines,
                },
            )
        )
    return docs


def main() -> None:
    orders = build()
    OUT.mkdir(exist_ok=True)
    truth = {"documents": {}, "orders": {}}
    for o in orders:
        for name, data, t in documents_for(o, held_out=True):
            (OUT / name).write_bytes(data)
            truth["documents"][name] = t
        truth["orders"][o.key] = {
            "stage": o.stage,
            "customer": o.customer.name,
            "layout": o.customer_layout,
            "planted": [asdict(p) for p in o.planted],
        }
    GROUND_TRUTH.write_text(
        json.dumps(truth, indent=1, default=lambda v: str(v) if isinstance(v, Decimal) else v),
        encoding="utf-8",
    )
    kinds: dict[str, int] = {}
    for t in truth["documents"].values():
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    print(f"{len(truth['documents'])} documents for {len(orders)} orders: {kinds}")
    print("planted:", planted_summary(orders))


if __name__ == "__main__":
    main()
