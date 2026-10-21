"""
Customer receipts.

DRAFT (with planned allocations) → POSTED → REVERSED. A draft no longer
wanted is CANCELLED.

Posting sends one entry through the posting engine:

    Dr Bank / Cash                          amount less tax withheld
    Dr Tax withheld by customer             tax withheld, if any
        Cr Accounts receivable              amount           (per customer)

The whole receipt is credited to the customer's receivable, whether or not it
names an invoice. A receipt with no invoice chosen is an ON-ACCOUNT receipt:
it brings the customer's net balance down and sits in the subledger as an
unallocated credit (kind AR). No invoice is marked paid until the receipt is
allocated, and allocating it later is bookkeeping in the subledger only: the
ledger already has the money against the customer, so nothing is posted
again. A receipt larger than what the customer owes leaves their account in
credit.

Reversal undoes every allocation and posts the mirror image of the receipt's
own entry, so the ledger ends exactly where it started.

Receipts posted before this rule (the ones brought over from the previous
ERP) are kind ADVANCE: their credit sits on the customer-advances account,
allocating them posts Dr Advances / Cr Receivable, and reversing them posts
Dr Advances / Cr Bank. Both kinds are handled below.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.audit.service import record
from app.common import currency as currency_codes
from app.finance import numbering, periods, posting
from app.finance.context import FinanceContext
from app.finance.errors import FinanceError, db_guard
from app.finance.models import Account
from app.finance.posting import PostingRequest, money
from app.receivables import subledger
from app.receivables.documents import require_customer
from app.receivables.models import (
    KIND_ADVANCE, KIND_AR, R_CANCELLED, R_DRAFT, R_POSTED, R_REVERSED, RECEIPT, ARItem, CustomerReceipt,
    PaymentMethod,
)

ZERO = Decimal("0")


def load(db, ctx: FinanceContext, receipt_id) -> CustomerReceipt:
    receipt = db.get(CustomerReceipt, receipt_id)
    if receipt is None or receipt.company_id != ctx.company_id:
        raise FinanceError("That receipt does not exist.", 404)
    if ctx.branch_ids is not None and receipt.branch_id not in ctx.branch_ids:
        raise FinanceError("That receipt does not exist.", 404)
    return receipt


def _plan(db, ctx: FinanceContext, customer_id, amount: Decimal, currency: str, planned: list[dict],
          on: date) -> list[dict]:
    """Validate planned allocations: the customer's own open invoices, each
    within what it still owes, and together within the receipt."""
    clean, total, seen = [], ZERO, set()
    for n, row in enumerate(planned or [], start=1):
        value = money(row.get("amount"))
        if value == 0:
            continue
        if value < 0:
            raise FinanceError(f"Allocation {n}: the amount cannot be negative.")
        item = db.get(ARItem, uuid.UUID(str(row["item_id"])))
        if item is None or item.company_id != ctx.company_id or item.customer_id != customer_id:
            raise FinanceError(f"Allocation {n}: that document does not belong to this customer.")
        if item.status != "OPEN" or item.amount <= 0:
            raise FinanceError(f"Allocation {n}: {item.document_number} cannot take a payment.")
        if item.currency != currency:
            raise FinanceError(f"Allocation {n}: {item.document_number} is in {item.currency}, the receipt in {currency}.")
        if item.document_date > on:
            raise FinanceError(f"Allocation {n}: {item.document_number} is dated after the receipt; post the "
                               "receipt first and allocate it once the document exists.")
        if item.id in seen:
            raise FinanceError(f"Allocation {n}: {item.document_number} is listed twice.")
        seen.add(item.id)
        outstanding = subledger.open_amounts(db, [item])[item.id]
        if value > outstanding:
            raise FinanceError(f"{item.document_number} has only {outstanding:,.2f} outstanding; "
                               f"{value:,.2f} cannot be allocated to it.")
        total += value
        clean.append({"item_id": str(item.id), "amount": str(value), "document_number": item.document_number})
    if total > amount:
        raise FinanceError(f"The allocations ({total:,.2f}) exceed the receipt ({amount:,.2f}).")
    return clean


def _fill(db, ctx: FinanceContext, receipt: CustomerReceipt, data: dict) -> None:
    customer = require_customer(db, ctx.company_id, data["customer_id"])
    method = db.get(PaymentMethod, data["payment_method_id"])
    if method is None or method.company_id != ctx.company_id or not method.is_active:
        raise FinanceError("Choose an active payment method.")
    account_id = data.get("deposit_account_id") or method.default_account_id
    account = db.get(Account, account_id) if account_id else None
    if (account is None or account.company_id != ctx.company_id or account.control_type not in ("CASH", "BANK")
            or not account.is_postable or not account.is_active):
        raise FinanceError("Choose the cash or bank account the money was received into.")
    if method.kind == "CASH" and account.control_type != "CASH":
        raise FinanceError("A cash receipt goes into a cash account.")
    amount = money(data["amount"])
    if amount <= 0:
        raise FinanceError("The amount must be greater than zero.")
    code = currency_codes.normalise(data.get("currency"))
    rate = Decimal(str(data.get("exchange_rate") or 1))
    if rate <= 0 or (code == "PKR" and rate != 1):
        raise FinanceError("A PKR receipt has an exchange rate of 1; others need a positive rate.")
    if method.kind == "CHEQUE" and not (data.get("cheque_number") or "").strip():
        raise FinanceError("Record the cheque number.")
    if method.requires_reference and method.kind != "CHEQUE" and not (data.get("reference") or "").strip():
        raise FinanceError(f"{method.name} needs a transaction reference.")
    periods.period_for_date(db, ctx.company_id, data["receipt_date"])

    receipt.customer_id = customer.id
    receipt.receipt_date = data["receipt_date"]
    receipt.branch_id = ctx.default_branch(data.get("branch_id"))
    receipt.payment_method_id = method.id
    receipt.deposit_account_id = account.id
    receipt.amount = amount
    receipt.currency = code
    receipt.exchange_rate = rate
    receipt.amount_base = money(amount * rate)
    withheld = money(data.get("wht_amount") or 0)
    if withheld < 0 or withheld >= amount:
        raise FinanceError("The tax withheld must be less than the amount the customer is credited with.")
    receipt.wht_amount = withheld
    receipt.reference = data.get("reference")
    receipt.cheque_number = data.get("cheque_number")
    receipt.cheque_date = data.get("cheque_date")
    receipt.bank_name = data.get("bank_name")
    receipt.notes = data.get("notes")
    receipt.planned_allocations = _plan(db, ctx, customer.id, amount, code, data.get("allocations") or [],
                                        data["receipt_date"])


def create(db, ctx: FinanceContext, data: dict) -> CustomerReceipt:
    fy = periods.year_for_date(db, ctx.company_id, data["receipt_date"])
    receipt = CustomerReceipt(id=uuid.uuid4(), company_id=ctx.company_id, financial_year_id=fy.id,
                              status=R_DRAFT, created_by=ctx.user_id)
    _fill(db, ctx, receipt, data)
    method = db.get(PaymentMethod, receipt.payment_method_id)
    series = "RV" if method.kind == "CASH" else "BRV"
    receipt.receipt_number = numbering.allocate(db, ctx.company_id, series, fy, receipt.branch_id)
    db.add(receipt)
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="create", module="receivables", entity="customer_receipts",
           entity_id=receipt.id, company_id=ctx.company_id,
           new_values={"number": receipt.receipt_number, "customer_id": receipt.customer_id,
                       "amount": receipt.amount, "allocations": receipt.planned_allocations})
    return receipt


def update(db, ctx: FinanceContext, receipt_id, data: dict) -> CustomerReceipt:
    receipt = load(db, ctx, receipt_id)
    if receipt.status != R_DRAFT:
        raise FinanceError(f"Receipt {receipt.receipt_number} is {receipt.status}; only a draft can be edited.")
    fy = periods.year_for_date(db, ctx.company_id, data["receipt_date"])
    if fy.id != receipt.financial_year_id:
        raise FinanceError("The new date is in another financial year; cancel this draft and enter it there.")
    method_before = db.get(PaymentMethod, receipt.payment_method_id)
    before = {"amount": receipt.amount, "date": receipt.receipt_date, "allocations": receipt.planned_allocations}
    _fill(db, ctx, receipt, data)
    method_after = db.get(PaymentMethod, receipt.payment_method_id)
    if (method_before.kind == "CASH") != (method_after.kind == "CASH"):
        raise FinanceError("Switching between cash and bank changes the voucher series; cancel this draft "
                           "and enter a new receipt.")
    receipt.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="update", module="receivables", entity="customer_receipts",
           entity_id=receipt.id, company_id=ctx.company_id, old_values=before,
           new_values={"amount": receipt.amount, "date": receipt.receipt_date,
                       "allocations": receipt.planned_allocations})
    return receipt


def post(db, ctx: FinanceContext, receipt_id) -> CustomerReceipt:
    receipt = load(db, ctx, receipt_id)
    if receipt.status != R_DRAFT:
        raise FinanceError(f"Receipt {receipt.receipt_number} is {receipt.status}.")
    require_customer(db, ctx.company_id, receipt.customer_id)
    # Re-check the plan now: other receipts may have paid those invoices since.
    plan = _plan(db, ctx, receipt.customer_id, receipt.amount, receipt.currency, receipt.planned_allocations,
                 receipt.receipt_date)
    allocated = sum((Decimal(p["amount"]) for p in plan), ZERO)
    unallocated = receipt.amount - allocated
    from app.partners.models import BusinessPartner
    customer = db.get(BusinessPartner, receipt.customer_id)

    withheld = receipt.wht_amount or ZERO
    amounts = {"bank_cash": receipt.amount - withheld, "receivable": receipt.amount}
    if withheld:
        amounts["wht"] = withheld
    journal = posting.post(db, PostingRequest(
        event_code="CUSTOMER_RECEIPT_POSTED", company_id=ctx.company_id, journal_date=receipt.receipt_date,
        branch_id=receipt.branch_id,
        description=f"Receipt {receipt.receipt_number} — {customer.name}",
        reference=receipt.cheque_number or receipt.reference, document_type="CUSTOMER_RECEIPT",
        document_id=receipt.id, source_module="ar", source_reference=receipt.receipt_number,
        amounts=amounts, customer_id=receipt.customer_id,
        account_overrides={"bank_cash": receipt.deposit_account_id},
        currency=receipt.currency, exchange_rate=receipt.exchange_rate,
    ), ctx.audit)

    item = subledger.record_item(
        db, company_id=ctx.company_id, branch_id=receipt.branch_id, customer_id=receipt.customer_id,
        item_type=RECEIPT, kind=KIND_AR, number=receipt.receipt_number,
        document_date=receipt.receipt_date, currency=receipt.currency, exchange_rate=receipt.exchange_rate,
        amount=-receipt.amount, amount_base=-receipt.amount_base, receipt_id=receipt.id,
        journal_entry_id=journal.id, user_id=ctx.user_id)
    with db_guard(db):
        db.flush()
    for p in plan:
        subledger.allocate(db, ctx.audit, ctx.company_id, item.id, uuid.UUID(p["item_id"]),
                           Decimal(p["amount"]), receipt.receipt_date, journal_posted=True)

    receipt.status = R_POSTED
    receipt.journal_entry_id = journal.id
    receipt.posted_by = ctx.user_id
    receipt.posted_at = datetime.now(timezone.utc)
    receipt.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="post", module="receivables", entity="customer_receipts",
           entity_id=receipt.id, company_id=ctx.company_id, old_values={"status": R_DRAFT},
           new_values={"status": R_POSTED, "journal": journal.journal_number, "allocated": allocated,
                       "on_account": unallocated, "tax_withheld": withheld})
    return receipt


def receipt_item(db, receipt: CustomerReceipt) -> ARItem | None:
    return db.scalar(select(ARItem).where(ARItem.receipt_id == receipt.id))


def allocate(db, ctx: FinanceContext, receipt_id, allocations: list[dict], on: date | None = None):
    """Allocate what is left of a posted receipt to further invoices."""
    receipt = load(db, ctx, receipt_id)
    if receipt.status != R_POSTED:
        raise FinanceError(f"Receipt {receipt.receipt_number} is {receipt.status}; only a posted receipt "
                           "can be allocated. Plan allocations on a draft instead.")
    item = receipt_item(db, receipt)
    created = []
    for row in allocations:
        created.append(subledger.allocate(db, ctx.audit, ctx.company_id, item.id, uuid.UUID(str(row["item_id"])),
                                          row["amount"], on or date.today()))
    return created


def cancel(db, ctx: FinanceContext, receipt_id, reason: str) -> CustomerReceipt:
    receipt = load(db, ctx, receipt_id)
    if receipt.status != R_DRAFT:
        raise FinanceError("Only a draft receipt can be cancelled; reverse a posted one.")
    receipt.status = R_CANCELLED
    receipt.cancelled_by = ctx.user_id
    receipt.cancelled_at = datetime.now(timezone.utc)
    receipt.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="cancel", module="receivables", entity="customer_receipts",
           entity_id=receipt.id, company_id=ctx.company_id, old_values={"status": R_DRAFT},
           new_values={"status": R_CANCELLED}, reason=reason)
    return receipt


def reverse(db, ctx: FinanceContext, receipt_id, reason: str) -> CustomerReceipt:
    receipt = load(db, ctx, receipt_id)
    if receipt.status != R_POSTED:
        raise FinanceError(f"Receipt {receipt.receipt_number} is {receipt.status}; only a posted receipt can be reversed.")
    if not reason or len(reason.strip()) < 3:
        raise FinanceError("Give a reason for the reversal (bounced cheque, entered twice, …).")
    item = receipt_item(db, receipt)
    for allocation in subledger.active_allocations(db, item.id, side="from"):
        subledger.unallocate(db, ctx.audit, ctx.company_id, allocation.id,
                             f"Receipt {receipt.receipt_number} reversed")
    today = max(date.today(), receipt.receipt_date)
    if item.kind == KIND_AR:
        # The receipt's own entry holds everything (bank, tax withheld, the
        # customer's credit), so its mirror image undoes all of it.
        from app.finance.models import JournalEntry
        journal = posting.reverse(db, db.get(JournalEntry, receipt.journal_entry_id), today,
                                  f"Receipt {receipt.receipt_number} reversed: {reason.strip()}", ctx.audit,
                                  allow_document=True)
    else:
      journal = posting.post(db, PostingRequest(
            event_code="CUSTOMER_RECEIPT_REVERSED", company_id=ctx.company_id, journal_date=today,
            branch_id=receipt.branch_id,
            description=f"Reversal of receipt {receipt.receipt_number}: {reason.strip()}",
            document_type="CUSTOMER_RECEIPT", document_id=receipt.id, source_module="ar",
            source_reference=receipt.receipt_number,
            amounts={"advance": receipt.amount, "bank_cash": receipt.amount}, customer_id=receipt.customer_id,
            account_overrides={"bank_cash": receipt.deposit_account_id},
            currency=receipt.currency, exchange_rate=receipt.exchange_rate,
        ), ctx.audit)
    subledger.cancel_item(db, item)
    receipt.status = R_REVERSED
    receipt.reversal_journal_id = journal.id
    receipt.reversed_by = ctx.user_id
    receipt.reversed_at = datetime.now(timezone.utc)
    receipt.reverse_reason = reason.strip()
    receipt.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="reverse", module="receivables", entity="customer_receipts",
           entity_id=receipt.id, company_id=ctx.company_id, old_values={"status": R_POSTED},
           new_values={"status": R_REVERSED, "journal": journal.journal_number}, reason=reason.strip())
    return receipt


def summary(db, receipt: CustomerReceipt) -> dict:
    item = receipt_item(db, receipt) if receipt.status in (R_POSTED, R_REVERSED) else None
    if item is None:
        planned = sum((Decimal(p["amount"]) for p in receipt.planned_allocations or []), ZERO)
        return {"allocated": planned, "unallocated": receipt.amount - planned,
                "allocation_status": "PLANNED" if planned else "UNALLOCATED"}
    unapplied = subledger.open_amounts(db, [item])[item.id] if item.status == "OPEN" else ZERO
    allocated = receipt.amount - unapplied if item.status == "OPEN" else ZERO
    status = ("REVERSED" if receipt.status == R_REVERSED else
              "FULLY_ALLOCATED" if unapplied == 0 else "PARTLY_ALLOCATED" if allocated else "UNALLOCATED")
    return {"allocated": allocated, "unallocated": unapplied, "allocation_status": status}
