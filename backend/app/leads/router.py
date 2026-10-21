"""Leads endpoints: the pipeline, its activities and follow-ups, sources,
assignments, and opportunities among our own customers."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.common.numbering import next_number
from app.core.database import get_db
from app.inventory.router import active_company_id
from app.leads.models import (
    ACTIVITY_TYPES, LOST_REASONS, OPEN_STAGES, RATINGS, STAGES, Lead, LeadActivity, LeadSource,
)
from app.partners.models import BusinessPartner
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument
from app.users.models import User

router = APIRouter(prefix="/leads", tags=["leads"])

VIEW = "leads.view.view"
EDIT = "leads.view.edit"


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


def _owned(db: Session, lead_id: uuid.UUID) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.company_id != active_company_id(db):
        raise HTTPException(404, "Lead not found.")
    return lead


def _users(db: Session) -> dict:
    return {u.id: (u.full_name or u.username) for u in db.scalars(select(User).where(User.is_active.is_(True)))}


def _next_follow_ups(db: Session, lead_ids) -> dict:
    """The earliest open follow-up of each lead."""
    ids = list(lead_ids)
    if not ids:
        return {}
    rows = db.execute(select(LeadActivity.lead_id, func.min(LeadActivity.due_date))
                      .where(LeadActivity.lead_id.in_(ids), LeadActivity.due_date.is_not(None),
                             LeadActivity.done_at.is_(None))
                      .group_by(LeadActivity.lead_id)).all()
    return dict(rows)


def _last_activity(db: Session, lead_ids) -> dict:
    ids = list(lead_ids)
    if not ids:
        return {}
    return dict(db.execute(select(LeadActivity.lead_id, func.max(LeadActivity.activity_at))
                           .where(LeadActivity.lead_id.in_(ids), LeadActivity.done_at.is_not(None)
                                  | LeadActivity.due_date.is_(None))
                           .group_by(LeadActivity.lead_id)).all())


def _summary(lead: Lead, users: dict, sources: dict, customers: dict, follow: dict, last: dict) -> dict:
    value = float(lead.estimated_value or 0)
    nxt = follow.get(lead.id)
    return {
        "id": str(lead.id), "lead_number": lead.lead_number, "lead_date": lead.lead_date, "title": lead.title,
        "customer_id": str(lead.customer_id) if lead.customer_id else None,
        "customer_name": customers.get(lead.customer_id), "is_customer": lead.customer_id is not None,
        "company_name": lead.company_name, "contact_person": lead.contact_person, "designation": lead.designation,
        "phone": lead.phone, "email": lead.email, "city": lead.city, "address": lead.address,
        "source_id": str(lead.source_id) if lead.source_id else None, "source": sources.get(lead.source_id),
        "interest": lead.interest, "estimated_value": value, "currency": lead.currency,
        "weighted_value": round(value * STAGES.get(lead.stage, 0) / 100, 2),
        "probability": STAGES.get(lead.stage, 0),
        "expected_close_date": lead.expected_close_date, "stage": lead.stage, "rating": lead.rating,
        "owner_id": str(lead.owner_id) if lead.owner_id else None, "owner": users.get(lead.owner_id),
        "quotation_id": str(lead.quotation_id) if lead.quotation_id else None,
        "lost_reason": lead.lost_reason, "closed_at": lead.closed_at, "remarks": lead.remarks,
        "next_follow_up": nxt, "overdue": bool(nxt and nxt < date.today()),
        "last_activity_at": last.get(lead.id), "updated_at": lead.updated_at,
    }


def _rows(db: Session, leads: list[Lead]) -> list[dict]:
    ids = [l.id for l in leads]
    sources = {s.id: s.name for s in db.scalars(select(LeadSource).where(
        LeadSource.company_id == active_company_id(db)))}
    cids = {l.customer_id for l in leads if l.customer_id}
    customers = dict(db.execute(select(BusinessPartner.id, BusinessPartner.name)
                                .where(BusinessPartner.id.in_(cids))).all()) if cids else {}
    users, follow, last = _users(db), _next_follow_ups(db, ids), _last_activity(db, ids)
    return [_summary(l, users, sources, customers, follow, last) for l in leads]


# ------------------------------------------------------------------ lookups and summary

@router.get("/lookups")
def lookups(db: Session = Depends(get_db), user: User = Depends(require_permission(VIEW))):
    company_id = active_company_id(db)
    return {
        "stages": [{"name": k, "probability": v, "open": k in OPEN_STAGES} for k, v in STAGES.items()],
        "ratings": RATINGS, "activity_types": ACTIVITY_TYPES, "lost_reasons": LOST_REASONS,
        "sources": [{"id": str(s.id), "name": s.name} for s in db.scalars(
            select(LeadSource).where(LeadSource.company_id == company_id, LeadSource.is_active.is_(True))
            .order_by(LeadSource.sort_order, LeadSource.name))],
        "users": [{"id": str(i), "name": n} for i, n in sorted(_users(db).items(), key=lambda x: x[1].lower())],
    }


@router.get("/summary")
def summary(owner_id: uuid.UUID | None = None, db: Session = Depends(get_db),
            user: User = Depends(require_permission(VIEW))):
    """The figures over the board: what is open and what it is worth, what was won
    and lost this month, how often we win, and which follow-ups are due."""
    company_id = active_company_id(db)
    base = select(Lead).where(Lead.company_id == company_id)
    if owner_id:
        base = base.where(Lead.owner_id == owner_id)
    leads = list(db.scalars(base))
    today = date.today()
    month = today.replace(day=1)
    open_leads = [l for l in leads if l.stage in OPEN_STAGES]
    closed_recent = [l for l in leads if l.stage in ("Won", "Lost") and l.closed_at
                     and l.closed_at.date() >= today - timedelta(days=90)]
    won_recent = [l for l in closed_recent if l.stage == "Won"]
    won_month = [l for l in leads if l.stage == "Won" and l.closed_at and l.closed_at.date() >= month]
    lost_month = [l for l in leads if l.stage == "Lost" and l.closed_at and l.closed_at.date() >= month]
    ids = [l.id for l in open_leads]
    due = db.execute(select(LeadActivity.due_date).where(
        LeadActivity.lead_id.in_(ids), LeadActivity.due_date.is_not(None),
        LeadActivity.done_at.is_(None))).scalars().all() if ids else []
    pkr = lambda ls: sum(float(l.estimated_value or 0) for l in ls if l.currency == "PKR")   # noqa: E731
    return {
        "open_count": len(open_leads), "pipeline_value": pkr(open_leads),
        "weighted_value": sum(float(l.estimated_value or 0) * STAGES[l.stage] / 100
                              for l in open_leads if l.currency == "PKR"),
        "won_month_count": len(won_month), "won_month_value": pkr(won_month), "lost_month_count": len(lost_month),
        "win_rate": round(len(won_recent) * 100 / len(closed_recent)) if closed_recent else None,
        "overdue_follow_ups": sum(1 for d in due if d < today), "today_follow_ups": sum(1 for d in due if d == today),
        "hot_open": sum(1 for l in open_leads if l.rating == "Hot"),
        "by_stage": [{"stage": s, "count": sum(1 for l in leads if l.stage == s),
                      "value": pkr([l for l in leads if l.stage == s])} for s in STAGES],
        "other_currencies": sorted({l.currency for l in open_leads if l.currency != "PKR"}),
    }


# ------------------------------------------------------------------ leads

@router.get("")
def list_leads(search: str | None = None, stage: str | None = None, owner_id: uuid.UUID | None = None,
               source_id: uuid.UUID | None = None, rating: str | None = None, customer_id: uuid.UUID | None = None,
               customers_only: bool = False,
               status: str | None = Query(None, pattern="^(open|closed|won|lost)$"),
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=5000),
               db: Session = Depends(get_db), user: User = Depends(require_permission(VIEW))):
    stmt = select(Lead).where(Lead.company_id == active_company_id(db))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Lead.lead_number.ilike(like), Lead.title.ilike(like), Lead.company_name.ilike(like),
                              Lead.contact_person.ilike(like), Lead.phone.ilike(like), Lead.city.ilike(like),
                              Lead.interest.ilike(like)))
    if stage:
        stmt = stmt.where(Lead.stage == stage)
    if owner_id:
        stmt = stmt.where(Lead.owner_id == owner_id)
    if source_id:
        stmt = stmt.where(Lead.source_id == source_id)
    if rating:
        stmt = stmt.where(Lead.rating == rating)
    if customer_id:
        stmt = stmt.where(Lead.customer_id == customer_id)
    if customers_only:
        stmt = stmt.where(Lead.customer_id.is_not(None))
    if status == "open":
        stmt = stmt.where(Lead.stage.in_(OPEN_STAGES))
    elif status == "closed":
        stmt = stmt.where(Lead.stage.in_(("Won", "Lost")))
    elif status in ("won", "lost"):
        stmt = stmt.where(Lead.stage == status.title())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    leads = list(db.scalars(stmt.order_by(Lead.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    return {"items": _rows(db, leads), "total": total, "page": page, "page_size": page_size}


class LeadIn(_Form):
    lead_date: date | None = None
    title: str
    customer_id: uuid.UUID | None = None
    company_name: str | None = None
    contact_person: str | None = None
    designation: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    address: str | None = None
    source_id: uuid.UUID | None = None
    interest: str | None = None
    estimated_value: Decimal = Decimal("0")
    currency: str = "PKR"
    expected_close_date: date | None = None
    stage: str = "New"
    rating: str = "Warm"
    owner_id: uuid.UUID | None = None
    quotation_id: uuid.UUID | None = None
    lost_reason: str | None = None
    remarks: str | None = None
    #: When creating: the first follow-up, so a new lead never sits without a next step.
    follow_up_date: date | None = None
    follow_up_type: str | None = None
    follow_up_note: str | None = None


FIELDS = ("title", "customer_id", "company_name", "contact_person", "designation", "phone", "email", "city",
          "address", "source_id", "interest", "estimated_value", "currency", "expected_close_date", "rating",
          "owner_id", "quotation_id", "remarks")


def _apply(db: Session, lead: Lead, payload: LeadIn) -> None:
    if payload.stage not in STAGES or payload.rating not in RATINGS:
        raise HTTPException(400, "Choose the stage and the rating.")
    if payload.estimated_value < 0:
        raise HTTPException(400, "The estimated value cannot be negative.")
    data = payload.model_dump()
    customer = None
    if payload.customer_id:
        customer = db.get(BusinessPartner, payload.customer_id)
        if customer is None:
            raise HTTPException(400, "That customer was not found.")
        # A lead for one of our customers takes their details where none were typed.
        for field, value in (("company_name", customer.name), ("phone", customer.phone or customer.cell),
                             ("email", customer.email), ("city", customer.city), ("address", customer.address)):
            if not data.get(field):
                data[field] = value
    if not (data.get("company_name") or "").strip():
        raise HTTPException(400, "Enter the company name, or choose one of our customers.")
    for field in FIELDS:
        value = data.get(field)
        setattr(lead, field, value.strip() if isinstance(value, str) else value)
    _set_stage(lead, payload.stage, payload.lost_reason)


def _set_stage(lead: Lead, stage: str, lost_reason: str | None) -> None:
    if stage == "Lost" and not (lost_reason or lead.lost_reason):
        raise HTTPException(400, "Say why the lead was lost.")
    if stage in ("Won", "Lost"):
        if lead.stage != stage or lead.closed_at is None:
            lead.closed_at = _now()
    else:
        lead.closed_at = None
    lead.lost_reason = (lost_reason or lead.lost_reason) if stage == "Lost" else None
    lead.stage = stage


def _activity(lead: Lead, kind: str, summary: str, user, *, due: date | None = None, outcome=None,
              when: datetime | None = None, owner_id=None) -> LeadActivity:
    if kind not in ACTIVITY_TYPES and kind != "Stage":
        raise HTTPException(400, f"Activity type must be one of {', '.join(ACTIVITY_TYPES)}.")
    act = LeadActivity(activity_type=kind, activity_at=when or _now(), summary=summary, outcome=outcome,
                       due_date=due, done_at=None if due else _now(), owner_id=owner_id or lead.owner_id,
                       created_by=user.id, created_at=_now())
    lead.activities.append(act)
    return act


def _detail(db: Session, lead: Lead) -> dict:
    data = _rows(db, [lead])[0]
    users = _users(db)
    data["activities"] = [{
        "id": str(a.id), "activity_type": a.activity_type, "activity_at": a.activity_at, "summary": a.summary,
        "outcome": a.outcome, "due_date": a.due_date, "done_at": a.done_at,
        "is_follow_up": a.due_date is not None, "open": a.due_date is not None and a.done_at is None,
        "owner": users.get(a.owner_id), "created_by": users.get(a.created_by),
    } for a in sorted(lead.activities, key=lambda a: (a.done_at is None, a.due_date or date.min,
                                                       a.activity_at), reverse=True)]
    quotation = db.get(SalesDocument, lead.quotation_id) if lead.quotation_id else None
    data["quotation"] = ({"id": str(quotation.id), "doc_number": quotation.doc_number,
                          "doc_date": quotation.doc_date, "status": quotation.status,
                          "net_receivable": float(quotation.net_receivable)} if quotation else None)
    return data


@router.get("/customer-opportunities")
def customer_opportunities(min_days: int = Query(90, ge=0, le=3650), search: str | None = None,
                           page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=5000),
                           db: Session = Depends(get_db), user: User = Depends(require_permission(VIEW))):
    """Our customers who have bought before but not in `min_days` days — the
    people worth calling again — from the sales orders themselves."""
    company_id = active_company_id(db)
    sales = (select(SalesDocument.customer_id.label("cid"), func.max(SalesDocument.doc_date).label("last"),
                    func.count(SalesDocument.id).label("orders"),
                    func.coalesce(func.sum(SalesDocument.net_receivable), 0).label("value"))
             .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
                    SalesDocument.status != "Cancelled")
             .group_by(SalesDocument.customer_id).subquery())
    open_leads = (select(Lead.customer_id.label("cid"), func.count(Lead.id).label("n"))
                  .where(Lead.company_id == company_id, Lead.stage.in_(OPEN_STAGES), Lead.customer_id.is_not(None))
                  .group_by(Lead.customer_id).subquery())
    stmt = (select(BusinessPartner, sales.c.last, sales.c.orders, sales.c.value, open_leads.c.n)
            .join(sales, sales.c.cid == BusinessPartner.id)
            .outerjoin(open_leads, open_leads.c.cid == BusinessPartner.id)
            .where(BusinessPartner.is_active.is_(True), sales.c.last <= date.today() - timedelta(days=min_days)))
    if search:
        stmt = stmt.where(BusinessPartner.name.ilike(f"%{search}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(sales.c.value.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    today = date.today()
    return {"items": [{
        "customer_id": str(p.id), "name": p.name, "city": p.city, "phone": p.phone or p.cell,
        "last_order_date": last, "days_since": (today - last).days, "orders": orders, "total_sales": float(value),
        "open_leads": n or 0,
    } for p, last, orders, value, n in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/followups")
def follow_ups(scope: str = Query("due", pattern="^(overdue|today|upcoming|due|all)$"),
               owner_id: uuid.UUID | None = None, db: Session = Depends(get_db),
               user: User = Depends(require_permission(VIEW))):
    """Open follow-ups: overdue, today, upcoming (next 14 days), due (overdue and today) or all."""
    today = date.today()
    stmt = (select(LeadActivity, Lead).join(Lead, Lead.id == LeadActivity.lead_id)
            .where(Lead.company_id == active_company_id(db), LeadActivity.due_date.is_not(None),
                   LeadActivity.done_at.is_(None)))
    if owner_id:
        stmt = stmt.where(LeadActivity.owner_id == owner_id)
    if scope == "overdue":
        stmt = stmt.where(LeadActivity.due_date < today)
    elif scope == "today":
        stmt = stmt.where(LeadActivity.due_date == today)
    elif scope == "upcoming":
        stmt = stmt.where(LeadActivity.due_date > today, LeadActivity.due_date <= today + timedelta(days=14))
    elif scope == "due":
        stmt = stmt.where(LeadActivity.due_date <= today)
    users = _users(db)
    out = []
    for act, lead in db.execute(stmt.order_by(LeadActivity.due_date, Lead.rating)).all():
        out.append({"id": str(act.id), "lead_id": str(lead.id), "lead_number": lead.lead_number,
                    "title": lead.title, "company_name": lead.company_name, "contact_person": lead.contact_person,
                    "phone": lead.phone, "stage": lead.stage, "rating": lead.rating,
                    "activity_type": act.activity_type, "summary": act.summary, "due_date": act.due_date,
                    "days_late": max((today - act.due_date).days, 0), "owner": users.get(act.owner_id)})
    counts = db.execute(select(
        func.count(case((LeadActivity.due_date < today, 1))), func.count(case((LeadActivity.due_date == today, 1))),
        func.count(case((and_(LeadActivity.due_date > today, LeadActivity.due_date <= today + timedelta(days=14)), 1))))
        .select_from(LeadActivity).join(Lead, Lead.id == LeadActivity.lead_id)
        .where(Lead.company_id == active_company_id(db), LeadActivity.due_date.is_not(None),
               LeadActivity.done_at.is_(None), *( [LeadActivity.owner_id == owner_id] if owner_id else []))).one()
    return {"items": out, "counts": {"overdue": counts[0], "today": counts[1], "upcoming": counts[2]}}


@router.get("/assignments")
def assignments(db: Session = Depends(get_db), user: User = Depends(require_permission("leads.assignments.view"))):
    """Each salesperson's open leads, what they are worth, and follow-ups gone overdue."""
    company_id = active_company_id(db)
    today = date.today()
    leads = list(db.scalars(select(Lead).where(Lead.company_id == company_id)))
    overdue = dict(db.execute(select(LeadActivity.owner_id, func.count()).join(Lead, Lead.id == LeadActivity.lead_id)
                              .where(Lead.company_id == company_id, LeadActivity.due_date < today,
                                     LeadActivity.done_at.is_(None)).group_by(LeadActivity.owner_id)).all())
    users = _users(db)
    owners = {l.owner_id for l in leads} | set(users)
    out = []
    for oid in owners:
        mine = [l for l in leads if l.owner_id == oid]
        if oid is not None and oid not in users and not mine:
            continue
        open_ = [l for l in mine if l.stage in OPEN_STAGES]
        won = [l for l in mine if l.stage == "Won"]
        lost = [l for l in mine if l.stage == "Lost"]
        out.append({"owner_id": str(oid) if oid else None, "owner": users.get(oid, "Unassigned" if oid is None else "—"),
                    "open": len(open_), "hot": sum(1 for l in open_ if l.rating == "Hot"),
                    "pipeline_value": sum(float(l.estimated_value or 0) for l in open_ if l.currency == "PKR"),
                    "won": len(won), "lost": len(lost),
                    "win_rate": round(len(won) * 100 / (len(won) + len(lost))) if (won or lost) else None,
                    "overdue_follow_ups": overdue.get(oid, 0)})
    out.sort(key=lambda r: (r["owner_id"] is not None, -r["open"], r["owner"]))
    return {"items": [r for r in out if r["owner_id"] is None and r["open"] or r["owner_id"] is not None]}


class ReassignIn(BaseModel):
    lead_ids: list[uuid.UUID]
    owner_id: uuid.UUID | None = None
    #: Move their open follow-ups to the new owner as well.
    move_follow_ups: bool = True


@router.post("/reassign")
def reassign(payload: ReassignIn, db: Session = Depends(get_db),
             user: User = Depends(require_permission("leads.assignments.edit"))):
    if payload.owner_id and payload.owner_id not in _users(db):
        raise HTTPException(400, "Choose an active user.")
    moved = 0
    for lead_id in payload.lead_ids:
        lead = _owned(db, lead_id)
        lead.owner_id = payload.owner_id
        lead.updated_by = user.id
        if payload.move_follow_ups:
            for a in lead.activities:
                if a.due_date and a.done_at is None:
                    a.owner_id = payload.owner_id
        moved += 1
    db.commit()
    return {"moved": moved}


@router.get("/{lead_id}")
def get_lead(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission(VIEW))):
    return _detail(db, _owned(db, lead_id))


@router.post("", status_code=201)
def create_lead(payload: LeadIn, db: Session = Depends(get_db),
                user: User = Depends(require_permission("leads.view.create"))):
    company_id = active_company_id(db)
    on = payload.lead_date or date.today()
    used = [n for (n,) in db.execute(select(Lead.lead_number).where(
        Lead.company_id == company_id, Lead.lead_number.like(f"LD-{on:%y}%")))]
    highest = max((int(n[5:]) for n in used if n[5:].isdigit()), default=0)
    number = f"LD-{on:%y}{int(next_number(db, company_id, 'lead', str(on.year), continue_from=highest)):05d}"
    lead = Lead(company_id=company_id, lead_number=number, lead_date=on, stage="New",
                owner_id=payload.owner_id or user.id, created_by=user.id, updated_by=user.id)
    if payload.owner_id is None:
        payload.owner_id = user.id
    _apply(db, lead, payload)
    db.add(lead)
    _activity(lead, "Note", f"Lead created{f' — {payload.title}' if payload.title else ''}.", user)
    if payload.follow_up_date:
        _activity(lead, payload.follow_up_type or "Call", payload.follow_up_note or "First contact", user,
                  due=payload.follow_up_date)
    db.commit()
    return _detail(db, lead)


@router.put("/{lead_id}")
def update_lead(lead_id: uuid.UUID, payload: LeadIn, db: Session = Depends(get_db),
                user: User = Depends(require_permission(EDIT))):
    lead = _owned(db, lead_id)
    before = lead.stage
    if payload.lead_date:
        lead.lead_date = payload.lead_date
    _apply(db, lead, payload)
    if lead.stage != before:
        _activity(lead, "Note", f"Stage changed: {before} → {lead.stage}"
                  + (f" ({lead.lost_reason})" if lead.stage == "Lost" else ""), user)
    lead.updated_by = user.id
    db.commit()
    return _detail(db, lead)


class StageIn(BaseModel):
    stage: str
    lost_reason: str | None = None


@router.post("/{lead_id}/stage")
def move_stage(lead_id: uuid.UUID, payload: StageIn, db: Session = Depends(get_db),
               user: User = Depends(require_permission(EDIT))):
    """Move a lead along the board (drag and drop, Won, Lost)."""
    lead = _owned(db, lead_id)
    if payload.stage not in STAGES:
        raise HTTPException(400, "Unknown stage.")
    before = lead.stage
    if before == payload.stage:
        return _detail(db, lead)
    _set_stage(lead, payload.stage, payload.lost_reason)
    _activity(lead, "Note", f"Stage changed: {before} → {lead.stage}"
              + (f" ({lead.lost_reason})" if lead.stage == "Lost" else ""), user)
    if lead.stage in ("Won", "Lost"):
        # A closed lead has nothing left to chase.
        for a in lead.activities:
            if a.due_date and a.done_at is None:
                a.done_at, a.outcome = _now(), f"Closed as {lead.stage}"
    lead.updated_by = user.id
    db.commit()
    return _detail(db, lead)


@router.delete("/{lead_id}", status_code=204)
def delete_lead(lead_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(require_permission("leads.view.delete"))):
    lead = _owned(db, lead_id)
    if lead.stage != "New" or any(a.activity_type not in ("Note",) and a.done_at for a in lead.activities):
        raise HTTPException(400, "Only a new lead with nothing done on it can be deleted; mark it Lost instead.")
    db.delete(lead)
    db.commit()


# ------------------------------------------------------------------ activities and follow-ups

class ActivityIn(_Form):
    activity_type: str
    summary: str
    outcome: str | None = None
    activity_at: datetime | None = None
    #: Plan it instead of logging it: a follow-up on this day.
    due_date: date | None = None
    owner_id: uuid.UUID | None = None
    #: After logging, the next step.
    next_follow_up_date: date | None = None
    next_follow_up_type: str | None = None
    next_follow_up_note: str | None = None
    #: Move the lead on at the same time.
    stage: str | None = None


@router.post("/{lead_id}/activities", status_code=201)
def add_activity(lead_id: uuid.UUID, payload: ActivityIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission(EDIT))):
    lead = _owned(db, lead_id)
    if not payload.summary.strip():
        raise HTTPException(400, "Say what happened, or what is to be done.")
    _activity(lead, payload.activity_type, payload.summary.strip(), user, due=payload.due_date,
              outcome=payload.outcome, when=payload.activity_at, owner_id=payload.owner_id)
    if payload.next_follow_up_date:
        _activity(lead, payload.next_follow_up_type or "Call", payload.next_follow_up_note or "Follow up", user,
                  due=payload.next_follow_up_date)
    if payload.stage and payload.stage != lead.stage and payload.stage in OPEN_STAGES:
        before = lead.stage
        _set_stage(lead, payload.stage, None)
        _activity(lead, "Note", f"Stage changed: {before} → {lead.stage}", user)
    # First contact moves a new lead on by itself.
    if lead.stage == "New" and not payload.due_date and payload.activity_type in ("Call", "Visit", "WhatsApp",
                                                                                   "Email", "Meeting", "Demo"):
        _set_stage(lead, "Contacted", None)
    lead.updated_by = user.id
    db.commit()
    return _detail(db, lead)


class DoneIn(_Form):
    outcome: str | None = None
    next_follow_up_date: date | None = None
    next_follow_up_type: str | None = None
    next_follow_up_note: str | None = None


@router.post("/activities/{activity_id}/done")
def complete_follow_up(activity_id: uuid.UUID, payload: DoneIn, db: Session = Depends(get_db),
                       user: User = Depends(require_permission("leads.followups.edit"))):
    """Tick a follow-up off, say how it went, and plan the next one in the same step."""
    act = db.get(LeadActivity, activity_id)
    if act is None:
        raise HTTPException(404, "Follow-up not found.")
    lead = _owned(db, act.lead_id)
    if act.done_at:
        raise HTTPException(400, "This follow-up is already done.")
    act.done_at, act.outcome = _now(), payload.outcome
    act.activity_at = _now()
    if payload.next_follow_up_date:
        _activity(lead, payload.next_follow_up_type or act.activity_type, payload.next_follow_up_note or "Follow up",
                  user, due=payload.next_follow_up_date, owner_id=act.owner_id)
    if lead.stage == "New" and act.activity_type != "Note":
        _set_stage(lead, "Contacted", None)
    lead.updated_by = user.id
    db.commit()
    return _detail(db, lead)


@router.delete("/activities/{activity_id}", status_code=204)
def delete_activity(activity_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(require_permission(EDIT))):
    act = db.get(LeadActivity, activity_id)
    if act is None:
        raise HTTPException(404, "Activity not found.")
    _owned(db, act.lead_id)
    if not (act.due_date and act.done_at is None):
        raise HTTPException(400, "Only a follow-up not yet done can be removed; what happened stays on record.")
    db.delete(act)
    db.commit()


# ------------------------------------------------------------------ customers and quotations

class LinkCustomerIn(BaseModel):
    customer_id: uuid.UUID


@router.post("/{lead_id}/customer")
def link_customer(lead_id: uuid.UUID, payload: LinkCustomerIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission(EDIT))):
    """The prospect became a customer (made from this lead, or found in our list)."""
    lead = _owned(db, lead_id)
    customer = db.get(BusinessPartner, payload.customer_id)
    if customer is None:
        raise HTTPException(400, "That customer was not found.")
    lead.customer_id = customer.id
    lead.company_name = customer.name
    _activity(lead, "Note", f"Linked to customer {customer.code} {customer.name}.", user)
    db.commit()
    return _detail(db, lead)


@router.get("/{lead_id}/quotations")
def lead_quotations(lead_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(require_permission(VIEW))):
    """The customer's quotations, newest first, to tie one to the lead."""
    lead = _owned(db, lead_id)
    if not lead.customer_id:
        return {"items": []}
    rows = db.scalars(select(SalesDocument).where(SalesDocument.customer_id == lead.customer_id,
                                                  SalesDocument.doc_type == QUOTATION)
                      .order_by(SalesDocument.doc_date.desc()).limit(50))
    return {"items": [{"id": str(q.id), "doc_number": q.doc_number, "doc_date": q.doc_date, "status": q.status,
                       "net_receivable": float(q.net_receivable)} for q in rows]}


# ------------------------------------------------------------------ sources

class SourceIn(_Form):
    name: str
    description: str | None = None
    is_active: bool = True
    sort_order: int = 100


@router.get("/sources/all")
def list_sources(db: Session = Depends(get_db), user: User = Depends(require_permission("leads.sources.view"))):
    """Every source with what came of its leads."""
    company_id = active_company_id(db)
    stats = {sid: (n, won, lost, open_, value) for sid, n, won, lost, open_, value in db.execute(
        select(Lead.source_id, func.count(), func.count(case((Lead.stage == "Won", 1))),
               func.count(case((Lead.stage == "Lost", 1))), func.count(case((Lead.stage.in_(OPEN_STAGES), 1))),
               func.coalesce(func.sum(case((and_(Lead.stage == "Won", Lead.currency == "PKR"),
                                               Lead.estimated_value))), 0))
        .where(Lead.company_id == company_id).group_by(Lead.source_id)).all()}
    out = []
    for s in db.scalars(select(LeadSource).where(LeadSource.company_id == company_id)
                        .order_by(LeadSource.sort_order, LeadSource.name)):
        n, won, lost, open_, value = stats.get(s.id, (0, 0, 0, 0, 0))
        out.append({"id": str(s.id), "name": s.name, "description": s.description, "is_active": s.is_active,
                    "sort_order": s.sort_order, "leads": n, "open": open_, "won": won, "lost": lost,
                    "won_value": float(value),
                    "win_rate": round(won * 100 / (won + lost)) if (won + lost) else None})
    return {"items": out, "total": len(out), "page": 1, "page_size": len(out)}


@router.post("/sources", status_code=201)
def create_source(payload: SourceIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("leads.sources.create"))):
    company_id = active_company_id(db)
    if db.scalar(select(LeadSource).where(LeadSource.company_id == company_id,
                                          func.lower(LeadSource.name) == payload.name.strip().lower())):
        raise HTTPException(400, f"{payload.name.strip()} is already a source.")
    s = LeadSource(company_id=company_id, name=payload.name.strip(), description=payload.description,
                   is_active=payload.is_active, sort_order=payload.sort_order, created_by=user.id)
    db.add(s)
    db.commit()
    return {"id": str(s.id)}


@router.put("/sources/{source_id}")
def update_source(source_id: uuid.UUID, payload: SourceIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("leads.sources.edit"))):
    s = db.get(LeadSource, source_id)
    if s is None or s.company_id != active_company_id(db):
        raise HTTPException(404, "Source not found.")
    s.name, s.description, s.is_active, s.sort_order = (payload.name.strip(), payload.description,
                                                        payload.is_active, payload.sort_order)
    s.updated_by = user.id
    db.commit()
    return {"id": str(s.id)}


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: uuid.UUID, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("leads.sources.delete"))):
    s = db.get(LeadSource, source_id)
    if s is None or s.company_id != active_company_id(db):
        raise HTTPException(404, "Source not found.")
    if db.scalar(select(func.count()).where(Lead.source_id == s.id)):
        raise HTTPException(400, "Leads came from this source. Turn it inactive instead.")
    db.delete(s)
    db.commit()
