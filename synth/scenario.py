"""Build a believable set of orders, each at a stage of the chain, with known problems planted in some.

Everything is decided by one seeded random generator, so the same seed gives the same orders, documents
and ground truth every time. The ground truth (what was planted where) is what the evaluation scores
the extractor and the check engine against.
"""

import random
import string
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from backend.check.model import Confirmation, CustomerPO, Line, OurPO, Shipment, ShipmentLine
from synth.catalogue import (
    CARRIERS,
    CUSTOMERS,
    DISTRIBUTORS,
    PRODUCT_BY_PART,
    SECTOR_BASKETS,
    SUBSTITUTES,
    TRACKING_FORMATS,
    Party,
)

STAGES = ["po_received", "po_sent", "confirmed", "received", "delivered", "ready_to_invoice"]
STAGE_COUNTS = {
    "po_received": 6,
    "po_sent": 7,
    "confirmed": 9,
    "received": 7,
    "delivered": 6,
    "ready_to_invoice": 7,
}

# Problems that can be planted, the earliest stage the order must have reached for them to exist,
# and whether they stop the goods count from completing (those keep the order where it is).
PROBLEMS = {
    "VAT_MATH": ("po_received", False),
    "TOTAL_MATH": ("po_received", False),
    "PART_MISMATCH": ("po_sent", False),
    "QTY_SHORT": ("confirmed", True),
    "PRICE_DIFF": ("confirmed", False),
    "SUBSTITUTION": ("confirmed", False),
    "MISSING_LINE": ("confirmed", True),
    "EXTRA_LINE": ("confirmed", False),
    "PO_REF": ("confirmed", False),
    "ETA_LATE": ("confirmed", False),
    "RECEIPT_SHORT": ("confirmed", True),  # goods arrived short, so the order is still open at "confirmed"
    "QTY_OVER": ("received", False),
    "SERIAL_COUNT": ("received", False),
    "DUPLICATE_SERIAL": ("received", False),
    "PARTIAL_SHIPMENT": ("confirmed", True),
}
# What the engine should report for each planted problem.
EXPECTED_CODE = {k: ("QTY_SHORT" if k == "RECEIPT_SHORT" else k) for k in PROBLEMS}

CUSTOMER_LAYOUT = {
    "government": "L1",
    "bank": "L2",
    "education": "L3",
    "healthcare": "L4",
    "enterprise": "L4",
}
CONFIRMATION_LAYOUT = {"FVD": "A", "CTS": "A", "DCP": "B"}
SERIAL_CHARS = "".join(c for c in string.ascii_uppercase + string.digits if c not in "IO01")
TODAY = date(2026, 10, 21)  # the documents are dated relative to this; the seed shifts times to "now"


@dataclass
class Planted:
    kind: str  # key of PROBLEMS
    code: str  # code the engine should report
    part_number: str | None


@dataclass
class SynthOrder:
    key: str
    customer: Party
    distributor: Party
    carrier: Party
    stage: str
    customer_layout: str
    confirmation_layout: str
    days_ago: dict[str, int]  # stage name -> days before TODAY it happened
    customer_po: CustomerPO
    true_lines: list[Line]  # what the customer really ordered (before any printing error)
    our_po: OurPO | None = None
    confirmation: Confirmation | None = None
    inbound: list[Shipment] = field(default_factory=list)
    outbound: list[Shipment] = field(default_factory=list)
    tracking: dict[str, str] = field(default_factory=dict)  # shipment reference -> tracking number
    planted: list[Planted] = field(default_factory=list)
    contact: str = ""
    deliver_to: str = ""


def money(x) -> Decimal:
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _qty_for(rng: random.Random, category: str) -> int:
    return {
        "server": rng.randint(1, 4),
        "storage": rng.randint(1, 2),
        "backup": 1,
        "network": rng.choice([2, 4, 8, 12, 16, 24]),
        "endpoint": rng.choice([5, 10, 12, 20, 25, 40, 60]),
        "software": rng.choice([25, 50, 64, 100, 150, 250]),
        "security": rng.choice([1, 2, 50, 100, 200, 300]),
        "service": rng.randint(1, 6),
    }[category]


def _serial(rng: random.Random, prefix: str) -> str:
    return prefix + "".join(rng.choice(SERIAL_CHARS) for _ in range(7 - len(prefix)))


def _tracking(rng: random.Random, carrier: Party) -> str:
    fmt = TRACKING_FORMATS[carrier.short_code]
    for n in (10, 9, 8):
        fmt = fmt.replace(f"{{d{n}}}", "".join(rng.choice(string.digits) for _ in range(n)))
    return fmt


def _customer_po_number(rng: random.Random, customer: Party, year: int) -> str:
    n = rng.randint(100, 9999)
    return {
        "government": f"{customer.short_code}/PROC/{year}/{n:04d}",
        "bank": f"{customer.short_code}-PO-{rng.randint(100000, 999999)}",
        "education": f"{customer.short_code}-{year % 100}-{n:04d}",
        "healthcare": f"{customer.short_code}/IT/PO/{n:04d}",
        "enterprise": f"{customer.short_code}45{rng.randint(10000000, 99999999)}",
    }[customer.sector]


def _confirmation_number(rng: random.Random, distributor: Party) -> str:
    return {
        "FVD": f"FVD-SOC-{rng.randint(100000, 999999)}",
        "DCP": f"DCP/OC/26/{rng.randint(1000, 9999)}",
        "CTS": f"CTS-CONF-{rng.randint(10000, 99999)}",
    }[distributor.short_code]


def problem_fits(kind: str, stage: str) -> bool:
    """Could this problem exist on an order at this stage? (Never one it could not have reached yet.)"""
    first, blocks = PROBLEMS[kind]
    if STAGES.index(first) > STAGES.index(stage):
        return False
    if blocks:  # a shortfall keeps the order open, so it only fits an order still waiting at "confirmed"
        return stage == "confirmed"
    if stage == "confirmed":  # nothing has arrived yet (shortfalls above are the exception)
        return first != "received"
    return True


def plan_problems(rng: random.Random, stages: list[str], per_code: int = 2) -> list[list[str]]:
    """Decide up front which orders carry which problems, so every problem type appears `per_code` times
    and the evaluation has something to find for each. About a third of orders stay clean."""
    plan: list[list[str]] = [[] for _ in stages]
    order_ids = list(range(len(stages)))
    for kind in PROBLEMS:
        fits = [i for i in order_ids if problem_fits(kind, stages[i]) and len(plan[i]) < 2]
        # Prefer orders that have no problem yet, so problems spread out.
        fits.sort(key=lambda i: (len(plan[i]), rng.random()))
        for i in fits[:per_code]:
            plan[i].append(kind)
    # Line-level confirmation problems on the same order read as noise: keep one of them.
    line_level = {"QTY_SHORT", "PRICE_DIFF", "SUBSTITUTION", "MISSING_LINE"}
    for picks in plan:
        clash = [k for k in picks if k in line_level]
        for k in clash[1:]:
            picks.remove(k)
    return plan


def build(seed: int = 2027) -> list[SynthOrder]:
    rng = random.Random(seed)
    stages = [s for s, n in STAGE_COUNTS.items() for _ in range(n)]
    rng.shuffle(stages)
    problem_plan = plan_problems(rng, stages)
    orders: list[SynthOrder] = []
    serial_pool: list[tuple[str, str]] = []  # (serial, order key) of every unit booked in so far
    our_po_counter = 101

    for i, stage in enumerate(stages, start=1):
        customer = rng.choice(CUSTOMERS)
        distributor = rng.choice(DISTRIBUTORS)
        carrier = rng.choice(CARRIERS)
        reached = STAGES.index(stage)

        # Timeline: older orders are further along. Days between steps vary like real life.
        gaps = [
            rng.randint(0, 2),
            rng.randint(1, 4),
            rng.randint(3, 12),
            rng.randint(1, 4),
            rng.randint(1, 5),
        ]
        waiting = rng.randint(0, 6)
        total_age = waiting + sum(gaps[:reached])
        days_ago = {"po_received": total_age}
        cursor = total_age
        for step in range(1, reached + 1):
            cursor -= gaps[step - 1]
            days_ago[STAGES[step]] = cursor

        po_date = TODAY - timedelta(days=total_age + rng.randint(0, 2))
        required_by = po_date + timedelta(days=rng.choice([21, 28, 30, 45]))

        problems = problem_plan[i - 1]
        basket = SECTOR_BASKETS[customer.sector]
        parts = rng.sample(basket, k=rng.randint(1, min(5, len(basket))))
        # Shape the order so its planned problem can exist: a part the distributor can swap, two lines to
        # drop one from, or a serialised item to miscount.
        if "SUBSTITUTION" in problems and not any(p in SUBSTITUTES for p in parts):
            parts[0] = rng.choice([p for p in basket if p in SUBSTITUTES] or list(SUBSTITUTES))
        if "MISSING_LINE" in problems and len(parts) < 2:
            parts.append(rng.choice([p for p in basket if p not in parts]))
        needs_units = {"SERIAL_COUNT", "DUPLICATE_SERIAL", "PARTIAL_SHIPMENT", "RECEIPT_SHORT", "QTY_SHORT"}
        if needs_units & set(problems) and not any(PRODUCT_BY_PART[p].serialised for p in parts):
            parts[0] = rng.choice([p for p in basket if PRODUCT_BY_PART[p].serialised])
        parts = list(dict.fromkeys(parts))
        true_lines = []
        for n, part in enumerate(parts, start=1):
            prod = PRODUCT_BY_PART[part]
            price = money(prod.list_price * Decimal(str(round(rng.uniform(0.86, 0.98), 3))))
            price = money((price / 5).to_integral_value() * 5)  # quotes are rounded to the nearest 5
            qty = (
                rng.randint(1, 6) if part == "RSA-SID-700-50" else _qty_for(rng, prod.category)
            )  # sold in packs
            if prod.serialised and needs_units & set(problems):
                qty = max(qty, 2)
            true_lines.append(Line(n, part, prod.description, qty, price))
        subtotal = money(sum(line.qty * line.unit_price for line in true_lines))
        vat = money(subtotal * Decimal("0.05"))
        total = subtotal + vat
        planted: list[Planted] = []
        if "VAT_MATH" in problems:
            vat = money(subtotal * Decimal("0.5"))  # a classic: 50% instead of 5%
            total = subtotal + vat
            planted.append(Planted("VAT_MATH", "VAT_MATH", None))
        if "TOTAL_MATH" in problems:
            total = total + Decimal(rng.choice([100, 1000, -500]))
            planted.append(Planted("TOTAL_MATH", "TOTAL_MATH", None))

        order = SynthOrder(
            key=f"O{i:02d}",
            customer=customer,
            distributor=distributor,
            carrier=carrier,
            stage=stage,
            customer_layout=CUSTOMER_LAYOUT[customer.sector],
            confirmation_layout=CONFIRMATION_LAYOUT[distributor.short_code],
            days_ago=days_ago,
            customer_po=CustomerPO(
                po_number=_customer_po_number(rng, customer, po_date.year),
                po_date=po_date,
                required_by=required_by,
                lines=list(true_lines),
                subtotal=subtotal,
                vat_amount=vat,
                total=total,
            ),
            true_lines=true_lines,
            planted=planted,
            contact=rng.choice(
                [
                    "Hessa Al Mazrouei",
                    "Rahul Menon",
                    "Fatima Khoury",
                    "Omar Haddad",
                    "Priya Nair",
                    "Yousef Al Ali",
                    "Grace Thomas",
                    "Khalid Rashed",
                ]
            ),
            deliver_to=f"{customer.name}, {customer.address}, {customer.emirate}",
        )

        if reached >= 1:
            our_lines = [
                Line(
                    x.line_no,
                    x.part_number,
                    x.description,
                    x.qty,
                    money(x.unit_price * Decimal(str(round(rng.uniform(0.80, 0.90), 3)))),
                )
                for x in true_lines
            ]
            if "PART_MISMATCH" in problems:
                j = rng.randrange(len(our_lines))
                wrong = rng.choice([p for p in basket if p not in parts] or [our_lines[j].part_number + "-B"])
                prod = PRODUCT_BY_PART.get(wrong)
                our_lines[j] = Line(
                    our_lines[j].line_no,
                    wrong,
                    prod.description if prod else our_lines[j].description,
                    our_lines[j].qty,
                    our_lines[j].unit_price,
                )
                planted.append(Planted("PART_MISMATCH", "PART_MISMATCH", true_lines[j].part_number))
            order.our_po = OurPO(f"PO-2026-{our_po_counter:04d}", our_lines)
            our_po_counter += 1

        if reached >= 2:
            conf_lines = [
                Line(x.line_no, x.part_number, x.description, x.qty, x.unit_price) for x in order.our_po.lines
            ]
            eta = TODAY - timedelta(days=days_ago["confirmed"]) + timedelta(days=rng.randint(3, 10))
            if eta > required_by and "ETA_LATE" not in problems:
                eta = required_by - timedelta(days=rng.randint(1, 5))
            referenced = order.our_po.our_po_number
            # Line-level problems land on a line with more than one unit where possible (shortfalls need it).
            multi = [k for k, x in enumerate(conf_lines) if x.qty > 1]
            j = rng.choice(multi) if multi else rng.randrange(len(conf_lines))
            target = conf_lines[j]
            if "QTY_SHORT" in problems and target.qty > 1:
                conf_lines[j] = Line(
                    target.line_no,
                    target.part_number,
                    target.description,
                    max(1, target.qty - rng.randint(1, max(1, target.qty // 2))),
                    target.unit_price,
                )
                planted.append(Planted("QTY_SHORT", "QTY_SHORT", target.part_number))
            if "PRICE_DIFF" in problems:
                conf_lines[j] = Line(
                    target.line_no,
                    target.part_number,
                    target.description,
                    conf_lines[j].qty,
                    money(target.unit_price * Decimal(rng.choice(["1.06", "1.12", "1.18"]))),
                )
                planted.append(Planted("PRICE_DIFF", "PRICE_DIFF", target.part_number))
            if "SUBSTITUTION" in problems:
                subs = [k for k, x in enumerate(conf_lines) if x.part_number in SUBSTITUTES]
                if subs:
                    k = subs[0]
                    old = conf_lines[k]
                    new_part = SUBSTITUTES[old.part_number]
                    conf_lines[k] = Line(
                        old.line_no,
                        new_part,
                        PRODUCT_BY_PART[new_part].description,
                        old.qty,
                        old.unit_price,
                        substitutes_part=old.part_number,
                    )
                    planted.append(Planted("SUBSTITUTION", "SUBSTITUTION", old.part_number))
            if "MISSING_LINE" in problems and len(conf_lines) > 1:
                gone = conf_lines.pop(j)
                conf_lines = [
                    Line(n, x.part_number, x.description, x.qty, x.unit_price, x.substitutes_part)
                    for n, x in enumerate(conf_lines, start=1)
                ]
                planted.append(Planted("MISSING_LINE", "MISSING_LINE", gone.part_number))
            if "EXTRA_LINE" in problems:
                extra = rng.choice(["PS-PRO-3Y-NBD", "SFP28-SR-25G", "WD22TB4-DK"])
                if extra not in {x.part_number for x in conf_lines}:
                    prod = PRODUCT_BY_PART[extra]
                    conf_lines.append(
                        Line(
                            len(conf_lines) + 1,
                            extra,
                            prod.description,
                            rng.randint(1, 4),
                            money(prod.list_price * Decimal("0.8")),
                        )
                    )
                    planted.append(Planted("EXTRA_LINE", "EXTRA_LINE", extra))
            if "PO_REF" in problems:
                referenced = f"PO-2026-{our_po_counter + rng.randint(5, 40):04d}"
                planted.append(Planted("PO_REF", "PO_REF", None))
            if "ETA_LATE" in problems:
                eta = required_by + timedelta(days=rng.randint(3, 15))
                planted.append(Planted("ETA_LATE", "ETA_LATE", None))
            order.confirmation = Confirmation(
                _confirmation_number(rng, distributor), referenced, conf_lines, eta
            )

        # Inbound: what physically arrives from the distributor. Extra lines the distributor added are not shipped.
        ordered_parts = {x.part_number for x in order.our_po.lines} if order.our_po else set()
        if reached >= 3 or "PARTIAL_SHIPMENT" in problems or "RECEIPT_SHORT" in problems:
            ship_lines = []
            source = [
                x for x in order.confirmation.lines if x.part_number in ordered_parts or x.substitutes_part
            ]
            # Physical, serialised goods first: part deliveries and short receipts are about boxes.
            source.sort(key=lambda x: (not PRODUCT_BY_PART[x.part_number].serialised, x.line_no))
            partial = "PARTIAL_SHIPMENT" in problems
            for n, line in enumerate(source):
                qty = line.qty
                if partial and n == 0 and qty > 1:
                    qty = qty // 2
                elif partial and n > 0:
                    continue
                ship_lines.append(ShipmentLine(line.part_number, qty))
            if "RECEIPT_SHORT" in problems:
                cand = [x for x in ship_lines if x.qty > 1]
                if cand:
                    cand[0].qty -= 1
                    planted.append(Planted("RECEIPT_SHORT", "QTY_SHORT", cand[0].part_number))
            if "QTY_OVER" in problems:
                ship_lines[0].qty += rng.randint(1, 2)
                planted.append(Planted("QTY_OVER", "QTY_OVER", ship_lines[0].part_number))
            for sl in ship_lines:
                prod = PRODUCT_BY_PART[sl.part_number]
                if prod.serialised:
                    sl.serials = [_serial(rng, prod.serial_prefix) for _ in range(sl.qty)]
            if "SERIAL_COUNT" in problems:
                withs = [x for x in ship_lines if len(x.serials) > 1]
                if withs:
                    withs[0].serials.pop()
                    planted.append(Planted("SERIAL_COUNT", "SERIAL_COUNT", withs[0].part_number))
            if "DUPLICATE_SERIAL" in problems and serial_pool:
                withs = [x for x in ship_lines if x.serials]
                if withs:
                    dup, _owner = rng.choice(serial_pool)
                    withs[0].serials[-1] = dup
                    planted.append(Planted("DUPLICATE_SERIAL", "DUPLICATE_SERIAL", withs[0].part_number))
            if partial:
                # Every confirmed part that this part delivery leaves short is a part-delivery finding.
                shipped = {sl.part_number: sl.qty for sl in ship_lines}
                for line in source:
                    if shipped.get(line.part_number, 0) < line.qty:
                        planted.append(Planted("PARTIAL_SHIPMENT", "PARTIAL_SHIPMENT", line.part_number))
            dn = f"DN-{distributor.short_code}-{rng.randint(10000, 99999)}"
            order.inbound.append(Shipment("inbound", dn, ship_lines, received=True, marked_partial=partial))
            order.tracking[dn] = _tracking(rng, carrier)
            for sl in ship_lines:
                serial_pool.extend((s, order.key) for s in sl.serials)

        # Outbound: we deliver to the customer what the customer ordered.
        if reached >= 4:
            out_lines = []
            inbound_serials = {sl.part_number: list(sl.serials) for sl in order.inbound[0].lines}
            for x in true_lines:
                out_lines.append(
                    ShipmentLine(x.part_number, x.qty, inbound_serials.get(x.part_number, [])[: x.qty])
                )
            ref = f"DO-KDS-{rng.randint(20000, 29999)}"
            order.outbound.append(Shipment("outbound", ref, out_lines, received=True))

        orders.append(order)
    return orders


def planted_summary(orders: list[SynthOrder]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for o in orders:
        for p in o.planted:
            counts[p.code] = counts.get(p.code, 0) + 1
    return dict(sorted(counts.items()))
