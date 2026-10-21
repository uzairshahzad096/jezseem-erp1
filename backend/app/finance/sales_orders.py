"""
A posted sales order is the invoice: its ledger entry, kept in step with its status.

As in the previous ERP, posting a sale order bills the customer. When an order
reaches Posted (or Delivered) it is posted through the posting engine, on its
own date, exactly as the old ERP's posted orders were brought over
(`import_legacy_sales`):

    Dr  Accounts Receivable, for the customer      net receivable
    Cr  Sales                                      value excluding tax
    Cr  Output Sales Tax                           sales tax, where there is any

with a receivable item under the order number so receipts can be matched to it.
Cancelling a posted order reverses that entry and cancels the item, unless a
receipt has already been matched to it. An order with a zero total has nothing
to post. Stock and cost of sales are not posted here.

A posted order's figures cannot change underneath its ledger entry: the
sales screen refuses an edit that would (see `figures`), so the order is
cancelled and entered again instead.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.audit.service import AuditContext
from app.finance import posting
from app.finance.errors import FinanceError
from app.finance.import_legacy_receipts import _financial_year
from app.finance.models import JournalEntry
from app.finance.posting import PostingRequest, money
from app.partners.models import BusinessPartner
from app.receivables import subledger
from app.receivables.models import INVOICE, KIND_AR, ARItem

IN_LEDGER = ("Posted", "Delivered")
ZERO = Decimal("0")


def figures(order) -> tuple:
    """What the ledger entry is made of; an edit may not change these once it is posted."""
    return (order.customer_id, order.doc_date, money(order.net_receivable or ZERO),
            money(order.excluding_tax_value or ZERO), money(order.sales_tax_value or ZERO),
            order.currency or "PKR", Decimal(str(order.exchange_rate or 1)))


def live_journal(db, order) -> JournalEntry | None:
    journal = db.get(JournalEntry, order.journal_entry_id) if order.journal_entry_id else None
    return journal if journal is not None and journal.status == "POSTED" else None


def sync(db, order, user) -> None:
    """Post or reverse the order's ledger entry to match its status. Call
    after the status is set and the totals worked out, before the commit."""
    audit = AuditContext.for_user(user)
    journal = live_journal(db, order)
    if order.status in IN_LEDGER and journal is None and order.journal_entry_id is None:
        _post(db, order, user, audit)
    elif order.status not in IN_LEDGER and journal is not None:
        _reverse(db, order, journal, audit)


def _post(db, order, user, audit) -> None:
    net, value, tax = money(order.net_receivable or ZERO), money(order.excluding_tax_value or ZERO), \
        money(order.sales_tax_value or ZERO)
    if net == 0:
        return
    if net < 0 or value < 0 or tax < 0:
        raise FinanceError("A sales order with negative totals cannot be posted to the ledger.")
    currency = order.currency or "PKR"
    rate = Decimal(str(order.exchange_rate or 0)) if currency != "PKR" else Decimal("1")
    if rate <= 0:
        raise FinanceError(f"Enter the exchange rate for {currency} before posting this order.")
    base = lambda v: money(v * rate)   # noqa: E731
    customer = db.get(BusinessPartner, order.customer_id)
    _financial_year(db, order.company_id, order.doc_date, audit, [])
    amounts = {"receivable": base(net), "revenue": base(net) - base(tax)}
    if tax:
        amounts["output_tax"] = base(tax)
    journal = posting.post(db, PostingRequest(
        event_code="SALES_INVOICE_POSTED", company_id=order.company_id, journal_date=order.doc_date,
        branch_id=order.branch_id, description=f"Invoice {order.doc_number} — {customer.name if customer else ''}",
        reference=order.customer_po_number, document_type="SALES_ORDER", document_id=order.id,
        source_module="sales", source_reference=order.doc_number,
        amounts=amounts, customer_id=order.customer_id), audit)
    subledger.record_item(
        db, company_id=order.company_id, branch_id=order.branch_id, customer_id=order.customer_id,
        item_type=INVOICE, kind=KIND_AR, number=order.doc_number, document_date=order.doc_date,
        due_date=order.due_date or order.doc_date, amount=net, amount_base=base(net),
        currency=currency, exchange_rate=rate, sales_document_id=order.id,
        journal_entry_id=journal.id, user_id=user.id)
    order.journal_entry_id = journal.id
    db.flush()


def _reverse(db, order, journal, audit) -> None:
    item = db.scalar(select(ARItem).where(ARItem.sales_document_id == order.id, ARItem.status == "OPEN"))
    if item is not None and subledger.active_allocations(db, item.id, "to"):
        raise FinanceError(f"Receipts are matched to {order.doc_number}. Undo those matches on the "
                           "receipts first, then cancel the order.")
    posting.reverse(db, journal, max(date.today(), journal.journal_date),
                    f"Sales order {order.doc_number} cancelled", audit, allow_document=True)
    if item is not None:
        subledger.cancel_item(db, item)
    db.flush()


def post_missing(db, company_id: uuid.UUID, user) -> list[str]:
    """Orders already Posted / Delivered that have no ledger entry yet."""
    from app.sales.models import SALES_ORDER, SalesDocument
    done = []
    for order in db.scalars(select(SalesDocument).where(
            SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
            SalesDocument.status.in_(IN_LEDGER), SalesDocument.journal_entry_id.is_(None))
            .order_by(SalesDocument.doc_date, SalesDocument.doc_number)):
        if money(order.net_receivable or ZERO) == 0:
            continue
        sync(db, order, user)
        done.append(order.doc_number)
    return done
