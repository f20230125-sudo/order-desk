"""The order chain as plain data. The check engine reads these; the database, the extractor and the
synthetic generator all produce them. No database or Flask code in here, so the rules are easy to test.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Line:
    line_no: int
    part_number: str
    description: str
    qty: int
    unit_price: Decimal
    substitutes_part: str | None = None  # on a confirmation: this line replaces the ordered part


@dataclass
class CustomerPO:
    po_number: str
    po_date: date
    lines: list[Line]
    required_by: date | None = None
    currency: str = "AED"
    vat_rate: Decimal = Decimal("0.05")
    subtotal: Decimal | None = None  # as printed on the document; checked against the lines
    vat_amount: Decimal | None = None
    total: Decimal | None = None


@dataclass
class OurPO:
    our_po_number: str
    lines: list[Line]


@dataclass
class Confirmation:
    confirmation_no: str
    referenced_po: str
    lines: list[Line]
    eta: date | None = None


@dataclass
class ShipmentLine:
    part_number: str
    qty: int
    serials: list[str] = field(default_factory=list)


@dataclass
class Shipment:
    direction: str  # inbound (distributor -> us) or outbound (us -> customer)
    reference: str  # delivery note or tracking number, for the explanation text
    lines: list[ShipmentLine]
    received: bool = True  # booked in (inbound) or signed for (outbound)
    marked_partial: bool = False  # the delivery note itself says "part delivery, balance to follow"


@dataclass
class OrderBundle:
    customer_po: CustomerPO
    our_po: OurPO | None = None
    confirmations: list[Confirmation] = field(default_factory=list)
    shipments: list[Shipment] = field(default_factory=list)
    serialised_parts: frozenset[str] = frozenset()
    # serial -> where else it has been booked (another order or shipment), for duplicate detection
    serials_seen_elsewhere: dict[str, str] = field(default_factory=dict)
