"""
General ledger, trial balance and the dashboard figures.

Everything here is computed from the lines of POSTED and REVERSED journals.
A reversed journal still counts, because its reversal is posted beside it and
the two cancel. DRAFT, SUBMITTED, APPROVED and CANCELLED journals never
appear. Nothing reads a stored balance, because there is none.

Until year-end closing exists (a later phase), an opening balance is
everything posted before the start date, for every account. That keeps the
trial balance balanced; the cost is that profit-and-loss accounts carry
their total across years rather than restarting each July.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, false, func, not_, or_, select, text, true
from sqlalchemy.orm import Session, aliased

from app.companies.models import Branch
from app.finance import periods
from app.finance.context import FinanceContext
from app.finance.errors import FinanceError
from app.finance.models import (
    APPROVED, CREDIT, DRAFT, POSTED, REVERSAL, REVERSED, SUBMITTED, Account, AccountingPeriod, AccountType,
    CostCenter, JournalEntry, JournalEntryLine, OB_POSTED, OB_VALIDATED, OpeningBalanceBatch,
)
from app.partners.models import BusinessPartner

ZERO = Decimal("0")
# The accounts that hold what a customer or supplier owes or is owed. A
# party's own ledger is its lines on these; the sales, tax and bank lines of
# the same journals also name the party but are not its balance.
PARTY_ACCOUNT_TYPES = ("RECEIVABLE", "CUSTOMER_ADVANCE", "PAYABLE")
LEDGER_STATUSES = (POSTED, REVERSED)


def _posted_lines(ctx: FinanceContext, branch_id: uuid.UUID | None = None):
    """Base query: lines of ledger journals, limited to the caller's company
    and branches."""
    stmt = (select(JournalEntryLine)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .where(JournalEntry.company_id == ctx.company_id,
                   JournalEntry.status.in_(LEDGER_STATUSES)))
    condition = ctx.branch_condition(JournalEntryLine.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if branch_id:
        ctx.check_branch(branch_id)
        stmt = stmt.where(JournalEntryLine.branch_id == branch_id)
    return stmt


def resolve_range(db: Session, ctx: FinanceContext, *, financial_year_id=None, period_id=None,
                  date_from: date | None = None, date_to: date | None = None) -> tuple[date | None, date | None]:
    """A period or year becomes its dates. Explicit dates narrow them."""
    start = end = None
    if period_id:
        period = db.get(AccountingPeriod, period_id)
        if period is None or period.company_id != ctx.company_id:
            raise FinanceError("That accounting period does not exist.", 404)
        start, end = period.period_start, period.period_end
    elif financial_year_id:
        from app.companies.models import FinancialYear
        fy = db.get(FinancialYear, financial_year_id)
        if fy is None or fy.company_id != ctx.company_id:
            raise FinanceError("That financial year does not exist.", 404)
        start, end = periods.fy_dates(fy)
    if date_from and (start is None or date_from > start):
        start = date_from
    if date_to and (end is None or date_to < end):
        end = date_to
    if start and end and end < start:
        raise FinanceError("The end date is before the start date.")
    return start, end


def _signed(balance: Decimal, normal: str) -> Decimal:
    """A debit-positive balance shown the way the account normally runs."""
    return -balance if normal == CREDIT else balance


# ------------------------------------------------------------ trial balance

def trial_balance(db: Session, ctx: FinanceContext, *, financial_year_id=None, period_id=None,
                  date_from=None, date_to=None, branch_id=None, include_zero=False,
                  by_customer=False) -> dict:
    """Opening, movement and closing per account. With `by_customer`, the
    receivable and customer-advance accounts are shown as one row per customer
    instead (the two netted, as the previous ERP's trial balance lists its
    customers), leaving on those accounts only lines that name no customer.
    Within one journal a customer's lines are netted, so moving money between
    their receivable and advance accounts is not shown as movement."""
    start, end = resolve_range(db, ctx, financial_year_id=financial_year_id, period_id=period_id,
                               date_from=date_from, date_to=date_to)
    lines = _posted_lines(ctx, branch_id).subquery()
    journals = aliased(JournalEntry)
    customer_accounts = select(Account.id).where(Account.company_id == ctx.company_id,
                                                 Account.control_type.in_(("RECEIVABLE", "CUSTOMER_ADVANCE")))
    date_col = journals.journal_date

    before = date_col < start if start else false()
    within = and_(date_col >= start if start else true(), date_col <= end if end else true())

    sums = db.execute(
        select(
            lines.c.account_id,
            func.sum(case((before, lines.c.base_debit), else_=0)),
            func.sum(case((before, lines.c.base_credit), else_=0)),
            func.sum(case((within, lines.c.base_debit), else_=0)),
            func.sum(case((within, lines.c.base_credit), else_=0)),
        )
        .join(journals, journals.id == lines.c.journal_entry_id)
        .where(date_col <= end if end else true(),
               # Customer lines on the party accounts are shown per customer below.
               not_(and_(lines.c.account_id.in_(customer_accounts), lines.c.customer_id.is_not(None)))
               if by_customer else true())
        .group_by(lines.c.account_id)
    ).all()
    by_account = {row[0]: row[1:] for row in sums}

    accounts = db.execute(
        select(Account, AccountType)
        .join(AccountType, AccountType.id == Account.account_type_id)
        .where(Account.company_id == ctx.company_id, Account.is_postable.is_(True))
        .order_by(Account.code)
    ).all()

    rows, totals = [], {k: ZERO for k in (
        "opening_debit", "opening_credit", "period_debit", "period_credit",
        "closing_debit", "closing_credit")}
    for account, account_type in accounts:
        od, oc, pd, pc = (Decimal(v or 0) for v in by_account.get(account.id, (0, 0, 0, 0)))
        opening = od - oc
        closing = opening + pd - pc
        if not include_zero and opening == 0 and pd == 0 and pc == 0:
            continue
        row = {
            "account_id": str(account.id), "account_code": account.code,
            "account_name": account.name, "account_type": account_type.code,
            "account_type_name": account_type.name, "normal_balance": account.normal_balance,
            "opening_debit": opening if opening > 0 else ZERO,
            "opening_credit": -opening if opening < 0 else ZERO,
            "period_debit": pd, "period_credit": pc,
            "closing_debit": closing if closing > 0 else ZERO,
            "closing_credit": -closing if closing < 0 else ZERO,
            # The spec's three columns: Debit / Credit are the closing
            # position, Balance is signed debit-positive.
            "debit": closing if closing > 0 else ZERO,
            "credit": -closing if closing < 0 else ZERO,
            "balance": closing,
        }
        for key in totals:
            totals[key] += row[key]
        rows.append(row)

    if by_customer:
        customer_rows = _customer_rows(db, ctx, lines, journals, customer_accounts, start, end, include_zero)
        receivable = db.scalar(select(Account).where(Account.company_id == ctx.company_id,
                                                     Account.control_type == "RECEIVABLE",
                                                     Account.is_postable.is_(True)).order_by(Account.code))
        kind = db.get(AccountType, receivable.account_type_id) if receivable else None
        for row in customer_rows:
            row.update(account_type=kind.code if kind else "ASSET", account_type_name=kind.name if kind else "Assets")
            for key in totals:
                totals[key] += row[key]
        # Every customer counts in the totals; only those with a balance are
        # listed (the owner's request), and a "Total Customers" line closes the
        # list with all of them added up, so the columns still reconcile.
        listed = customer_rows if include_zero else [r for r in customer_rows if r["balance"] != 0]
        if customer_rows:
            subtotal = {k: sum((r[k] for r in customer_rows), ZERO) for k in (
                "opening_debit", "opening_credit", "period_debit", "period_credit",
                "closing_debit", "closing_credit", "debit", "credit", "balance")}
            listed = listed + [{
                **subtotal, "account_id": "customer:total", "customer_id": None, "sub_group": "Customers",
                "is_subtotal": True, "account_code": "", "normal_balance": "DEBIT",
                "account_name": "Total Customers",
                "account_type": kind.code if kind else "ASSET", "account_type_name": kind.name if kind else "Assets",
            }]
        # In the chart's order, where the receivable account stands.
        at = next((n for n, r in enumerate(rows) if receivable and r["account_code"] >= receivable.code), len(rows))
        rows[at:at] = listed

    return {
        "date_from": start, "date_to": end,
        "rows": rows, "totals": totals,
        "is_balanced": (totals["closing_debit"] == totals["closing_credit"]
                        and totals["period_debit"] == totals["period_credit"]
                        and totals["opening_debit"] == totals["opening_credit"]),
        "difference": totals["closing_debit"] - totals["closing_credit"],
    }


def _customer_rows(db, ctx, lines, journals, customer_accounts, start, end, include_zero) -> list[dict]:
    from app.partners.models import BusinessPartner
    nets = db.execute(
        select(lines.c.customer_id, journals.journal_date,
               func.sum(lines.c.base_debit - lines.c.base_credit))
        .join(journals, journals.id == lines.c.journal_entry_id)
        .where(lines.c.account_id.in_(customer_accounts), lines.c.customer_id.is_not(None),
               journals.journal_date <= end if end else true())
        .group_by(lines.c.customer_id, journals.id, journals.journal_date)).all()
    figures: dict = {}
    for customer_id, on, net in nets:
        f = figures.setdefault(customer_id, [ZERO, ZERO, ZERO])   # opening, period Dr, period Cr
        net = Decimal(net or 0)
        if start and on < start:
            f[0] += net
        elif net > 0:
            f[1] += net
        else:
            f[2] += -net
    names = {p.id: p for p in db.scalars(select(BusinessPartner).where(BusinessPartner.id.in_(list(figures))))} \
        if figures else {}
    out = []
    for customer_id, (opening, pd, pc) in figures.items():
        closing = opening + pd - pc
        if not include_zero and opening == 0 and pd == 0 and pc == 0:
            continue
        p = names.get(customer_id)
        out.append({
            "account_id": f"customer:{customer_id}", "customer_id": str(customer_id), "sub_group": "Customers",
            "account_code": p.code if p else "", "account_name": p.name if p else "(unknown customer)",
            "normal_balance": "DEBIT",
            "opening_debit": opening if opening > 0 else ZERO, "opening_credit": -opening if opening < 0 else ZERO,
            "period_debit": pd, "period_credit": pc,
            "closing_debit": closing if closing > 0 else ZERO, "closing_credit": -closing if closing < 0 else ZERO,
            "debit": closing if closing > 0 else ZERO, "credit": -closing if closing < 0 else ZERO,
            "balance": closing,
        })
    out.sort(key=lambda r: r["account_name"].lower())
    return out


# ------------------------------------------------------------ general ledger
def general_ledger(db: Session, ctx: FinanceContext, account_id: uuid.UUID | None = None, *,
                   financial_year_id=None, period_id=None, date_from=None, date_to=None,
                   branch_id=None, cost_center_id=None, customer_id=None, supplier_id=None,
                   page: int = 1, page_size: int = 200) -> dict:
    """One account's lines, or one customer's (or supplier's) own account:
    their lines on the receivable, payable and advance accounts. With both,
    that party's lines on the one account."""
    account = party = None
    if account_id:
        account = db.get(Account, account_id)
        if account is None or account.company_id != ctx.company_id:
            raise FinanceError("That account does not exist.", 404)
    party_id = customer_id or supplier_id
    if party_id:
        party = db.get(BusinessPartner, party_id)
        if party is None or party.company_id != ctx.company_id:
            raise FinanceError("That customer or supplier does not exist.", 404)
    if account is None and party is None:
        raise FinanceError("Choose an account or a customer.")
    start, end = resolve_range(db, ctx, financial_year_id=financial_year_id, period_id=period_id,
                               date_from=date_from, date_to=date_to)

    base = _posted_lines(ctx, branch_id)
    if account:
        base = base.where(JournalEntryLine.account_id == account.id)
    else:
        base = base.where(JournalEntryLine.account_id.in_(party_accounts(ctx)))
    if cost_center_id:
        base = base.where(JournalEntryLine.cost_center_id == cost_center_id)
    for column, wanted in ((JournalEntryLine.customer_id, customer_id), (JournalEntryLine.supplier_id, supplier_id)):
        if not wanted:
            continue
        # The bank or cash line of a receipt does not name the customer; the
        # other side of the same journal does. A line with no party of its own
        # belongs to the party its journal was posted for.
        other = aliased(JournalEntryLine)
        other_column = other.customer_id if column is JournalEntryLine.customer_id else other.supplier_id
        base = base.where(or_(column == wanted, and_(
            JournalEntryLine.customer_id.is_(None), JournalEntryLine.supplier_id.is_(None),
            select(other.id).where(other.journal_entry_id == JournalEntryLine.journal_entry_id,
                                   other_column == wanted).exists())))

    if party:
        # A journal reversed on its own date and its reversal cancel within the
        # day; in a customer's or supplier's ledger the pair is left out, so a
        # corrected entry reads once. An account's ledger still shows both.
        twin = aliased(JournalEntry)
        base = base.where(~select(twin.id).where(
            twin.journal_date == JournalEntry.journal_date,
            or_(and_(JournalEntry.status == REVERSED, twin.id == JournalEntry.reversed_by_entry_id),
                and_(JournalEntry.journal_type == REVERSAL, twin.id == JournalEntry.reversed_entry_id))).exists())

    opening = _sum_before(db, base, start) if start else ZERO

    stmt = base.add_columns(JournalEntry)
    if start:
        stmt = stmt.where(JournalEntry.journal_date >= start)
    if end:
        stmt = stmt.where(JournalEntry.journal_date <= end)
    # Within a day, debits come before credits: an invoice and the receipt
    # that paid it the same day read in that order, whichever was keyed first.
    stmt = stmt.order_by(JournalEntry.journal_date, JournalEntryLine.base_debit == 0, JournalEntry.posted_at,
                         JournalEntry.journal_number, JournalEntryLine.line_number)
    results = db.execute(stmt).all()

    partner_ids = {pid for line, _ in results for pid in (line.customer_id, line.supplier_id) if pid}
    partners = {p.id: p.name for p in db.scalars(
        select(BusinessPartner).where(BusinessPartner.id.in_(partner_ids)))} if partner_ids else {}
    branch_names = {b.id: b.name for b in db.scalars(
        select(Branch).where(Branch.company_id == ctx.company_id))}
    center_names = {c.id: c.name for c in db.scalars(
        select(CostCenter).where(CostCenter.company_id == ctx.company_id))}
    account_ids = {line.account_id for line, _ in results}
    accounts = {a.id: a for a in db.scalars(
        select(Account).where(Account.id.in_(account_ids)))} if account_ids else {}

    details = _document_details(db, [journal for _, journal in results])

    running = opening
    rows = []
    total_dr = total_cr = ZERO
    for line, journal in results:
        detail = details.get(journal.id, {})
        total_dr += line.base_debit
        total_cr += line.base_credit
        # A receipt the customer withheld tax from reads as the previous ERP
        # shows it: what reached the bank, then the tax, both to their credit.
        withheld = detail.get("withheld")
        parts = [(line.base_debit, line.base_credit, None)]
        if withheld and (line.customer_id or line.supplier_id) and line.base_credit > withheld:
            parts = [(ZERO, line.base_credit - withheld, None), (ZERO, withheld, "WITH HOLDING TAX DEDUCTION")]
        for index, (debit, credit, label) in enumerate(parts):
            running += debit - credit
            narration = detail.get("narration") or journal.description or line.description
            if len(parts) > 1:
                narration = (narration or "").split(", =>")[0].strip()
            rows.append({
                "line_id": str(line.id) if index == 0 else f"{line.id}-wht",
                "journal_id": str(journal.id),
                "journal_number": journal.journal_number,
                "journal_date": journal.journal_date,
                "journal_type": journal.journal_type,
                "status": journal.status,
                "document_type": journal.document_type,
                "document_id": str(journal.document_id) if journal.document_id else None,
                "source_module": journal.source_module,
                "source_reference": journal.source_reference,
                "description": line.description or journal.description,
                "narration": label or narration,
                **{key: detail.get(key) for key in ("invoice_no", "voucher_no", "cheque_ref", "cheque_date")},
                "account_code": accounts[line.account_id].code,
                "account_name": accounts[line.account_id].name,
                "debit": debit, "credit": credit,
                "running_balance": running,
                "customer": partners.get(line.customer_id),
                "supplier": partners.get(line.supplier_id),
                "branch": branch_names.get(line.branch_id),
                "cost_center": center_names.get(line.cost_center_id),
            })

    total = len(rows)
    offset = (page - 1) * page_size
    return {
        "account": ({"id": str(account.id), "code": account.code, "name": account.name,
                     "normal_balance": account.normal_balance} if account else None),
        "party": ({"id": str(party.id), "code": party.code, "name": party.name,
                   "kind": "customer" if customer_id else "supplier"} if party else None),
        "date_from": start, "date_to": end,
        "opening_balance": opening,
        "total_debit": total_dr, "total_credit": total_cr,
        "closing_balance": running,
        "total": total, "page": page, "page_size": page_size,
        "rows": rows[offset: offset + page_size],
    }


def _document_details(db: Session, journals: list[JournalEntry]) -> dict[uuid.UUID, dict]:
    """What each journal was for, in the words of its document, laid out as
    the previous ERP's ledger lays it out: a sale's invoice number and its
    challan, customer PO and delivery person; a receipt's narration, cheque or
    reference, cheque date and voucher number. A journal with no document
    gets nothing here and keeps its own description."""
    from app.receivables.models import CustomerReceipt
    from app.sales.models import SALES_ORDER, SALES_INVOICE, SalesDocument

    sales: dict[uuid.UUID, uuid.UUID] = {}
    receipts: dict[uuid.UUID, uuid.UUID] = {}
    services: dict[uuid.UUID, uuid.UUID] = {}
    for journal in journals:
        if journal.document_id and journal.document_type == "CUSTOMER_RECEIPT":
            receipts[journal.document_id] = journal.id
        elif journal.document_id and journal.document_type == "SERVICE_INVOICE":
            services[journal.document_id] = journal.id
        elif journal.document_id and (journal.document_type or "").startswith("SALES_"):
            sales[journal.document_id] = journal.id
    out: dict[uuid.UUID, dict] = {}

    if sales:
        for doc in db.scalars(select(SalesDocument).where(SalesDocument.id.in_(sales))):
            if doc.doc_type in (SALES_ORDER, SALES_INVOICE):
                # Worded as the previous ERP's ledger words it.
                words = (f"SIN#: {doc.doc_number} DC NO:{doc.dc_number or ''}, "
                         f"PARTY PO(s):{doc.customer_po_number or ''} "
                         f"DELIVERY PERSON:{doc.delivery_person or ''}").strip()
            else:
                words = doc.reason or doc.remarks or doc.doc_number
            out[sales[doc.id]] = {"narration": words, "invoice_no": doc.doc_number}

    if services:
        from app.calibration.models import ServiceContract, ServiceInvoice
        for inv in db.scalars(select(ServiceInvoice).where(ServiceInvoice.id.in_(services))):
            contract = db.get(ServiceContract, inv.contract_id) if inv.contract_id else None
            period = (f" PERIOD:{inv.period_from:%d-%b-%Y} TO {inv.period_to:%d-%b-%Y}"
                      if inv.period_from and inv.period_to else "")
            words = (f"SRV#: {inv.invoice_number} {inv.service_type.upper()}"
                     + (f" CONTRACT:{contract.contract_number}" if contract else "") + period
                     + (f" PARTY PO(s):{inv.customer_po_number}" if inv.customer_po_number else ""))
            out[services[inv.id]] = {"narration": words, "invoice_no": inv.invoice_number}

    if receipts:
        found = {r.id: r for r in db.scalars(select(CustomerReceipt).where(CustomerReceipt.id.in_(receipts)))}
        # A receipt brought over from the previous ERP keeps that voucher's
        # number, reference and narration.
        old = {}
        columns = {c for (c,) in db.execute(text(
            "select column_name from information_schema.columns where table_name = 'voucher_import_staging'"))}
        if "posted_receipt_id" in columns:
            # The cheque date was read off the old ledger later and may not be there.
            cheque_date = "cheque_date" if "cheque_date" in columns else "null"
            withheld = "wht_amount" if "wht_amount" in columns else "null"
            old = {row[0]: row[1:] for row in db.execute(text(
                f"select posted_receipt_id, voucher_number, reference_number, narration, {cheque_date}, {withheld} "
                "from voucher_import_staging where posted_receipt_id = any(:ids)"), {"ids": list(receipts)})}
        # Which invoices each receipt has been matched to, as it stands now.
        from app.receivables.models import ARAllocation, ARItem
        source, target = aliased(ARItem), aliased(ARItem)
        paid: dict[uuid.UUID, list[tuple[str, Decimal]]] = {}
        for rid, number, amount in db.execute(
                select(source.receipt_id, target.document_number, ARAllocation.amount)
                .join(source, source.id == ARAllocation.from_item_id)
                .join(target, target.id == ARAllocation.to_item_id)
                .where(source.receipt_id.in_(receipts), ARAllocation.status == "ACTIVE")
                .order_by(ARAllocation.created_at)):
            paid.setdefault(rid, []).append((number, amount))

        def plain(amount: Decimal) -> str:
            return f"{amount:f}".rstrip("0").rstrip(".") if "." in f"{amount:f}" else f"{amount:f}"

        for rid, journal_id in receipts.items():
            receipt = found.get(rid)
            if receipt is None:
                continue
            number, reference, narration, old_cheque_date, withheld_tax = old.get(rid, (None,) * 5)
            imported = number is not None
            matched = paid.get(rid, [])
            if not imported:
                # Worded as the previous ERP words a receipt.
                narration = ("PAYMENT RECEIVED AGAINST INVOICES " + ", ".join(
                    f"{number}||{plain(amount)}" for number, amount in matched)) if matched else \
                    "PAYMENT RECEIVED ON ACCOUNT"
                if receipt.wht_amount:
                    narration += ", => WITH HOLDING TAX DEDUCTION"
                if (receipt.notes or "").strip():
                    narration += f" — {receipt.notes.strip()}"
            out[journal_id] = {
                "narration": (narration or "").strip() or None,
                "invoice_no": ", ".join(number for number, _ in matched) or None,
                "voucher_no": number or receipt.receipt_number,
                "cheque_ref": ((reference or "").strip() or None) if imported
                              else (receipt.cheque_number or receipt.reference),
                "cheque_date": old_cheque_date if imported else receipt.cheque_date,
                "withheld": (Decimal(withheld_tax) if withheld_tax else None) if imported
                            else (receipt.wht_amount or None),
            }
    return out


def party_accounts(ctx: FinanceContext):
    return select(Account.id).where(Account.company_id == ctx.company_id,
                                    Account.control_type.in_(PARTY_ACCOUNT_TYPES))


def _sum_before(db: Session, base, start: date) -> Decimal:
    sub = base.where(JournalEntry.journal_date < start).subquery()
    return Decimal(db.scalar(select(func.coalesce(func.sum(sub.c.base_debit - sub.c.base_credit), 0))) or 0)


# ------------------------------------------------------------ balances

def balances_by_control_type(db: Session, ctx: FinanceContext, as_of: date | None) -> dict[str, Decimal]:
    """Debit-positive balance per control type, e.g. {"CASH": 12000, "PAYABLE": -5000}."""
    stmt = (select(Account.control_type,
                   func.coalesce(func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit), 0))
            .select_from(JournalEntryLine)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .join(Account, Account.id == JournalEntryLine.account_id)
            .where(JournalEntry.company_id == ctx.company_id,
                   JournalEntry.status.in_(LEDGER_STATUSES),
                   Account.control_type.is_not(None))
            .group_by(Account.control_type))
    condition = ctx.branch_condition(JournalEntryLine.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if as_of:
        stmt = stmt.where(JournalEntry.journal_date <= as_of)
    return {code: Decimal(value) for code, value in db.execute(stmt).all()}


def balances_by_type(db: Session, ctx: FinanceContext, date_from: date | None,
                     date_to: date | None) -> dict[str, Decimal]:
    """Debit-positive movement per account type within a range."""
    stmt = (select(AccountType.code,
                   func.coalesce(func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit), 0))
            .select_from(JournalEntryLine)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .join(Account, Account.id == JournalEntryLine.account_id)
            .join(AccountType, AccountType.id == Account.account_type_id)
            .where(JournalEntry.company_id == ctx.company_id,
                   JournalEntry.status.in_(LEDGER_STATUSES))
            .group_by(AccountType.code))
    condition = ctx.branch_condition(JournalEntryLine.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if date_from:
        stmt = stmt.where(JournalEntry.journal_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.journal_date <= date_to)
    return {code: Decimal(value) for code, value in db.execute(stmt).all()}


# ------------------------------------------------------------ dashboard

# Parties whose balance the owner does not count as money owed by customers
# (asked 14-Oct-2026): staff, banks and the tax account kept as customers in
# the old ERP. Their entries stay in the ledger and trial balance; only the
# Receivables figure on the dashboards leaves them out. By code where they are
# in this system, and by name for those the old ERP had that are not here yet.
NOT_IN_RECEIVABLES_CODES = {"111112001248",        # Ali Raza Sialkot
                            "111112001250",        # Saqib Ali
                            "LEGACY-CUST-MWASIM"}  # M.WASIM
NOT_IN_RECEIVABLES_NAMES = ("naseem saki", "kaynet", "with holding tax", "withholding tax", "hbl",
                            "eden square", "eden sqaure")


def not_in_receivables(db: Session, ctx: FinanceContext, as_of: date) -> Decimal:
    """Ledger balance (receivable less advances) of the parties above."""
    from app.partners.models import BusinessPartner
    names = or_(*[func.lower(BusinessPartner.name).like(f"%{n}%") for n in NOT_IN_RECEIVABLES_NAMES])
    ids = list(db.scalars(select(BusinessPartner.id).where(
        BusinessPartner.company_id == ctx.company_id,
        or_(BusinessPartner.code.in_(NOT_IN_RECEIVABLES_CODES), names))))
    if not ids:
        return ZERO
    stmt = (select(func.coalesce(func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit), 0))
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .join(Account, Account.id == JournalEntryLine.account_id)
            .where(JournalEntry.company_id == ctx.company_id, JournalEntry.status.in_(LEDGER_STATUSES),
                   JournalEntry.journal_date <= as_of, JournalEntryLine.customer_id.in_(ids),
                   Account.control_type.in_(("RECEIVABLE", "CUSTOMER_ADVANCE"))))
    condition = ctx.branch_condition(JournalEntryLine.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    return Decimal(db.scalar(stmt) or 0)

def dashboard(db: Session, ctx: FinanceContext, today: date | None = None) -> dict:
    today = today or date.today()
    fy = periods.current_year(db, ctx.company_id)
    fy_start = periods.fy_dates(fy)[0] if fy else None
    period = db.scalar(select(AccountingPeriod).where(
        AccountingPeriod.company_id == ctx.company_id,
        AccountingPeriod.period_start <= today, AccountingPeriod.period_end >= today))

    control = balances_by_control_type(db, ctx, today)
    movement = balances_by_type(db, ctx, fy_start, today)
    revenue = -(movement.get("REVENUE", ZERO) + movement.get("OTHER_INCOME", ZERO))
    expenses = (movement.get("COST_OF_SALES", ZERO) + movement.get("EXPENSE", ZERO)
                + movement.get("OTHER_EXPENSE", ZERO))

    journal_scope = [JournalEntry.company_id == ctx.company_id]
    condition = ctx.branch_condition(JournalEntry.branch_id)
    if condition is not None:
        journal_scope.append(condition)

    def count(*where) -> int:
        return db.scalar(select(func.count()).select_from(JournalEntry).where(*journal_scope, *where)) or 0

    posted_count = count(JournalEntry.status.in_(LEDGER_STATUSES))
    opening_waiting = db.scalar(select(func.count()).select_from(OpeningBalanceBatch).where(
        OpeningBalanceBatch.company_id == ctx.company_id,
        OpeningBalanceBatch.status.in_([OB_VALIDATED, OB_POSTED]))) or 0

    return {
        "as_of": today,
        "financial_year": fy.name if fy else None,
        "current_period": ({"id": str(period.id), "name": period.name, "status": period.status}
                           if period else None),
        "has_postings": posted_count > 0,
        "posted_journals": posted_count,
        "cash": control.get("CASH", ZERO),
        "bank": control.get("BANK", ZERO),
        # What customers owe: the sum of their ledger balances, so receivables
        # less money received from them not yet matched to an invoice.
        "receivables": (control.get("RECEIVABLE", ZERO) + control.get("CUSTOMER_ADVANCE", ZERO)
                        - not_in_receivables(db, ctx, today)),
        "payables": -control.get("PAYABLE", ZERO),
        "inventory_value": control.get("INVENTORY", ZERO),
        "revenue": revenue,
        "expenses": expenses,
        "profit_loss": revenue - expenses,
        "pending": {
            "draft": count(JournalEntry.status == DRAFT),
            "submitted": count(JournalEntry.status == SUBMITTED),
            "approved_not_posted": count(JournalEntry.status == APPROVED),
            "opening_batches": opening_waiting,
        },
    }


# ------------------------------------------------------------ sales by month and year

SALES_EVENTS = ("SALES_INVOICE_POSTED", "SALES_CREDIT_NOTE_POSTED", "SALES_DEBIT_NOTE_POSTED")


def sales_summary(db: Session, ctx: FinanceContext) -> dict:
    """Sales from the ledger, by financial year and by month: what invoices,
    credit notes and debit notes put on the revenue accounts (net of returns)
    and on output sales tax. A reversed entry and its reversal are both in the
    ledger and cancel, so a cancelled or re-dated invoice counts once."""
    from app.companies.models import FinancialYear

    month = func.date_trunc("month", JournalEntry.journal_date)
    net = JournalEntryLine.base_credit - JournalEntryLine.base_debit
    stmt = (select(JournalEntry.financial_year_id, month,
                   func.coalesce(func.sum(case((AccountType.code == "REVENUE", net), else_=0)), 0),
                   func.coalesce(func.sum(case((AccountType.code == "LIABILITY", net), else_=0)), 0),
                   func.count(func.distinct(case((and_(JournalEntry.event_code == "SALES_INVOICE_POSTED",
                                                       JournalEntry.status == POSTED,
                                                       # adjustments to an invoice are not invoices
                                                       JournalEntry.document_type.in_(("SALES_ORDER", "SALES_INVOICE",
                                                                                       "SERVICE_INVOICE")),
                                                       JournalEntry.journal_type != REVERSAL),
                                                  JournalEntry.id)))))
            .select_from(JournalEntryLine)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .join(Account, Account.id == JournalEntryLine.account_id)
            .join(AccountType, AccountType.id == Account.account_type_id)
            .where(JournalEntry.company_id == ctx.company_id, JournalEntry.status.in_(LEDGER_STATUSES),
                   JournalEntry.event_code.in_(SALES_EVENTS))
            .group_by(JournalEntry.financial_year_id, month).order_by(month))
    condition = ctx.branch_condition(JournalEntryLine.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)

    names = {fy.id: fy for fy in db.scalars(select(FinancialYear).where(FinancialYear.company_id == ctx.company_id))}
    years: dict = {}
    for fy_id, first_day, sales, tax, invoices in db.execute(stmt):
        fy = names.get(fy_id)
        year = years.setdefault(fy_id, {
            "id": str(fy_id), "name": fy.name if fy else "—", "start": periods.fy_dates(fy)[0] if fy else None,
            "sales": ZERO, "sales_tax": ZERO, "total": ZERO, "invoices": 0, "months": []})
        sales, tax = Decimal(sales), Decimal(tax)
        year["months"].append({"month": first_day.date() if hasattr(first_day, "date") else first_day,
                               "sales": sales, "sales_tax": tax, "total": sales + tax, "invoices": invoices})
        year["sales"] += sales
        year["sales_tax"] += tax
        year["total"] += sales + tax
        year["invoices"] += invoices
    ordered = sorted(years.values(), key=lambda y: (y["start"] is None, y["start"]))
    return {"years": ordered,
            "totals": {k: sum((y[k] for y in ordered), ZERO if k != "invoices" else 0)
                       for k in ("sales", "sales_tax", "total", "invoices")}}


def journal_search_condition(search: str):
    like = f"%{search}%"
    return or_(JournalEntry.journal_number.ilike(like), JournalEntry.description.ilike(like),
               JournalEntry.reference.ilike(like), JournalEntry.source_reference.ilike(like))
