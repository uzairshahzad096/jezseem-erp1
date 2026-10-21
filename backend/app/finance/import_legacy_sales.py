"""
Post the previous ERP's posted sales orders to the ledger.

    python -m app.finance.import_legacy_sales            # dry run: reports, changes nothing
    python -m app.finance.import_legacy_sales --apply    # posts and commits

In the old ERP a posted sale order was the invoice: its number is the invoice
number on the customer's ledger and its total is the debit. Those orders are
already here as sales orders with status "Posted". This script gives each one
its ledger entry, on its own date, through the posting engine:

    Dr  Accounts Receivable, for the customer      net receivable
    Cr  Sales                                      value excluding tax
    Cr  Output Sales Tax                           sales tax, where the order has any

and a receivable item under the old invoice number, so receipts can be
allocated to it. The order's own totals are used as they stand; they are the
figures the old ledger shows.

Left alone:
  - Un-Posted orders and quotations: the old ledger does not carry them.
  - Orders with a zero total.
  - Stock and cost of sales: the goods left when the order was posted, and
    there is no cost basis to post.

The order records which journal it became (`journal_entry_id`), so the script
can be run again without posting anything twice, and such an order can no
longer be invoiced a second time from the Invoices screen.

Authorised by the business owner on 12-Oct-2026, after one customer's orders
were compared line by line with the old ERP's ledger.
"""

import sys
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, or_, select

from app.audit.service import AuditContext
from app.companies.models import Company
from app.core.config import settings
from app.core.database import SessionLocal
from app.finance import posting
from app.finance.context import FinanceContext
from app.finance.import_legacy_receipts import _financial_year
from app.finance.models import Account, JournalEntry, JournalEntryLine
from app.finance.posting import PostingRequest, money
from app.partners.models import BusinessPartner
from app.receivables import subledger
from app.receivables.models import INVOICE, KIND_AR
from app.sales.models import SALES_ORDER, SalesDocument
from app.users.models import User

ZERO = Decimal("0")
# Orders that were still Un-Posted when the sale order list was exported and have since been
# posted in the old ERP: its ledger now carries them (seen on the customer's ledger screen).
# They get their ledger entry here; the order's own status and stock are left to the Sales
# Orders screen.
POSTED_SINCE_EXPORT = {"202608231"}   # TMC PRIVATE LIMITED, 15-Sep-2026, 3,072,720.00


def run(apply: bool) -> None:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
        user = db.scalar(select(User).where(User.username == settings.DEV_USER_USERNAME)) or db.scalar(
            select(User).where(User.is_superuser.is_(True)).limit(1))
        audit = AuditContext.for_user(user)
        ctx = FinanceContext(company_id=company.id, user=user, audit=audit, branch_id=None, branch_ids=None)
        customers = {p.id: p for p in db.scalars(select(BusinessPartner).where(
            BusinessPartner.company_id == company.id))}

        orders = db.scalars(select(SalesDocument).where(
            SalesDocument.company_id == company.id, SalesDocument.doc_type == SALES_ORDER,
            or_(SalesDocument.status == "Posted", SalesDocument.doc_number.in_(POSTED_SINCE_EXPORT))).order_by(SalesDocument.doc_date, SalesDocument.doc_number)).all()

        posted, skipped, years = [], defaultdict(list), []
        for order in orders:
            net, value, tax = money(order.net_receivable), money(order.excluding_tax_value), money(order.sales_tax_value)
            if order.journal_entry_id:
                skipped["already in the ledger"].append(order)
                continue
            if net == 0:
                skipped["zero total"].append(order)
                continue
            if net < 0 or value < 0 or tax < 0 or net != value + tax or (order.currency or "PKR") != "PKR":
                skipped["totals do not add up"].append(order)
                continue
            customer = customers.get(order.customer_id)
            if customer is None:
                skipped["no customer"].append(order)
                continue

            _financial_year(db, company.id, order.doc_date, audit, years)
            amounts = {"receivable": net, "revenue": value}
            if tax:
                amounts["output_tax"] = tax
            journal = posting.post(db, PostingRequest(
                event_code="SALES_INVOICE_POSTED", company_id=company.id, journal_date=order.doc_date,
                branch_id=order.branch_id, description=f"Invoice {order.doc_number} — {customer.name}",
                reference=order.customer_po_number, document_type="SALES_ORDER", document_id=order.id,
                source_module="sales", source_reference=order.doc_number,
                amounts=amounts, customer_id=order.customer_id), audit)
            subledger.record_item(
                db, company_id=company.id, branch_id=order.branch_id, customer_id=order.customer_id,
                item_type=INVOICE, kind=KIND_AR, number=order.doc_number, document_date=order.doc_date,
                due_date=order.due_date or order.doc_date, amount=net, amount_base=net,
                sales_document_id=order.id, journal_entry_id=journal.id, user_id=ctx.user_id)
            order.journal_entry_id = journal.id
            posted.append(order)
        db.flush()

        # ------------------------------------------------------------ report
        print(f"\nPosted {len(posted)} sales orders, PKR {sum((o.net_receivable for o in posted), ZERO):,.2f}")
        print(f"  value excluding tax {sum((o.excluding_tax_value for o in posted), ZERO):>18,.2f}")
        print(f"  sales tax           {sum((o.sales_tax_value for o in posted), ZERO):>18,.2f}")
        if years:
            print("Financial years created:", ", ".join(dict.fromkeys(years)))
        print("\nNot posted:")
        for reason, items in sorted(skipped.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(items):>4}  {sum((i.net_receivable or ZERO for i in items), ZERO):>18,.2f}  {reason}")

        total = func.coalesce(func.sum(JournalEntryLine.base_debit), 0), func.coalesce(func.sum(JournalEntryLine.base_credit), 0)
        print("\nLedger after posting (posted journals only):")
        for code, name, debit, credit in db.execute(
                select(Account.code, Account.name, *total)
                .join(JournalEntryLine, JournalEntryLine.account_id == Account.id)
                .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
                .where(JournalEntry.company_id == company.id, JournalEntry.status == "POSTED")
                .group_by(Account.code, Account.name).order_by(Account.code)):
            print(f"  {code}  {name:<32} Dr {debit:>18,.2f}   Cr {credit:>18,.2f}")
        debit, credit, count = db.execute(
            select(func.coalesce(func.sum(JournalEntry.total_debit), 0),
                   func.coalesce(func.sum(JournalEntry.total_credit), 0), func.count())
            .where(JournalEntry.company_id == company.id, JournalEntry.status == "POSTED")).one()
        print(f"  {count} journals   Dr {debit:,.2f}   Cr {credit:,.2f}   "
              f"{'BALANCED' if debit == credit else 'OUT OF BALANCE'}")

        if apply:
            db.commit()
            print("\nCommitted.")
        else:
            db.rollback()
            print("\nDry run: nothing was changed. Re-run with --apply to post.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
