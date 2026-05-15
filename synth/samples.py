"""The sample documents offered on the intake screen, written to web/public/samples/.

    python -m synth.samples

They fit the seeded demo database (same seed), so they work again after every nightly reset:
new customer POs, a confirmation with a shortfall, and a delivery for an order that is waiting, whose
delivery note repeats a serial number already booked in on another order.
"""

import copy
import json
from dataclasses import replace
from pathlib import Path

from backend.check.model import Confirmation, Shipment, ShipmentLine
from synth.catalogue import PRODUCT_BY_PART
from synth.render_eml import dispatch_email
from synth.render_pdf import CONFIRMATION, CUSTOMER_PO, delivery_note
from synth.scenario import build

OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "samples"


def _by_our_po(orders, number):
    return next(o for o in orders if o.our_po and o.our_po.our_po_number == number)


def main() -> None:
    orders = build()
    OUT.mkdir(parents=True, exist_ok=True)
    samples = []

    def add(name: str, data: bytes, title: str, shows: str, order: str | None = None):
        (OUT / name).write_bytes(data)
        samples.append({"file": name, "title": title, "shows": shows, "order": order, "bytes": len(data)})

    new = build(seed=99)[2]
    add(
        "new-customer-po.pdf",
        CUSTOMER_PO[new.customer_layout](new),
        f"New PO from {new.customer.name}",
        "A customer PO not on the board yet. Every value comes with the box it was read from.",
    )
    odd = build(seed=98)[4]
    add(
        "new-po-unfamiliar-layout.pdf",
        CUSTOMER_PO["L5"](odd),
        f"New PO from {odd.customer.name}, unfamiliar layout",
        "A layout the reader was not written for. Values it is unsure of are marked Check.",
    )

    # A confirmation that comes back one unit short on a waiting order.
    short = copy.deepcopy(_by_our_po(orders, "PO-2026-0102"))
    lines = list(short.our_po.lines)
    k = next(i for i, ln in enumerate(lines) if PRODUCT_BY_PART[ln.part_number].serialised and ln.qty > 1)
    lines[k] = replace(lines[k], qty=lines[k].qty - 1)
    short.confirmation = Confirmation(
        "FVD-SOC-604711", short.our_po.our_po_number, lines, eta=short.customer_po.required_by
    )
    short.distributor = replace(short.distributor)
    add(
        "confirmation-one-short.pdf",
        CONFIRMATION["A"](short),
        "Confirmation for PO-2026-0102",
        f"The distributor confirms one {lines[k].part_number} fewer than we ordered.",
        "PO-2026-0102",
    )

    # A clean confirmation, then its goods: the delivery note repeats a serial booked on another order.
    good = copy.deepcopy(_by_our_po(orders, "PO-2026-0127"))
    good.confirmation = Confirmation(
        "DCP/OC/26/7310", good.our_po.our_po_number, list(good.our_po.lines), eta=good.customer_po.required_by
    )
    add(
        "confirmation-clean.pdf",
        CONFIRMATION["B"](good),
        "Confirmation for PO-2026-0127",
        "Everything confirmed as ordered.",
        "PO-2026-0127",
    )
    taken = next(s for o in orders for sh in o.inbound for sl in sh.lines for s in sl.serials)
    ship_lines = []
    for n, ln in enumerate(good.our_po.lines):
        prod = PRODUCT_BY_PART[ln.part_number]
        serials = [f"{prod.serial_prefix}S{n}{i:02d}QX"[:7] for i in range(ln.qty)] if prod.serialised else []
        ship_lines.append(ShipmentLine(ln.part_number, ln.qty, serials))
    first = next(sl for sl in ship_lines if sl.serials)
    first.serials[-1] = taken
    good.inbound = [Shipment("inbound", "DN-DCP-31877", ship_lines)]
    good.tracking = {"DN-DCP-31877": "176-40418822"}
    good.carrier = replace(good.carrier, short_code="AAF", name="Atlas Air Freight")
    add(
        "delivery-note.pdf",
        delivery_note(good, 0),
        "Delivery note for PO-2026-0127",
        "Goods in, with serial numbers. One of them is already booked in on another order.",
        "PO-2026-0127",
    )
    add(
        "dispatch-email.eml",
        dispatch_email(good, 0),
        "Dispatch email for PO-2026-0127",
        "The same delivery as an email with the serials attached as a CSV file.",
        "PO-2026-0127",
    )

    (OUT / "samples.json").write_text(json.dumps(samples, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(samples)} samples in {OUT}")


if __name__ == "__main__":
    main()
