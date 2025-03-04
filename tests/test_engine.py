"""Every rule of the check engine, with a case that must pass quietly and a case that must be caught."""

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from backend.check.engine import check
from backend.check.model import Confirmation, CustomerPO, Line, OrderBundle, OurPO, Shipment, ShipmentLine

SERVER = Line(1, "PER760-XS2", "PowerEdge R760 2U server", 4, D("42000.00"))
LICENCE = Line(2, "VVF-CORE-1Y", "VMware vSphere Foundation, per core", 64, D("620.00"))


def clean() -> OrderBundle:
    """A correct order, delivered: the engine must find nothing."""
    sub = 4 * D("42000.00") + 64 * D("620.00")
    po = CustomerPO(
        "GOV/PROC/2026/0001",
        date(2026, 10, 1),
        [SERVER, LICENCE],
        required_by=date(2026, 10, 30),
        subtotal=sub,
        vat_amount=(sub * D("0.05")).quantize(D("0.01")),
        total=sub + (sub * D("0.05")).quantize(D("0.01")),
    )
    ours = OurPO(
        "PO-2026-0101", [replace(SERVER, unit_price=D("36000.00")), replace(LICENCE, unit_price=D("540.00"))]
    )
    conf = Confirmation("FVD-SOC-100001", "PO-2026-0101", list(ours.lines), eta=date(2026, 10, 20))
    inbound = Shipment(
        "inbound",
        "DN-FVD-10001",
        [
            ShipmentLine("PER760-XS2", 4, ["7AAAA01", "7AAAA02", "7AAAA03", "7AAAA04"]),
            ShipmentLine("VVF-CORE-1Y", 64),
        ],
    )
    outbound = Shipment("outbound", "DO-1", [ShipmentLine("PER760-XS2", 4), ShipmentLine("VVF-CORE-1Y", 64)])
    return OrderBundle(po, ours, [conf], [inbound, outbound], serialised_parts=frozenset({"PER760-XS2"}))


def codes(b: OrderBundle) -> list[tuple[str, str | None]]:
    return sorted((f.code, f.part_number) for f in check(b))


def test_a_correct_order_has_no_findings():
    assert codes(clean()) == []


def test_pennies_of_rounding_are_not_a_problem():
    b = clean()
    b.customer_po.vat_amount += D("0.03")
    b.customer_po.total += D("0.03")
    assert codes(b) == []


def test_vat_math():
    b = clean()
    b.customer_po.vat_amount *= 10
    b.customer_po.total = b.customer_po.subtotal + b.customer_po.vat_amount
    assert codes(b) == [("VAT_MATH", None)]


def test_total_math():
    b = clean()
    b.customer_po.total += 1000
    assert codes(b) == [("TOTAL_MATH", None)]


def test_part_mismatch_on_our_po():
    b = clean()
    b.our_po.lines[0] = replace(
        b.our_po.lines[0], part_number="PER660-XS1", description="PowerEdge R660 1U server"
    )
    # the confirmation and goods follow our (wrong) PO, so only the root cause is reported
    b.confirmations[0].lines[0] = b.our_po.lines[0]
    b.shipments[0].lines[0].part_number = "PER660-XS1"
    found = codes(b)
    assert ("PART_MISMATCH", "PER760-XS2") in found


def test_confirmed_short_and_over():
    b = clean()
    b.confirmations[0].lines[0] = replace(b.confirmations[0].lines[0], qty=3)
    b.shipments = []
    assert codes(b) == [("QTY_SHORT", "PER760-XS2")]
    b.confirmations[0].lines[0] = replace(b.confirmations[0].lines[0], qty=5)
    assert codes(b) == [("QTY_OVER", "PER760-XS2")]


def test_price_change_beyond_one_percent():
    b = clean()
    b.shipments = []
    b.confirmations[0].lines[1] = replace(b.confirmations[0].lines[1], unit_price=D("544.00"))  # +0.7%
    assert codes(b) == []
    b.confirmations[0].lines[1] = replace(b.confirmations[0].lines[1], unit_price=D("600.00"))  # +11%
    [f] = check(b)
    assert f.code == "PRICE_DIFF" and "up 11%" in f.explanation


def test_substitution_stated_on_the_confirmation():
    b = clean()
    b.shipments = []
    b.confirmations[0].lines[0] = replace(
        b.confirmations[0].lines[0], part_number="PER770-XS2", substitutes_part="PER760-XS2"
    )
    assert codes(b) == [("SUBSTITUTION", "PER760-XS2")]


def test_substitution_spotted_by_description():
    b = clean()
    b.shipments = []
    b.confirmations[0].lines[0] = replace(
        b.confirmations[0].lines[0],
        part_number="PER760-XS3",
        description="PowerEdge R760 2U server (refresh)",
    )
    assert codes(b) == [("SUBSTITUTION", "PER760-XS2")]


def test_missing_and_extra_lines_on_the_confirmation():
    b = clean()
    b.shipments = []
    gone = b.confirmations[0].lines.pop(1)
    assert codes(b) == [("MISSING_LINE", gone.part_number)]
    b.confirmations[0].lines.append(Line(3, "SFP28-SR-25G", "SFP28 transceiver", 8, D("552.00")))
    b.confirmations[0].lines.append(gone)
    assert codes(b) == [("EXTRA_LINE", "SFP28-SR-25G")]


def test_confirmation_quoting_another_po():
    b = clean()
    b.confirmations[0].referenced_po = "PO-2026-0199"
    assert codes(b) == [("PO_REF", None)]


def test_eta_after_the_customer_needs_it():
    b = clean()
    b.confirmations[0].eta = date(2026, 11, 5)
    [f] = check(b)
    assert f.code == "ETA_LATE" and "6 days after" in f.explanation


def test_goods_in_short_versus_part_delivery():
    b = clean()
    b.shipments = [b.shipments[0]]  # goods in, not yet delivered on
    b.shipments[0].lines[1] = ShipmentLine("VVF-CORE-1Y", 60)
    assert codes(b) == [("QTY_SHORT", "VVF-CORE-1Y")]
    # The same shortfall on a delivery note that says "balance to follow" is a note, not a problem.
    b.shipments[0].marked_partial = True
    assert codes(b) == [("PARTIAL_SHIPMENT", "VVF-CORE-1Y")]
    assert check(b)[0].severity == "info"


def test_serial_count_and_duplicates():
    b = clean()
    b.shipments[0].lines[0].serials.pop()
    assert codes(b) == [("SERIAL_COUNT", "PER760-XS2")]
    b = clean()
    b.serials_seen_elsewhere = {"7AAAA02": "DN-DCP-20001"}
    [f] = check(b)
    assert f.code == "DUPLICATE_SERIAL" and "7AAAA02" in f.explanation and "DN-DCP-20001" in f.explanation


def test_same_serial_twice_on_one_delivery():
    b = clean()
    b.shipments[0].lines[0].serials[1] = "7AAAA01"
    assert ("DUPLICATE_SERIAL", "PER760-XS2") in codes(b)


def test_delivered_short_to_the_customer():
    b = clean()
    b.shipments[1].lines[0] = ShipmentLine("PER760-XS2", 3)
    assert codes(b) == [("QTY_SHORT", "PER760-XS2")]
    assert check(b)[0].stage == "delivered"


@pytest.mark.parametrize("code", ["QTY_SHORT", "PRICE_DIFF"])
def test_fingerprints_are_stable(code):
    b = clean()
    b.shipments = []
    if code == "QTY_SHORT":
        b.confirmations[0].lines[0] = replace(b.confirmations[0].lines[0], qty=3)
    else:
        b.confirmations[0].lines[0] = replace(b.confirmations[0].lines[0], unit_price=D("40000.00"))
    assert (
        [f.fingerprint for f in check(b)]
        == [f.fingerprint for f in check(b)]
        == [f"{code}:confirmed:PER760-XS2"]
    )


def test_explanations_are_plain_sentences_without_em_dashes():
    b = clean()
    b.customer_po.total += 1000
    b.confirmations[0].referenced_po = "PO-2026-0199"
    b.confirmations[0].eta = date(2026, 11, 5)
    for f in check(b):
        assert f.explanation.endswith(".") and "—" not in f.explanation
