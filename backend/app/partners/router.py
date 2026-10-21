"""Customers and suppliers."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status as http
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.inventory.router import active_company_id
from app.partners.models import BusinessPartner
from app.users.models import User

router = APIRouter(prefix="/partners", tags=["partners"])


class PartnerIn(BaseModel):
    code: str
    name: str
    is_customer: bool = True
    is_supplier: bool = False
    address: str | None = None
    city: str | None = None
    territory: str | None = None
    ntn: str | None = None
    stn: str | None = None
    phone: str | None = None
    cell: str | None = None
    email: str | None = None
    payment_terms: str | None = None
    credit_days: int | None = None
    is_active: bool = True

    # What an international supplier needs beyond a local one (spec 16).
    country: str | None = None
    country_of_origin: str | None = None
    is_international: bool = False
    currency: str | None = None
    incoterm: str | None = None
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_iban: str | None = None
    bank_swift: str | None = None
    bank_address: str | None = None


def _out(p: BusinessPartner) -> dict:
    return {
        "id": str(p.id), "code": p.code, "name": p.name,
        "is_customer": p.is_customer, "is_supplier": p.is_supplier,
        "address": p.address, "city": p.city, "territory": p.territory,
        "ntn": p.ntn, "stn": p.stn, "phone": p.phone, "cell": p.cell,
        "email": p.email, "payment_terms": p.payment_terms,
        "credit_days": p.credit_days, "is_active": p.is_active,
        "country": p.country, "country_of_origin": p.country_of_origin,
        "is_international": p.is_international, "currency": p.currency,
        "incoterm": p.incoterm, "bank_name": p.bank_name,
        "bank_account_number": p.bank_account_number, "bank_iban": p.bank_iban,
        "bank_swift": p.bank_swift, "bank_address": p.bank_address,
    }


@router.get("")
def list_partners(
    search: str | None = None,
    role: str | None = Query(None, pattern="^(customer|supplier)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("partners.customers.view")),
):
    stmt = select(BusinessPartner).where(BusinessPartner.company_id == active_company_id(db))
    if role == "customer":
        stmt = stmt.where(BusinessPartner.is_customer.is_(True))
    elif role == "supplier":
        stmt = stmt.where(BusinessPartner.is_supplier.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(BusinessPartner.name.ilike(like), BusinessPartner.code.ilike(like)))
    stmt = stmt.order_by(BusinessPartner.name)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_out(p) for p in rows], "total": total, "page": page, "page_size": page_size}


CUSTOMER_PREFIX = "111112"   # the previous ERP's customer codes: 111112 followed by a serial


@router.get("/next-code")
def next_code(
    role: str = Query("customer", pattern="^(customer|supplier)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("partners.customers.view")),
):
    """The code a new customer would take: one past the highest code in the
    old ERP's numbering. Suppliers have no such series, so none is proposed."""
    if role != "customer":
        return {"code": None}
    codes = db.scalars(select(BusinessPartner.code).where(
        BusinessPartner.company_id == active_company_id(db),
        BusinessPartner.code.like(f"{CUSTOMER_PREFIX}%"))).all()
    serials = [int(c[len(CUSTOMER_PREFIX):]) for c in codes if c[len(CUSTOMER_PREFIX):].isdigit()]
    width = max((len(c) - len(CUSTOMER_PREFIX) for c in codes if c[len(CUSTOMER_PREFIX):].isdigit()), default=6)
    return {"code": f"{CUSTOMER_PREFIX}{(max(serials, default=0) + 1):0{width}d}"}


@router.post("", status_code=http.HTTP_201_CREATED)
def create_partner(
    payload: PartnerIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("partners.customers.create")),
):
    company_id = active_company_id(db)
    payload.code, payload.name = payload.code.strip(), payload.name.strip()
    if not payload.code or not payload.name:
        raise HTTPException(400, "Code and name are required.")
    if db.scalar(select(BusinessPartner).where(
        BusinessPartner.company_id == company_id, BusinessPartner.code == payload.code
    )):
        raise HTTPException(400, f"Partner code '{payload.code}' already exists.")
    same = db.scalar(select(BusinessPartner).where(
        BusinessPartner.company_id == company_id,
        func.lower(func.trim(BusinessPartner.name)) == payload.name.lower()))
    if same:
        raise HTTPException(400, f"'{same.name}' already exists with code {same.code}. "
                                 "Open that one instead of adding it twice.")
    partner = BusinessPartner(company_id=company_id, created_by=user.id, **payload.model_dump())
    db.add(partner)
    db.commit()
    db.refresh(partner)
    return _out(partner)


@router.put("/{partner_id}")
def update_partner(
    partner_id: uuid.UUID,
    payload: PartnerIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("partners.customers.edit")),
):
    partner = db.get(BusinessPartner, partner_id)
    if partner is None:
        raise HTTPException(404, "Partner not found.")
    # Only what the form sent: a field it does not show (the mobile number,
    # credit days, bank address) is kept rather than cleared.
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(partner, key, value)
    partner.updated_by = user.id
    db.commit()
    return _out(partner)
