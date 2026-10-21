"""
Receivables master data for a company. Idempotent: anything that already
exists is left as the company set it.

Two defaults below are business decisions, so they are marked for
confirmation rather than assumed silently:
- the standard sales tax code at 18% (the rate on the existing documents);
- the default payment term (Due Immediately), since no customer in the
  imported data carries terms or credit days.
"""

import uuid
from datetime import date

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.audit.service import AuditContext, record
from app.finance import periods
from app.finance.models import POSTED, REVERSED, Account, JournalEntry, JournalEntryLine
from app.receivables.models import ARSettings, PaymentMethod, PaymentTerm, TaxCode

#: (code, name, days, is_cash, order)
PAYMENT_TERMS = [
    ("CASH", "Cash", 0, True, 10),
    ("IMMEDIATE", "Due Immediately", 0, False, 20),
    ("NET7", "7 Days", 7, False, 30),
    ("NET15", "15 Days", 15, False, 40),
    ("NET30", "30 Days", 30, False, 50),
    ("NET45", "45 Days", 45, False, 60),
    ("NET60", "60 Days", 60, False, 70),
]

#: (code, name, kind, requires reference, default account code, order)
PAYMENT_METHODS = [
    ("CASH", "Cash", "CASH", False, "1110", 10),
    ("BANK_TRANSFER", "Bank Transfer", "BANK", True, "1121", 20),
    ("CHEQUE", "Cheque", "CHEQUE", True, "1121", 30),
    ("ONLINE", "Online Transfer", "ONLINE", True, "1121", 40),
]

#: (code, name, type, rate, description)
TAX_CODES = [
    ("GST18", "Sales Tax 18%", "SALES_TAX", 18,
     "Standard rate as used on existing documents. REQUIRES BUSINESS CONFIRMATION of rate and "
     "applicability; change here, never in code."),
    ("EXEMPT", "Exempt", "EXEMPT", 0, "Exempt supply: no sales tax."),
    ("ZERO", "Zero-rated", "ZERO_RATED", 0, "Zero-rated supply (e.g. exports)."),
]


def install(db: Session, company_id: uuid.UUID, ctx: AuditContext | None) -> dict:
    user_id = ctx.user_id if ctx else None
    accounts = {a.code: a for a in db.scalars(select(Account).where(Account.company_id == company_id))}
    added = {"payment_terms": 0, "payment_methods": 0, "tax_codes": 0, "settings": 0, "advance_account": 0}

    have = set(db.scalars(select(PaymentTerm.code).where(PaymentTerm.company_id == company_id)))
    for code, name, days, cash, order in PAYMENT_TERMS:
        if code not in have:
            db.add(PaymentTerm(company_id=company_id, code=code, name=name, days=days, is_cash=cash,
                               sort_order=order, created_by=user_id))
            added["payment_terms"] += 1

    have = set(db.scalars(select(PaymentMethod.code).where(PaymentMethod.company_id == company_id)))
    for code, name, kind, needs_ref, account_code, order in PAYMENT_METHODS:
        if code not in have:
            account = accounts.get(account_code)
            db.add(PaymentMethod(company_id=company_id, code=code, name=name, kind=kind,
                                 requires_reference=needs_ref,
                                 default_account_id=account.id if account else None,
                                 sort_order=order, created_by=user_id))
            added["payment_methods"] += 1

    have = set(db.scalars(select(TaxCode.code).where(TaxCode.company_id == company_id)))
    for code, name, tax_type, rate, description in TAX_CODES:
        if code not in have:
            db.add(TaxCode(company_id=company_id, code=code, name=name, tax_type=tax_type, rate=rate,
                           description=description, created_by=user_id))
            added["tax_codes"] += 1
    db.flush()

    if db.scalar(select(ARSettings).where(ARSettings.company_id == company_id)) is None:
        fy = periods.current_year(db, company_id)
        immediate = db.scalar(select(PaymentTerm).where(PaymentTerm.company_id == company_id,
                                                        PaymentTerm.code == "IMMEDIATE"))
        db.add(ARSettings(
            company_id=company_id, credit_limit_policy="WARN",
            # Orders dated before the current financial year belong to the
            # old ERP and cannot be invoiced.
            sales_order_cutoff_date=periods.fy_dates(fy)[0] if fy else date.today(),
            allow_quotation_invoice=False,
            default_payment_term_id=immediate.id if immediate else None,
            created_by=user_id))
        added["settings"] = 1

    # Advances from customers becomes a customer-level control account, but
    # only while nothing has been posted to it without a customer.
    advance = accounts.get("2160")
    if advance is not None and advance.control_type is None:
        used = db.scalar(select(exists().where(
            JournalEntryLine.account_id == advance.id,
            JournalEntryLine.journal_entry_id == JournalEntry.id,
            JournalEntry.status.in_([POSTED, REVERSED]))))
        if not used:
            advance.control_type = "CUSTOMER_ADVANCE"
            advance.is_control_account = True
            advance.allow_manual_posting = False
            advance.description = "Control account: unallocated customer receipts, posted only with a customer."
            added["advance_account"] = 1

    if any(added.values()):
        record(db, ctx, action="create", module="receivables", entity="ar_setup",
               company_id=company_id, new_values=added, reason="Installed receivables master data")
    return added
