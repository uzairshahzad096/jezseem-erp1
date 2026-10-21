"""Calibration / Services endpoints: the six screens of the previous ERP,
plus the contract agreement, service invoice and calibration certificate prints."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_permission
from app.calibration import service
from app.calibration.models import (
    BILLING_FREQUENCIES, CONTRACT_STATUSES, CONTRACT_TYPES, MACHINE_STATUSES, OVERALL_RESULTS,
    REPORT_STATUSES, SERVICE_TYPES, CalibrationDefinition, CalibrationReport, CalibrationResult,
    CalibrationTest, CustomerMachine, MachineDefinition, ServiceContract, ServiceContractLine,
    ServiceInvoice,
)
from app.core.database import get_db
from app.finance.errors import FinanceError
from app.inventory.router import active_company_id
from app.partners.models import BusinessPartner
from app.users.models import User

router = APIRouter(prefix="/calibration", tags=["calibration"])


def _perm(sub: str, action: str):
    return require_permission(f"calibration.{sub}.{action}")


def _page(db: Session, stmt, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    return total, list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).unique())


def _blank(value):
    """Empty text from a form is stored as nothing."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _parties(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    return {p.id: p for p in db.scalars(select(BusinessPartner).where(BusinessPartner.id.in_(ids)))} if ids else {}


def _owned(db: Session, model, item_id: uuid.UUID, *options):
    row = db.scalar(select(model).options(*options).where(
        model.id == item_id, model.company_id == active_company_id(db)))
    if row is None:
        raise HTTPException(404, "Record not found.")
    return row


def _apply(row, data: dict, fields) -> None:
    for name in fields:
        if name in data:
            setattr(row, name, _blank(data[name]))


# ------------------------------------------------------------------ lookups

@router.get("/lookups")
def lookups(db: Session = Depends(get_db), user: User = Depends(_perm("machines", "view"))):
    return {"machine_statuses": MACHINE_STATUSES, "billing_frequencies": list(BILLING_FREQUENCIES),
            "contract_statuses": CONTRACT_STATUSES, "contract_types": CONTRACT_TYPES,
            "service_types": SERVICE_TYPES, "overall_results": OVERALL_RESULTS,
            "report_statuses": REPORT_STATUSES}


# ------------------------------------------------------------------ machine definitions

class MachineDefinitionIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    machine_category: str
    vendor_name: str
    model_number: str
    origin: str | None = None
    description: str | None = None
    remarks: str | None = None
    active: bool = True


MD_FIELDS = ("machine_category", "vendor_name", "model_number", "origin", "description", "remarks", "active")


def _md(m: MachineDefinition) -> dict:
    return {"id": str(m.id), **{f: getattr(m, f) for f in MD_FIELDS}, "updated_at": m.updated_at,
            "label": f"{m.machine_category} — {m.vendor_name} {m.model_number}"}


@router.get("/machine-definitions")
def list_machine_definitions(search: str | None = None, active_only: bool = False,
                             page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=5000),
                             db: Session = Depends(get_db), user: User = Depends(_perm("machines", "view"))):
    stmt = select(MachineDefinition).where(MachineDefinition.company_id == active_company_id(db))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(*(getattr(MachineDefinition, f).ilike(like) for f in MD_FIELDS[:5])))
    if active_only:
        stmt = stmt.where(MachineDefinition.active.is_(True))
    total, rows = _page(db, stmt.order_by(MachineDefinition.updated_at.desc()), page, page_size)
    return {"items": [_md(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/machine-definitions", status_code=201)
def create_machine_definition(payload: MachineDefinitionIn, db: Session = Depends(get_db),
                              user: User = Depends(_perm("machines", "create"))):
    row = MachineDefinition(company_id=active_company_id(db), created_by=user.id, updated_by=user.id)
    _apply(row, payload.model_dump(), MD_FIELDS)
    db.add(row)
    db.commit()
    return _md(row)


@router.put("/machine-definitions/{item_id}")
def update_machine_definition(item_id: uuid.UUID, payload: MachineDefinitionIn, db: Session = Depends(get_db),
                              user: User = Depends(_perm("machines", "edit"))):
    row = _owned(db, MachineDefinition, item_id)
    _apply(row, payload.model_dump(), MD_FIELDS)
    row.updated_by = user.id
    db.commit()
    return _md(row)


@router.delete("/machine-definitions/{item_id}", status_code=204)
def delete_machine_definition(item_id: uuid.UUID, db: Session = Depends(get_db),
                              user: User = Depends(_perm("machines", "delete"))):
    row = _owned(db, MachineDefinition, item_id)
    if db.scalar(select(func.count()).where(CustomerMachine.machine_definition_id == row.id)) or \
            db.scalar(select(func.count()).where(CalibrationDefinition.machine_definition_id == row.id)):
        raise HTTPException(400, "Customer machines or calibration definitions use this machine. "
                                 "Mark it inactive instead.")
    db.delete(row)
    db.commit()


# ------------------------------------------------------------------ customer machines

class CustomerMachineIn(BaseModel):
    customer_id: uuid.UUID
    machine_definition_id: uuid.UUID
    machine_code: str | None = None
    serial_number: str | None = None
    installation_date: date | None = None
    machine_status: str = "ACTIVE"
    machine_location: str | None = None
    remarks: str | None = None


CM_FIELDS = ("customer_id", "machine_definition_id", "machine_code", "serial_number", "installation_date",
             "machine_status", "machine_location", "remarks")


def _cm(m: CustomerMachine, parties: dict, defs: dict) -> dict:
    d, p = defs.get(m.machine_definition_id), parties.get(m.customer_id)
    data = {"id": str(m.id), **{f: getattr(m, f) for f in CM_FIELDS}, "updated_at": m.updated_at,
            "customer_id": str(m.customer_id), "machine_definition_id": str(m.machine_definition_id),
            "customer_name": p.name if p else None,
            "machine_category": d.machine_category if d else None, "vendor_name": d.vendor_name if d else None,
            "model_number": d.model_number if d else None, "origin": d.origin if d else None,
            "machine_description": d.description if d else None}
    data["label"] = " · ".join(x for x in (data["machine_category"], data["model_number"],
                                           f"S/N {m.serial_number}" if m.serial_number else None,
                                           m.machine_code) if x)
    return data


def _cm_rows(db: Session, rows: list[CustomerMachine]) -> list[dict]:
    parties = _parties(db, [r.customer_id for r in rows])
    ids = {r.machine_definition_id for r in rows}
    defs = {d.id: d for d in db.scalars(select(MachineDefinition).where(MachineDefinition.id.in_(ids)))} if ids else {}
    return [_cm(r, parties, defs) for r in rows]


@router.get("/customer-machines")
def list_customer_machines(search: str | None = None, customer_id: uuid.UUID | None = None,
                           page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=5000),
                           db: Session = Depends(get_db), user: User = Depends(_perm("customer_machines", "view"))):
    stmt = (select(CustomerMachine)
            .join(MachineDefinition, MachineDefinition.id == CustomerMachine.machine_definition_id)
            .join(BusinessPartner, BusinessPartner.id == CustomerMachine.customer_id)
            .where(CustomerMachine.company_id == active_company_id(db)))
    if customer_id:
        stmt = stmt.where(CustomerMachine.customer_id == customer_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(BusinessPartner.name.ilike(like), CustomerMachine.machine_code.ilike(like),
                              CustomerMachine.serial_number.ilike(like), CustomerMachine.machine_location.ilike(like),
                              MachineDefinition.machine_category.ilike(like), MachineDefinition.vendor_name.ilike(like),
                              MachineDefinition.model_number.ilike(like)))
    total, rows = _page(db, stmt.order_by(CustomerMachine.updated_at.desc()), page, page_size)
    return {"items": _cm_rows(db, rows), "total": total, "page": page, "page_size": page_size}


def _save_cm(db, row, payload: CustomerMachineIn, user):
    company_id = active_company_id(db)
    if db.get(BusinessPartner, payload.customer_id) is None:
        raise HTTPException(400, "Choose the customer.")
    md = db.get(MachineDefinition, payload.machine_definition_id)
    if md is None or md.company_id != company_id:
        raise HTTPException(400, "Choose the machine definition.")
    if payload.machine_status not in MACHINE_STATUSES:
        raise HTTPException(400, f"Machine status must be one of {', '.join(MACHINE_STATUSES)}.")
    _apply(row, payload.model_dump(), CM_FIELDS)
    row.updated_by = user.id
    db.commit()
    return _cm_rows(db, [row])[0]


@router.post("/customer-machines", status_code=201)
def create_customer_machine(payload: CustomerMachineIn, db: Session = Depends(get_db),
                            user: User = Depends(_perm("customer_machines", "create"))):
    row = CustomerMachine(company_id=active_company_id(db), created_by=user.id)
    db.add(row)
    return _save_cm(db, row, payload, user)


@router.put("/customer-machines/{item_id}")
def update_customer_machine(item_id: uuid.UUID, payload: CustomerMachineIn, db: Session = Depends(get_db),
                            user: User = Depends(_perm("customer_machines", "edit"))):
    return _save_cm(db, _owned(db, CustomerMachine, item_id), payload, user)


@router.delete("/customer-machines/{item_id}", status_code=204)
def delete_customer_machine(item_id: uuid.UUID, db: Session = Depends(get_db),
                            user: User = Depends(_perm("customer_machines", "delete"))):
    row = _owned(db, CustomerMachine, item_id)
    if db.scalar(select(func.count()).where(CalibrationReport.customer_machine_id == row.id)) or \
            db.scalar(select(func.count()).where(ServiceContractLine.customer_machine_id == row.id)):
        raise HTTPException(400, "Contracts or calibration reports refer to this machine. "
                                 "Change its status instead.")
    db.delete(row)
    db.commit()


# ------------------------------------------------------------------ contracts

class ContractLineIn(BaseModel):
    customer_machine_id: uuid.UUID | None = None
    description: str
    service_type: str | None = None
    quantity: Decimal = Decimal("1")
    remarks: str | None = None


class ContractIn(BaseModel):
    reference: str | None = None
    contract_date: date
    customer_id: uuid.UUID
    contract_type: str = "MAINTENANCE"
    division: str | None = None
    start_date: date
    end_date: date | None = None
    billing_frequency: str = "MONTHLY"
    currency: str = "PKR"
    charge_amount: Decimal = Decimal("0")
    tax_applicable: bool = False
    tax_percent: Decimal = Decimal("0")
    without_tax_deduction: bool = True
    response_hours: int | None = None
    spare_parts_by: str | None = None
    service_coverage: str | None = None
    additional_terms: str | None = None
    contract_status: str = "DRAFT"
    contract_owner: str | None = None
    remarks: str | None = None
    lines: list[ContractLineIn] = []


CONTRACT_FIELDS = ("reference", "contract_date", "customer_id", "contract_type", "division", "start_date",
                   "end_date", "billing_frequency", "currency", "charge_amount", "tax_applicable", "tax_percent",
                   "without_tax_deduction", "response_hours", "spare_parts_by", "service_coverage",
                   "additional_terms", "contract_status", "contract_owner", "remarks")


def _contract(db: Session, c: ServiceContract, parties: dict, detail: bool = False) -> dict:
    p = parties.get(c.customer_id)
    data = {"id": str(c.id), "contract_number": c.contract_number,
            **{f: getattr(c, f) for f in CONTRACT_FIELDS}, "customer_id": str(c.customer_id),
            "customer_name": p.name if p else None, "updated_at": c.updated_at,
            "charge_amount": float(c.charge_amount), "tax_percent": float(c.tax_percent),
            "equipment": ", ".join(l.description for l in c.lines)}
    if detail:
        machines = {m["id"]: m for m in _cm_rows(db, list(db.scalars(select(CustomerMachine).where(
            CustomerMachine.id.in_([l.customer_machine_id for l in c.lines if l.customer_machine_id])))))}
        data["lines"] = [{"id": str(l.id), "line_number": l.line_number,
                          "customer_machine_id": str(l.customer_machine_id) if l.customer_machine_id else None,
                          "machine_label": machines.get(str(l.customer_machine_id), {}).get("label"),
                          "description": l.description, "service_type": l.service_type,
                          "quantity": float(l.quantity), "remarks": l.remarks} for l in c.lines]
        data["invoices"] = [{"id": str(i.id), "invoice_number": i.invoice_number, "invoice_date": i.invoice_date,
                             "period_from": i.period_from, "period_to": i.period_to, "status": i.status,
                             "net_receivable": float(i.net_receivable)}
                            for i in db.scalars(select(ServiceInvoice).where(ServiceInvoice.contract_id == c.id)
                                                .order_by(ServiceInvoice.invoice_date))]
    return data


@router.get("/contracts")
def list_contracts(search: str | None = None, customer_id: uuid.UUID | None = None,
                   status: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=5000),
                   db: Session = Depends(get_db), user: User = Depends(_perm("contracts", "view"))):
    stmt = (select(ServiceContract).options(selectinload(ServiceContract.lines))
            .join(BusinessPartner, BusinessPartner.id == ServiceContract.customer_id)
            .where(ServiceContract.company_id == active_company_id(db)))
    if customer_id:
        stmt = stmt.where(ServiceContract.customer_id == customer_id)
    if status:
        stmt = stmt.where(ServiceContract.contract_status == status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(ServiceContract.contract_number.ilike(like), BusinessPartner.name.ilike(like),
                              ServiceContract.reference.ilike(like), ServiceContract.contract_owner.ilike(like)))
    total, rows = _page(db, stmt.order_by(ServiceContract.contract_date.desc(),
                                          ServiceContract.contract_number.desc()), page, page_size)
    parties = _parties(db, [r.customer_id for r in rows])
    return {"items": [_contract(db, r, parties) for r in rows], "total": total, "page": page,
            "page_size": page_size}


@router.get("/contracts/{item_id}")
def get_contract(item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_perm("contracts", "view"))):
    c = _owned(db, ServiceContract, item_id, selectinload(ServiceContract.lines))
    return _contract(db, c, _parties(db, [c.customer_id]), detail=True)


def _save_contract(db: Session, c: ServiceContract, payload: ContractIn, user) -> dict:
    if db.get(BusinessPartner, payload.customer_id) is None:
        raise HTTPException(400, "Choose the customer.")
    if payload.billing_frequency not in BILLING_FREQUENCIES:
        raise HTTPException(400, f"Billing frequency must be one of {', '.join(BILLING_FREQUENCIES)}.")
    if payload.contract_status not in CONTRACT_STATUSES:
        raise HTTPException(400, f"Contract status must be one of {', '.join(CONTRACT_STATUSES)}.")
    if payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(400, "The end date is before the start date.")
    if payload.charge_amount < 0:
        raise HTTPException(400, "The charges cannot be negative.")
    _apply(c, payload.model_dump(), CONTRACT_FIELDS)
    if not c.tax_applicable:
        c.tax_percent = Decimal("0")
    c.lines.clear()
    for number, line in enumerate((l for l in payload.lines if l.description.strip()), start=1):
        c.lines.append(ServiceContractLine(
            line_number=number, customer_machine_id=line.customer_machine_id, description=line.description.strip(),
            service_type=_blank(line.service_type), quantity=line.quantity, remarks=_blank(line.remarks)))
    c.updated_by = user.id
    db.commit()
    return get_contract(c.id, db, user)


@router.post("/contracts", status_code=201)
def create_contract(payload: ContractIn, db: Session = Depends(get_db),
                    user: User = Depends(_perm("contracts", "create"))):
    company_id = active_company_id(db)
    c = ServiceContract(company_id=company_id, created_by=user.id,
                        contract_number=service.allocate_number(db, company_id, "contract", payload.contract_date))
    db.add(c)
    return _save_contract(db, c, payload, user)


@router.put("/contracts/{item_id}")
def update_contract(item_id: uuid.UUID, payload: ContractIn, db: Session = Depends(get_db),
                    user: User = Depends(_perm("contracts", "edit"))):
    c = _owned(db, ServiceContract, item_id, selectinload(ServiceContract.lines))
    billed = db.scalar(select(func.count()).where(ServiceInvoice.contract_id == c.id,
                                                  ServiceInvoice.status != "Cancelled"))
    if billed and payload.customer_id != c.customer_id:
        raise HTTPException(400, "This contract has invoices, so its customer cannot change.")
    return _save_contract(db, c, payload, user)


@router.delete("/contracts/{item_id}", status_code=204)
def delete_contract(item_id: uuid.UUID, db: Session = Depends(get_db),
                    user: User = Depends(_perm("contracts", "delete"))):
    c = _owned(db, ServiceContract, item_id)
    if db.scalar(select(func.count()).where(ServiceInvoice.contract_id == c.id)) or \
            db.scalar(select(func.count()).where(CalibrationReport.contract_id == c.id)):
        raise HTTPException(400, "Invoices or calibration reports refer to this contract. "
                                 "Set its status to Terminated instead.")
    db.delete(c)
    db.commit()


@router.get("/contracts/{item_id}/next-invoice")
def contract_next_invoice(item_id: uuid.UUID, db: Session = Depends(get_db),
                          user: User = Depends(_perm("invoices", "create"))):
    """A new invoice filled in from the contract: the next unbilled period, at the contract's charges."""
    c = _owned(db, ServiceContract, item_id, selectinload(ServiceContract.lines))
    if c.contract_status != "ACTIVE":
        raise HTTPException(400, f"{c.contract_number} is {c.contract_status.lower()}; only an active "
                                 "contract can be billed.")
    start, end = service.next_period(db, c)
    if c.end_date and start > c.end_date:
        raise HTTPException(400, f"{c.contract_number} has been billed up to its end date.")
    kind = {"CALIBRATION": "Calibration"}.get(c.contract_type, "Maintenance")
    period = (f"{start:%B %Y}" if c.billing_frequency == "MONTHLY"
              else f"{start:%d-%b-%Y} to {end:%d-%b-%Y}")
    equipment = ", ".join(l.description for l in c.lines)
    return {"customer_id": str(c.customer_id), "contract_id": str(c.id), "service_type": kind,
            "period_from": start, "period_to": end, "currency": c.currency,
            "remarks": f"Contract {c.contract_number}" + (f" ({c.reference})" if c.reference else ""),
            "lines": [{"description": f"{c.billing_frequency.title()} {kind.lower()} charges — {period}"
                                      + (f" ({equipment})" if equipment else ""),
                       "quantity": 1, "unit_price": float(c.charge_amount), "discount_percent": 0,
                       "tax_percent": float(c.tax_percent) if c.tax_applicable else 0}]}


# ------------------------------------------------------------------ invoices

class InvoiceLineIn(BaseModel):
    customer_machine_id: uuid.UUID | None = None
    calibration_report_id: uuid.UUID | None = None
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    discount_percent: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")


class InvoiceIn(BaseModel):
    invoice_date: date
    due_date: date | None = None
    customer_id: uuid.UUID
    contract_id: uuid.UUID | None = None
    service_type: str = "Maintenance"
    period_from: date | None = None
    period_to: date | None = None
    customer_po_number: str | None = None
    currency: str = "PKR"
    exchange_rate: Decimal | None = None
    payment_terms: str | None = None
    remarks: str | None = None
    lines: list[InvoiceLineIn] = []
    #: Post to the ledger on saving.
    post: bool = False


INVOICE_FIELDS = ("invoice_date", "due_date", "customer_id", "contract_id", "service_type", "period_from",
                  "period_to", "customer_po_number", "currency", "exchange_rate", "payment_terms", "remarks")


def _invoice(db: Session, i: ServiceInvoice, parties: dict, contracts: dict, detail: bool = False) -> dict:
    p, c = parties.get(i.customer_id), contracts.get(i.contract_id)
    data = {"id": str(i.id), "invoice_number": i.invoice_number, **{f: getattr(i, f) for f in INVOICE_FIELDS},
            "customer_id": str(i.customer_id), "contract_id": str(i.contract_id) if i.contract_id else None,
            "customer_name": p.name if p else None, "contract_number": c.contract_number if c else None,
            "exchange_rate": float(i.exchange_rate) if i.exchange_rate is not None else None,
            "status": i.status, "in_ledger": i.journal_entry_id is not None and i.status == "Posted",
            "excluding_tax_value": float(i.excluding_tax_value), "sales_tax_value": float(i.sales_tax_value),
            "gross_amount": float(i.gross_amount), "discount_amount": float(i.discount_amount),
            "net_receivable": float(i.net_receivable), "updated_at": i.updated_at,
            "description": ", ".join(l.description for l in i.lines)}
    if detail:
        data["lines"] = [{"id": str(l.id), "line_number": l.line_number,
                          "customer_machine_id": str(l.customer_machine_id) if l.customer_machine_id else None,
                          "calibration_report_id": str(l.calibration_report_id) if l.calibration_report_id else None,
                          "description": l.description, "quantity": float(l.quantity),
                          "unit_price": float(l.unit_price), "discount_percent": float(l.discount_percent),
                          "tax_percent": float(l.tax_percent), "taxable_amount": float(l.taxable_amount),
                          "tax_amount": float(l.tax_amount), "net_amount": float(l.net_amount)} for l in i.lines]
    return data


def _invoice_rows(db: Session, rows: list[ServiceInvoice], detail=False) -> list[dict]:
    parties = _parties(db, [r.customer_id for r in rows])
    ids = {r.contract_id for r in rows if r.contract_id}
    contracts = {c.id: c for c in db.scalars(select(ServiceContract).where(ServiceContract.id.in_(ids)))} if ids else {}
    return [_invoice(db, r, parties, contracts, detail) for r in rows]


@router.get("/invoices")
def list_invoices(search: str | None = None, customer_id: uuid.UUID | None = None, status: str | None = None,
                  contract_id: uuid.UUID | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=5000),
                  db: Session = Depends(get_db), user: User = Depends(_perm("invoices", "view"))):
    stmt = (select(ServiceInvoice).options(selectinload(ServiceInvoice.lines))
            .join(BusinessPartner, BusinessPartner.id == ServiceInvoice.customer_id)
            .where(ServiceInvoice.company_id == active_company_id(db)))
    if customer_id:
        stmt = stmt.where(ServiceInvoice.customer_id == customer_id)
    if contract_id:
        stmt = stmt.where(ServiceInvoice.contract_id == contract_id)
    if status:
        stmt = stmt.where(ServiceInvoice.status == status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(ServiceInvoice.invoice_number.ilike(like), BusinessPartner.name.ilike(like),
                              ServiceInvoice.customer_po_number.ilike(like), ServiceInvoice.remarks.ilike(like)))
    total, rows = _page(db, stmt.order_by(ServiceInvoice.invoice_date.desc(),
                                          ServiceInvoice.invoice_number.desc()), page, page_size)
    return {"items": _invoice_rows(db, rows), "total": total, "page": page, "page_size": page_size}


@router.get("/invoices/{item_id}")
def get_invoice(item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_perm("invoices", "view"))):
    return _invoice_rows(db, [_owned(db, ServiceInvoice, item_id, selectinload(ServiceInvoice.lines))], True)[0]


def _save_invoice(db: Session, inv: ServiceInvoice, payload: InvoiceIn, user) -> dict:
    company_id = active_company_id(db)
    if db.get(BusinessPartner, payload.customer_id) is None:
        raise HTTPException(400, "Choose the customer.")
    if payload.service_type not in SERVICE_TYPES:
        raise HTTPException(400, f"Service type must be one of {', '.join(SERVICE_TYPES)}.")
    if payload.contract_id:
        contract = db.get(ServiceContract, payload.contract_id)
        if contract is None or contract.company_id != company_id or contract.customer_id != payload.customer_id:
            raise HTTPException(400, "The contract chosen belongs to another customer.")
    if payload.period_from and payload.period_to and payload.period_to < payload.period_from:
        raise HTTPException(400, "The period ends before it starts.")
    _apply(inv, payload.model_dump(exclude={"lines", "post"}), INVOICE_FIELDS)
    if inv.currency == "PKR":
        inv.exchange_rate = Decimal("1")
    service.apply_lines(inv, [l.model_dump() for l in payload.lines])
    inv.updated_by = user.id
    db.flush()
    if payload.post:
        service.post(db, inv, user)
    db.commit()
    return get_invoice(inv.id, db, user)


@router.post("/invoices", status_code=201)
def create_invoice(payload: InvoiceIn, db: Session = Depends(get_db),
                   user: User = Depends(_perm("invoices", "create"))):
    company_id = active_company_id(db)
    inv = ServiceInvoice(company_id=company_id, created_by=user.id, status="Draft",
                         invoice_number=service.allocate_number(db, company_id, "invoice", payload.invoice_date))
    db.add(inv)
    return _save_invoice(db, inv, payload, user)


@router.put("/invoices/{item_id}")
def update_invoice(item_id: uuid.UUID, payload: InvoiceIn, db: Session = Depends(get_db),
                   user: User = Depends(_perm("invoices", "edit"))):
    inv = _owned(db, ServiceInvoice, item_id, selectinload(ServiceInvoice.lines))
    if inv.status == "Cancelled":
        raise HTTPException(400, f"{inv.invoice_number} is cancelled.")
    if inv.status == "Posted":
        before = service.figures(inv)
        try:
            with db.no_autoflush:
                payload.post = False
                _apply(inv, payload.model_dump(exclude={"lines", "post"}), INVOICE_FIELDS)
                if inv.currency == "PKR":
                    inv.exchange_rate = Decimal("1")
                service.apply_lines(inv, [l.model_dump() for l in payload.lines])
                if service.figures(inv) != before:
                    raise FinanceError(f"{inv.invoice_number} is posted to the ledger, so its customer, date and "
                                       "amounts cannot change. Cancel it and enter a new invoice instead.")
        except Exception:
            db.rollback()
            raise
        inv.updated_by = user.id
        db.commit()
        return get_invoice(inv.id, db, user)
    return _save_invoice(db, inv, payload, user)


@router.post("/invoices/{item_id}/post")
def post_invoice(item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_perm("invoices", "post"))):
    inv = _owned(db, ServiceInvoice, item_id, selectinload(ServiceInvoice.lines))
    if inv.status != "Draft":
        raise HTTPException(400, f"{inv.invoice_number} is {inv.status.lower()}.")
    service.post(db, inv, user)
    db.commit()
    return get_invoice(inv.id, db, user)


@router.post("/invoices/{item_id}/cancel")
def cancel_invoice(item_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(_perm("invoices", "cancel"))):
    inv = _owned(db, ServiceInvoice, item_id, selectinload(ServiceInvoice.lines))
    if inv.status == "Cancelled":
        raise HTTPException(400, f"{inv.invoice_number} is already cancelled.")
    service.cancel(db, inv, user)
    db.commit()
    return get_invoice(inv.id, db, user)


@router.delete("/invoices/{item_id}", status_code=204)
def delete_invoice(item_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(_perm("invoices", "delete"))):
    inv = _owned(db, ServiceInvoice, item_id)
    if inv.status != "Draft" or inv.journal_entry_id:
        raise HTTPException(400, "Only a draft invoice can be deleted; cancel a posted one.")
    db.delete(inv)
    db.commit()


# ------------------------------------------------------------------ calibration definitions

class TestIn(BaseModel):
    seq: int | None = None
    test_title: str
    expected_result: str | None = None
    unit: str | None = None
    active: bool = True
    remarks: str | None = None


class DefinitionIn(BaseModel):
    machine_definition_id: uuid.UUID
    definition_name: str
    version_number: int = 1
    validity_days: int
    effective_from: date | None = None
    effective_to: date | None = None
    default_temperature: str | None = None
    default_relative_humidity: str | None = None
    default_main_voltage: str | None = None
    default_main_frequency: str | None = None
    default_noise_level: str | None = None
    active: bool = True
    standard_comments: str | None = None
    standard_note: str | None = None
    tests: list[TestIn] = []


DEF_FIELDS = ("machine_definition_id", "definition_name", "version_number", "validity_days", "effective_from",
              "effective_to", "default_temperature", "default_relative_humidity", "default_main_voltage",
              "default_main_frequency", "default_noise_level", "active", "standard_comments", "standard_note")


def _definition(d: CalibrationDefinition, defs: dict, detail=False) -> dict:
    m = defs.get(d.machine_definition_id)
    data = {"id": str(d.id), **{f: getattr(d, f) for f in DEF_FIELDS},
            "machine_definition_id": str(d.machine_definition_id), "updated_at": d.updated_at,
            "vendor_name": m.vendor_name if m else None, "model_number": m.model_number if m else None,
            "machine_category": m.machine_category if m else None, "test_count": len(d.tests)}
    if detail:
        data["tests"] = [{"id": str(t.id), "seq": t.seq, "test_title": t.test_title,
                          "expected_result": t.expected_result, "unit": t.unit, "active": t.active,
                          "remarks": t.remarks} for t in d.tests]
    return data


def _definition_rows(db: Session, rows, detail=False):
    ids = {r.machine_definition_id for r in rows}
    defs = {d.id: d for d in db.scalars(select(MachineDefinition).where(MachineDefinition.id.in_(ids)))} if ids else {}
    return [_definition(r, defs, detail) for r in rows]


@router.get("/definitions")
def list_definitions(search: str | None = None, machine_definition_id: uuid.UUID | None = None,
                     active_only: bool = False,
                     page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=5000),
                     db: Session = Depends(get_db), user: User = Depends(_perm("definitions", "view"))):
    stmt = (select(CalibrationDefinition).options(selectinload(CalibrationDefinition.tests))
            .join(MachineDefinition, MachineDefinition.id == CalibrationDefinition.machine_definition_id)
            .where(CalibrationDefinition.company_id == active_company_id(db)))
    if machine_definition_id:
        stmt = stmt.where(CalibrationDefinition.machine_definition_id == machine_definition_id)
    if active_only:
        stmt = stmt.where(CalibrationDefinition.active.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(CalibrationDefinition.definition_name.ilike(like),
                              MachineDefinition.vendor_name.ilike(like), MachineDefinition.model_number.ilike(like),
                              MachineDefinition.machine_category.ilike(like)))
    total, rows = _page(db, stmt.order_by(CalibrationDefinition.updated_at.desc()), page, page_size)
    return {"items": _definition_rows(db, rows), "total": total, "page": page, "page_size": page_size}


@router.get("/definitions/{item_id}")
def get_definition(item_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(_perm("definitions", "view"))):
    return _definition_rows(db, [_owned(db, CalibrationDefinition, item_id,
                                        selectinload(CalibrationDefinition.tests))], True)[0]


def _save_definition(db, d: CalibrationDefinition, payload: DefinitionIn, user):
    md = db.get(MachineDefinition, payload.machine_definition_id)
    if md is None or md.company_id != active_company_id(db):
        raise HTTPException(400, "Choose the machine definition.")
    if payload.validity_days <= 0:
        raise HTTPException(400, "Validity days must be more than zero.")
    if payload.effective_from and payload.effective_to and payload.effective_to < payload.effective_from:
        raise HTTPException(400, "Effective To is before Effective From.")
    _apply(d, payload.model_dump(exclude={"tests"}), DEF_FIELDS)
    d.tests.clear()
    tests = [t for t in payload.tests if t.test_title.strip()]
    for number, t in enumerate(sorted(tests, key=lambda t: (t.seq is None, t.seq or 0)), start=1):
        d.tests.append(CalibrationTest(seq=t.seq or number, test_title=t.test_title.strip(),
                                       expected_result=_blank(t.expected_result), unit=_blank(t.unit),
                                       active=t.active, remarks=_blank(t.remarks)))
    d.updated_by = user.id
    db.commit()
    return get_definition(d.id, db, user)


@router.post("/definitions", status_code=201)
def create_definition(payload: DefinitionIn, db: Session = Depends(get_db),
                      user: User = Depends(_perm("definitions", "create"))):
    d = CalibrationDefinition(company_id=active_company_id(db), created_by=user.id)
    db.add(d)
    return _save_definition(db, d, payload, user)


@router.put("/definitions/{item_id}")
def update_definition(item_id: uuid.UUID, payload: DefinitionIn, db: Session = Depends(get_db),
                      user: User = Depends(_perm("definitions", "edit"))):
    return _save_definition(db, _owned(db, CalibrationDefinition, item_id,
                                       selectinload(CalibrationDefinition.tests)), payload, user)


@router.delete("/definitions/{item_id}", status_code=204)
def delete_definition(item_id: uuid.UUID, db: Session = Depends(get_db),
                      user: User = Depends(_perm("definitions", "delete"))):
    d = _owned(db, CalibrationDefinition, item_id)
    if db.scalar(select(func.count()).where(CalibrationReport.calibration_definition_id == d.id)):
        raise HTTPException(400, "Calibration reports use this definition. Mark it inactive instead.")
    db.delete(d)
    db.commit()


# ------------------------------------------------------------------ calibration reports

class ResultIn(BaseModel):
    seq: int | None = None
    test_title: str
    expected_result: str | None = None
    unit: str | None = None
    initial_reading: str | None = None
    observed: str | None = None
    uncertainty: str | None = None
    passed: bool | None = None
    remarks: str | None = None


class ReportIn(BaseModel):
    certificate_number: str | None = None
    customer_id: uuid.UUID
    customer_machine_id: uuid.UUID
    calibration_definition_id: uuid.UUID
    contract_id: uuid.UUID | None = None
    contract_line_id: uuid.UUID | None = None
    calibration_date: date
    issue_date: date
    expiry_date: date | None = None
    next_calibration_date: date | None = None
    technician_name: str | None = None
    overall_result: str = "PENDING"
    report_status: str = "DRAFT"
    temperature: str | None = None
    relative_humidity: str | None = None
    main_voltage: str | None = None
    main_frequency: str | None = None
    noise_level: str | None = None
    comments: str | None = None
    note: str | None = None
    remarks: str | None = None
    results: list[ResultIn] = []


REPORT_FIELDS = ("customer_id", "customer_machine_id", "calibration_definition_id", "contract_id",
                 "contract_line_id", "calibration_date", "issue_date", "expiry_date", "next_calibration_date",
                 "technician_name", "overall_result", "report_status", "temperature", "relative_humidity",
                 "main_voltage", "main_frequency", "noise_level", "comments", "note", "remarks")


def _report_rows(db: Session, rows: list[CalibrationReport], detail=False) -> list[dict]:
    parties = _parties(db, [r.customer_id for r in rows])
    machines = {m["id"]: m for m in _cm_rows(db, list(db.scalars(select(CustomerMachine).where(
        CustomerMachine.id.in_({r.customer_machine_id for r in rows})))))} if rows else {}
    ids = {r.calibration_definition_id for r in rows}
    defs = {d.id: d for d in db.scalars(select(CalibrationDefinition).where(CalibrationDefinition.id.in_(ids)))} \
        if ids else {}
    cids = {r.contract_id for r in rows if r.contract_id}
    contracts = {c.id: c for c in db.scalars(select(ServiceContract).where(ServiceContract.id.in_(cids)))} \
        if cids else {}
    out = []
    for r in rows:
        m, p = machines.get(str(r.customer_machine_id), {}), parties.get(r.customer_id)
        d, c = defs.get(r.calibration_definition_id), contracts.get(r.contract_id)
        data = {"id": str(r.id), "certificate_number": r.certificate_number,
                **{f: getattr(r, f) for f in REPORT_FIELDS},
                **{f: (str(getattr(r, f)) if getattr(r, f) else None) for f in
                   ("customer_id", "customer_machine_id", "calibration_definition_id", "contract_id",
                    "contract_line_id")},
                "customer_name": p.name if p else None, "machine_code": m.get("machine_code"),
                "vendor_name": m.get("vendor_name"), "model_number": m.get("model_number"),
                "serial_number": m.get("serial_number"), "machine_category": m.get("machine_category"),
                "machine_label": m.get("label"), "definition_name": d.definition_name if d else None,
                "contract_number": c.contract_number if c else None, "updated_at": r.updated_at}
        if detail:
            data["results"] = [{"id": str(x.id), "seq": x.seq, "test_title": x.test_title,
                                "expected_result": x.expected_result, "unit": x.unit,
                                "initial_reading": x.initial_reading, "observed": x.observed,
                                "uncertainty": x.uncertainty, "passed": x.passed, "remarks": x.remarks}
                               for x in r.results]
        out.append(data)
    return out


@router.get("/reports")
def list_reports(search: str | None = None, customer_id: uuid.UUID | None = None, status: str | None = None,
                 due_within_days: int | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=5000),
                 db: Session = Depends(get_db), user: User = Depends(_perm("reports", "view"))):
    stmt = (select(CalibrationReport)
            .join(BusinessPartner, BusinessPartner.id == CalibrationReport.customer_id)
            .join(CustomerMachine, CustomerMachine.id == CalibrationReport.customer_machine_id)
            .where(CalibrationReport.company_id == active_company_id(db)))
    if customer_id:
        stmt = stmt.where(CalibrationReport.customer_id == customer_id)
    if status:
        stmt = stmt.where(CalibrationReport.report_status == status)
    if due_within_days is not None:
        stmt = stmt.where(CalibrationReport.next_calibration_date <= date.today() + timedelta(days=due_within_days),
                          CalibrationReport.report_status != "CANCELLED")
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(CalibrationReport.certificate_number.ilike(like), BusinessPartner.name.ilike(like),
                              CustomerMachine.serial_number.ilike(like), CustomerMachine.machine_code.ilike(like),
                              CalibrationReport.technician_name.ilike(like)))
    total, rows = _page(db, stmt.order_by(CalibrationReport.calibration_date.desc(),
                                          CalibrationReport.certificate_number.desc()), page, page_size)
    return {"items": _report_rows(db, rows), "total": total, "page": page, "page_size": page_size}


@router.get("/reports/{item_id}")
def get_report(item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_perm("reports", "view"))):
    return _report_rows(db, [_owned(db, CalibrationReport, item_id, selectinload(CalibrationReport.results))],
                        True)[0]


def _save_report(db: Session, r: CalibrationReport, payload: ReportIn, user) -> dict:
    company_id = active_company_id(db)
    machine = db.get(CustomerMachine, payload.customer_machine_id)
    if machine is None or machine.company_id != company_id or machine.customer_id != payload.customer_id:
        raise HTTPException(400, "Choose one of this customer's installed machines.")
    definition = db.get(CalibrationDefinition, payload.calibration_definition_id)
    if definition is None or definition.company_id != company_id:
        raise HTTPException(400, "Choose the calibration definition.")
    if payload.contract_id:
        contract = db.get(ServiceContract, payload.contract_id)
        if contract is None or contract.customer_id != payload.customer_id:
            raise HTTPException(400, "The contract chosen belongs to another customer.")
    if payload.overall_result not in OVERALL_RESULTS or payload.report_status not in REPORT_STATUSES:
        raise HTTPException(400, "Choose the overall result and the report status.")
    data = payload.model_dump(exclude={"results", "certificate_number"})
    # Expiry follows the definition's validity when it is left blank.
    if data["expiry_date"] is None:
        data["expiry_date"] = payload.issue_date + timedelta(days=definition.validity_days)
    if data["expiry_date"] < payload.issue_date:
        raise HTTPException(400, "The expiry date is before the issue date.")
    _apply(r, data, REPORT_FIELDS)
    number = _blank(payload.certificate_number)
    if number and number != r.certificate_number:
        clash = db.scalar(select(CalibrationReport.id).where(CalibrationReport.company_id == company_id,
                                                             CalibrationReport.certificate_number == number,
                                                             CalibrationReport.id != r.id))
        if clash:
            raise HTTPException(400, f"Certificate number {number} is already used.")
        r.certificate_number = number
    elif not r.certificate_number:
        r.certificate_number = service.allocate_number(db, company_id, "certificate", payload.issue_date)
    r.results.clear()
    rows = [x for x in payload.results if x.test_title.strip()]
    for number_, x in enumerate(rows, start=1):
        r.results.append(CalibrationResult(
            seq=x.seq or number_, test_title=x.test_title.strip(), expected_result=_blank(x.expected_result),
            unit=_blank(x.unit), initial_reading=_blank(x.initial_reading), observed=_blank(x.observed),
            uncertainty=_blank(x.uncertainty), passed=x.passed, remarks=_blank(x.remarks)))
    r.updated_by = user.id
    db.commit()
    return get_report(r.id, db, user)


@router.post("/reports", status_code=201)
def create_report(payload: ReportIn, db: Session = Depends(get_db), user: User = Depends(_perm("reports", "create"))):
    r = CalibrationReport(company_id=active_company_id(db), created_by=user.id, certificate_number="")
    db.add(r)
    return _save_report(db, r, payload, user)


@router.put("/reports/{item_id}")
def update_report(item_id: uuid.UUID, payload: ReportIn, db: Session = Depends(get_db),
                  user: User = Depends(_perm("reports", "edit"))):
    return _save_report(db, _owned(db, CalibrationReport, item_id, selectinload(CalibrationReport.results)),
                        payload, user)


@router.delete("/reports/{item_id}", status_code=204)
def delete_report(item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_perm("reports", "delete"))):
    r = _owned(db, CalibrationReport, item_id)
    if r.report_status == "ISSUED":
        raise HTTPException(400, "An issued certificate cannot be deleted; set it to Cancelled instead.")
    db.delete(r)
    db.commit()


# ------------------------------------------------------------------ prints

def _pdf(content: bytes, name: str) -> Response:
    safe = name.replace("/", "-")
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{safe}.pdf"'})


@router.get("/contracts/{item_id}/print.pdf")
def print_contract(item_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(_perm("contracts", "print"))):
    from app.calibration.pdf import render_agreement
    c = _owned(db, ServiceContract, item_id, selectinload(ServiceContract.lines))
    customer = db.get(BusinessPartner, c.customer_id)
    return _pdf(render_agreement(c, customer), f"agreement-{c.contract_number}")


@router.get("/reports/{item_id}/print.pdf")
def print_certificate(item_id: uuid.UUID, db: Session = Depends(get_db),
                      user: User = Depends(_perm("reports", "print"))):
    from app.calibration.pdf import render_certificate
    r = _owned(db, CalibrationReport, item_id, selectinload(CalibrationReport.results))
    if r.report_status == "CANCELLED":
        raise HTTPException(400, "This certificate is cancelled.")
    machine = db.get(CustomerMachine, r.customer_machine_id)
    model = db.get(MachineDefinition, machine.machine_definition_id) if machine else None
    return _pdf(render_certificate(r, db.get(BusinessPartner, r.customer_id), machine, model),
                f"certificate-{r.certificate_number}")


@router.get("/invoices/{item_id}/print.pdf")
def print_invoice(item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_perm("invoices", "print"))):
    from app.documents.pdf import render_document
    inv = _owned(db, ServiceInvoice, item_id, selectinload(ServiceInvoice.lines))
    if inv.status == "Cancelled":
        raise HTTPException(400, "This invoice is cancelled.")
    customer = db.get(BusinessPartner, inv.customer_id)
    contract = db.get(ServiceContract, inv.contract_id) if inv.contract_id else None
    period = (f"{inv.period_from:%d-%b-%Y} to {inv.period_to:%d-%b-%Y}"
              if inv.period_from and inv.period_to else None)
    content = render_document(
        doc_kind="service_invoice",
        header={"title": "SERVICE INVOICE" if inv.status == "Posted" else "PROFORMA SERVICE INVOICE",
                "doc_number": inv.invoice_number, "doc_date": inv.invoice_date.strftime("%B %d, %Y"),
                "extra_meta": [("PO NO #", inv.customer_po_number), ("Service", inv.service_type),
                               ("Contract", contract.contract_number if contract else None),
                               ("Period", period),
                               ("Due Date", inv.due_date.strftime("%B %d, %Y") if inv.due_date else None),
                               ("Payment Terms", inv.payment_terms)],
                "without_sales_tax": not inv.sales_tax_value, "remarks": inv.remarks, "currency": inv.currency},
        customer={"name": customer.name if customer else "", "address": customer.address if customer else None,
                  "ntn": customer.ntn if customer else None, "stn": customer.stn if customer else None},
        lines=[{"description": l.description, "quantity": l.quantity, "unit_price": l.unit_price,
                "tax_percent": l.tax_percent, "taxable_amount": l.taxable_amount, "tax_amount": l.tax_amount,
                "net_amount": l.net_amount} for l in inv.lines],
        totals={"excluding_tax_value": inv.excluding_tax_value, "sales_tax_value": inv.sales_tax_value,
                "gross_amount": inv.gross_amount, "discount_amount": inv.discount_amount, "freight_amount": 0,
                "net_total": inv.net_receivable})
    return _pdf(content, f"service-invoice-{inv.invoice_number}")
