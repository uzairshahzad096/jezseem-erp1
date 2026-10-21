"""CRM endpoints: customers seen whole (ledger, sales, service, people,
pipeline), their contacts, and the activity log shared with Leads.

Nothing here is a second copy of anything: the balance is the general
ledger's, sales are the sales orders, opportunities are the leads with our
customers, machines and contracts are Calibration / Services', and an
activity logged here sits in the same log as a lead's.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.calibration.models import (
    CalibrationReport, CustomerMachine, MachineDefinition, ServiceContract, ServiceInvoice,
)
from app.core.database import get_db
from app.finance.ledger import LEDGER_STATUSES, PARTY_ACCOUNT_TYPES
from app.finance.models import Account, JournalEntry, JournalEntryLine
from app.inventory.router import active_company_id
from app.leads.models import ACTIVITY_TYPES, OPEN_STAGES, STAGES, Lead, LeadActivity
from app.partners.models import BusinessPartner, PartnerContact
from app.receivables.models import CustomerReceipt
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument, SalesDocumentLine
from app.users.models import User

router = APIRouter(prefix="/crm", tags=["crm"])

#: Health, from the last sales order: within 90 days, 91-180, more than 180, or never.
SEGMENTS = ["Active", "Slowing", "Dormant", "Never ordered"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Form(BaseModel):
    """Empty form boxes arrive as "" and mean "not filled in"."""

    @model_validator(mode="before")
    @classmethod
    def _blank(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not (isinstance(v, str) and not v.strip())}
        return data


def _segment(last: date | None) -> str:
    if last is None:
        return "Never ordered"
    days = (date.today() - last).days
    return "Active" if days <= 90 else "Slowing" if days <= 180 else "Dormant"


def _users(db: Session) -> dict:
    return {u.id: (u.full_name or u.username) for u in db.scalars(select(User))}


def _customer(db: Session, customer_id: uuid.UUID) -> BusinessPartner:
    p = db.get(BusinessPartner, customer_id)
    if p is None or p.company_id != active_company_id(db):
        raise HTTPException(404, "Customer not found.")
    return p


def _balances(db: Session, company_id: uuid.UUID, ids=None):
    """Each customer's balance on their receivable and advance accounts (debit-positive), from the ledger."""
    stmt = (select(JournalEntryLine.customer_id, func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit))
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .where(JournalEntry.company_id == company_id, JournalEntry.status.in_(LEDGER_STATUSES),
                   JournalEntryLine.account_id.in_(select(Account.id).where(
                       Account.company_id == company_id, Account.control_type.in_(PARTY_ACCOUNT_TYPES))),
                   JournalEntryLine.customer_id.is_not(None))
            .group_by(JournalEntryLine.customer_id))
    if ids is not None:
        stmt = stmt.where(JournalEntryLine.customer_id.in_(ids))
    return {k: float(v or 0) for k, v in db.execute(stmt).all()}


def _sales_subquery(company_id: uuid.UUID):
    year_ago = date.today() - timedelta(days=365)
    return (select(SalesDocument.customer_id.label("cid"),
                   func.count(SalesDocument.id).label("orders"),
                   func.max(SalesDocument.doc_date).label("last"),
                   func.coalesce(func.sum(SalesDocument.net_receivable), 0).label("total"),
                   func.coalesce(func.sum(case((SalesDocument.doc_date >= year_ago, SalesDocument.net_receivable),
                                               else_=0)), 0).label("year"))
            .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
                   SalesDocument.status != "Cancelled")
            .group_by(SalesDocument.customer_id).subquery())


# ------------------------------------------------------------------ customers

@router.get("/customers")
def list_customers(search: str | None = None, segment: str | None = None, city: str | None = None,
                   sort: str = Query("sales_12m", pattern="^(name|sales_12m|sales_total|balance|last_order)$"),
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=5000),
                   db: Session = Depends(get_db), user: User = Depends(require_permission("crm.customers.view"))):
    """Customers with their ledger balance, sales and health, for the CRM list."""
    company_id = active_company_id(db)
    sales = _sales_subquery(company_id)
    leads = (select(Lead.customer_id.label("cid"), func.count(Lead.id).label("n"))
             .where(Lead.company_id == company_id, Lead.stage.in_(OPEN_STAGES), Lead.customer_id.is_not(None))
             .group_by(Lead.customer_id).subquery())
    contacts = (select(PartnerContact.partner_id.label("cid"), func.count(PartnerContact.id).label("n"))
                .group_by(PartnerContact.partner_id).subquery())
    stmt = (select(BusinessPartner, sales.c.orders, sales.c.last, sales.c.total, sales.c.year, leads.c.n, contacts.c.n)
            .outerjoin(sales, sales.c.cid == BusinessPartner.id)
            .outerjoin(leads, leads.c.cid == BusinessPartner.id)
            .outerjoin(contacts, contacts.c.cid == BusinessPartner.id)
            .where(BusinessPartner.company_id == company_id, BusinessPartner.is_customer.is_(True)))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(BusinessPartner.name.ilike(like), BusinessPartner.code.ilike(like),
                              BusinessPartner.city.ilike(like), BusinessPartner.phone.ilike(like),
                              BusinessPartner.cell.ilike(like), BusinessPartner.ntn.ilike(like)))
    if city:
        stmt = stmt.where(BusinessPartner.city.ilike(city))
    today = date.today()
    if segment == "Active":
        stmt = stmt.where(sales.c.last >= today - timedelta(days=90))
    elif segment == "Slowing":
        stmt = stmt.where(sales.c.last < today - timedelta(days=90), sales.c.last >= today - timedelta(days=180))
    elif segment == "Dormant":
        stmt = stmt.where(sales.c.last < today - timedelta(days=180))
    elif segment == "Never ordered":
        stmt = stmt.where(sales.c.last.is_(None))
    order = {"name": func.lower(BusinessPartner.name), "sales_12m": sales.c.year.desc().nulls_last(),
             "sales_total": sales.c.total.desc().nulls_last(), "last_order": sales.c.last.desc().nulls_last(),
             "balance": func.lower(BusinessPartner.name)}[sort]
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort == "balance":
        rows = db.execute(stmt).all()
    else:
        rows = db.execute(stmt.order_by(order, BusinessPartner.name).offset((page - 1) * page_size).limit(page_size)).all()
    balances = _balances(db, company_id, [r[0].id for r in rows])
    items = [{
        "id": str(p.id), "code": p.code, "name": p.name, "city": p.city, "address": p.address, "phone": p.phone or p.cell,
        "email": p.email, "ntn": p.ntn, "is_active": p.is_active,
        "orders": orders or 0, "last_order_date": last, "days_since_order": (today - last).days if last else None,
        "sales_total": float(total_ or 0), "sales_12m": float(year or 0), "segment": _segment(last),
        "balance": balances.get(p.id, 0.0), "open_leads": n_leads or 0, "contacts": n_contacts or 0,
    } for p, orders, last, total_, year, n_leads, n_contacts in rows]
    if sort == "balance":
        items.sort(key=lambda r: -r["balance"])
        items = items[(page - 1) * page_size: page * page_size]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/customers/summary")
def customers_summary(db: Session = Depends(get_db),
                      user: User = Depends(require_permission("crm.customers.view"))):
    """How many customers are in each state of health, and what they owe in all."""
    company_id = active_company_id(db)
    sales = _sales_subquery(company_id)
    rows = db.execute(select(BusinessPartner.id, sales.c.last, sales.c.year)
                      .outerjoin(sales, sales.c.cid == BusinessPartner.id)
                      .where(BusinessPartner.company_id == company_id, BusinessPartner.is_customer.is_(True))).all()
    counts = {s: 0 for s in SEGMENTS}
    for _id, last, _year in rows:
        counts[_segment(last)] += 1
    balances = _balances(db, company_id)
    return {"customers": len(rows), "segments": counts,
            "receivable": round(sum(v for v in balances.values() if v > 0), 2),
            "sales_12m": round(sum(float(y or 0) for _i, _l, y in rows), 2),
            "buying_12m": sum(1 for _i, last, _y in rows if last and last >= date.today() - timedelta(days=365))}


@router.get("/customers/{customer_id}")
def customer_360(customer_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("crm.customers.view"))):
    """One customer, whole: account, sales, service, people and pipeline."""
    p = _customer(db, customer_id)
    company_id = p.company_id
    today = date.today()
    users = _users(db)
    orders_q = select(SalesDocument).where(SalesDocument.customer_id == p.id, SalesDocument.doc_type == SALES_ORDER,
                                           SalesDocument.status != "Cancelled")
    orders = list(db.scalars(orders_q.order_by(SalesDocument.doc_date.desc())))
    quotations = list(db.scalars(select(SalesDocument).where(
        SalesDocument.customer_id == p.id, SalesDocument.doc_type == QUOTATION).order_by(SalesDocument.doc_date.desc())))
    converted = {o.source_document_id for o in orders if o.source_document_id}
    receipts = list(db.scalars(select(CustomerReceipt).where(
        CustomerReceipt.customer_id == p.id, CustomerReceipt.status == "POSTED")
        .order_by(CustomerReceipt.receipt_date.desc()).limit(10)))

    # Sales by month, the last 12 months, oldest first.
    first = (today.replace(day=1) - timedelta(days=330)).replace(day=1)
    months = []
    cursor = first
    while cursor <= today:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    by_month = {(m.year, m.month): 0.0 for m in months}
    for o in orders:
        key = (o.doc_date.year, o.doc_date.month)
        if key in by_month:
            by_month[key] += float(o.net_receivable or 0)

    top = db.execute(select(SalesDocumentLine.description, func.sum(SalesDocumentLine.quantity),
                            func.sum(SalesDocumentLine.net_amount), func.max(SalesDocument.doc_date))
                     .join(SalesDocument, SalesDocument.id == SalesDocumentLine.document_id)
                     .where(SalesDocument.customer_id == p.id, SalesDocument.doc_type == SALES_ORDER,
                            SalesDocument.status != "Cancelled")
                     .group_by(SalesDocumentLine.description)
                     .order_by(func.sum(SalesDocumentLine.net_amount).desc()).limit(8)).all()

    leads = list(db.scalars(select(Lead).where(Lead.customer_id == p.id).order_by(Lead.updated_at.desc())))
    lead_ids = [l.id for l in leads]
    activities = list(db.scalars(select(LeadActivity).where(or_(
        LeadActivity.customer_id == p.id, LeadActivity.lead_id.in_(lead_ids) if lead_ids else False))
        .order_by(LeadActivity.activity_at.desc()).limit(60)))
    lead_numbers = {l.id: l.lead_number for l in leads}
    contacts = list(db.scalars(select(PartnerContact).where(PartnerContact.partner_id == p.id)
                               .order_by(PartnerContact.is_primary.desc(), PartnerContact.contact_name)))
    contact_names = {c.id: c.contact_name for c in contacts}

    machines = db.execute(select(CustomerMachine, MachineDefinition)
                          .join(MachineDefinition, MachineDefinition.id == CustomerMachine.machine_definition_id)
                          .where(CustomerMachine.customer_id == p.id)).all()
    certs = {m: (exp, nxt) for m, exp, nxt in db.execute(
        select(CalibrationReport.customer_machine_id, func.max(CalibrationReport.expiry_date),
               func.max(CalibrationReport.next_calibration_date))
        .where(CalibrationReport.customer_id == p.id, CalibrationReport.report_status != "CANCELLED")
        .group_by(CalibrationReport.customer_machine_id)).all()}
    contracts = list(db.scalars(select(ServiceContract).where(ServiceContract.customer_id == p.id)
                                .order_by(ServiceContract.start_date.desc())))
    service_invoices = list(db.scalars(select(ServiceInvoice).where(ServiceInvoice.customer_id == p.id,
                                                                    ServiceInvoice.status != "Cancelled")
                                       .order_by(ServiceInvoice.invoice_date.desc()).limit(10)))

    last = orders[0].doc_date if orders else None
    total_sales = sum(float(o.net_receivable or 0) for o in orders)
    year_sales = sum(float(o.net_receivable or 0) for o in orders if o.doc_date >= today - timedelta(days=365))
    open_leads = [l for l in leads if l.stage in OPEN_STAGES]
    doc = lambda d: {"id": str(d.id), "doc_number": d.doc_number, "doc_date": d.doc_date, "status": d.status,   # noqa: E731
                     "net_receivable": float(d.net_receivable or 0), "customer_po_number": d.customer_po_number,
                     "converted": d.id in converted}
    return {
        "customer": {
            "id": str(p.id), "code": p.code, "name": p.name, "address": p.address, "city": p.city,
            "territory": p.territory, "phone": p.phone, "cell": p.cell, "email": p.email, "ntn": p.ntn,
            "stn": p.stn, "payment_terms": p.payment_terms, "credit_days": p.credit_days,
            "credit_limit": float(p.credit_limit) if p.credit_limit is not None else None,
            "is_active": p.is_active, "is_supplier": p.is_supplier, "is_customer": p.is_customer,
            # Everything the customer form edits, so saving it from here keeps what is not shown.
            "country": p.country, "country_of_origin": p.country_of_origin, "currency": p.currency,
            "incoterm": p.incoterm, "is_international": p.is_international, "bank_name": p.bank_name,
            "bank_account_number": p.bank_account_number, "bank_iban": p.bank_iban, "bank_swift": p.bank_swift,
        },
        "kpis": {
            "balance": _balances(db, company_id, [p.id]).get(p.id, 0.0),
            "sales_total": total_sales, "sales_12m": year_sales, "orders": len(orders),
            "average_order": round(total_sales / len(orders), 2) if orders else 0,
            "last_order_date": last, "days_since_order": (today - last).days if last else None,
            "segment": _segment(last), "first_order_date": orders[-1].doc_date if orders else None,
            "quotations": len(quotations),
            "quotation_conversion": round(len([q for q in quotations if q.id in converted]) * 100 / len(quotations))
            if quotations else None,
            "last_receipt_date": receipts[0].receipt_date if receipts else None,
            "last_receipt_amount": float(receipts[0].amount) if receipts else None,
            "open_leads": len(open_leads),
            "pipeline_value": sum(float(l.estimated_value or 0) for l in open_leads if l.currency == "PKR"),
            "machines": len(machines), "active_contracts": sum(1 for c in contracts if c.contract_status == "ACTIVE"),
        },
        "sales_by_month": [{"month": m.strftime("%b %y"), "value": round(by_month[(m.year, m.month)], 2)} for m in months],
        "top_products": [{"description": d, "quantity": float(q or 0), "value": float(v or 0), "last": l}
                         for d, q, v, l in top],
        "quotations": [doc(q) for q in quotations[:10]],
        "orders": [doc(o) for o in orders[:10]],
        "receipts": [{"id": str(r.id), "receipt_number": r.receipt_number, "receipt_date": r.receipt_date,
                      "amount": float(r.amount), "reference": getattr(r, "reference", None)} for r in receipts],
        "leads": [{"id": str(l.id), "lead_number": l.lead_number, "title": l.title, "stage": l.stage,
                   "rating": l.rating, "estimated_value": float(l.estimated_value or 0), "currency": l.currency,
                   "probability": STAGES.get(l.stage, 0), "owner": users.get(l.owner_id),
                   "updated_at": l.updated_at} for l in leads],
        "contacts": [_contact(c) for c in contacts],
        "activities": [{
            "id": str(a.id), "activity_type": a.activity_type, "activity_at": a.activity_at, "summary": a.summary,
            "outcome": a.outcome, "due_date": a.due_date, "done_at": a.done_at,
            "open": a.due_date is not None and a.done_at is None,
            "lead_id": str(a.lead_id) if a.lead_id else None, "lead_number": lead_numbers.get(a.lead_id),
            "contact": contact_names.get(a.contact_id), "owner": users.get(a.owner_id),
            "created_by": users.get(a.created_by)} for a in activities],
        "machines": [{"id": str(m.id), "machine_code": m.machine_code, "serial_number": m.serial_number,
                      "category": d.machine_category, "vendor": d.vendor_name, "model": d.model_number,
                      "status": m.machine_status, "location": m.machine_location,
                      "certificate_expiry": certs.get(m.id, (None, None))[0],
                      "next_calibration": certs.get(m.id, (None, None))[1]} for m, d in machines],
        "contracts": [{"id": str(c.id), "contract_number": c.contract_number, "contract_type": c.contract_type,
                       "start_date": c.start_date, "end_date": c.end_date, "billing_frequency": c.billing_frequency,
                       "charge_amount": float(c.charge_amount), "status": c.contract_status} for c in contracts],
        "service_invoices": [{"id": str(i.id), "invoice_number": i.invoice_number, "invoice_date": i.invoice_date,
                              "service_type": i.service_type, "net_receivable": float(i.net_receivable),
                              "status": i.status} for i in service_invoices],
    }


# ------------------------------------------------------------------ contacts

def _contact(c: PartnerContact, partner: BusinessPartner | None = None) -> dict:
    return {"id": str(c.id), "partner_id": str(c.partner_id), "customer_name": partner.name if partner else None,
            "contact_name": c.contact_name, "title": c.title, "department": c.department, "phone": c.phone,
            "cell": c.cell, "whatsapp": c.whatsapp, "email": c.email, "description": c.description,
            "is_primary": c.is_primary, "is_active": c.is_active, "updated_at": c.updated_at}


@router.get("/contacts")
def list_contacts(search: str | None = None, customer_id: uuid.UUID | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=5000),
                  db: Session = Depends(get_db), user: User = Depends(require_permission("crm.contacts.view"))):
    stmt = (select(PartnerContact, BusinessPartner).join(BusinessPartner, BusinessPartner.id == PartnerContact.partner_id)
            .where(PartnerContact.company_id == active_company_id(db)))
    if customer_id:
        stmt = stmt.where(PartnerContact.partner_id == customer_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(PartnerContact.contact_name.ilike(like), PartnerContact.title.ilike(like),
                              PartnerContact.department.ilike(like), PartnerContact.phone.ilike(like),
                              PartnerContact.cell.ilike(like), PartnerContact.email.ilike(like),
                              BusinessPartner.name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(BusinessPartner.name, PartnerContact.is_primary.desc(), PartnerContact.contact_name)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_contact(c, p) for c, p in rows], "total": total, "page": page, "page_size": page_size}


class ContactIn(_Form):
    partner_id: uuid.UUID
    contact_name: str
    title: str | None = None
    department: str | None = None
    phone: str | None = None
    cell: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    description: str | None = None
    is_primary: bool = False
    is_active: bool = True


CONTACT_FIELDS = ("contact_name", "title", "department", "phone", "cell", "whatsapp", "email", "description",
                  "is_primary", "is_active")


def _save_contact(db: Session, c: PartnerContact, payload: ContactIn, user) -> dict:
    partner = _customer(db, payload.partner_id)
    if not payload.contact_name.strip():
        raise HTTPException(400, "Enter the contact's name.")
    c.partner_id = partner.id
    for f in CONTACT_FIELDS:
        v = getattr(payload, f)
        setattr(c, f, v.strip() if isinstance(v, str) else v)
    if c.is_primary:
        # One main contact per customer.
        for other in db.scalars(select(PartnerContact).where(PartnerContact.partner_id == partner.id,
                                                             PartnerContact.id != c.id, PartnerContact.is_primary)):
            other.is_primary = False
    c.updated_by = user.id
    db.commit()
    return _contact(c, partner)


@router.post("/contacts", status_code=201)
def create_contact(payload: ContactIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("crm.contacts.create"))):
    c = PartnerContact(id=uuid.uuid4(), company_id=active_company_id(db), partner_id=payload.partner_id,
                       contact_name=payload.contact_name, created_by=user.id)
    db.add(c)
    return _save_contact(db, c, payload, user)


@router.put("/contacts/{contact_id}")
def update_contact(contact_id: uuid.UUID, payload: ContactIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("crm.contacts.edit"))):
    c = db.get(PartnerContact, contact_id)
    if c is None or c.company_id != active_company_id(db):
        raise HTTPException(404, "Contact not found.")
    return _save_contact(db, c, payload, user)


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("crm.contacts.delete"))):
    c = db.get(PartnerContact, contact_id)
    if c is None or c.company_id != active_company_id(db):
        raise HTTPException(404, "Contact not found.")
    if db.scalar(select(func.count()).where(LeadActivity.contact_id == c.id)):
        raise HTTPException(400, "Activities name this contact. Mark them inactive instead.")
    db.delete(c)
    db.commit()


# ------------------------------------------------------------------ activities

def _activity_rows(db: Session, rows) -> list[dict]:
    users = _users(db)
    today = date.today()
    return [{
        "id": str(a.id), "activity_type": a.activity_type, "activity_at": a.activity_at, "summary": a.summary,
        "outcome": a.outcome, "due_date": a.due_date, "done_at": a.done_at,
        "open": a.due_date is not None and a.done_at is None,
        "overdue": a.due_date is not None and a.done_at is None and a.due_date < today,
        "customer_id": str(cid) if cid else None, "customer_name": cname,
        "lead_id": str(a.lead_id) if a.lead_id else None, "lead_number": lnum, "lead_title": ltitle,
        "contact": contact, "owner": users.get(a.owner_id), "created_by": users.get(a.created_by),
    } for a, cid, cname, lnum, ltitle, contact in rows]


@router.get("/activities")
def list_activities(search: str | None = None, customer_id: uuid.UUID | None = None,
                    activity_type: str | None = None, owner_id: uuid.UUID | None = None,
                    scope: str = Query("all", pattern="^(all|todo|overdue|done)$"),
                    date_from: date | None = None, date_to: date | None = None,
                    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=5000),
                    db: Session = Depends(get_db), user: User = Depends(require_permission("crm.activities.view"))):
    """The whole activity log: everything done or planned with customers and leads."""
    company_id = active_company_id(db)
    cust = func.coalesce(LeadActivity.customer_id, Lead.customer_id)
    stmt = (select(LeadActivity, cust, BusinessPartner.name, Lead.lead_number, Lead.title, PartnerContact.contact_name)
            .outerjoin(Lead, Lead.id == LeadActivity.lead_id)
            .outerjoin(BusinessPartner, BusinessPartner.id == cust)
            .outerjoin(PartnerContact, PartnerContact.id == LeadActivity.contact_id)
            .where(or_(Lead.company_id == company_id, BusinessPartner.company_id == company_id),
                   LeadActivity.activity_type != "Note" if scope != "all" else True))
    if customer_id:
        stmt = stmt.where(cust == customer_id)
    if activity_type:
        stmt = stmt.where(LeadActivity.activity_type == activity_type)
    if owner_id:
        stmt = stmt.where(LeadActivity.owner_id == owner_id)
    today = date.today()
    if scope == "todo":
        stmt = stmt.where(LeadActivity.due_date.is_not(None), LeadActivity.done_at.is_(None))
    elif scope == "overdue":
        stmt = stmt.where(LeadActivity.due_date < today, LeadActivity.done_at.is_(None))
    elif scope == "done":
        stmt = stmt.where(LeadActivity.done_at.is_not(None))
    if date_from:
        stmt = stmt.where(func.date(LeadActivity.activity_at) >= date_from)
    if date_to:
        stmt = stmt.where(func.date(LeadActivity.activity_at) <= date_to)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(LeadActivity.summary.ilike(like), LeadActivity.outcome.ilike(like),
                              BusinessPartner.name.ilike(like), Lead.company_name.ilike(like),
                              Lead.lead_number.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = (LeadActivity.due_date.asc(),) if scope in ("todo", "overdue") else (LeadActivity.activity_at.desc(),)
    rows = db.execute(stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    counts = db.execute(select(
        func.count(case((and_(LeadActivity.due_date < today, LeadActivity.done_at.is_(None)), 1))),
        func.count(case((and_(LeadActivity.due_date.is_not(None), LeadActivity.done_at.is_(None)), 1))),
        func.count(case((LeadActivity.activity_at >= datetime.combine(today - timedelta(days=7), datetime.min.time(),
                                                                     tzinfo=timezone.utc), 1))))
        .select_from(LeadActivity).outerjoin(Lead, Lead.id == LeadActivity.lead_id)
        .outerjoin(BusinessPartner, BusinessPartner.id == func.coalesce(LeadActivity.customer_id, Lead.customer_id))
        .where(or_(Lead.company_id == company_id, BusinessPartner.company_id == company_id))).one()
    return {"items": _activity_rows(db, rows), "total": total, "page": page, "page_size": page_size,
            "counts": {"overdue": counts[0], "todo": counts[1], "last_7_days": counts[2]}}


class CustomerActivityIn(_Form):
    customer_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    activity_type: str
    summary: str
    outcome: str | None = None
    activity_at: datetime | None = None
    due_date: date | None = None
    owner_id: uuid.UUID | None = None
    next_follow_up_date: date | None = None
    next_follow_up_note: str | None = None


@router.post("/activities", status_code=201)
def log_activity(payload: CustomerActivityIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("crm.activities.create"))):
    """Log (or plan) something with a customer: a visit, a complaint call, a courtesy call."""
    customer = _customer(db, payload.customer_id)
    if payload.activity_type not in ACTIVITY_TYPES:
        raise HTTPException(400, f"Activity type must be one of {', '.join(ACTIVITY_TYPES)}.")
    if not payload.summary.strip():
        raise HTTPException(400, "Say what happened, or what is to be done.")
    if payload.lead_id:
        lead = db.get(Lead, payload.lead_id)
        if lead is None or lead.customer_id != customer.id:
            raise HTTPException(400, "That lead is not this customer's.")
    if payload.contact_id:
        contact = db.get(PartnerContact, payload.contact_id)
        if contact is None or contact.partner_id != customer.id:
            raise HTTPException(400, "That contact is not this customer's.")
    owner = payload.owner_id or user.id
    made = []
    for summary, due, when in ((payload.summary.strip(), payload.due_date, payload.activity_at),
                               (payload.next_follow_up_note or "Follow up", payload.next_follow_up_date, None)):
        if summary is None or (made and not due):
            continue
        a = LeadActivity(customer_id=customer.id, lead_id=payload.lead_id, contact_id=payload.contact_id,
                         activity_type=payload.activity_type if not made else "Call", activity_at=when or _now(),
                         summary=summary, outcome=payload.outcome if not made else None, due_date=due,
                         done_at=None if due else _now(), owner_id=owner, created_by=user.id, created_at=_now())
        db.add(a)
        made.append(a)
    db.commit()
    return {"ids": [str(a.id) for a in made]}


class DoneIn(_Form):
    outcome: str | None = None
    next_follow_up_date: date | None = None


@router.post("/activities/{activity_id}/done")
def complete_activity(activity_id: uuid.UUID, payload: DoneIn, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("crm.activities.edit"))):
    """Tick off a to-do (a customer's or a lead's), and plan the next one."""
    a = db.get(LeadActivity, activity_id)
    if a is None:
        raise HTTPException(404, "Activity not found.")
    company = active_company_id(db)
    owner_company = (db.get(Lead, a.lead_id).company_id if a.lead_id
                     else db.get(BusinessPartner, a.customer_id).company_id)
    if owner_company != company:
        raise HTTPException(404, "Activity not found.")
    if a.done_at:
        raise HTTPException(400, "This is already done.")
    a.done_at, a.outcome, a.activity_at = _now(), payload.outcome, _now()
    if payload.next_follow_up_date:
        db.add(LeadActivity(customer_id=a.customer_id, lead_id=a.lead_id, contact_id=a.contact_id,
                            activity_type=a.activity_type, activity_at=_now(), summary="Follow up",
                            due_date=payload.next_follow_up_date, owner_id=a.owner_id, created_by=user.id,
                            created_at=_now()))
    if a.lead_id:
        lead = db.get(Lead, a.lead_id)
        if lead.stage == "New" and a.activity_type != "Note":
            lead.stage = "Contacted"
    db.commit()
    return {"id": str(a.id)}
