"""
Calibration / Services rules: document numbers, invoice totals, the next
billing period of a contract, and the ledger entry of a service invoice.

A service invoice bills the customer when it is posted, through the posting
engine, on its own date:

    Dr  Accounts Receivable, for the customer      net receivable
    Cr  Sales - Services (4200)                    value excluding tax
    Cr  Output Sales Tax                           sales tax, where there is any

with a receivable item under the invoice number, so it appears in the
customer's ledger, AR aging and Payment Receipts like any other invoice.
Cancelling a posted invoice reverses that entry and cancels the item, unless a
receipt has already been matched to it. A posted invoice's figures cannot be
edited; it is cancelled and entered again instead.
"""

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import AuditContext
from app.calibration.models import (
    BILLING_FREQUENCIES, CalibrationReport, ServiceContract, ServiceInvoice, ServiceInvoiceLine,
)
from app.common.calculations import LineInput, calculate_document
from app.common.numbering import next_number
from app.finance import posting
from app.finance.errors import FinanceError
from app.finance.import_legacy_receipts import _financial_year
from app.finance.models import Account, JournalEntry
from app.finance.posting import PostingRequest, money
from app.partners.models import BusinessPartner
from app.receivables import subledger
from app.receivables.models import INVOICE, KIND_AR, ARItem

ZERO = Decimal("0")
DOCUMENT_TYPE = "SERVICE_INVOICE"
SERVICE_REVENUE = "4200"

#: Prefix and the column holding the number, per numbered document.
NUMBERED = {
    "contract": ("CON", ServiceContract, "contract_number"),
    "invoice": ("SRV", ServiceInvoice, "invoice_number"),
    "certificate": ("CAL", CalibrationReport, "certificate_number"),
}


def allocate_number(db: Session, company_id: uuid.UUID, kind: str, on_date: date) -> str:
    """CON/1/2026/00009 — the previous ERP's form: prefix, 1, year, a
    five-digit counter that restarts each calendar year."""
    prefix, model, column = NUMBERED[kind]
    year = on_date.year
    head = f"{prefix}/1/{year}/"
    used = [n for (n,) in db.execute(select(getattr(model, column)).where(
        model.company_id == company_id, getattr(model, column).like(f"{head}%")))]
    highest = max((int(n[len(head):]) for n in used if n[len(head):].isdigit()), default=0)
    counter = next_number(db, company_id, f"svc_{kind}", str(year), continue_from=highest)
    return f"{head}{int(counter):05d}"


def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_period(db: Session, contract: ServiceContract) -> tuple[date, date]:
    """The billing period after the last one invoiced on this contract (or the
    first one, from the contract's start), one billing frequency long."""
    last = db.scalar(select(func.max(ServiceInvoice.period_to)).where(
        ServiceInvoice.contract_id == contract.id, ServiceInvoice.status != "Cancelled"))
    start = last + timedelta(days=1) if last else contract.start_date
    end = add_months(start, BILLING_FREQUENCIES.get(contract.billing_frequency, 1)) - timedelta(days=1)
    if contract.end_date and end > contract.end_date:
        end = contract.end_date
    return start, end


def apply_lines(invoice: ServiceInvoice, raw_lines: list[dict]) -> None:
    """Replace the invoice's lines and work out every figure from them."""
    if not raw_lines:
        raise FinanceError("Add at least one line to the invoice.")
    inputs = [LineInput(quantity=Decimal(str(l.get("quantity") or 0)),
                        unit_price=Decimal(str(l.get("unit_price") or 0)),
                        discount_percent=Decimal(str(l.get("discount_percent") or 0)),
                        tax_percent=Decimal(str(l.get("tax_percent") or 0))) for l in raw_lines]
    totals = calculate_document(inputs)
    invoice.lines.clear()
    for number, (raw, result) in enumerate(zip(raw_lines, totals.lines), start=1):
        if not (raw.get("description") or "").strip():
            raise FinanceError(f"Line {number} needs a description.")
        invoice.lines.append(ServiceInvoiceLine(
            line_number=number,
            customer_machine_id=_uuid(raw.get("customer_machine_id")),
            calibration_report_id=_uuid(raw.get("calibration_report_id")),
            description=raw["description"].strip(),
            quantity=Decimal(str(raw.get("quantity") or 0)),
            unit_price=Decimal(str(raw.get("unit_price") or 0)),
            discount_percent=Decimal(str(raw.get("discount_percent") or 0)),
            tax_percent=Decimal(str(raw.get("tax_percent") or 0)),
            gross_amount=result.gross_amount, discount_amount=result.discount_amount,
            taxable_amount=result.taxable_amount, tax_amount=result.tax_amount,
            net_amount=result.net_amount))
    invoice.excluding_tax_value = totals.excluding_tax_value
    invoice.sales_tax_value = totals.sales_tax_value
    invoice.gross_amount = totals.gross_amount
    invoice.discount_amount = totals.discount_total
    invoice.net_receivable = totals.net_receivable


def _uuid(value):
    return uuid.UUID(str(value)) if value else None


def figures(invoice: ServiceInvoice) -> tuple:
    """What the ledger entry is made of; an edit may not change these once it is posted."""
    return (invoice.customer_id, invoice.invoice_date, money(invoice.net_receivable or ZERO),
            money(invoice.excluding_tax_value or ZERO), money(invoice.sales_tax_value or ZERO),
            invoice.currency or "PKR", Decimal(str(invoice.exchange_rate or 1)))


def live_journal(db: Session, invoice: ServiceInvoice) -> JournalEntry | None:
    journal = db.get(JournalEntry, invoice.journal_entry_id) if invoice.journal_entry_id else None
    return journal if journal is not None and journal.status == "POSTED" else None


def post(db: Session, invoice: ServiceInvoice, user) -> None:
    """Bill the customer: the ledger entry and the receivable item."""
    if live_journal(db, invoice) is not None:
        raise FinanceError(f"{invoice.invoice_number} is already posted.")
    net, value, tax = (money(invoice.net_receivable), money(invoice.excluding_tax_value),
                       money(invoice.sales_tax_value))
    if net <= 0 or value < 0 or tax < 0:
        raise FinanceError("An invoice needs a total above zero to be posted.")
    currency = invoice.currency or "PKR"
    rate = Decimal(str(invoice.exchange_rate or 0)) if currency != "PKR" else Decimal("1")
    if rate <= 0:
        raise FinanceError(f"Enter the exchange rate for {currency} before posting this invoice.")
    base = lambda v: money(v * rate)   # noqa: E731
    audit = AuditContext.for_user(user)
    customer = db.get(BusinessPartner, invoice.customer_id)
    revenue_account = db.scalar(select(Account.id).where(
        Account.company_id == invoice.company_id, Account.code == SERVICE_REVENUE))
    if revenue_account is None:
        raise FinanceError(f"Account {SERVICE_REVENUE} Sales - Services is missing from the chart of accounts.")
    _financial_year(db, invoice.company_id, invoice.invoice_date, audit, [])
    amounts = {"receivable": base(net), "revenue": base(net) - base(tax)}
    if tax:
        amounts["output_tax"] = base(tax)
    journal = posting.post(db, PostingRequest(
        event_code="SALES_INVOICE_POSTED", company_id=invoice.company_id, journal_date=invoice.invoice_date,
        branch_id=invoice.branch_id,
        description=f"Service invoice {invoice.invoice_number} — {customer.name if customer else ''}",
        reference=invoice.customer_po_number, document_type=DOCUMENT_TYPE, document_id=invoice.id,
        source_module="calibration", source_reference=invoice.invoice_number,
        amounts=amounts, customer_id=invoice.customer_id,
        account_overrides={"revenue": revenue_account}), audit)
    subledger.record_item(
        db, company_id=invoice.company_id, branch_id=invoice.branch_id, customer_id=invoice.customer_id,
        item_type=INVOICE, kind=KIND_AR, number=invoice.invoice_number, document_date=invoice.invoice_date,
        due_date=invoice.due_date or invoice.invoice_date, amount=net, amount_base=base(net),
        currency=currency, exchange_rate=rate, journal_entry_id=journal.id, user_id=user.id,
        service_invoice_id=invoice.id)
    invoice.journal_entry_id = journal.id
    invoice.status = "Posted"
    invoice.posted_by, invoice.posted_at = user.id, datetime.now(timezone.utc)
    db.flush()


def cancel(db: Session, invoice: ServiceInvoice, user) -> None:
    """Reverse a posted invoice's entry and cancel its receivable item."""
    journal = live_journal(db, invoice)
    if journal is not None:
        item = db.scalar(select(ARItem).where(ARItem.journal_entry_id == journal.id, ARItem.status == "OPEN"))
        if item is not None and subledger.active_allocations(db, item.id, "to"):
            raise FinanceError(f"Receipts are matched to {invoice.invoice_number}. Undo those matches on the "
                               "receipts first, then cancel the invoice.")
        posting.reverse(db, journal, max(date.today(), journal.journal_date),
                        f"Service invoice {invoice.invoice_number} cancelled",
                        AuditContext.for_user(user), allow_document=True)
        if item is not None:
            subledger.cancel_item(db, item)
    invoice.status = "Cancelled"
    invoice.cancelled_by, invoice.cancelled_at = user.id, datetime.now(timezone.utc)
    db.flush()
