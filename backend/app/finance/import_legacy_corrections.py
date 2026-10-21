"""
Ledger entries that bring a customer into line with the previous ERP's ledger.

    python -m app.finance.import_legacy_corrections            # dry run
    python -m app.finance.import_legacy_corrections --apply    # posts and commits

Each entry below was read off the old ERP's General Ledger for that customer
and approved by the business owner. Two kinds:

  INVOICE     an invoice on the old ledger that is in neither the sale order
              list nor this system. It is recorded as a posted sales order
              with its number, date and amount and no item lines, because the
              old ledger gives none. No stock moves.
  ADJUSTMENT  an invoice whose old-ledger amount differs from the sales order
              here. The difference is recorded as a debit note against that
              order, or a credit note when the old ledger is lower; the order
              itself is left as it is.

  DEBIT       any other debit the old ledger carries on the customer; recorded
              as a debit note under the number given.

An entry may name the account its credit goes to (the bank, for a debit that
cancels a receipt). Otherwise all post Dr Accounts Receivable (customer) / Cr Sales through the posting
engine. No sales tax is split out: the old ledger shows one amount.

An entry is recognised by its number in the receivables subledger, so the
script can be run again without posting anything twice.
"""

import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.audit.service import AuditContext
from app.companies.models import Company, FinancialYear
from app.finance import periods
from app.core.config import settings
from app.core.database import SessionLocal
from app.finance import posting
from app.finance.import_legacy_receipts import _financial_year
from app.finance.models import Account
from app.finance.posting import PostingRequest
from app.partners.models import BusinessPartner
from app.receivables import subledger
from app.receivables.models import CREDIT_NOTE, DEBIT_NOTE, INVOICE, KIND_AR, ARItem
from app.sales.models import (
    CREDIT_NOTE as DOC_CREDIT_NOTE, DEBIT_NOTE as DOC_DEBIT_NOTE, SALES_ORDER, SalesDocument,
)
from app.users.models import User

# (customer code, kind, old invoice number, date, amount, note)
ENTRIES = [
    # SADAQAT LIMITED — old ledger checked row by row on 12-Oct-2026 (127 rows,
    # closing 2,909,680.92).
    ("111112001227", "INVOICE", "202610122", date(2025, 4, 4), "534719.00", "old voucher SALV04250083"),
    ("111112001227", "INVOICE", "202610121", date(2025, 6, 2), "446316.00", "old voucher SALV06250063"),
    ("111112001227", "ADJUSTMENT", "202604141", date(2026, 4, 14), "11800.00",
     "old ledger 218,300.00, sales order 206,500.00"),
    ("111112001227", "ADJUSTMENT", "202607276", date(2026, 7, 27), "112336.00",
     "old ledger 224,672.00, sales order 112,336.00"),
    # JTEX INCORPORATON PVT LTD — old ledger checked row by row on 12-Oct-2026
    # (56 rows, closing 1,738,891.52).
    ("111112001238", "ADJUSTMENT", "202605194", date(2026, 5, 19), "-10332.00",
     "old ledger 57,400.00, sales order 67,732.00"),
    ("111112001238", "ADJUSTMENT", "202606162", date(2026, 6, 16), "16.52",
     "old ledger 159,316.52, sales order 159,300.00"),
    # OMBRE HOLDING (PVT) LTD. — old ledger checked row by row on 12-Oct-2026
    # (54 rows, closing 2,811,957.50).
    ("111112001229", "ADJUSTMENT", "202606111", date(2026, 6, 11), "88500.00",
     "old ledger 652,687.50, sales order 564,187.50"),
    # The owner's instruction for the next three: "create as same as old".
    ("111112001229", "INVOICE", "202610025", date(2026, 10, 2), "561680.00",
     "old voucher SALV10260011; same PO and amount as 202610029"),
    ("111112001229", "DEBIT", "202607212-OMBRE", date(2026, 7, 21), "94400.00",
     "old voucher SALV07260056: the old ledger carries invoice 202607212 on this customer; "
     "the sales order belongs to Nizam Sons"),
    ("111112001229", "DEBIT", "OPENING-OMBRE", date(2024, 6, 30), "1000.00",
     "opening balance at 1-Jul-2024 on the old ledger"),
    # Nizam Sons (Pvt) Ltd — old ledger checked row by row on 12-Oct-2026
    # (104 rows, closing 2,821,250.00).
    ("111112001241", "ADJUSTMENT", "202607192", date(2026, 7, 19), "75850.00",
     "old ledger 154,350.00, sales order 78,500.00"),
    ("111112001241", "ADJUSTMENT", "202609159", date(2026, 9, 15), "76550.00",
     "old ledger 251,600.00, sales order 175,050.00"),
    ("111112001241", "ADJUSTMENT", "202607212", date(2026, 7, 21), "-94400.00",
     "the old ledger carries this invoice on OMBRE HOLDING, not on this customer"),
    # Three Stars Hosiery MILLS (PVT) LIMITED — old ledger checked row by row
    # on 13-Oct-2026 (8 rows, closing 0).
    ("111112001132", "ADJUSTMENT", "202501304", date(2025, 1, 30), "-82800.00",
     "the old ledger does not carry this invoice, only the receipt against it"),
    # COLARO SPORTS — old ledger checked row by row on 13-Oct-2026 (6 rows, closing 1,000).
    ("111112000512", "ADJUSTMENT", "202604271", date(2026, 4, 27), "1000.00",
     "old ledger 35,000.00, sales order 34,000.00"),
    # FASHION & TRENDS (PVT) LTD. — old ledger checked row by row on 13-Oct-2026 (28 rows, closing 9,000).
    ("111112000595", "ADJUSTMENT", "202604031", date(2026, 4, 3), "2000.00",
     "old ledger 5,000.00, sales order 3,000.00"),
    # GULSHAN FABRICS — old ledger checked row by row on 13-Oct-2026 (10 rows, closing 0).
    ("111112000653", "ADJUSTMENT", "202603282", date(2026, 3, 28), "-11500.00",
     "the old ledger does not carry this invoice"),
    # HILTON ENTERPRISES — old ledger checked row by row on 13-Oct-2026 (16 rows, closing 75,000).
    ("111112000688", "ADJUSTMENT", "202608241", date(2026, 8, 24), "-2000.00",
     "old ledger 68,000.00, sales order 70,000.00"),
    # IQRA TEX. — old ledger checked row by row on 13-Oct-2026 (14 rows, closing 37,000).
    ("111112000723", "ADJUSTMENT", "202605071", date(2026, 5, 7), "2000.00",
     "old ledger 37,000.00, sales order 35,000.00"),
    ("111112000723", "ADJUSTMENT", "202610081", date(2026, 10, 8), "500.00",
     "old ledger 35,000.00, sales order 34,500.00"),
    # JAGUAR (PVT) LTD. — old ledger checked row by row on 13-Oct-2026 (9 rows, closing 142,000).
    ("111112000738", "ADJUSTMENT", "202605235", date(2026, 5, 23), "2000.00",
     "old ledger 70,000.00, sales order 68,000.00"),
    ("111112000738", "ADJUSTMENT", "202610051", date(2026, 10, 5), "4000.00",
     "old ledger 140,000.00, sales order 136,000.00"),
    # KAMAL TEXTILE MILLS (PVT) LTD — old ledger checked row by row on 13-Oct-2026 (27 rows, closing 610,178).
    ("111112000756", "DEBIT", "202609292-KTM", date(2026, 9, 29), "20.00",
     "old voucher SALV09260074: the old ledger carries invoice 202609292 on this customer; "
     "the sales order belongs to KAMAL LIMITED"),
    # KAY & EMMS (PVT) LTD. — old ledger checked row by row on 13-Oct-2026 (83 rows, closing 2,399,708).
    ("111112000766", "ADJUSTMENT", "202607019", date(2026, 7, 1), "-17994.00",
     "old ledger 6.00, sales order 18,000.00"),
    ("111112000766", "ADJUSTMENT", "202607061", date(2026, 7, 6), "2000.00",
     "old ledger 55,000.00, sales order 53,000.00"),
    ("111112000766", "ADJUSTMENT", "202609032", date(2026, 9, 3), "-84000.00",
     "the old ledger does not carry this invoice"),
    # SAPPHIRE FIBRES LTD. (SFL-Knits Division) — old ledger checked row by row on 13-Oct-2026
    # (20 rows, closing 254,536.68).
    ("111112001013", "ADJUSTMENT", "202603151", date(2026, 3, 15), "4396.68",
     "old ledger 25,636.68, sales order 21,240.00"),
    # SHAHKAM INDUSTRIES (PVT) LTD. — old ledger checked row by row on 13-Oct-2026
    # (17 rows, closing 5,994.99 credit).
    ("111112001039", "ADJUSTMENT", "202509035", date(2025, 9, 3), "-6000.00",
     "old ledger 150,000.00, sales order 156,000.00"),
    # KAMAL GARMENTS — old ledger checked row by row on 13-Oct-2026 (21 rows, closing 941,276).
    # The old ERP's "TEST" voucher debits this customer and credits the bank (its trial balance
    # shows the same 1,935,500 as the bank's only credit), cancelling receipt BRV01260045.
    ("111112001228", "DEBIT", "CRV09260004", date(2026, 9, 16), "1935500.00",
     "old voucher CRV09260004, narration TEST: debit to the customer, credit to the bank", "1121"),
    # KAMAL LIMITED — old ledger checked row by row on 13-Oct-2026 (45 rows, closing 2,174,324.84).
    ("111112001231", "ADJUSTMENT", "202501112", date(2025, 1, 11), "-14868.00",
     "old ledger 82,600.00, sales order 97,468.00"),
    ("111112001231", "ADJUSTMENT", "202505121", date(2025, 5, 12), "-23600.00",
     "old ledger 47,200.00, sales order 70,800.00"),
    ("111112001231", "ADJUSTMENT", "202604213", date(2026, 4, 21), "-9440.00",
     "old ledger 71,390.00, sales order 80,830.00"),
    ("111112001231", "ADJUSTMENT", "202605233", date(2026, 5, 23), "1180.00",
     "old ledger 82,010.00, sales order 80,830.00"),
    ("111112001231", "ADJUSTMENT", "202609292", date(2026, 9, 29), "-20.00",
     "the old ledger carries this invoice on KAMAL TEXTILE MILLS, not on this customer"),
    # Crescent Bahuman Ltd. — old ledger checked row by row on 13-Oct-2026 (35 rows, closing 317,061).
    ("111112001233", "ADJUSTMENT", "202610101", date(2026, 10, 9), "4720.00",
     "the old ledger carries the 9-Oct-2026 invoice as 202610093 at 238,006.00; sales order 233,286.00"),
    # BEACON IMPEX (PVT) LTD. (…1258) — old ledger checked row by row on 13-Oct-2026 (43 rows, closing 271,017.34).
    ("111112001258", "ADJUSTMENT", "202607042", date(2026, 7, 4), "73675.66",
     "old ledger 979,105.00, sales order 905,429.34"),
    # BEACON IMPEX (HAWK) — old ledger checked row by row on 13-Oct-2026 (14 rows, closing 180,504.60).
    ("111112001240", "ADJUSTMENT", "202501201", date(2025, 1, 20), "-1281.00",
     "the old ledger does not carry this invoice on this customer"),
    # SPRY SPORTS CORPORATION — old ledger checked row by row on 13-Oct-2026 (38 rows, closing 1,715,129).
    ("111112001257", "ADJUSTMENT", "202609192", date(2026, 9, 19), "-54200.00",
     "old ledger 54,200.00, sales order 108,400.00"),
    # Newways Industries. — old ledger checked row by row on 13-Oct-2026 (40 rows, closing 354,313).
    ("111112001261", "ADJUSTMENT", "202608252", date(2026, 8, 25), "6000.00",
     "old ledger 74,000.00, sales order 68,000.00"),
    # Nishat Mills Limited (Apparel Division 2). — old ledger checked row by row on 13-Oct-2026
    # (22 rows, closing 30,419.60 credit).
    ("111112001263", "ADJUSTMENT", "202607221", date(2026, 7, 22), "-30420.00",
     "old ledger 169,000.00, sales order 199,420.00"),
    # Chiniot Fabrics — old ledger checked row by row on 13-Oct-2026 (10 rows, closing 305,000).
    ("111112001269", "INVOICE", "202610132", date(2026, 10, 13), "5000.00",
     "old voucher SALV10260036; entered in the old ERP after the sale order list was exported"),
    # Swiss Pro — old ledger checked row by row on 13-Oct-2026 (15 rows, closing 63,000).
    ("111112001270", "ADJUSTMENT", "202603021", date(2026, 3, 2), "2000.00",
     "old ledger 70,000.00, sales order 68,000.00"),
    # US APPAREL AND TEXTILES (PVT) LTD — old ledger checked row by row on 13-Oct-2026 (16 rows, closing 18,324.36).
    ("111112001272", "ADJUSTMENT", "202505053", date(2025, 5, 5), "-7821.36",
     "old ledger 43,452.00, sales order 51,273.36"),
    ("111112001272", "ADJUSTMENT", "202601281", date(2026, 1, 28), "3000.00",
     "old ledger 20,000.00, sales order 17,000.00"),
    # Reemaxe group of industries — old ledger checked row by row on 13-Oct-2026 (4 rows, closing 8,000).
    ("111112001298", "ADJUSTMENT", "202609174", date(2026, 9, 17), "8000.00",
     "old ledger 74,000.00, sales order 66,000.00"),
    # GALAXY (LYP) APPAREL — old ledger checked row by row on 13-Oct-2026 (44 rows, closing 1,692,595.46).
    ("111112001301", "ADJUSTMENT", "202603111", date(2026, 3, 11), "-10206.00",
     "old ledger 56,700.00, sales order 66,906.00"),
    ("111112001301", "ADJUSTMENT", "202609193", date(2026, 9, 19), "-133812.00",
     "the old ledger does not carry this invoice"),
    ("111112001301", "ADJUSTMENT", "202609221", date(2026, 9, 22), "-187979.90",
     "old ledger 473,374.70, sales order 661,354.60"),
    ("111112001301", "ADJUSTMENT", "202609224", date(2026, 9, 22), "70000.00",
     "old ledger 70,000.00, sales order 0.00"),
    # Naeem Shafi (PVT) LTD. — old ledger checked row by row on 13-Oct-2026 (29 rows, closing 165,200).
    # The number 202610082 belongs to an ICON FASHION order here, so the entry carries a suffix.
    ("111112001302", "DEBIT", "202610082-NAEEM", date(2026, 10, 8), "82600.00",
     "old voucher SALV10260025: invoice 202610082 on the old ledger, PO 2610030012; not in this system"),
    # VEER SPORTS PVT. LIMITED — old ledger checked row by row on 13-Oct-2026 (20 rows, closing 0).
    ("111112001253", "ADJUSTMENT", "202504103", date(2025, 4, 10), "66600.00",
     "old ledger 74,000.00, sales order 7,400.00"),
    ("111112001240", "ADJUSTMENT", "202503261", date(2025, 3, 26), "-496.00",
     "the old ledger does not carry this invoice on this customer"),
]


def run(apply: bool) -> None:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
        user = db.scalar(select(User).where(User.username == settings.DEV_USER_USERNAME)) or db.scalar(
            select(User).where(User.is_superuser.is_(True)).limit(1))
        audit = AuditContext.for_user(user)
        for code, kind, invoice, on, amount, note, *contra in ENTRIES:
            amount = Decimal(amount)
            # The credit goes to Sales unless the entry names another account.
            overrides = {}
            if contra:
                overrides["revenue"] = db.scalar(select(Account.id).where(
                    Account.company_id == company.id, Account.code == contra[0]))
            customer = db.scalar(select(BusinessPartner).where(
                BusinessPartner.company_id == company.id, BusinessPartner.code == code))
            number = f"{invoice}-ADJ" if kind == "ADJUSTMENT" else invoice
            if db.scalar(select(ARItem.id).where(ARItem.company_id == company.id, ARItem.customer_id == customer.id,
                                                 ARItem.document_number == number)):
                print(f"  already posted   {number:<16} {customer.name}")
                continue
            _financial_year(db, company.id, on, audit, [])
            label = {"INVOICE": "Invoice", "ADJUSTMENT": "Adjustment to invoice", "DEBIT": "Debit"}[kind]
            year = next(fy for fy in db.scalars(select(FinancialYear).where(FinancialYear.company_id == company.id))
                        if periods.fy_dates(fy)[0] <= on <= periods.fy_dates(fy)[1])
            order = db.scalar(select(SalesDocument).where(
                SalesDocument.company_id == company.id, SalesDocument.doc_type == SALES_ORDER,
                SalesDocument.doc_number == invoice))
            if kind != "DEBIT" and (order is None) != (kind == "INVOICE"):
                raise SystemExit(f"{invoice}: {'already a sales order here' if order else 'no such sales order here'}")
            doc = SalesDocument(
                id=uuid.uuid4(), company_id=company.id, customer_id=customer.id, doc_number=number, doc_date=on,
                doc_type=SALES_ORDER if kind == "INVOICE" else DOC_DEBIT_NOTE if amount > 0 else DOC_CREDIT_NOTE,
                # A debit note is saved confirmed and becomes POSTED with its
                # journal in one step, as the database requires.
                status="Posted" if kind == "INVOICE" else "CONFIRMED",
                fiscal_year=year.name, financial_year_id=year.id, with_sales_tax=False, currency="PKR",
                exchange_rate=Decimal("1"), source_document_id=order.id if order else None,
                branch_id=order.branch_id if order else None,
                excluding_tax_value=abs(amount), gross_amount=abs(amount), net_receivable=abs(amount), due_date=on,
                remarks=f"From the previous ERP's ledger ({note}). No item lines: the old ledger gives none.",
                reason=None if kind == "INVOICE" else f"{invoice}: {note}.",
                created_by=user.id if user else None)
            db.add(doc)
            db.flush()
            journal = posting.post(db, PostingRequest(
                event_code="SALES_INVOICE_POSTED", company_id=company.id, journal_date=on, branch_id=doc.branch_id,
                description=f"{label} {invoice} — {customer.name} (previous ERP: {note})",
                document_type=("SALES_ORDER" if kind == "INVOICE" else
                               "SALES_DEBIT_NOTE" if amount > 0 else "SALES_CREDIT_NOTE"), document_id=doc.id,
                source_module="sales", source_reference=number,
                amounts={"receivable": amount, "revenue": amount}, customer_id=customer.id,
                account_overrides=overrides), audit)
            doc.journal_entry_id = journal.id
            doc.posted_by, doc.posted_at = (user.id if user else None), datetime.now(timezone.utc)
            if kind != "INVOICE":
                doc.status = "POSTED"
            item = subledger.record_item(
                db, company_id=company.id, branch_id=doc.branch_id, customer_id=customer.id,
                item_type=INVOICE if kind == "INVOICE" else DEBIT_NOTE if amount > 0 else CREDIT_NOTE,
                kind=KIND_AR, number=number,
                document_date=on, amount=amount, amount_base=amount, sales_document_id=doc.id,
                journal_entry_id=journal.id, user_id=user.id if user else None)
            db.flush()
            if amount < 0:
                # The credit comes straight off the invoice it corrects.
                subledger.allocate(db, audit, company.id, item.id, subledger.item_for_document(db, order.id).id,
                                   -amount, on, note="Correction to the previous ERP's amount")
            print(f"  posted {journal.journal_number}  {number:<16} {on:%d-%b-%Y} {amount:>14,.2f}  {customer.name}")
        if apply:
            db.commit()
            print("Committed.")
        else:
            db.rollback()
            print("Dry run: nothing was changed. Re-run with --apply to post.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
