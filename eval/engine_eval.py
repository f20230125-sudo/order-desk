"""Score the check engine against the problems planted in the synthetic orders, twice:

1. on the true order data (does the engine find what was planted, and nothing else?)
2. end to end: customer PO, confirmation and goods-in read back from the generated PDFs and emails by the
   extractor, so extraction mistakes count against the result too.

A finding counts as found when its code, stage and part number match a planted problem on the same order.
"""

from decimal import Decimal

from backend.check.engine import check
from backend.check.model import Confirmation, CustomerPO, Line, OrderBundle, Shipment, ShipmentLine
from backend.extract.detect import extract
from synth.catalogue import PRODUCT_BY_PART
from synth.generate import documents_for
from synth.scenario import PROBLEMS, build

SERIALISED = frozenset(p for p, prod in PRODUCT_BY_PART.items() if prod.serialised)
PLANTED_STAGE = {kind: stage for kind, (stage, _stops) in PROBLEMS.items()}
PLANTED_STAGE.update(RECEIPT_SHORT="received", PARTIAL_SHIPMENT="received")


def _seen_before(orders, upto: int) -> dict[str, str]:
    seen = {}
    for o in orders[:upto]:
        for s in o.inbound:
            for sl in s.lines:
                for serial in sl.serials:
                    seen.setdefault(serial, o.key)
    return seen


def bundle_from_truth(orders, i: int) -> OrderBundle:
    o = orders[i]
    return OrderBundle(
        customer_po=o.customer_po,
        our_po=o.our_po,
        confirmations=[o.confirmation] if o.confirmation else [],
        shipments=o.inbound + o.outbound,
        serialised_parts=SERIALISED,
        serials_seen_elsewhere=_seen_before(orders, i),
    )


def _v(d: dict, key: str, default=None):
    return d.get(key, {}).get("value", default) if isinstance(d.get(key), dict) else default


def _lines(got: dict, price: bool = True) -> list[Line]:
    out = []
    for n, ln in enumerate(got["lines"], start=1):
        out.append(
            Line(
                n,
                _v(ln, "part_number", ""),
                _v(ln, "description", "") or "",
                int(_v(ln, "qty", 0) or 0),
                Decimal(_v(ln, "unit_price", 0) or 0) if price else Decimal(0),
                substitutes_part=_v(ln, "substitutes_part"),
            )
        )
    return out


def bundle_from_documents(orders, i: int) -> OrderBundle:
    o = orders[i]
    docs = {t["kind"] + ("" if t["layout"] != "L5" else "-L5"): (data, t) for _n, data, t in documents_for(o)}
    _m, po = extract(docs["customer_po"][0])
    f = po["fields"]
    customer_po = CustomerPO(
        po_number=_v(f, "po_number", ""),
        po_date=_v(f, "po_date"),
        lines=_lines(po),
        required_by=_v(f, "required_by"),
        subtotal=_v(f, "subtotal"),
        vat_amount=_v(f, "vat_amount"),
        total=_v(f, "total"),
    )
    confirmations = []
    if "vendor_confirmation" in docs:
        _m, c = extract(docs["vendor_confirmation"][0])
        confirmations.append(
            Confirmation(
                _v(c["fields"], "confirmation_no", ""),
                _v(c["fields"], "referenced_po", ""),
                _lines(c),
                _v(c["fields"], "eta"),
            )
        )
    shipments = []
    if "delivery_note" in docs:
        _m, dn = extract(docs["delivery_note"][0])
        lines = [
            ShipmentLine(
                _v(ln, "part_number", ""), int(_v(ln, "qty", 0) or 0), list(_v(ln, "serials", []) or [])
            )
            for ln in dn["lines"]
        ]
        shipments.append(
            Shipment(
                "inbound",
                _v(dn["fields"], "delivery_note_no", ""),
                lines,
                marked_partial=bool(_v(dn["fields"], "marked_partial", False)),
            )
        )
    shipments += o.outbound  # we create outbound deliveries ourselves; nothing to read
    return OrderBundle(
        customer_po=customer_po,
        our_po=o.our_po,
        confirmations=confirmations,
        shipments=shipments,
        serialised_parts=SERIALISED,
        serials_seen_elsewhere=_seen_before(orders, i),
    )


def _score(orders, make) -> dict:
    tp = fp = fn = 0
    false_alarms, missed = [], []
    for i, o in enumerate(orders):
        planted = {(p.code, PLANTED_STAGE[p.kind], p.part_number) for p in o.planted}
        found = {(f.code, f.stage, f.part_number) for f in check(make(orders, i))}
        tp += len(planted & found)
        for x in sorted(found - planted, key=str):
            fp += 1
            false_alarms.append({"order": o.key, "code": x[0], "stage": x[1], "part": x[2]})
        for x in sorted(planted - found, key=str):
            fn += 1
            missed.append({"order": o.key, "code": x[0], "stage": x[1], "part": x[2]})
    return {
        "true_positives": tp,
        "false_positives": fp,
        "missed": fn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "false_alarms": false_alarms,
        "missed_list": missed,
    }


def evaluate_engine(_truth: dict | None = None) -> dict:
    orders = build()
    on_truth = _score(orders, bundle_from_truth)
    end_to_end = _score(orders, bundle_from_documents)
    return {
        **on_truth,
        "end_to_end": end_to_end,
        "orders": len(orders),
        "planted": sum(len(o.planted) for o in orders),
    }
