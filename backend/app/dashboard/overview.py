"""
The home dashboard: how the business is doing and what needs doing today.

Every figure comes from where it is kept — sales from the sales orders, what
customers owe and cash in hand from the general ledger (the Finance
dashboard's own figures, with its exclusions), stock from the valuation
report, the pipeline from Leads, and the to-do counts from each module's
records. Nothing is stored here.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.audit.service import AuditContext
from app.calibration import service as calibration
from app.calibration.models import CalibrationReport, ServiceContract, ServiceInvoice
from app.finance import ledger, periods
from app.finance.context import FinanceContext
from app.finance.models import Account, JournalEntry, JournalEntryLine
from app.leads.models import OPEN_STAGES, STAGES, Lead, LeadActivity
from app.partners.models import BusinessPartner
from app.procurement import models as pm
from app.receivables.models import CustomerReceipt
from app.reports import valuation
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument, SalesDocumentLine

IN_SALES = ("Posted", "Delivered")
ZERO = Decimal("0")


def _month_start(d: date, back: int = 0) -> date:
    m = d.month - 1 - back
    return date(d.year + m // 12, m % 12 + 1, 1)


def _sales(db: Session, company_id: uuid.UUID, start: date, end: date) -> tuple[float, int]:
    total, count = db.execute(select(func.coalesce(func.sum(SalesDocument.net_receivable), 0), func.count())
                              .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
                                     SalesDocument.status.in_(IN_SALES), SalesDocument.doc_date >= start,
                                     SalesDocument.doc_date <= end)).one()
    return float(total or 0), int(count or 0)


def _delta(now: float, before: float) -> float | None:
    return round((now - before) * 100 / before, 1) if before else None


def overview(db: Session, company_id: uuid.UUID, user) -> dict:
    today = date.today()
    ctx = FinanceContext(company_id=company_id, user=user, audit=AuditContext.for_user(user))
    fin = ledger.dashboard(db, ctx, today)
    fy = periods.current_year(db, company_id)
    fy_start = periods.fy_dates(fy)[0] if fy else date(today.year if today.month >= 7 else today.year - 1, 7, 1)

    # ---- sales: this month against the same days of last month; the year against last year to date
    month_start = _month_start(today)
    last_start = _month_start(today, 1)
    last_same_day = min(today.replace(day=1) - timedelta(days=1), last_start + (today - month_start))
    month, month_orders = _sales(db, company_id, month_start, today)
    last_month_to_date, _ = _sales(db, company_id, last_start, last_same_day)
    last_month_full, _ = _sales(db, company_id, last_start, month_start - timedelta(days=1))
    year, year_orders = _sales(db, company_id, fy_start, today)
    prev_fy_start = date(fy_start.year - 1, fy_start.month, fy_start.day)
    prev_year_to_date, _ = _sales(db, company_id, prev_fy_start, date(today.year - 1, today.month, min(today.day, 28)))

    # ---- sales by month: the last 12, with the same months a year before
    months = [_month_start(today, back) for back in range(11, -1, -1)]
    def by_month(first: date) -> dict:
        bucket = func.date_trunc("month", SalesDocument.doc_date)
        rows = db.execute(select(bucket, func.sum(SalesDocument.net_receivable))
                          .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
                                 SalesDocument.status.in_(IN_SALES), SalesDocument.doc_date >= first)
                          .group_by(bucket)).all()
        return {(d.year, d.month): float(v or 0) for d, v in rows}
    this_year = by_month(months[0])
    prior = by_month(date(months[0].year - 1, months[0].month, 1))

    # ---- stock
    stock_rows = valuation.rows(db, company_id)
    stock = valuation.summarise(stock_rows)

    # ---- customers: who buys most this year, who owes most
    top_customers = db.execute(
        select(BusinessPartner.id, BusinessPartner.name, func.sum(SalesDocument.net_receivable), func.count())
        .join(SalesDocument, SalesDocument.customer_id == BusinessPartner.id)
        .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
               SalesDocument.status.in_(IN_SALES), SalesDocument.doc_date >= fy_start)
        .group_by(BusinessPartner.id, BusinessPartner.name)
        .order_by(func.sum(SalesDocument.net_receivable).desc()).limit(8)).all()
    party_accounts = select(Account.id).where(Account.company_id == company_id,
                                              Account.control_type.in_(("RECEIVABLE", "CUSTOMER_ADVANCE")))
    excluded_names = or_(*[func.lower(BusinessPartner.name).like(f"%{n}%") for n in ledger.NOT_IN_RECEIVABLES_NAMES])
    owing = db.execute(
        select(BusinessPartner.id, BusinessPartner.name,
               func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit).label("bal"))
        .join(JournalEntryLine, JournalEntryLine.customer_id == BusinessPartner.id)
        .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
        .where(JournalEntry.company_id == company_id, JournalEntry.status.in_(ledger.LEDGER_STATUSES),
               JournalEntryLine.account_id.in_(party_accounts),
               ~BusinessPartner.code.in_(ledger.NOT_IN_RECEIVABLES_CODES), ~excluded_names)
        .group_by(BusinessPartner.id, BusinessPartner.name)
        .order_by(func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit).desc()).limit(8)).all()

    top_products = db.execute(
        select(SalesDocumentLine.description, func.sum(SalesDocumentLine.quantity), func.sum(SalesDocumentLine.net_amount))
        .join(SalesDocument, SalesDocument.id == SalesDocumentLine.document_id)
        .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
               SalesDocument.status.in_(IN_SALES), SalesDocument.doc_date >= today - timedelta(days=90))
        .group_by(SalesDocumentLine.description)
        .order_by(func.sum(SalesDocumentLine.net_amount).desc()).limit(8)).all()

    # ---- pipeline
    open_leads = list(db.scalars(select(Lead).where(Lead.company_id == company_id, Lead.stage.in_(OPEN_STAGES))))
    pipeline = sum(float(l.estimated_value or 0) for l in open_leads if l.currency == "PKR")
    weighted = sum(float(l.estimated_value or 0) * STAGES[l.stage] / 100 for l in open_leads if l.currency == "PKR")

    # ---- what needs doing
    def count(stmt) -> int:
        return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    follow = (select(LeadActivity.id).outerjoin(Lead, Lead.id == LeadActivity.lead_id)
              .outerjoin(BusinessPartner, BusinessPartner.id == LeadActivity.customer_id)
              .where(or_(Lead.company_id == company_id, BusinessPartner.company_id == company_id),
                     LeadActivity.due_date.is_not(None), LeadActivity.done_at.is_(None)))
    converted = select(SalesDocument.source_document_id).where(SalesDocument.source_document_id.is_not(None))
    quotes_waiting = (select(SalesDocument.id).where(
        SalesDocument.company_id == company_id, SalesDocument.doc_type == QUOTATION,
        SalesDocument.status.in_(("Sent", "Approved")), SalesDocument.doc_date >= today - timedelta(days=30),
        SalesDocument.id.not_in(converted)))
    po = lambda *s: select(pm.PurchaseOrder.id).where(pm.PurchaseOrder.company_id == company_id,   # noqa: E731
                                                      pm.PurchaseOrder.status.in_(s))
    contracts_to_bill = 0
    for c in db.scalars(select(ServiceContract).where(ServiceContract.company_id == company_id,
                                                      ServiceContract.contract_status == "ACTIVE")):
        start, _end = calibration.next_period(db, c)
        if start <= today and (c.end_date is None or start <= c.end_date):
            contracts_to_bill += 1

    todo = [
        {"key": "followups_overdue", "label": "Follow-ups overdue", "count": count(follow.where(LeadActivity.due_date < today)),
         "href": "/crm/activities", "tone": "rose"},
        {"key": "followups_today", "label": "Follow-ups due today", "count": count(follow.where(LeadActivity.due_date == today)),
         "href": "/leads/followups", "tone": "amber"},
        {"key": "quotes_waiting", "label": "Quotations sent, no order yet (last 30 days)", "count": count(quotes_waiting),
         "href": "/inventory/transactions/quotations", "tone": "sky"},
        {"key": "draft_orders", "label": "Sales orders still in draft", "count": count(select(SalesDocument.id).where(
            SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER, SalesDocument.status == "Draft")),
         "href": "/inventory/transactions/sales-orders", "tone": "amber"},
        {"key": "po_approval", "label": "Purchase orders to approve", "count": count(po("Draft", "Pending Approval")),
         "href": "/inventory/inhouse-orders/purchase-orders", "tone": "violet"},
        {"key": "po_open", "label": "Purchase orders awaiting goods",
         "count": count(po("Approved", "Sent", "Acknowledged", "Open", "Partially Received")),
         "href": "/inventory/inhouse-orders/purchase-orders", "tone": "sky"},
        {"key": "in_transit", "label": "Import shipments not yet received", "count": count(select(pm.ImportShipment.id).where(
            pm.ImportShipment.company_id == company_id,
            pm.ImportShipment.transit_status.not_in(("Warehouse Received", "Closed", "Cancelled")))),
         "href": "/inventory/inhouse-orders/shipments", "tone": "sky"},
        {"key": "costings", "label": "Landed costings not posted", "count": count(select(pm.LandedCost.id).where(
            pm.LandedCost.company_id == company_id, pm.LandedCost.status.not_in(("Posted", "Cancelled")))),
         "href": "/inventory/inhouse-orders/landed-costs", "tone": "violet"},
        {"key": "calibration_due", "label": "Calibrations due in 30 days", "count": count(select(CalibrationReport.id).where(
            CalibrationReport.company_id == company_id, CalibrationReport.report_status != "CANCELLED",
            CalibrationReport.next_calibration_date <= today + timedelta(days=30))),
         "href": "/calibration/reports", "tone": "amber"},
        {"key": "contracts_to_bill", "label": "Service contracts due for invoicing", "count": contracts_to_bill,
         "href": "/calibration/contracts", "tone": "primary"},
        {"key": "service_drafts", "label": "Service invoices in draft", "count": count(select(ServiceInvoice.id).where(
            ServiceInvoice.company_id == company_id, ServiceInvoice.status == "Draft")),
         "href": "/calibration/invoices", "tone": "amber"},
        {"key": "journals", "label": "Journals waiting to be posted",
         "count": int(fin["pending"]["draft"] + fin["pending"]["submitted"] + fin["pending"]["approved_not_posted"]),
         "href": "/finance/journals", "tone": "violet"},
    ]

    # ---- latest
    recent_orders = db.execute(select(SalesDocument, BusinessPartner.name)
                               .join(BusinessPartner, BusinessPartner.id == SalesDocument.customer_id)
                               .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
                                      SalesDocument.status != "Cancelled")
                               .order_by(SalesDocument.doc_date.desc(), SalesDocument.created_at.desc()).limit(7)).all()
    recent_receipts = db.execute(select(CustomerReceipt, BusinessPartner.name)
                                 .join(BusinessPartner, BusinessPartner.id == CustomerReceipt.customer_id)
                                 .where(CustomerReceipt.company_id == company_id, CustomerReceipt.status == "POSTED")
                                 .order_by(CustomerReceipt.receipt_date.desc(), CustomerReceipt.created_at.desc())
                                 .limit(7)).all()
    def buyers(since: date) -> int:
        return int(db.scalar(select(func.count(func.distinct(SalesDocument.customer_id))).where(
            SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
            SalesDocument.status.in_(IN_SALES), SalesDocument.doc_date >= since)) or 0)
    customers_month, customers_90d = buyers(month_start), buyers(today - timedelta(days=90))
    received_month = db.scalar(select(func.coalesce(func.sum(CustomerReceipt.amount_base), 0)).where(
        CustomerReceipt.company_id == company_id, CustomerReceipt.status == "POSTED",
        CustomerReceipt.receipt_date >= month_start)) or 0

    return {
        "as_of": today, "financial_year": fy.name if fy else None, "fy_start": fy_start,
        "kpis": {
            "sales_month": month, "sales_month_orders": month_orders,
            "sales_month_delta": _delta(month, last_month_to_date), "sales_last_month": last_month_full,
            "sales_year": year, "sales_year_orders": year_orders, "sales_year_delta": _delta(year, prev_year_to_date),
            "received_month": float(received_month),
            "receivables": float(fin["receivables"]), "cash": float(fin["cash"]), "bank": float(fin["bank"]),
            "stock_value": stock["total_stock_value"], "stock_products": stock["products"],
            "stock_without_cost": stock["products_without_a_cost"],
            "pipeline": pipeline, "weighted_pipeline": weighted, "open_leads": len(open_leads),
            "customers_month": customers_month, "customers_90d": customers_90d,
        },
        "sales_trend": [{"month": m.strftime("%b %y"), "value": round(this_year.get((m.year, m.month), 0), 2),
                         "previous": round(prior.get((m.year - 1, m.month), 0), 2)} for m in months],
        "top_customers": [{"id": str(i), "name": n, "value": float(v or 0), "orders": c} for i, n, v, c in top_customers],
        "owing": [{"id": str(i), "name": n, "balance": float(b or 0)} for i, n, b in owing if (b or 0) > 0],
        "top_products": [{"description": d, "quantity": float(q or 0), "value": float(v or 0)} for d, q, v in top_products],
        "todo": todo,
        "recent_orders": [{"id": str(o.id), "doc_number": o.doc_number, "doc_date": o.doc_date, "customer": n,
                           "customer_id": str(o.customer_id), "value": float(o.net_receivable or 0), "status": o.status}
                          for o, n in recent_orders],
        "recent_receipts": [{"id": str(r.id), "receipt_number": r.receipt_number, "receipt_date": r.receipt_date,
                             "customer": n, "customer_id": str(r.customer_id), "amount": float(r.amount)}
                            for r, n in recent_receipts],
    }


def simple(db: Session, company_id: uuid.UUID, user) -> dict:
    """The dashboard for staff who do not see the business figures: their own
    follow-ups and leads, and the day's work — with no sales or money in it."""
    from app.gatepass.models import GatePass
    today = date.today()
    fy = periods.current_year(db, company_id)

    mine = (select(LeadActivity, Lead.lead_number, Lead.title, func.coalesce(BusinessPartner.name, Lead.company_name))
            .outerjoin(Lead, Lead.id == LeadActivity.lead_id)
            .outerjoin(BusinessPartner, BusinessPartner.id == func.coalesce(LeadActivity.customer_id, Lead.customer_id))
            .where(LeadActivity.owner_id == user.id, LeadActivity.due_date.is_not(None), LeadActivity.done_at.is_(None),
                   LeadActivity.due_date <= today + timedelta(days=7),
                   or_(Lead.company_id == company_id, BusinessPartner.company_id == company_id))
            .order_by(LeadActivity.due_date).limit(20))
    follow_ups = [{
        "id": str(a.id), "activity_type": a.activity_type, "summary": a.summary, "due_date": a.due_date,
        "overdue": a.due_date < today, "today": a.due_date == today, "lead_id": str(a.lead_id) if a.lead_id else None,
        "lead_number": num, "lead_title": title, "who": who,
        "customer_id": str(a.customer_id) if a.customer_id else None,
    } for a, num, title, who in db.execute(mine).all()]

    my_leads = list(db.scalars(select(Lead).where(Lead.company_id == company_id, Lead.owner_id == user.id,
                                                  Lead.stage.in_(OPEN_STAGES)).order_by(Lead.updated_at.desc())))
    done_recently = db.execute(
        select(LeadActivity, func.coalesce(BusinessPartner.name, Lead.company_name))
        .outerjoin(Lead, Lead.id == LeadActivity.lead_id)
        .outerjoin(BusinessPartner, BusinessPartner.id == func.coalesce(LeadActivity.customer_id, Lead.customer_id))
        .where(LeadActivity.created_by == user.id, LeadActivity.done_at.is_not(None), LeadActivity.activity_type != "Note",
               or_(Lead.company_id == company_id, BusinessPartner.company_id == company_id))
        .order_by(LeadActivity.done_at.desc()).limit(6)).all()

    def count(stmt) -> int:
        return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    work = [
        {"key": "my_overdue", "label": "My follow-ups overdue", "count": sum(1 for f in follow_ups if f["overdue"]),
         "href": "/crm/activities", "tone": "rose"},
        {"key": "my_today", "label": "My follow-ups today", "count": sum(1 for f in follow_ups if f["today"]),
         "href": "/leads/followups", "tone": "amber"},
        {"key": "gate_passes", "label": "Gate passes waiting for approval", "count": count(select(GatePass.id).where(
            GatePass.company_id == company_id, GatePass.status == "Draft")),
         "href": "/inventory/transactions/outward-gate-pass", "tone": "sky"},
        {"key": "po_open", "label": "Purchase orders awaiting goods", "count": count(select(pm.PurchaseOrder.id).where(
            pm.PurchaseOrder.company_id == company_id,
            pm.PurchaseOrder.status.in_(("Approved", "Sent", "Acknowledged", "Open", "Partially Received")))),
         "href": "/inventory/inhouse-orders/purchase-orders", "tone": "violet"},
        {"key": "in_transit", "label": "Import shipments on the way", "count": count(select(pm.ImportShipment.id).where(
            pm.ImportShipment.company_id == company_id,
            pm.ImportShipment.transit_status.not_in(("Warehouse Received", "Closed", "Cancelled")))),
         "href": "/inventory/inhouse-orders/shipments", "tone": "sky"},
        {"key": "receipts", "label": "Goods receipts in draft", "count": count(select(pm.MaterialReceivingNote.id).where(
            pm.MaterialReceivingNote.company_id == company_id, pm.MaterialReceivingNote.status == "Draft")),
         "href": "/inventory/inhouse-orders/goods-receipts", "tone": "amber"},
        {"key": "calibration_due", "label": "Calibrations due in 30 days", "count": count(select(CalibrationReport.id).where(
            CalibrationReport.company_id == company_id, CalibrationReport.report_status != "CANCELLED",
            CalibrationReport.next_calibration_date <= today + timedelta(days=30))),
         "href": "/calibration/reports", "tone": "amber"},
    ]
    return {
        "mode": "simple", "as_of": today, "financial_year": fy.name if fy else None,
        "follow_ups": follow_ups, "work": work,
        "my_leads": [{"id": str(l.id), "lead_number": l.lead_number, "title": l.title, "company_name": l.company_name,
                      "stage": l.stage, "rating": l.rating} for l in my_leads[:8]],
        "my_leads_count": len(my_leads), "my_hot_leads": sum(1 for l in my_leads if l.rating == "Hot"),
        "done_recently": [{"id": str(a.id), "activity_type": a.activity_type, "summary": a.summary, "who": who,
                           "done_at": a.done_at} for a, who in done_recently],
    }
