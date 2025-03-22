"""What a person confirms on the intake screen, validated before anything is written."""

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PART = re.compile(r"^[A-Z0-9][A-Z0-9.\-/]{3,39}$")
SERIAL = re.compile(r"^[A-Z0-9]{5,30}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _part(v: str) -> str:
    v = v.upper()
    if not PART.match(v):
        raise ValueError(f"{v!r} does not look like a part number")
    return v


class PriceLine(Strict):
    part_number: str
    description: str = Field(default="", max_length=300)
    qty: int = Field(gt=0, le=100000)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    substitutes_part: str | None = None

    _p = field_validator("part_number")(_part)

    @field_validator("substitutes_part")
    @classmethod
    def _sub(cls, v):
        return _part(v) if v else None


class GoodsLine(Strict):
    part_number: str
    qty: int = Field(gt=0, le=100000)
    serials: list[str] = Field(default_factory=list, max_length=500)

    _p = field_validator("part_number")(_part)

    @field_validator("serials")
    @classmethod
    def _serials(cls, v):
        out = [s.strip().upper() for s in v if s.strip()]
        bad = [s for s in out if not SERIAL.match(s)]
        if bad:
            raise ValueError(f"not serial numbers: {', '.join(bad[:3])}")
        return out


class CustomerPOIn(Strict):
    kind: Literal["customer_po"]
    customer_id: int
    po_number: str = Field(min_length=3, max_length=60)
    po_date: date
    required_by: date | None = None
    subtotal: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    vat_amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    total: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    lines: list[PriceLine] = Field(min_length=1, max_length=200)


class ConfirmationIn(Strict):
    kind: Literal["vendor_confirmation"]
    order_id: int
    confirmation_no: str = Field(min_length=3, max_length=60)
    referenced_po: str = Field(min_length=3, max_length=60)
    eta: date | None = None
    lines: list[PriceLine] = Field(min_length=1, max_length=200)


class GoodsInIn(Strict):
    kind: Literal["delivery_note", "shipment_email"]
    order_id: int
    delivery_note_no: str = Field(min_length=3, max_length=60)
    tracking_number: str | None = Field(default=None, max_length=40)
    marked_partial: bool = False
    lines: list[GoodsLine] = Field(min_length=1, max_length=200)


CONFIRM_MODELS = {
    "customer_po": CustomerPOIn,
    "vendor_confirmation": ConfirmationIn,
    "delivery_note": GoodsInIn,
    "shipment_email": GoodsInIn,
}
