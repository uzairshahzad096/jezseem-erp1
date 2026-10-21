"""Request shapes for procurement.

No total is accepted from the client anywhere in here: the server recomputes
every money figure from quantity, price, discount and tax. Currencies are
normalised to their ISO code on the way in, so a form may offer "$".
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.common import currency as cur

# ------------------------------------------------------------- in-house order


class InHouseOrderLineIn(BaseModel):
    id: str | None = None
    item_id: str | None = None
    item_code: str | None = None
    description: str | None = None
    uom: str | None = None
    requested_quantity: Decimal = Field(gt=0)
    approved_quantity: Decimal | None = None
    fulfilment_source: str | None = None
    required_date: date | None = None
    destination_warehouse_id: str | None = None
    remarks: str | None = None


class InHouseOrderIn(BaseModel):
    doc_date: date
    branch_id: str | None = None
    warehouse_id: str | None = None
    department: str | None = None
    requested_by: str | None = None
    required_date: date | None = None
    priority: str = "Normal"
    purpose: str | None = None
    source: str = "Manual"
    source_document_type: str | None = None
    source_document_id: str | None = None
    remarks: str | None = None
    status: str = "Draft"
    lines: list[InHouseOrderLineIn]


# ------------------------------------------------------------ purchase order

class _BlankIsUnset(BaseModel):
    """A box left empty on the form arrives as "" — treated as not filled in, so
    an empty Freight or date takes its default rather than failing the save."""

    @model_validator(mode="before")
    @classmethod
    def _drop_blanks(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not (isinstance(v, str) and not v.strip())}
        return data


class PurchaseOrderLineIn(_BlankIsUnset):
    id: str | None = None
    in_house_order_line_id: str | None = None
    item_id: str | None = None
    item_code: str | None = None
    description: str | None = None
    uom: str | None = None
    hs_code: str | None = None
    origin_country: str | None = None
    quantity: Decimal = Field(gt=0)
    free_quantity: Decimal = Decimal("0")
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    discount_percent: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")
    unit_weight: Decimal | None = None
    unit_volume: Decimal | None = None
    warehouse_id: str | None = None
    required_date: date | None = None
    remarks: str | None = None


class PurchaseOrderIn(_BlankIsUnset):
    doc_date: date
    purchase_type: str = "Local"
    supplier_id: str
    in_house_order_id: str | None = None
    branch_id: str | None = None
    warehouse_id: str | None = None

    purchaser: str | None = None
    purchaser_email: str | None = None
    contact_number: str | None = None
    status: str = "Draft"
    po_type: str | None = None
    expiry_date: date | None = None
    target_date: date | None = None
    expected_delivery_date: date | None = None
    priority: str = "Medium"
    purchase_category: str | None = None
    buyer_designation: str | None = None
    supplier_contact: str | None = None
    supplier_contact_designation: str | None = None
    ship_to_address: str | None = None
    bill_to_address: str | None = None
    incoterm_edition: str | None = None
    named_place: str | None = None
    partial_shipment: str | None = None
    transshipment: str | None = None
    packing_marks: str | None = None
    country_of_export: str | None = None
    payment_method: str | None = None
    balance_trigger: str | None = None
    bank_charges: str | None = None
    payment_reference: str | None = None
    goods_condition: str | None = None
    warranty_terms: str | None = None
    defect_remedy: str | None = None
    special_packing: str | None = None
    pre_shipment_inspection: str | None = None
    special_instructions: str | None = None
    packing_amount: Decimal = Decimal("0")
    insurance_amount: Decimal = Decimal("0")
    other_charges: Decimal = Decimal("0")
    advance_amount: Decimal = Decimal("0")
    advance_percent: Decimal = Decimal("0")
    payment_terms: str | None = None
    delivery_terms: str | None = None
    shipping_terms: str | None = None
    credit_days: int | None = None
    indent_number: str | None = None
    supplier_quotation_number: str | None = None
    supplier_quotation_date: date | None = None
    remarks: str | None = None

    currency: str = "PKR"
    exchange_rate: Decimal = Decimal("1")
    exchange_rate_date: date | None = None

    # Import block. Ignored on a local order rather than rejected, so
    # switching a draft from Import to Local does not fail on leftovers.
    supplier_country: str | None = None
    country_of_origin: str | None = None
    incoterm: str | None = None
    shipping_mode: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    expected_shipment_date: date | None = None
    expected_arrival_date: date | None = None
    commercial_invoice_number: str | None = None
    commercial_invoice_date: date | None = None
    packing_list_number: str | None = None
    bill_of_lading_number: str | None = None
    airway_bill_number: str | None = None
    container_number: str | None = None
    lc_number: str | None = None
    lc_date: date | None = None
    bank_name: str | None = None
    freight_forwarder: str | None = None
    clearing_agent: str | None = None
    insurance_provider: str | None = None
    customs_reference: str | None = None
    import_reference: str | None = None

    freight_amount: Decimal = Decimal("0")
    document_discount: Decimal = Decimal("0")
    lines: list[PurchaseOrderLineIn]

    @field_validator("currency")
    @classmethod
    def _code(cls, value: str) -> str:
        return cur.normalise(value)

    @field_validator("purchase_type")
    @classmethod
    def _type(cls, value: str) -> str:
        cleaned = (value or "Local").strip().title()
        if cleaned not in ("Local", "Import"):
            raise ValueError("Purchase type must be Local or Import.")
        return cleaned


class PurchaseOrderFromRequirementIn(BaseModel):
    """Raise an order from an approved requirement (spec section 10).

    Only the lines and quantities chosen are ordered, so one requirement can
    become a local order for what is available here and an import order for
    what is not.
    """

    purchase_type: str = "Local"
    supplier_id: str
    doc_date: date | None = None
    currency: str | None = None
    exchange_rate: Decimal | None = None
    warehouse_id: str | None = None
    remarks: str | None = None
    #: {"line_id": ..., "quantity": ..., "unit_price": ...}
    lines: list[dict]


# ---------------------------------------------------------- import shipment

class ImportShipmentLineIn(BaseModel):
    id: str | None = None
    purchase_order_line_id: str | None = None
    item_id: str | None = None
    item_code: str | None = None
    description: str | None = None
    uom: str | None = None
    hs_code: str | None = None
    shipped_quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Decimal("0")
    total_weight: Decimal | None = None
    total_volume: Decimal | None = None
    remarks: str | None = None


class ImportShipmentIn(BaseModel):
    doc_date: date
    purchase_order_id: str
    warehouse_id: str | None = None
    status: str = "Draft"
    transit_status: str = "Purchased"
    customs_status: str | None = None
    clearance_status: str | None = None

    currency: str = "USD"
    exchange_rate: Decimal = Decimal("1")
    exchange_rate_date: date | None = None

    container_number: str | None = None
    bill_of_lading_number: str | None = None
    airway_bill_number: str | None = None
    vessel_or_flight: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    shipping_mode: str | None = None
    clearing_agent: str | None = None
    customs_reference: str | None = None

    etd: date | None = None
    eta: date | None = None
    actual_arrival_date: date | None = None
    cleared_date: date | None = None

    freight_amount: Decimal = Decimal("0")
    insurance_amount: Decimal = Decimal("0")
    remarks: str | None = None
    lines: list[ImportShipmentLineIn]

    @field_validator("currency")
    @classmethod
    def _code(cls, value: str) -> str:
        return cur.normalise(value)


# ------------------------------------------------------------- landed cost

class ChargeTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    cost_group: str
    default_allocation: str = "Value"
    default_rate_percent: Decimal | None = None
    account_code: str | None = None
    is_inventoriable: bool = True
    is_active: bool = True
    sort_order: int = 0

    @field_validator("cost_group")
    @classmethod
    def _group(cls, value: str) -> str:
        from app.procurement.models import COST_GROUPS
        cleaned = (value or "").strip().title()
        if cleaned not in COST_GROUPS:
            raise ValueError(f"Cost group must be one of: {', '.join(COST_GROUPS)}.")
        return cleaned


class LandedCostChargeIn(BaseModel):
    id: str | None = None
    charge_type_id: str | None = None
    name: str | None = None
    cost_group: str | None = None
    vendor_id: str | None = None
    reference: str | None = None
    currency: str = "PKR"
    exchange_rate: Decimal = Decimal("1")
    amount: Decimal = Field(default=Decimal("0"), ge=0)
    allocation_method: str | None = None
    is_inventoriable: bool | None = None
    remarks: str | None = None


class LandedCostItemIn(BaseModel):
    id: str | None = None
    purchase_order_line_id: str | None = None
    shipment_line_id: str | None = None
    item_id: str | None = None
    item_code: str | None = None
    description: str | None = None
    uom: str | None = None
    hs_code: str | None = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Decimal("0")
    total_weight: Decimal | None = None
    total_volume: Decimal | None = None
    manual_share_percent: Decimal | None = None


class LandedCostIn(BaseModel):
    doc_date: date
    purchase_order_id: str | None = None
    shipment_id: str | None = None
    supplier_id: str | None = None
    status: str = "Draft"
    currency: str = "USD"
    exchange_rate: Decimal = Field(default=Decimal("1"), gt=0)
    exchange_rate_date: date | None = None
    allocation_method: str = "Value"
    supplier_invoice_number: str | None = None
    supplier_invoice_date: date | None = None
    customs_reference: str | None = None
    remarks: str | None = None
    charges: list[LandedCostChargeIn] = []
    items: list[LandedCostItemIn] = []

    @field_validator("currency")
    @classmethod
    def _code(cls, value: str) -> str:
        return cur.normalise(value)

    @field_validator("allocation_method")
    @classmethod
    def _method(cls, value: str) -> str:
        from app.procurement.models import ALLOCATION_METHODS
        cleaned = (value or "Value").strip().title()
        if cleaned not in ALLOCATION_METHODS:
            raise ValueError(f"Allocation must be one of: {', '.join(ALLOCATION_METHODS)}.")
        return cleaned


class LandedCostFromShipmentIn(BaseModel):
    """Start a costing from a shipment, pre-filled with its goods."""
    doc_date: date | None = None
    exchange_rate: Decimal | None = None
    allocation_method: str = "Value"
    #: Copy the shipment's freight and insurance in as charges, which is
    #: almost always wanted and saves retyping them.
    include_shipment_charges: bool = True


# -------------------------------------------------------------- goods receipt

class GrnLineIn(BaseModel):
    id: str | None = None
    purchase_order_line_id: str | None = None
    shipment_line_id: str | None = None
    item_id: str | None = None
    item_code: str | None = None
    description: str | None = None
    uom: str | None = None
    ordered_quantity: Decimal = Decimal("0")
    received_quantity: Decimal = Field(gt=0)
    rejected_quantity: Decimal = Decimal("0")
    #: What passed inspection; left out, everything received is accepted.
    accepted_quantity: Decimal | None = None
    condition: str = "Good"
    unit_price: Decimal = Decimal("0")
    discount_percent: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")
    warehouse_id: str | None = None
    remarks: str | None = None


class GrnIn(BaseModel):
    doc_date: date
    supplier_id: str
    purchase_order_id: str | None = None
    shipment_id: str | None = None
    landed_cost_id: str | None = None
    warehouse_id: str | None = None
    branch_id: str | None = None
    supplier_invoice_number: str | None = None
    supplier_invoice_date: date | None = None
    vehicle_number: str | None = None
    received_by: str | None = None
    remarks: str | None = None
    delivery_note_number: str | None = None
    delivery_date: date | None = None
    transporter: str | None = None
    gd_reference: str | None = None
    inspection_notes: str | None = None
    discrepancy_notes: str | None = None
    bill_to_finance: str = "No"
    checked_by: str | None = None
    status: str = "Draft"
    currency: str = "PKR"
    exchange_rate: Decimal = Decimal("1")
    freight_amount: Decimal = Decimal("0")
    document_discount: Decimal = Decimal("0")
    lines: list[GrnLineIn]

    @field_validator("currency")
    @classmethod
    def _code(cls, value: str) -> str:
        return cur.normalise(value)


class StatusChangeIn(BaseModel):
    status: str
