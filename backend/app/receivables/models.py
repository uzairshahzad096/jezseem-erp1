"""
Accounts receivable — Finance Phase 2.

Invoices, credit notes and debit notes live on `sales_documents` (doc types
sales_invoice / credit_note / debit_note). This module adds what a
receivable needs beyond the document:

- master data: payment terms, payment methods, tax codes, AR settings;
- customer receipts;
- the AR subledger.

The subledger is two tables. `ARItem` is written once, when a receivable
document posts: an invoice or debit note (positive), a credit note or receipt
(negative), or an opening balance line. Its amount never changes afterwards;
the database only lets its status move from OPEN to CANCELLED.
`ARAllocation` matches a credit item against a debit item. So the outstanding
amount on anything is its amount less its active allocations, and there is
no stored balance to drift from the ledger.

`kind` says which GL account holds an item's unallocated balance:
- AR: the receivable account (invoices, debit notes, credit notes, opening AR);
- ADVANCE: the customer-advances account (receipts, opening advances).
Allocating an ADVANCE item therefore moves money between the two accounts
through the posting engine, while allocating an AR credit moves nothing.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base

# Item types
INVOICE = "INVOICE"
DEBIT_NOTE = "DEBIT_NOTE"
CREDIT_NOTE = "CREDIT_NOTE"
RECEIPT = "RECEIPT"
OPENING = "OPENING"
JOURNAL = "JOURNAL"

KIND_AR = "AR"
KIND_ADVANCE = "ADVANCE"

# Receipt statuses
R_DRAFT = "DRAFT"
R_POSTED = "POSTED"
R_REVERSED = "REVERSED"
R_CANCELLED = "CANCELLED"

CREDIT_POLICIES = ["NONE", "WARN", "BLOCK", "APPROVAL"]
PAYMENT_METHOD_KINDS = ["CASH", "BANK", "CHEQUE", "ONLINE", "OTHER"]
TAX_TYPES = ["SALES_TAX", "EXEMPT", "ZERO_RATED", "OTHER"]


class PaymentTerm(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "payment_terms"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_payment_term_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Due date = invoice date + days.
    days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_cash: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PaymentMethod(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "payment_methods"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_payment_method_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    #: Cheques and transfers need their number / reference recorded.
    requires_reference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: The cash or bank account a receipt defaults to.
    default_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TaxCode(UUIDPKMixin, AuditMixin, Base):
    """A sales tax treatment. The rate is data, never code. Pakistan-specific
    rules (further tax, provincial services tax, withholding) come with the
    Tax phase; this covers standard, exempt and zero-rated supplies."""

    __tablename__ = "tax_codes"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_tax_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tax_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    #: Liability account for this code. Null means the posting rule
    #: SALES_INVOICE_POSTED.output_tax decides.
    output_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class ARSettings(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "ar_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, unique=True)
    #: What happens when an invoice would take a customer over their limit.
    credit_limit_policy: Mapped[str] = mapped_column(String(10), default="WARN", nullable=False)
    #: Sales orders dated before this cannot be invoiced. Keeps the old ERP's
    #: orders out of AR; their balances enter through Opening Balances.
    sales_order_cutoff_date: Mapped[date | None] = mapped_column(Date)
    #: Quotation → invoice without a sales order. Off unless the business allows it.
    allow_quotation_invoice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_payment_term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_terms.id"))
    #: Upper bounds of the aging buckets after "Current", in days.
    aging_buckets: Mapped[str] = mapped_column(String(60), default="30,60,90,120", nullable=False)


class CustomerReceipt(UUIDPKMixin, AuditMixin, Base):
    """Money received from a customer. DRAFT → POSTED → (REVERSED); a draft
    no longer wanted is CANCELLED. The planned allocations of a draft are
    kept as JSON: they are intentions, not accounting, until posting turns
    them into ARAllocation rows."""

    __tablename__ = "customer_receipts"
    __table_args__ = (
        UniqueConstraint("company_id", "financial_year_id", "receipt_number", name="uq_receipt_number"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    financial_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_years.id"), nullable=False)
    receipt_number: Mapped[str] = mapped_column(String(40), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), nullable=False, index=True)
    payment_method_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_methods.id"), nullable=False)
    deposit_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    amount_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    #: Part of `amount` the customer withheld as tax; it never reached the bank.
    wht_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, server_default="0", nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100))
    cheque_number: Mapped[str | None] = mapped_column(String(50))
    cheque_date: Mapped[date | None] = mapped_column(Date)
    bank_name: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(Text)
    planned_allocations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=R_DRAFT, nullable=False)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    reversal_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    posted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverse_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ARItem(UUIDPKMixin, Base):
    __tablename__ = "ar_items"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(12), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), default=KIND_AR, nullable=False)
    sales_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_documents.id"))
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_receipts.id"))
    opening_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opening_balance_lines.id"))
    #: A posted Calibration / Services invoice (migration 0020).
    service_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("svc_invoices.id"))
    #: A posted manual journal line on the receivable account (migration 0025).
    journal_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entry_lines.id"))
    document_number: Mapped[str] = mapped_column(String(50), nullable=False)
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    #: Signed: positive is owed by the customer, negative is owed to them.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    status: Mapped[str] = mapped_column(String(10), default="OPEN", nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ARAllocation(UUIDPKMixin, Base):
    __tablename__ = "ar_allocations"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    #: The credit side: receipt, credit note, or opening credit / advance.
    from_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_items.id"), nullable=False, index=True)
    #: The debit side: invoice, debit note, or opening receivable.
    to_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ar_items.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    allocation_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: The advance → AR journal, when the allocation moved money between accounts.
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reversal_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
