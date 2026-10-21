"""
Procurement: the chain from an inventory requirement to stock on a shelf.

    In-House Order        what we need, and why
      -> Purchase Order   what we ordered, from whom (local or import)
        -> Shipment       what left the supplier  (import only)
          -> Landed Cost  what it really cost     (import only)
            -> GRN        what actually arrived
              -> stock ledger

Three rules hold the chain together, and everything else follows from them:

1. Only a posted GRN moves stock. A purchase order is a promise, a shipment
   is goods someone else is holding, and goods in transit are not warehouse
   stock. None of them touch the ledger.
2. A quantity is owned by one document. Ordered, shipped and received are
   maintained by the document that causes them, so a figure cannot drift away
   from the papers that produced it.
3. Every document names its parent. From a ledger entry you can reach the
   GRN, the shipment, the order, and the requirement that started it.

Master data is reused, never re-created (spec section 2): products come from
`inventory_items`, suppliers from `business_partners`, warehouses from
`item_locations`, numbering from `document_sequences`.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base

# ---------------------------------------------------------------- vocabulary

LOCAL = "Local"
IMPORT = "Import"
PURCHASE_TYPES = (LOCAL, IMPORT)

#: Where a requirement came from (spec section 4). Stored so "why did we buy
#: this?" is answerable without asking the person who typed it in.
IHO_SOURCES = (
    "Manual", "Reorder", "Sales Demand", "Production",
    "Branch Request", "Warehouse Request", "Stock Shortage",
)

PRIORITIES = ("Low", "Normal", "High", "Urgent")

#: How a requirement is to be met (spec section 8). Internal Transfer is
#: offered first when another warehouse already holds the stock, because
#: moving it is cheaper than buying more.
FULFILMENT_SOURCES = (
    "Existing Stock", "Internal Transfer", "Local Purchase",
    "Import Purchase", "Production",
)

#: Cost groups a landed-cost charge can belong to (spec section 26). The
#: charge types themselves are master data a user can add to; these are the
#: buckets the landed-costing report has columns for, so they are fixed.
COST_GROUPS = (
    "Freight", "Insurance", "Customs", "Tax",
    "Port", "Clearing", "Bank", "Other",
)

#: Bases for spreading a charge across the goods (spec section 27).
ALLOCATION_METHODS = ("Value", "Quantity", "Weight", "Volume", "Percentage", "Manual")

#: Where the goods physically are, in the order of spec section 20. This is a
#: different vocabulary from a shipment's document status, and mixing the two
#: up silently empties the goods-in-transit figures — so both live here, and
#: `TRANSIT_FROM_STATUS` is the only mapping between them.
TRANSIT_STATES = (
    "Purchased", "Shipped", "In Transit", "Arrived Pakistan",
    "Customs", "Cleared", "Warehouse Received",
)

#: Goods the company owns, that exist, and that cannot be picked: everything
#: after it leaves the supplier and before a warehouse takes it in.
TRANSIT_IN_FLIGHT = ("Shipped", "In Transit", "Arrived Pakistan", "Customs", "Cleared")

#: A shipment's document status decides where its goods are, so the two can
#: never disagree (spec sections 20 and 41).
TRANSIT_FROM_STATUS = {
    "Draft": "Purchased",
    "Booked": "Purchased",
    "Shipped": "Shipped",
    "In Transit": "In Transit",
    "Arrived": "Arrived Pakistan",
    "Customs Pending": "Customs",
    "Customs Cleared": "Cleared",
    "Warehouse Pending": "Cleared",
    "Partially Received": "Cleared",
    "Fully Received": "Warehouse Received",
}


# ------------------------------------------------------------ in-house order

class InHouseOrder(UUIDPKMixin, AuditMixin, Base):
    """An internal requirement for stock — not an order to a supplier.

    A warehouse, a branch, production or the reorder rule says "we need this
    much of that". Approving it authorises procurement; it buys nothing and
    it does not touch stock.
    """

    __tablename__ = "in_house_orders"
    __table_args__ = (UniqueConstraint("company_id", "doc_number", name="uq_iho_number"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True
    )
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fiscal_year: Mapped[str | None] = mapped_column(String(20))

    # The warehouse that needs the stock. Reuses Item Locations rather than
    # standing up a second warehouse list.
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id"), index=True
    )
    department: Mapped[str | None] = mapped_column(String(150))
    requested_by: Mapped[str | None] = mapped_column(String(150))
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    required_date: Mapped[date | None] = mapped_column(Date)

    priority: Mapped[str] = mapped_column(String(20), default="Normal", nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="Manual", nullable=False, index=True)
    #: Set when the reorder rule or a sales order produced this requirement,
    #: so the trail back is a link rather than a sentence in the remarks.
    source_document_type: Mapped[str | None] = mapped_column(String(50))
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    remarks: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False, index=True)

    submitted_at: Mapped[date | None] = mapped_column(Date)
    approved_at: Mapped[date | None] = mapped_column(Date)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    lines: Mapped[list["InHouseOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan",
        order_by="InHouseOrderLine.line_number",
    )


class InHouseOrderLine(UUIDPKMixin, Base):
    """One product wanted, with the stock picture as it looked when asked for.

    The availability figures are a snapshot, deliberately: they record what
    the requester could see, which is what made the quantity they asked for
    reasonable. Live figures are read from the ledger when a screen opens.
    """

    __tablename__ = "in_house_order_lines"

    in_house_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("in_house_orders.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), index=True
    )
    item_code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    uom: Mapped[str | None] = mapped_column(String(30))

    # Snapshot of the stock position when the requirement was raised.
    stock_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    reserved_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    available_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    stock_other_warehouses: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=0, nullable=False)
    stock_on_order: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    goods_in_transit: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    reorder_level: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    min_level: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    max_level: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    #: What the approver authorised — the quantity procurement may order. It
    #: follows the request until the order is approved, so an untouched line
    #: does not read as approved for nothing.
    approved_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)

    #: Maintained by the purchase orders raised against this line.
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    #: Maintained by the goods receipts posted against those orders.
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)

    #: How this line is to be met. A line marked Internal Transfer is not
    #: offered to the purchase-order builder.
    fulfilment_source: Mapped[str | None] = mapped_column(String(40))

    required_date: Mapped[date | None] = mapped_column(Date)
    destination_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id")
    )
    remarks: Mapped[str | None] = mapped_column(Text)

    order: Mapped["InHouseOrder"] = relationship(back_populates="lines")


# ----------------------------------------------------------- purchase orders

class PurchaseOrder(UUIDPKMixin, AuditMixin, Base):
    """An order placed on a supplier — local or import.

    Import orders carry the shipping and customs block; local orders leave it
    empty. One table, because everything before and after an order is
    identical and a second table would double every report that reads
    purchases.
    """

    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("company_id", "doc_number", name="uq_po_number"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True
    )
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fiscal_year: Mapped[str | None] = mapped_column(String(20))

    #: Local or Import. Decides which fields the form shows, and whether
    #: shipments and landed costing apply at all.
    purchase_type: Mapped[str] = mapped_column(
        String(20), default=LOCAL, nullable=False, index=True
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), nullable=False, index=True
    )
    #: The requirement this order came from, when it was raised from one.
    in_house_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("in_house_orders.id"), index=True
    )
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id"), index=True
    )

    purchaser: Mapped[str | None] = mapped_column(String(150))
    purchaser_email: Mapped[str | None] = mapped_column(String(255))
    contact_number: Mapped[str | None] = mapped_column(String(50))

    po_status: Mapped[str] = mapped_column(
        String(30), default="RUNNING", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False, index=True)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    #: Urgent / High / Medium / Low, printed on the order.
    priority: Mapped[str] = mapped_column(String(20), default="Medium", nullable=False)
    # From the company's Import Purchase Order template.
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    purchase_category: Mapped[str | None] = mapped_column(Text)
    buyer_designation: Mapped[str | None] = mapped_column(Text)
    supplier_contact: Mapped[str | None] = mapped_column(Text)
    supplier_contact_designation: Mapped[str | None] = mapped_column(Text)
    ship_to_address: Mapped[str | None] = mapped_column(Text)
    bill_to_address: Mapped[str | None] = mapped_column(Text)
    incoterm_edition: Mapped[str | None] = mapped_column(Text)
    named_place: Mapped[str | None] = mapped_column(Text)
    partial_shipment: Mapped[str | None] = mapped_column(Text)
    transshipment: Mapped[str | None] = mapped_column(Text)
    packing_marks: Mapped[str | None] = mapped_column(Text)
    country_of_export: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[str | None] = mapped_column(Text)
    balance_trigger: Mapped[str | None] = mapped_column(Text)
    bank_charges: Mapped[str | None] = mapped_column(Text)
    payment_reference: Mapped[str | None] = mapped_column(Text)
    goods_condition: Mapped[str | None] = mapped_column(Text)
    warranty_terms: Mapped[str | None] = mapped_column(Text)
    defect_remedy: Mapped[str | None] = mapped_column(Text)
    special_packing: Mapped[str | None] = mapped_column(Text)
    pre_shipment_inspection: Mapped[str | None] = mapped_column(Text)
    special_instructions: Mapped[str | None] = mapped_column(Text)
    packing_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    insurance_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    other_charges: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    advance_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    advance_percent: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    po_type: Mapped[str | None] = mapped_column(String(50))
    payment_terms: Mapped[str | None] = mapped_column(String(255))
    delivery_terms: Mapped[str | None] = mapped_column(String(255))
    shipping_terms: Mapped[str | None] = mapped_column(String(255))
    credit_days: Mapped[int | None] = mapped_column(Integer)
    indent_number: Mapped[str | None] = mapped_column(String(100))
    supplier_quotation_number: Mapped[str | None] = mapped_column(String(100))
    supplier_quotation_date: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(Text)

    approved_at: Mapped[date | None] = mapped_column(Date)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    # --- currency. The order is written in the supplier's currency and also
    # carried in PKR, because stock, tax and accounts are all in PKR.
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    exchange_rate_date: Mapped[date | None] = mapped_column(Date)

    # --- import information (spec section 17). Left null on a local order.
    supplier_country: Mapped[str | None] = mapped_column(String(100))
    country_of_origin: Mapped[str | None] = mapped_column(String(100))
    incoterm: Mapped[str | None] = mapped_column(String(30))
    shipping_mode: Mapped[str | None] = mapped_column(String(30))
    port_of_loading: Mapped[str | None] = mapped_column(String(150))
    port_of_discharge: Mapped[str | None] = mapped_column(String(150))
    expected_shipment_date: Mapped[date | None] = mapped_column(Date)
    expected_arrival_date: Mapped[date | None] = mapped_column(Date)
    commercial_invoice_number: Mapped[str | None] = mapped_column(String(100))
    commercial_invoice_date: Mapped[date | None] = mapped_column(Date)
    packing_list_number: Mapped[str | None] = mapped_column(String(100))
    bill_of_lading_number: Mapped[str | None] = mapped_column(String(100))
    airway_bill_number: Mapped[str | None] = mapped_column(String(100))
    container_number: Mapped[str | None] = mapped_column(String(100))
    lc_number: Mapped[str | None] = mapped_column(String(100))
    lc_date: Mapped[date | None] = mapped_column(Date)
    bank_name: Mapped[str | None] = mapped_column(String(200))
    freight_forwarder: Mapped[str | None] = mapped_column(String(200))
    clearing_agent: Mapped[str | None] = mapped_column(String(200))
    insurance_provider: Mapped[str | None] = mapped_column(String(200))
    customs_reference: Mapped[str | None] = mapped_column(String(100))
    import_reference: Mapped[str | None] = mapped_column(String(100))

    # --- money, in document currency
    excluding_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    sales_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_payable: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    #: Net payable at this document's rate — what the purchase is worth to the
    #: company, and what every PKR report totals.
    net_payable_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.line_number",
    )
    shipments: Mapped[list["ImportShipment"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan",
    )


class PurchaseOrderLine(UUIDPKMixin, Base):
    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: The requirement line this satisfies, so one order can serve several
    #: requirements and one requirement can be met by several orders.
    in_house_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("in_house_order_lines.id"), index=True
    )

    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), index=True
    )
    item_code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    uom: Mapped[str | None] = mapped_column(String(30))
    hs_code: Mapped[str | None] = mapped_column(String(40))
    origin_country: Mapped[str | None] = mapped_column(String(100))

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    free_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    #: Running totals, each maintained by the document that causes it: a
    #: shipment moves `shipped_quantity`, a posted GRN moves
    #: `received_quantity`. Held on the line because every listing needs them
    #: and a subquery per row would not scale; the service is the only writer.
    shipped_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)

    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)

    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    # Allocation bases for landed costing: by weight and by volume need the
    # figures to travel with the goods.
    unit_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit_volume: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id")
    )
    required_date: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(Text)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")


# ---------------------------------------------------------- import shipments

class ImportShipment(UUIDPKMixin, AuditMixin, Base):
    """Goods that have left an international supplier.

    One import order can ship several times, so this is where quantities,
    documents and the customs trail actually live. A shipment never moves
    warehouse stock: until a GRN is posted these goods are in transit, and
    in transit is not a warehouse (spec sections 20 and 50).
    """

    __tablename__ = "import_shipments"
    __table_args__ = (UniqueConstraint("company_id", "doc_number", name="uq_shipment_number"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fiscal_year: Mapped[str | None] = mapped_column(String(20))

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), nullable=False, index=True
    )
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id"), index=True
    )

    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False, index=True)
    #: Where the goods physically are (spec section 20), which is a different
    #: question from how far the paperwork has got.
    transit_status: Mapped[str] = mapped_column(
        String(30), default="Purchased", nullable=False, index=True)
    customs_status: Mapped[str | None] = mapped_column(String(30), index=True)
    clearance_status: Mapped[str | None] = mapped_column(String(30))

    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    exchange_rate_date: Mapped[date | None] = mapped_column(Date)

    container_number: Mapped[str | None] = mapped_column(String(100))
    bill_of_lading_number: Mapped[str | None] = mapped_column(String(100))
    airway_bill_number: Mapped[str | None] = mapped_column(String(100))
    vessel_or_flight: Mapped[str | None] = mapped_column(String(150))
    port_of_loading: Mapped[str | None] = mapped_column(String(150))
    port_of_discharge: Mapped[str | None] = mapped_column(String(150))
    shipping_mode: Mapped[str | None] = mapped_column(String(30))
    clearing_agent: Mapped[str | None] = mapped_column(String(200))
    customs_reference: Mapped[str | None] = mapped_column(String(100))

    etd: Mapped[date | None] = mapped_column(Date)
    eta: Mapped[date | None] = mapped_column(Date)
    actual_arrival_date: Mapped[date | None] = mapped_column(Date)
    cleared_date: Mapped[date | None] = mapped_column(Date)

    #: Freight and insurance for the shipment, **in PKR** — not in the
    #: shipment's currency like the goods are. Both are normally settled
    #: locally with a forwarder and an insurer, and leaving them to inherit
    #: the goods' currency turned a PKR 600,000 freight bill into USD 600,000.
    #: A charge billed in another currency is entered on the landed cost
    #: voucher instead, where each charge carries its own rate.
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    insurance_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    shipment_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    shipment_value_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="shipments")
    lines: Mapped[list["ImportShipmentLine"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan",
        order_by="ImportShipmentLine.line_number",
    )


class ImportShipmentLine(UUIDPKMixin, Base):
    __tablename__ = "import_shipment_lines"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_shipments.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"), index=True
    )

    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), index=True
    )
    item_code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    uom: Mapped[str | None] = mapped_column(String(30))
    hs_code: Mapped[str | None] = mapped_column(String(40))

    shipped_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    #: Maintained by posted GRNs against this shipment.
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    line_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    total_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    total_volume: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    remarks: Mapped[str | None] = mapped_column(Text)

    shipment: Mapped["ImportShipment"] = relationship(back_populates="lines")


# ------------------------------------------------------------- landed costing

class LandedCostChargeType(UUIDPKMixin, AuditMixin, Base):
    """A kind of import cost the company actually incurs — master data.

    Deliberately a table and not an enum: spec section 48 requires that no
    duty or tax rate be hard-coded, and a company that meets a new charge
    next year must be able to add it without a release. Each type belongs to
    one of the report's cost groups so the landed-costing columns stay fixed
    while the charges under them can grow.
    """

    __tablename__ = "landed_cost_charge_types"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_charge_type_name"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    cost_group: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    #: What to spread this charge by unless the user says otherwise — freight
    #: usually by weight, duty usually by value.
    default_allocation: Mapped[str] = mapped_column(
        String(20), default="Value", nullable=False)
    #: A percentage the user normally applies, e.g. a customs duty rate. Only
    #: a default for the form; the amount on the voucher is what counts, and
    #: the rate can be changed per shipment.
    default_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    #: Where this cost is posted once there is a chart of accounts. Held as
    #: text until then so the mapping is not lost.
    account_code: Mapped[str | None] = mapped_column(String(50))
    #: False for a cost that is an expense rather than part of stock value —
    #: demurrage, say, where the company chooses not to capitalise it.
    is_inventoriable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LandedCost(UUIDPKMixin, AuditMixin, Base):
    """What an import actually cost, once everything is in.

    Supplier invoice plus freight, insurance, duty, taxes, port, clearing and
    bank charges, spread across the goods on a stated basis, giving a unit
    cost per item. Only a posted voucher feeds inventory valuation (spec
    section 42), and posting is what stamps the cost onto the goods.
    """

    __tablename__ = "landed_costs"
    __table_args__ = (UniqueConstraint("company_id", "doc_number", name="uq_landed_cost_number"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fiscal_year: Mapped[str | None] = mapped_column(String(20))

    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), index=True
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_shipments.id"), index=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), index=True
    )

    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False, index=True)
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    posted_at: Mapped[date | None] = mapped_column(Date)
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    approved_at: Mapped[date | None] = mapped_column(Date)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    exchange_rate_date: Mapped[date | None] = mapped_column(Date)

    #: The basis used unless a charge overrides it.
    allocation_method: Mapped[str] = mapped_column(
        String(20), default="Value", nullable=False)

    supplier_invoice_number: Mapped[str | None] = mapped_column(String(100))
    supplier_invoice_date: Mapped[date | None] = mapped_column(Date)
    customs_reference: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(Text)

    # --- totals, all in PKR: this is where foreign becomes local and stays.
    purchase_cost_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    additional_cost_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_landed_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    charges: Mapped[list["LandedCostCharge"]] = relationship(
        back_populates="landed_cost", cascade="all, delete-orphan",
    )
    items: Mapped[list["LandedCostItem"]] = relationship(
        back_populates="landed_cost", cascade="all, delete-orphan",
        order_by="LandedCostItem.line_number",
    )


class LandedCostCharge(UUIDPKMixin, Base):
    """One cost incurred on the import, and how it is to be spread."""

    __tablename__ = "landed_cost_charges"

    landed_cost_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("landed_costs.id"), nullable=False, index=True
    )
    charge_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("landed_cost_charge_types.id"), index=True
    )
    #: Copied from the charge type so a renamed or retired type does not
    #: rewrite history on a posted voucher.
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    cost_group: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    #: Who was paid — the forwarder, the agent, the bank. Not necessarily the
    #: supplier of the goods, which is the whole point of landed costing.
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), index=True
    )
    reference: Mapped[str | None] = mapped_column(String(100))

    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    #: The amount that is actually allocated. A charge billed in dollars is
    #: converted once, here, and never again.
    amount_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    allocation_method: Mapped[str] = mapped_column(String(20), default="Value", nullable=False)
    is_inventoriable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)

    landed_cost: Mapped["LandedCost"] = relationship(back_populates="charges")


class LandedCostItem(UUIDPKMixin, Base):
    """One product on the import, with its share of every cost group.

    The per-group columns are written when the voucher is costed. They are a
    rolled-up copy of the allocation rows below, kept because the landed
    costing report has a column per group and a posted voucher never changes
    — which is exactly when storing the answer is right rather than lazy.
    """

    __tablename__ = "landed_cost_items"

    landed_cost_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("landed_costs.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"), index=True
    )
    shipment_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_shipment_lines.id"), index=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), index=True
    )
    item_code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    uom: Mapped[str | None] = mapped_column(String(30))
    hs_code: Mapped[str | None] = mapped_column(String(40))

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    total_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    total_volume: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    #: Used when the voucher allocates by Percentage or Manual.
    manual_share_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))

    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    purchase_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    purchase_cost_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    # One column per report cost group.
    freight_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    insurance_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    customs_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    port_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    clearing_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    bank_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    other_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    additional_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_landed_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    unit_landed_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)

    landed_cost: Mapped["LandedCost"] = relationship(back_populates="items")
    allocations: Mapped[list["LandedCostAllocation"]] = relationship(
        back_populates="item", cascade="all, delete-orphan",
    )


class LandedCostAllocation(UUIDPKMixin, Base):
    """How much of one charge landed on one product.

    The audit detail behind the rolled-up columns: for any unit cost, this
    says which charge contributed what, and on what basis. Section 47 wants
    posted figures explainable, and a total on its own is not an explanation.
    """

    __tablename__ = "landed_cost_allocations"

    landed_cost_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("landed_cost_items.id"), nullable=False, index=True
    )
    charge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("landed_cost_charges.id"), nullable=False, index=True
    )
    cost_group: Mapped[str] = mapped_column(String(30), nullable=False)
    allocation_method: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The item's share of the basis, kept so the arithmetic can be re-read
    #: rather than re-derived.
    basis_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    basis_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    item: Mapped["LandedCostItem"] = relationship(back_populates="allocations")


# --------------------------------------------------------------- goods receipt

class MaterialReceivingNote(UUIDPKMixin, AuditMixin, Base):
    """Goods Receipt Note — what actually arrived, and the only thing that
    moves stock.

    Kept under its existing table name (the ERP called it an MRN) and exposed
    as GRN in the API, which is the spec's term. Receives against a local
    purchase order, or against an import shipment; a partial receipt is the
    normal case and several receipts against one order are expected.
    """

    __tablename__ = "material_receiving_notes"
    __table_args__ = (UniqueConstraint("company_id", "doc_number", name="uq_mrn_number"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True
    )
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fiscal_year: Mapped[str | None] = mapped_column(String(20))

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), nullable=False, index=True
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), index=True
    )
    #: Set when receiving an import: the goods came off this shipment.
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_shipments.id"), index=True
    )
    #: The requirement that started it, carried down so a ledger entry can
    #: reach the requirement in one hop instead of three.
    in_house_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("in_house_orders.id"), index=True
    )
    #: The costing whose unit cost was used, on an import receipt.
    landed_cost_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("landed_costs.id"), index=True
    )
    #: Which warehouse took the goods in. Drives where the stock lands.
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id"), index=True
    )

    supplier_invoice_number: Mapped[str | None] = mapped_column(String(100))
    supplier_invoice_date: Mapped[date | None] = mapped_column(Date)
    vehicle_number: Mapped[str | None] = mapped_column(String(100))
    received_by: Mapped[str | None] = mapped_column(String(150))
    remarks: Mapped[str | None] = mapped_column(Text)
    # From the company's GRN template.
    delivery_note_number: Mapped[str | None] = mapped_column(String(100))
    delivery_date: Mapped[date | None] = mapped_column(Date)
    transporter: Mapped[str | None] = mapped_column(String(150))
    gd_reference: Mapped[str | None] = mapped_column(String(100))
    inspection_notes: Mapped[str | None] = mapped_column(Text)
    discrepancy_notes: Mapped[str | None] = mapped_column(Text)
    #: Yes / No / Hold — whether the supplier's bill has gone to Finance.
    bill_to_finance: Mapped[str] = mapped_column(String(10), default="No", nullable=False)
    checked_by: Mapped[str | None] = mapped_column(String(150))

    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False, index=True)
    #: True once stock ledger entries exist, so nothing can post twice.
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    posted_at: Mapped[date | None] = mapped_column(Date)
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)

    excluding_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    sales_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_payable: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    lines: Mapped[list["MrnLine"]] = relationship(
        back_populates="mrn", cascade="all, delete-orphan", order_by="MrnLine.line_number",
    )


class MrnLine(UUIDPKMixin, Base):
    __tablename__ = "mrn_lines"

    mrn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("material_receiving_notes.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"), index=True
    )
    shipment_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_shipment_lines.id"), index=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), index=True
    )
    item_code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    uom: Mapped[str | None] = mapped_column(String(30))

    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    #: What this receipt takes in — the quantity that hits the ledger.
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    #: Ordered less everything received including this note, worked out on
    #: save so the paper says what was still outstanding at the time.
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    #: What passed inspection: the only quantity that goes into stock, counts
    #: against the order and is valued. Received less accepted is rejected.
    accepted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    #: Good / Damaged / Short / Excess / Under Inspection.
    condition: Mapped[str] = mapped_column(String(30), default="Good", nullable=False)

    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)

    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    #: The cost one unit actually enters stock at. On a local receipt that is
    #: the purchase price; on an import it is the landed unit cost, which is
    #: why costing happens before the goods are taken in.
    unit_cost_base: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)

    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id")
    )
    remarks: Mapped[str | None] = mapped_column(Text)

    mrn: Mapped["MaterialReceivingNote"] = relationship(back_populates="lines")
