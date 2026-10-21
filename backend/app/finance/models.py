"""
Finance Phase 1 — the accounting foundation.

    Business transaction -> accounting event -> posting rule
        -> journal entry -> journal lines -> general ledger -> reports

The general ledger is not a table. It is the set of lines of POSTED journals.
No balance is stored anywhere that could drift from the entries behind it,
the same principle as the stock ledger.

Master data is referenced, never copied. Companies, branches, financial
years, users, customers and suppliers (`business_partners`) and inventory
items are the existing tables.

The rules that must never break are enforced in the database too (migration
0008). The model docstrings say which.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base

ZERO = Decimal("0")

# Normal balances
DEBIT = "DEBIT"
CREDIT = "CREDIT"

#: Accounts fed by a subledger or a document chain. Manual journals may not
#: touch them unless the account explicitly allows it, which is what keeps a
#: receivable total equal to the sum of the customers behind it.
CONTROL_TYPES = ["RECEIVABLE", "PAYABLE", "INVENTORY", "BANK", "CASH", "TAX", "GRNI",
                 "CUSTOMER_ADVANCE"]

# Journal statuses, in workflow order
DRAFT = "DRAFT"
SUBMITTED = "SUBMITTED"
APPROVED = "APPROVED"
POSTED = "POSTED"
REVERSED = "REVERSED"
CANCELLED = "CANCELLED"
JOURNAL_STATUSES = [DRAFT, SUBMITTED, APPROVED, POSTED, REVERSED, CANCELLED]

# Journal types
MANUAL = "MANUAL"
ADJUSTMENT = "ADJUSTMENT"
OPENING = "OPENING"
REVERSAL = "REVERSAL"
SYSTEM = "SYSTEM"
JOURNAL_TYPES = [MANUAL, ADJUSTMENT, OPENING, REVERSAL, SYSTEM]

# Period statuses
OPEN = "OPEN"
CLOSED = "CLOSED"
LOCKED = "LOCKED"


class AccountType(UUIDPKMixin, Base):
    """The eight families every account belongs to. Global reference data,
    seeded by the migration: what an asset *is* does not vary by company."""

    __tablename__ = "account_types"

    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    normal_balance: Mapped[str] = mapped_column(String(6), nullable=False)
    #: BS = balance sheet, PL = profit and loss.
    statement: Mapped[str] = mapped_column(String(2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AccountGroup(UUIDPKMixin, AuditMixin, Base):
    """A reporting grouping within a type — Current Assets, Non-Current
    Liabilities — so statements can subtotal without parsing account codes."""

    __tablename__ = "account_groups"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_account_group_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_types.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_groups.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Account(UUIDPKMixin, AuditMixin, Base):
    """One line of the chart of accounts.

    A header account (`is_postable = False`) only groups its children; the
    database refuses to post to it. Codes are the company's own. The
    standard chart is only a starting point and nothing reads meaning from
    the digits.
    """

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_account_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_types.id"), nullable=False)
    account_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_groups.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), index=True)
    normal_balance: Mapped[str] = mapped_column(String(6), nullable=False)
    is_postable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_control_account: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    control_type: Mapped[str | None] = mapped_column(String(20))
    allow_manual_posting: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Null means any currency. Multi-currency accounting is a later phase.
    currency: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)

    account_type: Mapped[AccountType] = relationship(lazy="joined")


class CostCenter(UUIDPKMixin, AuditMixin, Base):
    """Minimal for Phase 1: enough for a journal line to carry a real
    foreign key. Budgets and cost-centre P&L come with the dimensions phase."""

    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_cost_center_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_centers.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AccountingPeriod(UUIDPKMixin, AuditMixin, Base):
    """A month of an existing financial year.

    OPEN accepts postings. CLOSED refuses them but can be reopened by someone
    holding finance.close_period. LOCKED is final: the database refuses any
    further change to the row.
    """

    __tablename__ = "accounting_periods"
    __table_args__ = (
        UniqueConstraint("financial_year_id", "period_number", name="uq_period_number"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    financial_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_years.id"), nullable=False, index=True)
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default=OPEN, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class DocumentSeries(UUIDPKMixin, AuditMixin, Base):
    """How one document type is numbered. The counters themselves live in
    the existing `document_sequences` table.

    `format` tokens: {prefix}, {seq} (zero-padded to `padding`), {fy}
    (financial year name) and {branch} (branch code). A per-branch series
    must contain {branch}, or two branches would issue the same number.
    """

    __tablename__ = "document_series"
    __table_args__ = (UniqueConstraint("company_id", "doc_type", name="uq_document_series_type"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    padding: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    format: Mapped[str] = mapped_column(String(60), default="{prefix}-{seq}", nullable=False)
    reset_each_fiscal_year: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    per_branch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class JournalEntry(UUIDPKMixin, AuditMixin, Base):
    """A journal header.

    Created DRAFT. Manual journals go DRAFT → SUBMITTED → APPROVED → POSTED;
    journals from the posting engine are created and posted in one
    transaction. Once POSTED the database allows exactly one further
    change, to REVERSED, made by the reversal journal that cancels it.

    `document_type` / `document_id` / `source_reference` name the business
    document that caused the entry, which is what drill-down follows.
    """

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("company_id", "financial_year_id", "journal_number",
                         name="uq_journal_number"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    financial_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_years.id"), nullable=False)
    accounting_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounting_periods.id"), nullable=False, index=True)
    journal_number: Mapped[str] = mapped_column(String(40), nullable=False)
    journal_date: Mapped[date] = mapped_column(Date, nullable=False)
    journal_type: Mapped[str] = mapped_column(String(20), default=MANUAL, nullable=False)
    event_code: Mapped[str | None] = mapped_column(String(50))
    document_type: Mapped[str | None] = mapped_column(String(50))
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(12), default=DRAFT, nullable=False)
    source_module: Mapped[str | None] = mapped_column(String(30))
    source_reference: Mapped[str | None] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    total_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    #: On a reversal: the journal it cancels.
    reversed_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    #: On a reversed journal: the reversal that cancelled it.
    reversed_by_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))

    lines: Mapped[list["JournalEntryLine"]] = relationship(
        back_populates="journal", cascade="all, delete-orphan",
        order_by="JournalEntryLine.line_number",
        # Lines are written through the ORM only while DRAFT; passive deletes
        # leave the rest to the database, whose trigger has the final say.
        passive_deletes=True,
    )


class JournalEntryLine(UUIDPKMixin, Base):
    """One debit or one credit — never both, never negative, never zero
    (CHECK constraints). `debit`/`credit` are in the line currency and
    `base_debit`/`base_credit` in the company currency; the balance rule is
    applied to the base amounts."""

    __tablename__ = "journal_entry_lines"
    __table_args__ = (
        UniqueConstraint("journal_entry_id", "line_number", name="uq_journal_line_number"),
    )

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False, index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    base_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    base_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), index=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), index=True)
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cost_centers.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    journal: Mapped[JournalEntry] = relationship(back_populates="lines")


class PostingRule(UUIDPKMixin, AuditMixin, Base):
    """Which account one line of one accounting event goes to.

    The events and the shape of their entries are defined in code
    (`finance/events.py`); which account each line hits is data, set on the
    Finance Settings screen. Nothing in the posting engine names an account.
    """

    __tablename__ = "posting_rules"
    __table_args__ = (
        UniqueConstraint("company_id", "event_code", "line_key", name="uq_posting_rule"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    event_code: Mapped[str] = mapped_column(String(50), nullable=False)
    line_key: Mapped[str] = mapped_column(String(40), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"))
    description: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# ------------------------------------------------------------ opening balances

# Batch statuses
OB_DRAFT = "DRAFT"
OB_VALIDATED = "VALIDATED"
OB_APPROVED = "APPROVED"
OB_POSTED = "POSTED"
OB_COMPLETED = "COMPLETED"
OB_CANCELLED = "CANCELLED"

SCHEDULES = ["GL", "AR", "AP", "INVENTORY", "BANK"]

#: Categories on the reconciliation screen, in the order they are shown.
RECONCILIATION_CATEGORIES = [
    "TRIAL_BALANCE", "ACCOUNTS_RECEIVABLE", "ACCOUNTS_PAYABLE",
    "INVENTORY", "CASH", "BANK", "EQUITY",
]


class OpeningBalanceBatch(UUIDPKMixin, AuditMixin, Base):
    """One accountant-prepared opening position at a cut-over date.

    DRAFT → VALIDATED → APPROVED → POSTED → COMPLETED. COMPLETED requires
    every reconciliation category to agree with the legacy figure or carry
    an explanation, and freezes the batch (database trigger).
    """

    __tablename__ = "opening_balance_batches"
    __table_args__ = (UniqueConstraint("company_id", "batch_number", name="uq_opening_batch_number"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"))
    financial_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_years.id"), nullable=False)
    batch_number: Mapped[str] = mapped_column(String(40), nullable=False)
    cutover_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=OB_DRAFT, nullable=False)
    #: What the figures came from — "Legacy TB signed 30-06-2026, file X".
    source_document: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    prepared_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    lines: Mapped[list["OpeningBalanceLine"]] = relationship(
        back_populates="batch", order_by="OpeningBalanceLine.row_number", passive_deletes=True)


class OpeningBalanceLine(UUIDPKMixin, Base):
    """One row of one opening schedule, holding both what the file said
    (codes, names, `raw`) and what it resolved to (ids), so a validation
    error can always be shown against the accountant's own wording.

    `amount` is signed on the account's normal side: a positive AR amount is
    owed to us, a negative one is a customer advance.
    """

    __tablename__ = "opening_balance_lines"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opening_balance_batches.id", ondelete="CASCADE"),
        nullable=False, index=True)
    schedule: Mapped[str] = mapped_column(String(12), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str | None] = mapped_column(String(30))
    account_name: Mapped[str | None] = mapped_column(String(200))
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"))
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    party_code: Mapped[str | None] = mapped_column(String(50))
    party_name: Mapped[str | None] = mapped_column(String(255))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"))
    item_code: Mapped[str | None] = mapped_column(String(40))
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"))
    location_name: Mapped[str | None] = mapped_column(String(150))
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id"))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    reference: Mapped[str | None] = mapped_column(String(100))
    document_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    bank_name: Mapped[str | None] = mapped_column(String(150))
    bank_account_number: Mapped[str | None] = mapped_column(String(60))
    statement_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    uncleared_deposits: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    uncleared_payments: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    branch_code: Mapped[str | None] = mapped_column(String(50))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"))
    raw: Mapped[dict | None] = mapped_column(JSONB)
    errors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    batch: Mapped[OpeningBalanceBatch] = relationship(back_populates="lines")


class OpeningBalanceImport(UUIDPKMixin, Base):
    """Each file loaded into a batch. The SHA-256 hash is how the same file
    is recognised if someone tries to load it into a second batch."""

    __tablename__ = "opening_balance_imports"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opening_balance_batches.id", ondelete="CASCADE"),
        nullable=False, index=True)
    schedule: Mapped[str] = mapped_column(String(12), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OpeningBalanceReconciliation(UUIDPKMixin, Base):
    """Legacy figure against ERP figure for one category of one batch.

    `legacy_balance` is typed from the approved legacy closing trial balance,
    not derived from the import, since checking an import against itself
    proves nothing. `erp_balance` is recomputed from the posted ledger every
    time the screen is loaded.
    """

    __tablename__ = "opening_balance_reconciliations"
    __table_args__ = (
        UniqueConstraint("batch_id", "category", name="uq_opening_reconciliation_category"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opening_balance_batches.id", ondelete="CASCADE"),
        nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    legacy_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    erp_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    difference: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    explanation: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
