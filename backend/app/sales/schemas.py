from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator

from app.common import currency as cur


class SalesLineIn(BaseModel):
    item_id: str | None = None
    item_code: str | None = None
    description: str | None = None
    uom: str | None = None
    hs_code: str | None = None
    lot_number: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    currency: str | None = None
    discount_percent: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")

    @field_validator("currency")
    @classmethod
    def _code(cls, value: str | None) -> str | None:
        # The form lets a currency be typed as its symbol; the column holds
        # the ISO code so amounts can still be grouped and totalled.
        return cur.normalise(value) if value else None


class SalesDocumentIn(BaseModel):
    """Note the absence of any total field: the server computes them all."""
    doc_date: date
    customer_id: str
    status: str = "Draft"
    remarks: str | None = None
    demand_number: str | None = None
    customer_po_number: str | None = None
    dc_number: str | None = None
    delivery_person: str | None = None
    vehicle_number: str | None = None
    location: str | None = None
    with_sales_tax: bool = True
    is_service: bool = False
    currency: str = "PKR"
    exchange_rate: Decimal | None = None
    payment_terms: str | None = None
    payment_status: str | None = None
    payment_reference: str | None = None
    freight_amount: Decimal = Decimal("0")
    document_discount: Decimal = Decimal("0")
    # Set when a sales order is being raised from an approved quotation: the
    # order records where it came from, and that quotation is then closed.
    source_document_id: str | None = None
    lines: list[SalesLineIn]

    @field_validator("currency")
    @classmethod
    def _code(cls, value: str) -> str:
        return cur.normalise(value)


class StatusChangeIn(BaseModel):
    status: str


class ConvertIn(BaseModel):
    doc_date: date | None = None
    customer_po_number: str | None = None
    delivery_person: str | None = None
    vehicle_number: str | None = None
    location: str | None = None
