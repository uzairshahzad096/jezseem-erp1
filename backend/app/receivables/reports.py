"""
Receivables reports.

Where each figure comes from:
- Customer statement: ledger lines on the receivable and customer-advance
  accounts that carry the customer.
- Sales summary / dashboard sales: revenue lines, which carry the customer
  and the product because invoices post revenue per line.
- Aging and balances: the subledger, which is written only by posting.
- Reconciliation: subledger against ledger, per customer and in total.

Registers list documents, since that is what a register is, with their
posting status and journal number beside them.
"""

import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import case, func, or_, select, text

from app.finance import ledger
from app.finance.context import FinanceContext
from app.finance.errors import FinanceError
from app.finance.models import Account, AccountType, JournalEntry, JournalEntryLine
from app.inventory.models import InventoryItem
from app.partners.models import BusinessPartner
from app.receivables import subledger
from app.receivables.documents import payment_state
from app.receivables.models import ARItem, ARSettings, CustomerReceipt, PaymentMethod
from app.receivables.receipts import summary as receipt_summary
from app.sales.models import SalesDocument

ZERO = Decimal("0")
STATEMENT_CONTROLS = ("RECEIVABLE", "CUSTOMER_ADVANCE")


def _names(db, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {p.id: p for p in db.scalars(select(BusinessPartner).where(BusinessPartner.id.in_(ids)))}


# ------------------------------------------------------------ statement

def statement(db, ctx: FinanceContext, customer_id: uuid.UUID, date_from: date | None, date_to: date | None,
              branch_id=None, currency: str | None = None) -> dict:
    customer = db.get(BusinessPartner, customer_id)
    if customer is None or customer.company_id != ctx.company_id:
        raise FinanceError("That customer does not exist.", 404)
    base = (select(JournalEntryLine, JournalEntry, Account)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .join(Account, Account.id == JournalEntryLine.account_id)
            .where(JournalEntry.company_id == ctx.company_id,
                   JournalEntry.status.in_(ledger.LEDGER_STATUSES),
                   JournalEntryLine.customer_id == customer_id,
                   Account.control_type.in_(STATEMENT_CONTROLS)))
    condition = ctx.branch_condition(JournalEntryLine.branch_id)
    if condition is not None:
        base = base.where(condition)
    if branch_id:
        ctx.check_branch(branch_id)
        base = base.where(JournalEntryLine.branch_id == branch_id)
    if currency:
        base = base.where(JournalEntryLine.currency == currency)

    opening = ZERO
    if date_from:
        sub = base.where(JournalEntry.journal_date < date_from).subquery()
        opening = Decimal(db.scalar(select(func.coalesce(
            func.sum(sub.c.base_debit - sub.c.base_credit), 0))) or 0)
    stmt = base
    if date_from:
        stmt = stmt.where(JournalEntry.journal_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.journal_date <= date_to)
    rows = db.execute(stmt.order_by(JournalEntry.journal_date, JournalEntry.posted_at,
                                    JournalEntry.journal_number, JournalEntryLine.line_number)).all()

    running, out, total_dr, total_cr = opening, [], ZERO, ZERO
    for line, journal, account in rows:
        running += line.base_debit - line.base_credit
        total_dr += line.base_debit
        total_cr += line.base_credit
        out.append({
            "date": journal.journal_date, "journal_id": str(journal.id), "journal_number": journal.journal_number,
            "document_type": journal.document_type,
            "document_id": str(journal.document_id) if journal.document_id else None,
            "document": journal.source_reference or journal.journal_number,
            "reference": journal.reference,
            "description": journal.description if journal.journal_type != "REVERSAL" else journal.description,
            "account": "Advance" if account.control_type == "CUSTOMER_ADVANCE" else "Receivable",
            "debit": line.base_debit, "credit": line.base_credit, "balance": running,
        })
    return {"customer": {"id": str(customer.id), "code": customer.code, "name": customer.name,
                         "address": customer.address, "ntn": customer.ntn},
            "date_from": date_from, "date_to": date_to, "opening_balance": opening,
            "total_debit": total_dr, "total_credit": total_cr, "closing_balance": running, "rows": out}


# ------------------------------------------------------------ aging

def money_2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _old_narrations(db, receipt_ids) -> dict:
    """Narration of the previous ERP's voucher, for receipts that came from one."""
    if not receipt_ids:
        return {}
    columns = {c for (c,) in db.execute(text(
        "select column_name from information_schema.columns where table_name = 'voucher_import_staging'"))}
    if "posted_receipt_id" not in columns:
        return {}
    return {rid: narration for rid, narration in db.execute(text(
        "select posted_receipt_id, narration from voucher_import_staging where posted_receipt_id = any(:ids)"),
        {"ids": list(receipt_ids)})}


def invoices_named(narration: str, known) -> list[tuple[str, Decimal | None]]:
    """Invoices and amounts in a narration such as
    "PAYMENT RECEIVED AGAINST INVOICES 202511052||34680202511112||34680".
    The old ERP runs one amount straight into the next invoice number, so the
    text is read against the customer's own invoice numbers."""
    spots = []
    for number in sorted(known, key=len, reverse=True):
        for found in re.finditer(re.escape(number) + r"\|\|", narration or ""):
            if not any(start <= found.start() < end for start, end, _ in spots):
                spots.append((found.start(), found.end(), number))
    spots.sort()
    out = []
    for n, (_, end, number) in enumerate(spots):
        upto = spots[n + 1][0] if n + 1 < len(spots) else len(narration)
        amount = re.match(r"\s*(\d+(?:\.\d+)?)", narration[end:upto])
        if amount:
            out.append((number, Decimal(amount.group(1))))
    if not spots:
        # Written by hand, e.g. "against invoice no# 202605214": the invoices
        # are named without amounts, and are paid in the order they are named.
        found = [(m.start(), number) for number in known
                 for m in re.finditer(r"(?<!\d)" + re.escape(number) + r"(?!\d)", narration or "")]
        out = [(number, None) for _, number in sorted(found)]
    return out


def buckets_for(db, company_id) -> list[int]:
    row = db.scalar(select(ARSettings).where(ARSettings.company_id == company_id))
    text = row.aging_buckets if row else "30,60,90,120"
    try:
        edges = sorted({int(x) for x in text.split(",") if x.strip()})
    except ValueError:
        edges = [30, 60, 90, 120]
    return edges or [30, 60, 90, 120]


def bucket_labels(edges: list[int]) -> list[str]:
    labels, low = ["Current"], 1
    for edge in edges:
        labels.append(f"{low}–{edge} days")
        low = edge + 1
    labels.append(f"{edges[-1]}+ days")
    return labels


def aging(db, ctx: FinanceContext, as_of: date | None = None, customer_id=None, branch_id=None,
          edges: list[int] | None = None) -> dict:
    as_of = as_of or date.today()
    edges = edges or buckets_for(db, ctx.company_id)
    labels = bucket_labels(edges)
    items = subledger.items_for(db, ctx.company_id, customer_id=customer_id, as_of=as_of,
                                branch_ids=ctx.branch_ids, branch_id=branch_id)
    open_ = subledger.open_amounts(db, items, as_of)
    customers = _names(db, {i.customer_id for i in items})

    # An invoice ages from the date it stands on in the ledger. That is the
    # document's own date except where its journal was posted on another one.
    ledger_dates = dict(db.execute(
        select(SalesDocument.id, JournalEntry.journal_date)
        .join(JournalEntry, JournalEntry.id == SalesDocument.journal_entry_id)
        .where(SalesDocument.id.in_({i.sales_document_id for i in items if i.sales_document_id}))).all()) if items else {}

    def dates(item):
        on = item.document_date
        due = item.due_date or on
        ledger_date = ledger_dates.get(item.sales_document_id)
        if ledger_date and ledger_date != on:
            on, due = ledger_date, ledger_date + (due - on)
        return on, due

    # Money the customer has paid that is not yet matched to an invoice (receipts
    # on account, advances, credit notes) is taken off their invoices, so the
    # buckets add up to the balance on the customer's ledger. A receipt brought
    # over from the previous ERP says in its narration which invoices it paid,
    # and comes off those; whatever is left comes off the oldest invoices first.
    # Nothing is posted or allocated by this: it is how the report reads.
    debits, credits, paying = defaultdict(list), defaultdict(lambda: ZERO), defaultdict(list)
    narrations = _old_narrations(db, {i.receipt_id for i in items if i.receipt_id and i.amount < 0})
    for item in items:
        remaining = money_2(open_[item.id] * (item.exchange_rate or Decimal("1")))
        if remaining == 0:
            continue
        if item.amount < 0:
            credits[item.customer_id] += remaining
            if narrations.get(item.receipt_id):
                paying[item.customer_id].append((narrations[item.receipt_id], remaining))
        else:
            debits[item.customer_id].append([dates(item), item, remaining])

    detail, rows = [], []
    for customer_id in set(debits) | set(credits):
        c = customers[customer_id]
        row = {"customer_id": str(customer_id), "customer_code": c.code, "customer_name": c.name,
               "buckets": [ZERO] * len(labels), "total_due": ZERO, "on_account": ZERO,
               "credit_balance": ZERO, "net": ZERO}
        credit = credits[customer_id]
        by_number = {d[1].document_number: d for d in debits[customer_id]}
        for narration, available in paying[customer_id]:
            for number, amount in invoices_named(narration, by_number):
                taken = min(available if amount is None else amount, available, by_number[number][2])
                by_number[number][2] -= taken
                available -= taken
                credit -= taken
                row["on_account"] += taken
        for (on, due), item, remaining in sorted(debits[customer_id], key=lambda d: (d[0][1], d[1].document_number)):
            taken = min(credit, remaining)
            credit -= taken
            row["on_account"] += taken
            remaining -= taken
            if remaining == 0:
                continue
            days = (as_of - due).days
            index = 0 if days <= 0 else next((n + 1 for n, e in enumerate(edges) if days <= e), len(edges) + 1)
            row["buckets"][index] += remaining
            row["total_due"] += remaining
            detail.append({
                "customer_id": str(customer_id), "customer_name": c.name, "item_id": str(item.id),
                "item_type": item.item_type, "document_number": item.document_number,
                "sales_document_id": str(item.sales_document_id) if item.sales_document_id else None,
                "document_date": on, "due_date": due,
                "original": item.amount_base, "paid": item.amount_base - remaining,
                "outstanding": remaining, "days_overdue": max(days, 0), "bucket": labels[index],
            })
        row["credit_balance"] = credit            # paid more than invoiced
        row["net"] = row["total_due"] - credit
        if row["net"] or row["total_due"]:
            rows.append(row)
    rows.sort(key=lambda r: r["customer_name"])
    totals = {"buckets": [ZERO] * len(labels), "total_due": ZERO, "on_account": ZERO,
              "credit_balance": ZERO, "net": ZERO}
    for r in rows:
        for n, v in enumerate(r["buckets"]):
            totals["buckets"][n] += v
        for key in ("total_due", "on_account", "credit_balance", "net"):
            totals[key] += r[key]
    detail.sort(key=lambda d: (d["customer_name"], d["due_date"], d["document_number"]))
    return {"as_of": as_of, "labels": labels, "customers": rows, "invoices": detail, "totals": totals}


# ------------------------------------------------------------ balances

def customer_balances(db, ctx: FinanceContext, as_of: date | None = None, customer_id=None) -> list[dict]:
    data = subledger.balances(db, ctx.company_id, customer_id=customer_id, as_of=as_of,
                              branch_ids=ctx.branch_ids)
    customers = _names(db, data.keys())
    out = []
    for cid, row in data.items():
        c = customers[cid]
        limit = c.credit_limit
        out.append({"customer_id": str(cid), "customer_code": c.code, "customer_name": c.name,
                    **row, "credit_limit": limit,
                    "available_credit": (limit - row["net_balance"]) if limit is not None else None})
    return sorted(out, key=lambda r: r["customer_name"])


def customer_profile(db, ctx: FinanceContext, customer_id) -> dict:
    customer = db.get(BusinessPartner, customer_id)
    if customer is None or customer.company_id != ctx.company_id:
        raise FinanceError("That customer does not exist.", 404)
    row = subledger.balances(db, ctx.company_id, customer_id=customer.id, branch_ids=ctx.branch_ids).get(customer.id)
    gl = ledger_by_customer(db, ctx, None).get(customer.id, {"receivable": ZERO, "advances": ZERO})
    empty = {"invoiced": ZERO, "credit_notes": ZERO, "receipts": ZERO, "receivable": ZERO, "advances": ZERO,
             "overdue": ZERO, "net_balance": ZERO, "open_invoices": 0, "partly_paid": 0,
             "gross_outstanding": ZERO, "unallocated_receipts": ZERO}
    row = row or empty
    return {"customer_id": str(customer.id), "customer_code": customer.code, "customer_name": customer.name,
            **row, "total_paid": row["receipts"], "credit_limit": customer.credit_limit,
            "available_credit": (customer.credit_limit - row["net_balance"]) if customer.credit_limit is not None else None,
            "ledger_receivable": gl["receivable"], "ledger_advances": gl["advances"],
            "payment_term_id": str(customer.default_payment_term_id) if customer.default_payment_term_id else None}


def large_balances(db, ctx: FinanceContext, minimum: Decimal, as_of: date | None = None) -> dict:
    """Customers whose ledger balance (receivable less advances) is at least
    `minimum`, largest first. The parties left out of the Receivables figure
    are left out here too."""
    as_of = as_of or date.today()
    gl = ledger_by_customer(db, ctx, as_of)
    left_out = set(db.scalars(select(BusinessPartner.id).where(
        BusinessPartner.company_id == ctx.company_id,
        or_(BusinessPartner.code.in_(ledger.NOT_IN_RECEIVABLES_CODES),
            *[func.lower(BusinessPartner.name).like(f"%{n}%") for n in ledger.NOT_IN_RECEIVABLES_NAMES]))))
    big = {cid: v["receivable"] - v["advances"] for cid, v in gl.items()
           if cid and cid not in left_out and v["receivable"] - v["advances"] >= minimum}
    customers = _names(db, big.keys())
    rows = sorted(({"customer_id": str(cid), "customer_code": customers[cid].code,
                    "customer_name": customers[cid].name, "balance": balance} for cid, balance in big.items()),
                  key=lambda r: -r["balance"])
    return {"as_of": as_of, "minimum": minimum, "customers": rows,
            "total": sum((r["balance"] for r in rows), ZERO)}


# ------------------------------------------------------------ reconciliation

def ledger_by_customer(db, ctx: FinanceContext, as_of: date | None) -> dict:
    """Receivable (debit-positive) and advances (credit-positive) per
    customer, straight from posted journal lines."""
    stmt = (select(JournalEntryLine.customer_id, Account.control_type,
                   func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit))
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .join(Account, Account.id == JournalEntryLine.account_id)
            .where(JournalEntry.company_id == ctx.company_id,
                   JournalEntry.status.in_(ledger.LEDGER_STATUSES),
                   Account.control_type.in_(STATEMENT_CONTROLS))
            .group_by(JournalEntryLine.customer_id, Account.control_type))
    condition = ctx.branch_condition(JournalEntryLine.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if as_of:
        stmt = stmt.where(JournalEntry.journal_date <= as_of)
    out: dict = defaultdict(lambda: {"receivable": ZERO, "advances": ZERO})
    for cid, control, total in db.execute(stmt).all():
        if control == "RECEIVABLE":
            out[cid]["receivable"] += Decimal(total or 0)
        else:
            out[cid]["advances"] += -Decimal(total or 0)
    return out


def reconciliation(db, ctx: FinanceContext, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    gl = ledger_by_customer(db, ctx, as_of)
    sub = subledger.balances(db, ctx.company_id, as_of=as_of, branch_ids=ctx.branch_ids)
    customers = _names(db, set(gl) | set(sub))
    rows, totals = [], {k: ZERO for k in ("sub_receivable", "gl_receivable", "sub_advances", "gl_advances")}
    for cid in set(gl) | set(sub):
        s = sub.get(cid, {"receivable": ZERO, "advances": ZERO})
        g = gl.get(cid, {"receivable": ZERO, "advances": ZERO})
        row = {"customer_id": str(cid) if cid else None,
               "customer_name": customers[cid].name if cid in customers else "(no customer on ledger line)",
               "sub_receivable": s["receivable"], "gl_receivable": g["receivable"],
               "receivable_difference": g["receivable"] - s["receivable"],
               "sub_advances": s["advances"], "gl_advances": g["advances"],
               "advances_difference": g["advances"] - s["advances"]}
        for k in totals:
            totals[k] += row[k]
        if any(row[k] for k in ("sub_receivable", "gl_receivable", "sub_advances", "gl_advances")):
            rows.append(row)
    # The control accounts in total, including any line without a customer.
    control = ledger.balances_by_control_type(db, ctx, as_of)
    control_receivable = control.get("RECEIVABLE", ZERO)
    control_advances = -control.get("CUSTOMER_ADVANCE", ZERO)
    differences = [r for r in rows if r["receivable_difference"] or r["advances_difference"]]
    return {
        "as_of": as_of,
        "receivable": {"subledger": totals["sub_receivable"], "control_account": control_receivable,
                       "difference": control_receivable - totals["sub_receivable"]},
        "advances": {"subledger": totals["sub_advances"], "control_account": control_advances,
                     "difference": control_advances - totals["sub_advances"]},
        "reconciled": control_receivable == totals["sub_receivable"] and control_advances == totals["sub_advances"]
        and not differences,
        "differences": sorted(differences, key=lambda r: r["customer_name"]),
        "customers": sorted(rows, key=lambda r: r["customer_name"]),
    }


# ------------------------------------------------------------ sales from the ledger

def _revenue_lines(db, ctx: FinanceContext, date_from, date_to):
    stmt = (select(JournalEntryLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .join(Account, Account.id == JournalEntryLine.account_id)
            .join(AccountType, AccountType.id == Account.account_type_id)
            .where(JournalEntry.company_id == ctx.company_id,
                   JournalEntry.status.in_(ledger.LEDGER_STATUSES),
                   AccountType.code == "REVENUE"))
    condition = ctx.branch_condition(JournalEntryLine.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if date_from:
        stmt = stmt.where(JournalEntry.journal_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.journal_date <= date_to)
    return db.execute(stmt).all()


def sales_summary(db, ctx: FinanceContext, date_from: date | None, date_to: date | None) -> dict:
    """Net sales (revenue credits less returns and discounts) by month,
    customer and product, from posted revenue lines."""
    lines = _revenue_lines(db, ctx, date_from, date_to)
    by_month, by_customer, by_product = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    qty = defaultdict(lambda: ZERO)
    total = ZERO
    for line, journal in lines:
        value = line.base_credit - line.base_debit
        total += value
        by_month[journal.journal_date.strftime("%Y-%m")] += value
        by_customer[line.customer_id] += value
        by_product[line.inventory_item_id] += value
        if line.inventory_item_id and line.quantity:
            qty[line.inventory_item_id] += line.quantity if value > 0 else -line.quantity
    customers = _names(db, by_customer.keys())
    items = {i.id: i for i in db.scalars(select(InventoryItem).where(
        InventoryItem.id.in_([k for k in by_product if k])))} if any(by_product) else {}
    return {
        "date_from": date_from, "date_to": date_to, "net_sales": total,
        "by_month": [{"month": m, "net_sales": v} for m, v in sorted(by_month.items())],
        "by_customer": sorted([{"customer_id": str(k) if k else None,
                                "customer_name": customers[k].name if k in customers else "Other / not by customer",
                                "net_sales": v} for k, v in by_customer.items()],
                              key=lambda r: -r["net_sales"]),
        "by_product": sorted([{"item_id": str(k) if k else None,
                               "item_code": items[k].item_code if k in items else None,
                               "description": items[k].description if k in items else "Not by product",
                               "quantity": qty.get(k, ZERO), "net_sales": v} for k, v in by_product.items()],
                             key=lambda r: -r["net_sales"]),
    }


def dashboard(db, ctx: FinanceContext, today: date | None = None) -> dict:
    today = today or date.today()
    month_start = today.replace(day=1)
    month = sales_summary(db, ctx, month_start, today)
    day = sales_summary(db, ctx, today, today)
    balances = subledger.balances(db, ctx.company_id, branch_ids=ctx.branch_ids)
    receipts_today = db.scalar(select(func.coalesce(func.sum(CustomerReceipt.amount_base), 0)).where(
        CustomerReceipt.company_id == ctx.company_id, CustomerReceipt.status.in_(["POSTED", "REVERSED"]),
        CustomerReceipt.receipt_date == today)) or ZERO
    control = ledger.balances_by_control_type(db, ctx, today)
    return {
        "as_of": today,
        "sales_today": day["net_sales"], "sales_this_month": month["net_sales"],
        # The sum of the customers' ledger balances: receivables less advances.
        "outstanding_ar": (control.get("RECEIVABLE", ZERO) + control.get("CUSTOMER_ADVANCE", ZERO)
                           - ledger.not_in_receivables(db, ctx, today)),
        "customer_advances": -control.get("CUSTOMER_ADVANCE", ZERO),
        # Overdue after money on account is taken off the oldest invoices, as on the aging report.
        "overdue_ar": sum(aging(db, ctx, today)["totals"]["buckets"][1:], ZERO),
        "receipts_today": Decimal(receipts_today),
        "unpaid_invoices": sum((b["open_invoices"] - b["partly_paid"] for b in balances.values()), 0),
        "partially_paid_invoices": sum((b["partly_paid"] for b in balances.values()), 0),
        "customers_with_balance": sum(1 for b in balances.values() if b["net_balance"] != 0),
        "customer_count": db.scalar(select(func.count()).select_from(BusinessPartner).where(
            BusinessPartner.company_id == ctx.company_id, BusinessPartner.is_customer.is_(True),
            BusinessPartner.is_active.is_(True))) or 0,
        "top_customers": month["by_customer"][:8],
        "top_products": month["by_product"][:8],
        "sales_by_month": sales_summary(db, ctx, today.replace(day=1) - timedelta(days=330), today)["by_month"],
    }


# ------------------------------------------------------------ registers

def document_register(db, ctx: FinanceContext, doc_type: str, *, date_from=None, date_to=None,
                      customer_id=None, status=None, search=None) -> list[dict]:
    stmt = select(SalesDocument).where(SalesDocument.company_id == ctx.company_id,
                                       SalesDocument.doc_type == doc_type)
    condition = ctx.branch_condition(SalesDocument.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if date_from:
        stmt = stmt.where(SalesDocument.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(SalesDocument.doc_date <= date_to)
    if customer_id:
        stmt = stmt.where(SalesDocument.customer_id == customer_id)
    if status:
        stmt = stmt.where(SalesDocument.status == status)
    if search:
        stmt = stmt.where(SalesDocument.doc_number.ilike(f"%{search}%"))
    docs = db.scalars(stmt.order_by(SalesDocument.doc_date, SalesDocument.doc_number)).all()
    customers = _names(db, {d.customer_id for d in docs})
    journals = {j.id: j.journal_number for j in db.scalars(select(JournalEntry).where(
        JournalEntry.id.in_({d.journal_entry_id for d in docs if d.journal_entry_id})))} if docs else {}
    out = []
    for d in docs:
        state = payment_state(db, d)
        out.append({"id": str(d.id), "doc_number": d.doc_number, "doc_date": d.doc_date, "due_date": d.due_date,
                    "customer": customers[d.customer_id].name if d.customer_id in customers else None,
                    "status": d.status, "payment_status": state["payment_status"],
                    "excluding_tax_value": d.excluding_tax_value, "sales_tax_value": d.sales_tax_value,
                    "freight_amount": d.freight_amount, "net_total": d.net_receivable,
                    "paid": state["paid"], "outstanding": state["outstanding"], "currency": d.currency,
                    "journal_number": journals.get(d.journal_entry_id)})
    return out


def receipt_register(db, ctx: FinanceContext, *, date_from=None, date_to=None, customer_id=None,
                     status=None) -> list[dict]:
    stmt = select(CustomerReceipt).where(CustomerReceipt.company_id == ctx.company_id)
    condition = ctx.branch_condition(CustomerReceipt.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if date_from:
        stmt = stmt.where(CustomerReceipt.receipt_date >= date_from)
    if date_to:
        stmt = stmt.where(CustomerReceipt.receipt_date <= date_to)
    if customer_id:
        stmt = stmt.where(CustomerReceipt.customer_id == customer_id)
    if status:
        stmt = stmt.where(CustomerReceipt.status == status)
    receipts = db.scalars(stmt.order_by(CustomerReceipt.receipt_date, CustomerReceipt.receipt_number)).all()
    customers = _names(db, {r.customer_id for r in receipts})
    methods = {m.id: m.name for m in db.scalars(select(PaymentMethod).where(PaymentMethod.company_id == ctx.company_id))}
    accounts = {a.id: f"{a.code} {a.name}" for a in db.scalars(select(Account).where(
        Account.id.in_({r.deposit_account_id for r in receipts})))} if receipts else {}
    journals = {j.id: j.journal_number for j in db.scalars(select(JournalEntry).where(
        JournalEntry.id.in_({r.journal_entry_id for r in receipts if r.journal_entry_id})))} if receipts else {}
    out = []
    for r in receipts:
        s = receipt_summary(db, r)
        out.append({"id": str(r.id), "receipt_number": r.receipt_number, "receipt_date": r.receipt_date,
                    "customer": customers[r.customer_id].name, "method": methods.get(r.payment_method_id),
                    "deposit_account": accounts.get(r.deposit_account_id), "amount": r.amount,
                    "currency": r.currency, "amount_base": r.amount_base,
                    "reference": r.cheque_number or r.reference, "status": r.status,
                    "allocated": s["allocated"], "unallocated": s["unallocated"],
                    "allocation_status": s["allocation_status"],
                    "journal_number": journals.get(r.journal_entry_id)})
    return out


def open_items(db, ctx: FinanceContext, customer_id, include_credits: bool = False) -> list[dict]:
    """A customer's documents that can still take (or give) an allocation."""
    items = subledger.items_for(db, ctx.company_id, customer_id=customer_id, branch_ids=ctx.branch_ids)
    open_ = subledger.open_amounts(db, items)
    today = date.today()
    # An invoice is offered only for what the customer still owes on it, read
    # the way the aging and the ledger read it: money already received on
    # account (the old ERP's receipts are not matched to invoices) comes off
    # the invoices its narration names, then the oldest. So an invoice the
    # ledger shows as paid is not offered again (owner's request, 15-Oct-2026).
    still_owed = {d["item_id"]: d["outstanding"]
                  for d in aging(db, ctx, today, customer_id=customer_id)["invoices"]}
    for i in items:
        if i.amount > 0:
            rate = i.exchange_rate or Decimal("1")
            owed = still_owed.get(str(i.id), ZERO) / rate
            open_[i.id] = min(open_[i.id], owed.quantize(Decimal("0.01")))
    return [{"item_id": str(i.id), "item_type": i.item_type, "kind": i.kind,
             "document_number": i.document_number, "document_date": i.document_date, "due_date": i.due_date,
             "sales_document_id": str(i.sales_document_id) if i.sales_document_id else None,
             "receipt_id": str(i.receipt_id) if i.receipt_id else None,
             "currency": i.currency, "amount": abs(i.amount), "outstanding": open_[i.id],
             "is_credit": i.amount < 0, "overdue": i.amount > 0 and bool(i.due_date and i.due_date < today)}
            for i in items if open_[i.id] > 0 and (include_credits or i.amount > 0)]
