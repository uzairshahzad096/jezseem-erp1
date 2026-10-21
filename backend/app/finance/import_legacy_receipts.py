"""
Post the previous ERP's receipt vouchers as customer receipts.

    python -m app.finance.import_legacy_receipts            # dry run: reports, changes nothing
    python -m app.finance.import_legacy_receipts --apply    # posts and commits

Source: `voucher_import_staging`, the voucher list exported from the old ERP.
Each row is one party and one amount; the old system holds no account lines.
What that allows, and what this script does:

  BANK / CASH RECEIPT VOUCHER, amount > 0, party matched to exactly one customer
      -> a customer receipt, posted through the normal receipt service:
             Dr  Bank (bank voucher) or Cash in Hand (cash voucher)
             Cr  Advances from Customers, for that customer
         The credit is an advance because the invoices these receipts paid are
         not in this ledger; nothing here guesses them. Once opening balances
         or invoices exist, the receipts are allocated like any other.

  BANK / CASH PAYMENT VOUCHER against a customer
      -> the same. In the old ERP these are customers' payments entered on the
         payment form: their narrations are instalments and "payment received
         against invoice", and for customers whose only credits they are
         (Sportica Group, Diamond Fabrics) they bring the balance to exactly
         zero. Posted on the owner's instruction of 12-Oct-2026.

  Everything else stays in staging, unposted, with the reason in `import_note`:
      the journal voucher     it has no second account
      zero-amount rows        blank vouchers
      the TEST voucher
      unmatched / ambiguous   the party is not (exactly one) customer here

Known limits of the source, carried into the ledger as they are:
  - A receipt marked "WITH HOLDING TAX DEDUCTION" shows the full invoice
    amount; the tax withheld is not split out, so Bank is debited in full.
  - Almost every voucher is "Unapproved" in the old ERP.

The financial years the vouchers fall in are created if missing. Each posted
receipt keeps the old voucher number as its reference and the old voucher id
in its notes, and the staging row records which receipt it became, so the
script can be run again without posting anything twice.

Authorised by the business owner on 12-Oct-2026 after the limits above were
set out. To undo a posting, reverse the receipt (Finance > Customer Receipts).
"""

import re
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text

from app.audit.service import AuditContext
from app.companies.models import Company, FinancialYear
from app.core.config import settings
from app.core.database import SessionLocal
from app.finance import periods
from app.finance.context import FinanceContext
from app.finance.models import Account, JournalEntry, JournalEntryLine
from app.partners.models import BusinessPartner
from app.receivables import receipts
from app.receivables.models import PaymentMethod
from app.users.models import User

RECEIPT_TYPES = {"BANK RECEIPT VOUCHER": "BANK_TRANSFER", "CASH RECEIPT VOUCHER": "CASH",
                 # Money from customers that the old ERP's staff keyed as payment vouchers.
                 "BANK PAYMENT VOUCHER": "BANK_TRANSFER", "CASH PAYMENT VOUCHER": "CASH",
                 # The one journal voucher (VEER SPORTS, JV10250001) credits the customer; the owner
                 # confirmed on 13-Oct-2026 that its other side is the bank.
                 "JOURNAL VOUCHER RECEIVABLE": "BANK_TRANSFER"}
# Parties the business owner said to leave out (12-Oct-2026): an old customer
# code with no customer behind it in this ERP.
SKIPPED_PARTIES = {"111112001237"}
SKIPPED_NOTE = "Not posted: skipped on the owner's instruction; this old customer code is not a customer in this ERP."


def _key(name: str | None) -> str:
    """Names compared without case, spacing or trailing punctuation:
    'Nizam Sons (Pvt) Ltd,' is 'NIZAM SONS (PVT) LTD'."""
    return re.sub(r"\s+", " ", (name or "")).strip(" ,.").lower()


def _financial_year(db, company_id, on: date, audit: AuditContext, created: list[str]) -> None:
    """Make sure a July-June year with open monthly periods covers the date."""
    for fy in db.scalars(select(FinancialYear).where(FinancialYear.company_id == company_id)):
        start, end = periods.fy_dates(fy)
        if start <= on <= end:
            return
    start_year = on.year if on.month >= 7 else on.year - 1
    name = f"{start_year}-{str(start_year + 1)[2:]}"
    periods.create_financial_year(db, company_id, name, date(start_year, 7, 1), date(start_year + 1, 6, 30),
                                  False, audit)
    db.flush()
    created.append(name)


def run(apply: bool) -> None:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
        user = db.scalar(select(User).where(User.username == settings.DEV_USER_USERNAME)) or db.scalar(
            select(User).where(User.is_superuser.is_(True)).limit(1))
        audit = AuditContext.for_user(user)
        ctx = FinanceContext(company_id=company.id, user=user, audit=audit, branch_id=None, branch_ids=None)

        # Where each staging row ended up. Added once; harmless if already there.
        for column in ("posted_receipt_id uuid", "posted_receipt_number text", "posted_at timestamptz",
                       "import_note text"):
            db.execute(text(f"alter table voucher_import_staging add column if not exists {column}"))

        methods = {m.code: m for m in db.scalars(select(PaymentMethod).where(
            PaymentMethod.company_id == company.id, PaymentMethod.is_active.is_(True)))}
        # The customer file holds accounts that differ only in capitals
        # ("Beacon Impex (Pvt) Ltd." and "BEACON IMPEX (PVT) LTD." are two
        # accounts). The old ERP printed the account's own name on the
        # voucher, so the exact spelling is tried first; the looser match is
        # used only when it points at one customer.
        by_exact: dict[str, list[BusinessPartner]] = defaultdict(list)
        by_name: dict[str, list[BusinessPartner]] = defaultdict(list)
        by_code: dict[str, BusinessPartner] = {}
        for p in db.scalars(select(BusinessPartner).where(BusinessPartner.company_id == company.id,
                                                         BusinessPartner.is_customer.is_(True))):
            by_exact[(p.name or "").strip()].append(p)
            by_name[_key(p.name)].append(p)
            by_code[p.code] = p

        rows = db.execute(text(
            "select source_voucher_id, voucher_number, voucher_date, voucher_type, customer_name, debit_total, "
            "credit_total, reference_number, narration, posted_receipt_id "
            "from voucher_import_staging order by voucher_date, source_voucher_id")).mappings().all()

        posted, skipped, years = [], defaultdict(list), []
        for r in rows:
            amount = Decimal(r["debit_total"] or 0)
            note = None
            if r["posted_receipt_id"]:
                skipped["already posted earlier"].append(r)
                continue
            if r["voucher_type"] not in RECEIPT_TYPES:
                note = "Not posted: a journal voucher needs a second account, which the old ERP export does not give."
            elif amount <= 0:
                note = "Not posted: blank voucher (no party, zero amount)."
            elif (r["narration"] or "").strip().upper() == "TEST":
                # Posted separately, as the old ledger carries it: see import_legacy_corrections.
                skipped["the TEST voucher, handled as a correction"].append(r)
                continue
            elif (r["customer_name"] or "").strip() in SKIPPED_PARTIES:
                note = SKIPPED_NOTE
            elif amount != Decimal(r["credit_total"] or 0):
                note = "Not posted: debit and credit totals differ."
            else:
                matches = by_exact.get((r["customer_name"] or "").strip(), [])
                if len(matches) != 1:
                    matches = by_name.get(_key(r["customer_name"]), [])
                if not matches and r["customer_name"] in by_code:
                    matches = [by_code[r["customer_name"]]]
                if not matches:
                    note = f"Not posted: '{r['customer_name']}' is not a customer in this ERP."
                elif len(matches) > 1:
                    note = (f"Not posted: {len(matches)} customers are called '{r['customer_name']}' "
                            f"({', '.join(m.code for m in matches)}); it is not clear which one paid.")
            if note:
                skipped[note.split(":")[1].split(";")[0].split("(")[0].strip()[:60]].append(r)
                db.execute(text("update voucher_import_staging set import_note = :n where source_voucher_id = :i"),
                           {"n": note, "i": r["source_voucher_id"]})
                continue

            customer = matches[0]
            _financial_year(db, company.id, r["voucher_date"], audit, years)
            method = methods[RECEIPT_TYPES[r["voucher_type"]]]
            old_reference = (r["reference_number"] or "").strip()
            receipt = receipts.create(db, ctx, {
                "customer_id": customer.id, "receipt_date": r["voucher_date"], "payment_method_id": method.id,
                "amount": amount, "currency": "PKR",
                # The old voucher number is how staff know this receipt.
                "reference": r["voucher_number"],
                "notes": "\n".join(x for x in (
                    f"Imported from the previous ERP: voucher {r['voucher_number']} (id {r['source_voucher_id']}).",
                    "Entered there as a payment voucher; it is money received from the customer."
                    if "PAYMENT" in r["voucher_type"] else
                    "Entered there as a journal voucher; the owner confirmed the bank as its other side."
                    if "JOURNAL" in r["voucher_type"] else None,
                    f"Old reference: {old_reference}" if old_reference else None,
                    (r["narration"] or "").strip() or None) if x),
            })
            receipts.post(db, ctx, receipt.id)
            db.execute(text(
                "update voucher_import_staging set posted_receipt_id = :rid, posted_receipt_number = :num, "
                "posted_at = now(), import_status = 'POSTED', import_note = :note where source_voucher_id = :i"),
                {"rid": receipt.id, "num": receipt.receipt_number, "i": r["source_voucher_id"],
                 "note": f"Posted as receipt {receipt.receipt_number} for {customer.code} {customer.name}."})
            posted.append((r, receipt, customer))
        db.flush()

        # ------------------------------------------------------------ report
        total = sum((Decimal(r["debit_total"]) for r, _, _ in posted), Decimal(0))
        print(f"\nPosted {len(posted)} receipts, PKR {total:,.2f}")
        for kind in RECEIPT_TYPES:
            part = [Decimal(r["debit_total"]) for r, _, _ in posted if r["voucher_type"] == kind]
            print(f"  {kind:<22} {len(part):>4}   {sum(part, Decimal(0)):>18,.2f}")
        if years:
            print("Financial years created:", ", ".join(dict.fromkeys(years)))
        print("\nLeft in staging, not posted:")
        for reason, items in sorted(skipped.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(items):>4}  {sum((Decimal(i['debit_total'] or 0) for i in items), Decimal(0)):>18,.2f}  {reason}")

        print("\nLedger after posting (posted journals only):")
        for code, name, debit, credit in db.execute(
                select(Account.code, Account.name, func_sum(JournalEntryLine.base_debit),
                       func_sum(JournalEntryLine.base_credit))
                .join(JournalEntryLine, JournalEntryLine.account_id == Account.id)
                .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
                .where(JournalEntry.company_id == company.id, JournalEntry.status == "POSTED")
                .group_by(Account.code, Account.name).order_by(Account.code)):
            print(f"  {code}  {name:<32} Dr {debit:>18,.2f}   Cr {credit:>18,.2f}")
        debit, credit, count = db.execute(
            select(func_sum(JournalEntry.total_debit), func_sum(JournalEntry.total_credit), func_count())
            .where(JournalEntry.company_id == company.id, JournalEntry.status == "POSTED")).one()
        print(f"  {count} journals   Dr {debit or 0:,.2f}   Cr {credit or 0:,.2f}   "
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


def func_sum(column):
    from sqlalchemy import func
    return func.coalesce(func.sum(column), 0)


def func_count():
    from sqlalchemy import func
    return func.count()


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
