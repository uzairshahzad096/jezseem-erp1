"""
The AR subledger: receivable items and their allocations.

An item's outstanding amount is always computed: amount less its active
allocations, optionally as at a past date. Nothing here writes a balance.
Any money moving between the receivable and advances accounts goes through
the posting engine, so the subledger and the general ledger cannot disagree
about where a customer's money sits.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.types import Date as SADate

from app.audit.service import AuditContext, record
from app.finance import posting
from app.finance.errors import FinanceError, db_guard
from app.finance.models import Account, JournalEntry
from app.finance.posting import PostingRequest, money
from app.receivables.models import (
    KIND_ADVANCE, KIND_AR, OPENING, ARAllocation, ARItem,
)

ZERO = Decimal("0")


# ------------------------------------------------------------ recording items

def record_item(db: Session, *, company_id, customer_id, item_type: str, kind: str, number: str,
                document_date: date, amount: Decimal, amount_base: Decimal,
                branch_id=None, due_date=None, currency="PKR", exchange_rate=Decimal("1"),
                sales_document_id=None, receipt_id=None, opening_line_id=None,
                journal_entry_id=None, user_id=None, service_invoice_id=None,
                journal_line_id=None) -> ARItem:
    item = ARItem(
        id=uuid.uuid4(), company_id=company_id, branch_id=branch_id, customer_id=customer_id,
        item_type=item_type, kind=kind, document_number=number, document_date=document_date,
        due_date=due_date or document_date, currency=currency, exchange_rate=exchange_rate,
        amount=money(amount), amount_base=money(amount_base), sales_document_id=sales_document_id,
        receipt_id=receipt_id, opening_line_id=opening_line_id, service_invoice_id=service_invoice_id,
        journal_entry_id=journal_entry_id, journal_line_id=journal_line_id,
        status="OPEN", created_by=user_id,
    )
    db.add(item)
    return item


def record_opening_items(db: Session, batch, journal, ctx: AuditContext | None) -> int:
    """Called when an opening batch posts: every customer line becomes an
    item. Lines on the advances account become ADVANCE items (money held for
    the customer), the rest AR items."""
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.company_id == batch.company_id))}
    count = 0
    for line in batch.lines:
        if line.schedule != "AR" or not line.customer_id or not line.amount:
            continue
        account = accounts.get(line.account_id)
        kind = KIND_ADVANCE if account and account.control_type == "CUSTOMER_ADVANCE" else KIND_AR
        record_item(
            db, company_id=batch.company_id, branch_id=line.branch_id or batch.branch_id,
            customer_id=line.customer_id, item_type=OPENING, kind=kind,
            number=line.reference or batch.batch_number,
            document_date=line.document_date or batch.cutover_date,
            due_date=line.due_date or line.document_date or batch.cutover_date,
            amount=line.amount, amount_base=line.amount, opening_line_id=line.id,
            journal_entry_id=journal.id, user_id=ctx.user_id if ctx else None)
        count += 1
    return count


# ------------------------------------------------------------ outstanding

def _alloc_active(as_of: date | None):
    """Allocations in force at the end of `as_of` (or now)."""
    if as_of is None:
        return ARAllocation.status == "ACTIVE"
    return and_(ARAllocation.allocation_date <= as_of,
                or_(ARAllocation.status == "ACTIVE",
                    cast(ARAllocation.reversed_at, SADate) > as_of))


def item_live(as_of: date | None):
    """Items that exist and are not cancelled at the end of `as_of`."""
    if as_of is None:
        return ARItem.status == "OPEN"
    return and_(ARItem.document_date <= as_of,
                or_(ARItem.status == "OPEN", cast(ARItem.cancelled_at, SADate) > as_of))


def allocated(db: Session, item_ids, side: str, as_of: date | None = None) -> dict[uuid.UUID, Decimal]:
    """Sum of allocations per item, on the debit side ("to") or credit side ("from")."""
    ids = list(item_ids)
    if not ids:
        return {}
    column = ARAllocation.to_item_id if side == "to" else ARAllocation.from_item_id
    rows = db.execute(select(column, func.sum(ARAllocation.amount))
                      .where(column.in_(ids), _alloc_active(as_of)).group_by(column)).all()
    return {item_id: Decimal(total or 0) for item_id, total in rows}


def open_amounts(db: Session, items: list[ARItem], as_of: date | None = None) -> dict[uuid.UUID, Decimal]:
    """Outstanding for debit items, unapplied (as a positive number) for credit items."""
    ids = [i.id for i in items]
    to_side = allocated(db, ids, "to", as_of)
    from_side = allocated(db, ids, "from", as_of)
    out = {}
    for item in items:
        if item.amount > 0:
            out[item.id] = item.amount - to_side.get(item.id, ZERO)
        else:
            out[item.id] = -item.amount - from_side.get(item.id, ZERO)
    return out


def items_for(db: Session, company_id: uuid.UUID, *, customer_id=None, as_of: date | None = None,
              branch_ids=None, branch_id=None) -> list[ARItem]:
    stmt = select(ARItem).where(ARItem.company_id == company_id, item_live(as_of))
    if customer_id:
        stmt = stmt.where(ARItem.customer_id == customer_id)
    if branch_ids is not None:
        stmt = stmt.where(ARItem.branch_id.in_(branch_ids))
    if branch_id:
        stmt = stmt.where(ARItem.branch_id == branch_id)
    return list(db.scalars(stmt.order_by(ARItem.document_date, ARItem.document_number)))


def item_for_document(db: Session, sales_document_id: uuid.UUID) -> ARItem | None:
    return db.scalar(select(ARItem).where(ARItem.sales_document_id == sales_document_id))


def balances(db: Session, company_id: uuid.UUID, *, customer_id=None, as_of: date | None = None,
             branch_ids=None, branch_id=None) -> dict[uuid.UUID, dict]:
    """Per customer, in company currency:
    receivable = debit outstanding − unapplied AR credits (the AR control account);
    advances   = unapplied ADVANCE credits (the advances account);
    overdue    = debit outstanding past its due date."""
    items = items_for(db, company_id, customer_id=customer_id, as_of=as_of,
                      branch_ids=branch_ids, branch_id=branch_id)
    open_ = open_amounts(db, items, as_of)
    today = as_of or date.today()
    out: dict[uuid.UUID, dict] = defaultdict(lambda: {
        "invoiced": ZERO, "credit_notes": ZERO, "receipts": ZERO, "receivable": ZERO,
        "advances": ZERO, "overdue": ZERO, "open_invoices": 0, "partly_paid": 0,
        # What the invoices still show unpaid, before any on-account money is
        # taken off, and receipts not yet matched to an invoice.
        "gross_outstanding": ZERO, "unallocated_receipts": ZERO})
    for item in items:
        row = out[item.customer_id]
        rate = item.exchange_rate or Decimal("1")
        value = money(open_[item.id] * rate)
        if item.amount > 0:
            row["invoiced"] += item.amount_base
            row["receivable"] += value
            row["gross_outstanding"] += value
            if open_[item.id] > 0:
                row["open_invoices"] += 1
                if open_[item.id] < item.amount:
                    row["partly_paid"] += 1
                if item.due_date and item.due_date < today:
                    row["overdue"] += value
        else:
            if item.item_type == "CREDIT_NOTE":
                row["credit_notes"] += -item.amount_base
            if item.item_type == "RECEIPT":
                row["receipts"] += -item.amount_base
                row["unallocated_receipts"] += value
            if item.kind == KIND_ADVANCE:
                row["advances"] += value
            else:
                row["receivable"] -= value
    for row in out.values():
        row["net_balance"] = row["receivable"] - row["advances"]
    return dict(out)


def exposure(db: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> Decimal:
    """What the customer owes now, net of money we hold for them."""
    row = balances(db, company_id, customer_id=customer_id).get(customer_id)
    return row["net_balance"] if row else ZERO


# ------------------------------------------------------------ allocation

def _lock(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, ARItem]:
    """Lock the items in a fixed order, so two allocations touching the same
    invoice queue instead of both passing the outstanding check."""
    rows = db.scalars(select(ARItem).where(ARItem.id.in_(ids)).order_by(ARItem.id).with_for_update()).all()
    return {r.id: r for r in rows}


def allocate(db: Session, ctx: AuditContext, company_id: uuid.UUID, from_item_id: uuid.UUID,
             to_item_id: uuid.UUID, amount, on: date, *, journal_posted: bool = False,
             note: str | None = None) -> ARAllocation:
    """Match a credit item (receipt, credit note, opening credit) against a
    debit item (invoice, debit note, opening receivable).

    `journal_posted` is set by receipt posting, whose own journal already
    credited the receivable for the allocated part.
    """
    amount = money(amount)
    if amount <= 0:
        raise FinanceError("The allocation amount must be greater than zero.")
    items = _lock(db, [from_item_id, to_item_id])
    source, target = items.get(from_item_id), items.get(to_item_id)
    if source is None or target is None or source.company_id != company_id or target.company_id != company_id:
        raise FinanceError("That receivable item does not exist.", 404)
    if source.customer_id != target.customer_id:
        raise FinanceError("A credit can only be allocated to the same customer's documents.")
    if source.status != "OPEN" or target.status != "OPEN":
        raise FinanceError("One of the documents is cancelled.")
    if source.amount >= 0:
        raise FinanceError(f"{source.document_number} is not a credit that can be allocated.")
    if target.amount <= 0:
        raise FinanceError(f"{target.document_number} is not an invoice or debit that can be paid.")
    if source.currency != target.currency:
        raise FinanceError("The receipt and the invoice are in different currencies.")
    if source.currency != "PKR" and source.exchange_rate != target.exchange_rate:
        raise FinanceError("Settling foreign-currency invoices at a different rate needs exchange "
                           "gain/loss accounting, which comes with multi-currency (a later phase).")

    open_ = open_amounts(db, [source, target])
    if amount > open_[target.id]:
        raise FinanceError(f"{target.document_number} has only {open_[target.id]:,.2f} outstanding; "
                           f"{amount:,.2f} cannot be allocated to it.")
    if amount > open_[source.id]:
        raise FinanceError(f"{source.document_number} has only {open_[source.id]:,.2f} left to allocate.")
    on = max(on, source.document_date, target.document_date)

    allocation_id = uuid.uuid4()
    journal_id = None
    # Money held as an advance moves onto the receivable it now settles. The
    # journal is posted first so the allocation row is written once, complete:
    # the database allows nothing but reversal to change it afterwards.
    if source.kind == KIND_ADVANCE and not journal_posted:
        journal = posting.post(db, PostingRequest(
            event_code="CUSTOMER_ADVANCE_ALLOCATED", company_id=company_id, journal_date=on,
            branch_id=target.branch_id,
            description=f"Advance {source.document_number} applied to {target.document_number}",
            document_type="AR_ALLOCATION", document_id=allocation_id,
            source_module="ar", source_reference=f"{source.document_number}→{target.document_number}",
            amounts={"advance": amount, "receivable": amount}, customer_id=source.customer_id,
            currency=source.currency, exchange_rate=source.exchange_rate,
        ), ctx)
        journal_id = journal.id

    allocation = ARAllocation(
        id=allocation_id, company_id=company_id, from_item_id=source.id, to_item_id=target.id,
        amount=amount, amount_base=money(amount * target.exchange_rate), allocation_date=on,
        journal_entry_id=journal_id, status="ACTIVE", reason=note,
        created_by=ctx.user_id if ctx else None)
    db.add(allocation)
    with db_guard(db):
        db.flush()

    record(db, ctx, action="allocate", module="receivables", entity="ar_allocations",
           entity_id=allocation.id, company_id=company_id,
           new_values={"from": source.document_number, "to": target.document_number,
                       "amount": amount, "date": on, "journal": allocation.journal_entry_id})
    return allocation


def unallocate(db: Session, ctx: AuditContext, company_id: uuid.UUID, allocation_id: uuid.UUID,
               reason: str) -> ARAllocation:
    """Undo an allocation. If the credit was an advance, its money goes back
    to the advances account through the posting engine."""
    allocation = db.scalar(select(ARAllocation).where(ARAllocation.id == allocation_id).with_for_update())
    if allocation is None or allocation.company_id != company_id:
        raise FinanceError("That allocation does not exist.", 404)
    if allocation.status != "ACTIVE":
        raise FinanceError("That allocation has already been undone.")
    if not reason or len(reason.strip()) < 3:
        raise FinanceError("Give a reason for undoing the allocation.")
    source = db.get(ARItem, allocation.from_item_id)
    target = db.get(ARItem, allocation.to_item_id)
    today = date.today()

    reversal_id = None
    if source.kind == KIND_ADVANCE:
        if allocation.journal_entry_id:
            original = db.get(JournalEntry, allocation.journal_entry_id)
            reversal = posting.reverse(db, original, max(today, original.journal_date), reason, ctx,
                                       allow_document=True)
            reversal_id = reversal.id
        else:
            # Allocated when the receipt posted, inside the receipt's own entry.
            journal = posting.post(db, PostingRequest(
                event_code="CUSTOMER_ADVANCE_ALLOCATED", company_id=company_id, journal_date=today,
                branch_id=target.branch_id,
                description=f"Unallocated {source.document_number} from {target.document_number}: {reason}",
                document_type="AR_ALLOCATION", document_id=allocation.id, source_module="ar",
                source_reference=f"{source.document_number}→{target.document_number}",
                amounts={"advance": -allocation.amount, "receivable": -allocation.amount},
                customer_id=source.customer_id, currency=source.currency,
                exchange_rate=source.exchange_rate,
            ), ctx)
            reversal_id = journal.id

    allocation.status = "REVERSED"
    allocation.reversed_at = datetime.now(timezone.utc)
    allocation.reversed_by = ctx.user_id if ctx else None
    allocation.reversal_journal_id = reversal_id
    allocation.reason = reason.strip()
    with db_guard(db):
        db.flush()
    record(db, ctx, action="unallocate", module="receivables", entity="ar_allocations",
           entity_id=allocation.id, company_id=company_id,
           old_values={"status": "ACTIVE"},
           new_values={"status": "REVERSED", "from": source.document_number, "to": target.document_number,
                       "amount": allocation.amount, "journal": reversal_id},
           reason=reason.strip())
    return allocation


def active_allocations(db: Session, item_id: uuid.UUID, side: str = "to") -> list[ARAllocation]:
    column = ARAllocation.to_item_id if side == "to" else ARAllocation.from_item_id
    return list(db.scalars(select(ARAllocation).where(column == item_id, ARAllocation.status == "ACTIVE")))


def cancel_item(db: Session, item: ARItem) -> None:
    item.status = "CANCELLED"
    item.cancelled_at = datetime.now(timezone.utc)
    with db_guard(db):
        db.flush()
