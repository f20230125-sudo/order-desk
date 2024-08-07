"""Check one order's chain, link by link, and say in plain words what does not match.

    customer PO          its own arithmetic (VAT, total)
    our PO               against the customer PO (did we order what they asked for?)
    confirmation         against our PO (PO number, parts, quantities, prices, substitutes, ETA)
    goods received       against what was confirmed (quantities, part deliveries, serial numbers)
    goods delivered      against what the customer ordered

Pure functions over the dataclasses in model.py: no database, so every rule is tested on its own.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from rapidfuzz import fuzz

from backend.check.model import Line, OrderBundle

ENGINE_VERSION = "1.0"
PRICE_TOLERANCE = Decimal("0.01")  # a price change under 1% is rounding, not a problem
MONEY_TOLERANCE = Decimal("0.05")  # printed totals may be off by rounding of a few fils
SIMILAR_DESCRIPTION = 80  # rapidfuzz token_set_ratio at or above this suggests the same kind of item

SEVERITY = {
    "VAT_MATH": "block",
    "TOTAL_MATH": "block",
    "PART_MISMATCH": "block",
    "QTY_SHORT": "block",
    "PRICE_DIFF": "block",
    "SUBSTITUTION": "block",
    "MISSING_LINE": "block",
    "PO_REF": "block",
    "DUPLICATE_SERIAL": "block",
    "QTY_OVER": "warn",
    "EXTRA_LINE": "warn",
    "ETA_LATE": "warn",
    "SERIAL_COUNT": "warn",
    "PARTIAL_SHIPMENT": "info",
}


@dataclass(frozen=True)
class Finding:
    code: str
    stage: str  # the link of the chain where it was found
    explanation: str
    part_number: str | None = None
    expected: str | None = None
    found: str | None = None

    @property
    def severity(self) -> str:
        return SEVERITY[self.code]

    @property
    def fingerprint(self) -> str:
        """Stable across runs, so a problem found again keeps its status and note."""
        key = f"{self.code}:{self.stage}:{self.part_number or '-'}"
        return f"{key}:{self.found}" if self.code == "DUPLICATE_SERIAL" else key


def money(x: Decimal) -> str:
    return f"{x:,.2f}"


def _r2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# ---------------------------------------------------------------- customer PO


def check_customer_po(b: OrderBundle) -> list[Finding]:
    po = b.customer_po
    out: list[Finding] = []
    lines_sum = _r2(sum((Decimal(x.qty) * x.unit_price for x in po.lines), Decimal(0)))
    if po.subtotal is not None and abs(po.subtotal - lines_sum) > MONEY_TOLERANCE:
        out.append(
            Finding(
                "TOTAL_MATH",
                "po_received",
                f"The lines add up to {money(lines_sum)}, but the PO prints a subtotal of {money(po.subtotal)}.",
                expected=money(lines_sum),
                found=money(po.subtotal),
            )
        )
    base = po.subtotal if po.subtotal is not None else lines_sum
    if po.vat_amount is not None:
        vat = _r2(base * po.vat_rate)
        if abs(po.vat_amount - vat) > MONEY_TOLERANCE:
            out.append(
                Finding(
                    "VAT_MATH",
                    "po_received",
                    f"VAT at {po.vat_rate * 100:.0f}% of {money(base)} is {money(vat)}; the PO says "
                    f"{money(po.vat_amount)}.",
                    expected=money(vat),
                    found=money(po.vat_amount),
                )
            )
    if po.total is not None and po.vat_amount is not None:
        total = base + po.vat_amount
        if abs(po.total - total) > MONEY_TOLERANCE:
            out.append(
                Finding(
                    "TOTAL_MATH",
                    "po_received",
                    f"Subtotal {money(base)} plus VAT {money(po.vat_amount)} is {money(total)}; the PO "
                    f"total is {money(po.total)}.",
                    expected=money(total),
                    found=money(po.total),
                )
            )
    return out


# ---------------------------------------------------------------- matching two sets of lines


def _match(ours: list[Line], theirs: list[Line], hows=("part", "substitute", "description")):
    """Pair lines by part number, then a stated substitute ("replaces X"), then a similar description.
    Returns (pairs, only_ours, only_theirs); pairs carry how they were matched."""
    pairs = []
    left = list(ours)
    right = list(theirs)
    for how in hows:
        for o in list(left):
            for t in right:
                if (
                    (how == "part" and t.part_number == o.part_number)
                    or (how == "substitute" and t.substitutes_part == o.part_number)
                    or (
                        how == "description"
                        and t.part_number != o.part_number
                        and o.description
                        and t.description
                        and fuzz.token_set_ratio(o.description, t.description) >= SIMILAR_DESCRIPTION
                    )
                ):
                    pairs.append((o, t, how))
                    left.remove(o)
                    right.remove(t)
                    break
    return pairs, left, right


# ---------------------------------------------------------------- our PO against the customer's


def check_our_po(b: OrderBundle) -> list[Finding]:
    if not b.our_po:
        return []
    out = []
    # We wrote our PO ourselves, so only an exact part number counts as the same item; a similar-sounding
    # server is exactly the mistake worth catching here.
    pairs, cust_only, ours_only = _match(b.customer_po.lines, b.our_po.lines, hows=("part",))
    for c, o, _how in pairs:
        if o.qty < c.qty:
            out.append(
                Finding(
                    "QTY_SHORT",
                    "po_sent",
                    f"The customer ordered {c.qty} {c.part_number}; our PO to the distributor asks for {o.qty}.",
                    c.part_number,
                    str(c.qty),
                    str(o.qty),
                )
            )
        elif o.qty > c.qty:
            out.append(
                Finding(
                    "QTY_OVER",
                    "po_sent",
                    f"The customer ordered {c.qty} {c.part_number}; our PO asks for {o.qty}.",
                    c.part_number,
                    str(c.qty),
                    str(o.qty),
                )
            )
    # A customer line we ordered under a different part number: same line on both POs.
    by_line = {o.line_no: o for o in ours_only}
    for c in list(cust_only):
        o = by_line.get(c.line_no)
        if o is not None:
            out.append(
                Finding(
                    "PART_MISMATCH",
                    "po_sent",
                    f"Line {c.line_no}: the customer asked for {c.part_number}, our PO orders "
                    f"{o.part_number}.",
                    c.part_number,
                    c.part_number,
                    o.part_number,
                )
            )
            cust_only.remove(c)
            ours_only.remove(o)
    for c in cust_only:
        out.append(
            Finding(
                "MISSING_LINE",
                "po_sent",
                f"{c.part_number} is on the customer's PO but not on our PO to the distributor.",
                c.part_number,
                f"{c.qty} x {c.part_number}",
                "not ordered",
            )
        )
    for o in ours_only:
        out.append(
            Finding(
                "EXTRA_LINE",
                "po_sent",
                f"Our PO orders {o.qty} {o.part_number}, which the customer did not ask for.",
                o.part_number,
                "not on the customer PO",
                f"{o.qty} x {o.part_number}",
            )
        )
    return out


# ---------------------------------------------------------------- confirmation against our PO


def check_confirmations(b: OrderBundle) -> list[Finding]:
    if not b.our_po or not b.confirmations:
        return []
    out = []
    conf = b.confirmations[-1]  # the latest confirmation replaces earlier ones
    if conf.referenced_po.strip().upper() != b.our_po.our_po_number.upper():
        out.append(
            Finding(
                "PO_REF",
                "confirmed",
                f"The confirmation quotes {conf.referenced_po}, but this order went out as "
                f"{b.our_po.our_po_number}.",
                None,
                b.our_po.our_po_number,
                conf.referenced_po,
            )
        )
    pairs, ours_only, theirs_only = _match(b.our_po.lines, conf.lines)
    for o, t, how in pairs:
        part = o.part_number
        if how != "part":
            why = "says it replaces it" if how == "substitute" else "has a similar description"
            out.append(
                Finding(
                    "SUBSTITUTION",
                    "confirmed",
                    f"We ordered {part}; the distributor confirmed {t.part_number} instead (the confirmation "
                    f"{why}). The customer has to agree to the swap.",
                    part,
                    part,
                    t.part_number,
                )
            )
        if t.qty < o.qty:
            out.append(
                Finding(
                    "QTY_SHORT",
                    "confirmed",
                    f"Short {o.qty - t.qty}: we ordered {o.qty} {part}, the distributor confirmed {t.qty}.",
                    part,
                    str(o.qty),
                    str(t.qty),
                )
            )
        elif t.qty > o.qty:
            out.append(
                Finding(
                    "QTY_OVER",
                    "confirmed",
                    f"We ordered {o.qty} {part}; the distributor confirmed {t.qty}.",
                    part,
                    str(o.qty),
                    str(t.qty),
                )
            )
        if o.unit_price and abs(t.unit_price - o.unit_price) / o.unit_price > PRICE_TOLERANCE:
            change = (t.unit_price - o.unit_price) / o.unit_price * 100
            word = "up" if change > 0 else "down"
            out.append(
                Finding(
                    "PRICE_DIFF",
                    "confirmed",
                    f"Price {word} {abs(change):.0f}%: our PO says {money(o.unit_price)} each for {part}, "
                    f"the confirmation says {money(t.unit_price)}.",
                    part,
                    money(o.unit_price),
                    money(t.unit_price),
                )
            )
    for o in ours_only:
        out.append(
            Finding(
                "MISSING_LINE",
                "confirmed",
                f"The confirmation leaves out {o.qty} {o.part_number} that we ordered.",
                o.part_number,
                f"{o.qty} x {o.part_number}",
                "not confirmed",
            )
        )
    for t in theirs_only:
        out.append(
            Finding(
                "EXTRA_LINE",
                "confirmed",
                f"The confirmation adds {t.qty} {t.part_number}, which is not on our PO.",
                t.part_number,
                "not ordered",
                f"{t.qty} x {t.part_number}",
            )
        )
    required = b.customer_po.required_by
    if conf.eta and required and conf.eta > required:
        days = (conf.eta - required).days
        out.append(
            Finding(
                "ETA_LATE",
                "confirmed",
                f"The distributor expects delivery on {conf.eta:%d %b %Y}, {_plural(days, 'day')} after the "
                f"customer needs it ({required:%d %b %Y}).",
                None,
                f"{required:%d %b %Y}",
                f"{conf.eta:%d %b %Y}",
            )
        )
    return out


# ---------------------------------------------------------------- goods received and delivered


def _expected_inbound(b: OrderBundle) -> dict[str, int]:
    expected: Counter = Counter()
    if b.confirmations:
        conf = b.confirmations[-1]
        ordered = {x.part_number for x in b.our_po.lines} if b.our_po else set()
        for x in conf.lines:
            if x.part_number in ordered or x.substitutes_part:
                expected[x.part_number] += x.qty
    elif b.our_po:
        for x in b.our_po.lines:
            expected[x.part_number] += x.qty
    return dict(expected)


def check_inbound(b: OrderBundle) -> list[Finding]:
    inbound = [s for s in b.shipments if s.direction == "inbound" and s.received]
    if not inbound:
        return []
    out = []
    expected = _expected_inbound(b)
    received: Counter = Counter()
    for s in inbound:
        for sl in s.lines:
            received[sl.part_number] += sl.qty
    partial = any(s.marked_partial for s in inbound)
    for part, want in expected.items():
        got = received.get(part, 0)
        if got < want and partial:
            out.append(
                Finding(
                    "PARTIAL_SHIPMENT",
                    "received",
                    f"Part delivery: {got} of {want} {part} arrived; the distributor says the balance will follow.",
                    part,
                    str(want),
                    str(got),
                )
            )
        elif got < want:
            out.append(
                Finding(
                    "QTY_SHORT",
                    "received",
                    f"Short {want - got}: {want} {part} were confirmed, {got} arrived.",
                    part,
                    str(want),
                    str(got),
                )
            )
        elif got > want:
            out.append(
                Finding(
                    "QTY_OVER",
                    "received",
                    f"{got} {part} arrived, {want} were confirmed.",
                    part,
                    str(want),
                    str(got),
                )
            )
    for part in sorted(received.keys() - expected.keys()):
        out.append(
            Finding(
                "EXTRA_LINE",
                "received",
                f"{received[part]} {part} arrived, which was not expected on this order.",
                part,
                "not expected",
                f"{received[part]} x {part}",
            )
        )
    seen_here: Counter = Counter()
    for s in inbound:
        for sl in s.lines:
            if sl.part_number in b.serialised_parts and len(sl.serials) != sl.qty:
                out.append(
                    Finding(
                        "SERIAL_COUNT",
                        "received",
                        f"{s.reference} lists {sl.qty} {sl.part_number} but {_plural(len(sl.serials), 'serial number')}.",
                        sl.part_number,
                        str(sl.qty),
                        str(len(sl.serials)),
                    )
                )
            seen_here.update(sl.serials)
    for s in inbound:
        for sl in s.lines:
            for serial in sl.serials:
                where = b.serials_seen_elsewhere.get(serial)
                if where or seen_here[serial] > 1:
                    place = f"already booked in on {where}" if where else "listed twice on this order"
                    out.append(
                        Finding(
                            "DUPLICATE_SERIAL",
                            "received",
                            f"Serial {serial} ({sl.part_number}) is {place}. One unit cannot arrive twice.",
                            sl.part_number,
                            "a new serial",
                            serial,
                        )
                    )
    return out


def check_outbound(b: OrderBundle) -> list[Finding]:
    outbound = [s for s in b.shipments if s.direction == "outbound" and s.received]
    if not outbound:
        return []
    delivered: Counter = Counter()
    subs = {
        f.found: f.expected
        for f in check_confirmations(b)
        if f.code == "SUBSTITUTION" and b.approved_substitutions.get(f.found) == f.expected
    }
    for s in outbound:
        for sl in s.lines:
            delivered[subs.get(sl.part_number, sl.part_number)] += sl.qty
    out = []
    for c in b.customer_po.lines:
        got = delivered.get(c.part_number, 0)
        if got < c.qty:
            out.append(
                Finding(
                    "QTY_SHORT",
                    "delivered",
                    f"The customer ordered {c.qty} {c.part_number}; {got} were delivered.",
                    c.part_number,
                    str(c.qty),
                    str(got),
                )
            )
    return out


def check(b: OrderBundle) -> list[Finding]:
    findings = (
        check_customer_po(b) + check_our_po(b) + check_confirmations(b) + check_inbound(b) + check_outbound(b)
    )
    unique: dict[str, Finding] = {}
    for f in findings:
        unique.setdefault(f.fingerprint, f)  # one finding per problem, even if two rules see it
    return list(unique.values())
