"""
Sales documents: Product Quotation and Product Sales Order.

Both share one table because they share nearly every field and because a
sales order is created *from* a quotation — keeping them together makes the
conversion a copy with a changed doc_type and a link back, rather than a
mapping between two different shapes.

Chain (spec section 4 of the requirements doc):

    Quotation --approved--> Sales Order --> Delivery Note / Invoices
"""

import uuid
from datetime import date
from decimal import Decimal

from datetime import datetime

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base

# doc_type values
QUOTATION = "quotation"
SALES_ORDER = "sales_order"
# Finance Phase 2: receivable documents on the same table.
SALES_INVOICE = "sales_invoice"
CREDIT_NOTE = "credit_note"
DEBIT_NOTE = "debit_note"
AR_DOC_TYPES = (SALES_INVOICE, CREDIT_NOTE, DEBIT_NOTE)
#: Lifecycle of the AR document types. Payment state (open / partly paid /
#: paid / overdue) is derived from the AR subledger, never stored.
AR_DOC_STATUSES = ["DRAFT", "CONFIRMED", "POSTED", "CANCELLED"]

# Status values seen in the legacy export.
# REQUIRES BUSINESS CONFIRMATION: the full allowed set and which transitions
# are legal. Only the transitions the requirements doc states explicitly are
# enforced in code; the rest are accepted as data.
QUOTATION_STATUSES = ["Draft", "Sent", "Approved", "Rejected", "Closed"]
SALES_ORDER_STATUSES = ["Draft", "Posted", "Delivered", "Cancelled"]
PAYMENT_STATUSES = ["PENDING", "PARTIAL", "PAID"]


class SalesDocument(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "sales_documents"
    __table_args__ = (
        # Quotations and orders: unique per company as before. Invoices and
        # notes restart their numbering each financial year (migration 0009).
        Index("uq_sales_doc_number_legacy", "company_id", "doc_type", "doc_number", unique=True,
              postgresql_where=text("doc_type not in ('sales_invoice','credit_note','debit_note')")),
        Index("uq_sales_doc_number_fy", "company_id", "doc_type", "financial_year_id", "doc_number",
              unique=True,
              postgresql_where=text("doc_type in ('sales_invoice','credit_note','debit_note')")),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True
    )

    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fiscal_year: Mapped[str | None] = mapped_column(String(20), index=True)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), nullable=False, index=True
    )

    # Link back to the quotation a sales order was converted from, so the
    # chain stays traceable and a quotation cannot be converted twice.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_documents.id"), index=True
    )

    status: Mapped[str] = mapped_column(String(30), default="Draft", nullable=False, index=True)
    payment_status: Mapped[str | None] = mapped_column(String(30), index=True)

    #: The old ERP's "Quotation No#" as imported. The relationship itself is
    #: source_document_id; this text is shown when no quotation could be
    #: linked (e.g. the quotation was never imported).
    quotation_number: Mapped[str | None] = mapped_column(String(100))

    # Quotation-only
    demand_number: Mapped[str | None] = mapped_column(String(100))

    # Sales-order-only
    customer_po_number: Mapped[str | None] = mapped_column(String(100))
    dc_number: Mapped[str | None] = mapped_column(String(100))
    delivery_person: Mapped[str | None] = mapped_column(String(150))
    vehicle_number: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(150))

    # "With Sale Tax" / "Without Sale Tax" in the legacy export. Drives which
    # invoice document the listing's print icons produce.
    with_sales_tax: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # A service order: printed as a Service Invoice instead of a sales / sales tax invoice.
    is_service: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    payment_terms: Mapped[str | None] = mapped_column(String(255))
    payment_reference: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)

    # Every figure below is computed by app.common.calculations on save and
    # is never accepted from the client.
    excluding_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    sales_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_receivable: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ---- Finance Phase 2: invoices, credit notes, debit notes ----
    financial_year_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_years.id"), index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_date_overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_terms.id"))
    billing_address: Mapped[str | None] = mapped_column(Text)
    shipping_address: Mapped[str | None] = mapped_column(Text)
    #: Commercial chain: source_document_id is the sales order (for an
    #: invoice) or the invoice (for a note); these keep the rest of the trail.
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_documents.id"))
    gate_pass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gate_passes.id"))
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_cash_sale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cash_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"))
    reason_code: Mapped[str | None] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    cancel_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    #: OK / WARNING / APPROVAL_REQUIRED / APPROVED, set when confirmed.
    credit_check_status: Mapped[str | None] = mapped_column(String(20))
    credit_approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    credit_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["SalesDocumentLine"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="SalesDocumentLine.line_number",
    )


class SalesDocumentLine(UUIDPKMixin, Base):
    __tablename__ = "sales_document_lines"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_documents.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), index=True
    )
    # Description is copied onto the line rather than read through the item,
    # so a later edit to the product catalogue cannot silently change the
    # wording on a document that was already sent to a customer.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(40))
    uom: Mapped[str | None] = mapped_column(String(30))
    hs_code: Mapped[str | None] = mapped_column(String(50))
    lot_number: Mapped[str | None] = mapped_column(String(50))
    rack_name: Mapped[str | None] = mapped_column(String(100))

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    delivered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10))

    discount_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)

    # Derived — written by the calculation engine only.
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    # ---- Finance Phase 2 ----
    #: The order line this invoice line bills, or the invoice line a credit
    #: note credits. Invoiced / remaining quantities are derived from it.
    source_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_document_lines.id"), index=True)
    gate_pass_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gate_pass_lines.id"), index=True)
    tax_code_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_codes.id"))

    document: Mapped["SalesDocument"] = relationship(back_populates="lines")


# Tables the Phase 2 columns point at, so the foreign keys resolve wherever
# this module is imported on its own (import scripts, tests).
import app.finance.models  # noqa: E402,F401
import app.gatepass.models  # noqa: E402,F401
import app.receivables.models  # noqa: E402,F401
