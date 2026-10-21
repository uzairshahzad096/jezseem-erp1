"""
Outward and Inward Gate Passes.

One table for both, distinguished by `pass_type`, because the legacy exports
(Outward_Gate_Pass and Returnable_IGP) carry effectively the same columns and
a returnable IGP references the OGP it came back against.

Gate passes move physical stock, so posting one writes to the stock ledger.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base

OUTWARD = "outward"
INWARD = "inward"


class GatePass(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "gate_passes"
    __table_args__ = (
        UniqueConstraint("company_id", "pass_type", "doc_number", name="uq_gatepass_number"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    pass_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fiscal_year: Mapped[str | None] = mapped_column(String(20))

    party_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), index=True
    )

    # An inward (returnable) pass points at the outward pass it settles.
    reference_gate_pass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gate_passes.id"), index=True
    )
    sales_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_documents.id"), index=True
    )

    vehicle_number: Mapped[str | None] = mapped_column(String(100))
    driver: Mapped[str | None] = mapped_column(String(150))
    issue_type: Mapped[str | None] = mapped_column(String(50))   # "Foc", "Returnable" …
    issue_to: Mapped[str | None] = mapped_column(String(255))
    challan_number: Mapped[str | None] = mapped_column(String(100))
    dc_number: Mapped[str | None] = mapped_column(String(100))
    container_number: Mapped[str | None] = mapped_column(String(100))
    po_number: Mapped[str | None] = mapped_column(String(100))
    reference_number: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(Text)
    # When goods on a returnable outward pass are due back.
    expected_return_date: Mapped[date | None] = mapped_column(Date)

    # Where the goods leave from (outward) or return to (inward). Matched to
    # Item Locations by name when the pass posts, so stock moves off the right
    # location rather than an undifferentiated pool.
    location: Mapped[str | None] = mapped_column(String(150))

    # The party's registrations, printed on the pass itself.
    ntn: Mapped[str | None] = mapped_column(String(50))
    gst_number: Mapped[str | None] = mapped_column(String(50))

    payment_status: Mapped[str | None] = mapped_column(String(30))
    payment_reference: Mapped[str | None] = mapped_column(String(150))

    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False, index=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    excluding_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    sales_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    lines: Mapped[list["GatePassLine"]] = relationship(
        back_populates="gate_pass", cascade="all, delete-orphan",
        order_by="GatePassLine.line_number",
    )


class GatePassLine(UUIDPKMixin, Base):
    __tablename__ = "gate_pass_lines"

    gate_pass_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gate_passes.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), index=True
    )
    item_code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    uom: Mapped[str | None] = mapped_column(String(30))
    hs_code: Mapped[str | None] = mapped_column(String(50))
    remarks: Mapped[str | None] = mapped_column(Text)
    # On an inward pass: the outward line these goods are returning against.
    reference_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gate_pass_lines.id"), index=True
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)

    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    gate_pass: Mapped["GatePass"] = relationship(back_populates="lines")
