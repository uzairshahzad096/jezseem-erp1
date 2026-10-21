from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class GatePassLineIn(BaseModel):
    item_id: str | None = None
    item_code: str | None = None
    description: str = Field(min_length=1)
    uom: str | None = None
    hs_code: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Decimal("0")
    remarks: str | None = None
    # Inward only: the outward pass line this item is returning against.
    reference_line_id: str | None = None


class GatePassIn(BaseModel):
    """A gate pass as entered on the form.

    No total fields: like every other document here, the server computes the
    money and the item count from the lines.
    """
    doc_date: date
    party_id: str | None = None
    vehicle_number: str | None = None
    driver: str | None = None
    issue_type: str | None = None
    issue_to: str | None = None
    location: str | None = None
    challan_number: str | None = None
    dc_number: str | None = None
    container_number: str | None = None
    po_number: str | None = None
    reference_number: str | None = None
    ntn: str | None = None
    gst_number: str | None = None
    currency: str = "PKR"
    payment_status: str | None = None
    payment_reference: str | None = None
    remarks: str | None = None
    expected_return_date: date | None = None
    # "Draft" saves it; "Approved" saves and sends the goods through the gate in one step.
    status: str = "Draft"

    # Inward passes settle an outward one; set from the picker on that screen.
    reference_gate_pass_id: str | None = None

    lines: list[GatePassLineIn]


class GatePassStatusIn(BaseModel):
    status: str
