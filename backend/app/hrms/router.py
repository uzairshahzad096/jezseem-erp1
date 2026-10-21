"""
HRMS REST API.

Every endpoint declares its own permission and resolves the company on the
server. Rules live in the service modules (attendance, leave, payroll); this
file checks who is asking, calls them, records the audit entry and shapes
the answer.
"""

import re
import uuid
from datetime import date, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.audit import service as audit
from app.audit.service import AuditContext, request_context
from app.auth.dependencies import require_permission
from app.common.numbering import next_number
from app.companies.models import Branch, Company
from app.core.config import settings as app_settings
from app.core.database import get_db
from app.hrms import attendance, leave, outputs, payroll
from app.hrms import models as m
from app.hrms import schemas as s
from app.hrms.calendar import month_bounds
from app.hrms.setup import get_settings, install_defaults
from app.finance.models import Account
from app.inventory import images
from app.inventory.router import active_company_id
from app.users.models import User

router = APIRouter(prefix="/hrms", tags=["hrms"])

#: Subdirectory of UPLOAD_DIR holding employee photos.
EMPLOYEE_PHOTO_DIR = "employees"

CONSTRAINT_MESSAGES = {
    "uq_hr_department_code": "A department with that code already exists.",
    "uq_hr_designation_code": "A designation with that code already exists.",
    "uq_hr_shift_code": "A shift with that code already exists.",
    "uq_hr_holiday_date": "There is already a holiday on that date.",
    "uq_hr_leave_type_code": "A leave type with that code already exists.",
    "uq_hr_salary_component_code": "A salary component with that code already exists.",
    "uq_hr_employee_code": "That employee code is already in use.",
    "uq_hr_payroll_month": "A payroll run already exists for that month.",
}


def _conflict(exc: IntegrityError) -> HTTPException:
    """A database refusal, said in the user's terms."""
    text = str(exc.orig)
    for name, message in CONSTRAINT_MESSAGES.items():
        if name in text:
            return HTTPException(409, message)
    if "foreign key" in text.lower():
        return HTTPException(409, "This record is used elsewhere, so it cannot be deleted. "
                                  "Switch it to inactive instead.")
    return HTTPException(409, "That could not be saved because it conflicts with an existing record.")


def _flush(db: Session) -> None:
    """Send pending changes to the database. Duplicates are checked for
    before this point; a refusal here is two people saving the same thing at
    the same moment, and still comes back as a readable message."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc)


def _auto_code(db: Session, model, company_id: uuid.UUID, name: str) -> str:
    """A short code made from a name, for a setup row saved without one.

    An abbreviation given in brackets is used as it stands ("Information
    Technology (IT)" gives IT). Otherwise several words give their initials
    ("Human Resources" gives HR) and a single word its first five letters
    ("Sales" gives SALES). A number is added if the code is already taken.
    """
    bracket = re.search(r"\(([A-Za-z0-9&]{2,10})\)", name)
    words = re.findall(r"[A-Za-z0-9]+", re.sub(r"\(.*?\)", " ", name))
    words = [w for w in words if w.lower() not in ("and", "of", "the", "for")] or words
    if bracket:
        base = bracket.group(1)
    elif len(words) > 1:
        base = "".join(w[0] for w in words)
    else:
        base = (words[0] if words else "CODE")[:5]
    base = re.sub(r"[^A-Z0-9]", "", base.upper())[:26] or "CODE"
    taken = set(db.scalars(select(model.code).where(model.company_id == company_id, model.code.like(f"{base}%"))))
    code, n = base, 1
    while code in taken:
        n += 1
        code = f"{base}{n}"
    return code


def _check_department_level(db: Session, row) -> None:
    """Departments go two levels deep: a department and its sub departments."""
    if not isinstance(row, m.Department) or row.parent_id is None:
        return
    if row.parent_id == row.id:
        raise HTTPException(400, "A department cannot be its own parent.")
    parent = db.get(m.Department, row.parent_id)
    if parent is None or parent.company_id != row.company_id:
        raise HTTPException(404, "Department not found.")
    if parent.parent_id is not None:
        raise HTTPException(400, f"{parent.name} is itself a sub department. Choose a main department.")
    has_subs = db.scalar(select(m.Department.name).where(m.Department.parent_id == row.id).limit(1))
    if has_subs is not None:
        raise HTTPException(400, f"{row.name} has sub departments of its own (such as {has_subs}), "
                                 "so it cannot be made a sub department.")


def _refuse_duplicate(db: Session, model, company_id: uuid.UUID, row, label: str) -> None:
    """Setup rows are unique by code (holidays by date) within a company."""
    field = "holiday_date" if model is m.Holiday else "code"
    value = getattr(row, field)
    clash = db.scalar(select(model.id).where(model.company_id == company_id, getattr(model, field) == value,
                                             model.id != row.id))
    if clash is not None:
        shown = f"{value:%d-%b-%Y}" if isinstance(value, date) else value
        raise HTTPException(409, f"{label} {shown} already exists.")


def _save(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict(exc)


def _uuid(value, what: str = "id") -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(400, f"'{value}' is not a valid {what}.")


def _dict(obj) -> dict:
    out = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.key)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, time):
            value = value.strftime("%H:%M")
        out[column.key] = value
    return out


def _apply(obj, data: dict) -> None:
    for key, value in data.items():
        if key.endswith("_id"):
            value = _uuid(value, key)
        elif isinstance(value, str):
            value = value.strip() or None
        setattr(obj, key, value)


def _allowed(user: User, code: str) -> bool:
    if app_settings.AUTH_DISABLED or user.is_superuser:
        return True
    return code in {perm.code for role in user.roles for perm in role.permissions}


def _owned(db: Session, model, company_id: uuid.UUID, row_id: uuid.UUID, what: str):
    row = db.get(model, row_id)
    if row is None or row.company_id != company_id:
        raise HTTPException(404, f"{what} not found.")
    return row


def _names(db: Session, model, company_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(db.execute(select(model.id, model.name).where(model.company_id == company_id)).all())


# ======================================================================
# Settings, lookups and the master lists
# ======================================================================

@router.get("/settings")
def read_settings(db: Session = Depends(get_db), user: User = Depends(require_permission("hrms.module.view"))):
    company_id = active_company_id(db)
    settings = get_settings(db, company_id)
    db.commit()
    return _dict(settings)


@router.put("/settings")
def write_settings(payload: s.SettingsIn, db: Session = Depends(get_db),
                   ctx: AuditContext = Depends(request_context),
                   user: User = Depends(require_permission("hrms.setup.edit"))):
    company_id = active_company_id(db)
    settings = get_settings(db, company_id)
    before = audit.snapshot(settings)
    _apply(settings, payload.model_dump())
    settings.employee_code_prefix = (payload.employee_code_prefix or "").strip().upper()
    settings.updated_by = user.id
    old, new = audit.changed(before, audit.snapshot(settings))
    if new:
        audit.record(db, ctx, action="update", module="hrms", entity="hr_settings", entity_id=settings.id,
                     company_id=company_id, old_values=old, new_values=new)
    _save(db)
    return _dict(settings)


@router.post("/setup/install-defaults")
def setup_defaults(db: Session = Depends(get_db), ctx: AuditContext = Depends(request_context),
                   user: User = Depends(require_permission("hrms.setup.edit"))):
    """Add the standard departments, designations, shift, leave types and
    salary components that are missing. Amounts are all zero."""
    company_id = active_company_id(db)
    added = install_defaults(db, company_id)
    audit.record(db, ctx, action="install_defaults", module="hrms", entity="hr_setup",
                 company_id=company_id, new_values=added)
    _save(db)
    return added


@router.get("/lookups")
def lookups(db: Session = Depends(get_db), user: User = Depends(require_permission("hrms.module.view"))):
    """Everything the HR forms offer in a dropdown, in one call."""
    company_id = active_company_id(db)

    def plain(value):
        return float(value) if isinstance(value, Decimal) else str(value) if isinstance(value, uuid.UUID) else value

    def rows(model, order, *fields):
        return [{"id": str(r.id), **{f: plain(getattr(r, f)) for f in fields}}
                for r in db.scalars(select(model).where(model.company_id == company_id).order_by(order))]

    return {
        # What the next new employee will be numbered, shown on the form.
        "next_employee_code": _next_employee_code(db, company_id),
        # Whether the Confidential tab of the employee form is shown / editable.
        "can_see_pay": _allowed(user, "hrms.payroll.view"),
        "can_edit_pay": _allowed(user, "hrms.payroll.edit"),
        "week_off_days": get_settings(db, company_id).week_off_days,
        "departments": rows(m.Department, m.Department.name, "code", "name", "is_active", "parent_id"),
        "designations": rows(m.Designation, m.Designation.name, "code", "name", "is_active", "grade"),
        "shifts": rows(m.Shift, m.Shift.name, "code", "name", "is_active"),
        "leave_types": rows(m.LeaveType, m.LeaveType.sort_order, "code", "name", "is_paid", "annual_days", "is_active"),
        "salary_components": rows(m.SalaryComponent, m.SalaryComponent.sort_order, "code", "name", "kind",
                                  "calc_type", "default_value", "is_active"),
        "branches": [{"id": str(b.id), "code": b.code, "name": b.name}
                     for b in db.scalars(select(Branch).where(Branch.company_id == company_id).order_by(Branch.name))],
        "employees": [{"id": str(e.id), "code": e.employee_code, "name": e.full_name, "status": e.status}
                      for e in db.scalars(select(m.Employee).where(m.Employee.company_id == company_id)
                                          .order_by(m.Employee.employee_code))],
        "users": [{"id": str(u.id), "username": u.username, "name": u.full_name}
                  for u in db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username))],
    }


def _master(path: str, model, schema, order, entity: str, label: str) -> None:
    """List / add / edit / delete for one setup table."""

    @router.get(f"/{path}", name=f"list_{entity}")
    def list_rows(db: Session = Depends(get_db), user: User = Depends(require_permission("hrms.module.view"))):
        company_id = active_company_id(db)
        return [_dict(r) for r in db.scalars(select(model).where(model.company_id == company_id).order_by(order))]

    @router.post(f"/{path}", status_code=201, name=f"create_{entity}")
    def create_row(payload: schema, db: Session = Depends(get_db), ctx: AuditContext = Depends(request_context),
                   user: User = Depends(require_permission("hrms.setup.edit"))):
        company_id = active_company_id(db)
        row = model(id=uuid.uuid4(), company_id=company_id, created_by=user.id)
        _apply(row, payload.model_dump())
        if hasattr(row, "code") and not row.code:
            row.code = _auto_code(db, model, company_id, row.name)
        _check_department_level(db, row)
        _refuse_duplicate(db, model, company_id, row, label)
        db.add(row)
        _flush(db)
        audit.record(db, ctx, action="create", module="hrms", entity=entity, entity_id=row.id,
                     company_id=company_id, new_values=audit.snapshot(row))
        _save(db)
        return _dict(row)

    @router.put(f"/{path}/{{row_id}}", name=f"update_{entity}")
    def update_row(row_id: uuid.UUID, payload: schema, db: Session = Depends(get_db),
                   ctx: AuditContext = Depends(request_context),
                   user: User = Depends(require_permission("hrms.setup.edit"))):
        company_id = active_company_id(db)
        row = _owned(db, model, company_id, row_id, label)
        before = audit.snapshot(row)
        data = payload.model_dump()
        if "code" in data and not data["code"]:
            data.pop("code")                     # a blank code on an edit keeps the one it has
        _apply(row, data)
        _check_department_level(db, row)
        _refuse_duplicate(db, model, company_id, row, label)
        row.updated_by = user.id
        _flush(db)
        old, new = audit.changed(before, audit.snapshot(row))
        if new:
            audit.record(db, ctx, action="update", module="hrms", entity=entity, entity_id=row.id,
                         company_id=company_id, old_values=old, new_values=new)
        _save(db)
        return _dict(row)

    @router.delete(f"/{path}/{{row_id}}", status_code=204, name=f"delete_{entity}")
    def delete_row(row_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuditContext = Depends(request_context),
                   user: User = Depends(require_permission("hrms.setup.delete"))):
        company_id = active_company_id(db)
        row = _owned(db, model, company_id, row_id, label)
        old = audit.snapshot(row)
        db.expunge(row)
        try:
            # In its own savepoint: a row that is in use is refused by its
            # foreign keys, and only this statement is undone.
            with db.begin_nested():
                db.execute(delete(model).where(model.id == row_id))
        except IntegrityError:
            raise HTTPException(409, f"This {label.lower()} is in use, so it cannot be deleted. "
                                     "Switch it to inactive instead.")
        audit.record(db, ctx, action="delete", module="hrms", entity=entity, entity_id=row_id,
                     company_id=company_id, old_values=old)
        _save(db)
        return Response(status_code=204)


_master("departments", m.Department, s.DepartmentIn, m.Department.name, "hr_department", "Department")
_master("designations", m.Designation, s.DesignationIn, m.Designation.name, "hr_designation", "Designation")
_master("shifts", m.Shift, s.ShiftIn, m.Shift.name, "hr_shift", "Shift")
_master("holidays", m.Holiday, s.HolidayIn, m.Holiday.holiday_date.desc(), "hr_holiday", "Holiday")
_master("leave-types", m.LeaveType, s.LeaveTypeIn, m.LeaveType.sort_order, "hr_leave_type", "Leave type")
_master("salary-components", m.SalaryComponent, s.SalaryComponentIn, m.SalaryComponent.sort_order,
        "hr_salary_component", "Salary component")


# ======================================================================
# Employees
# ======================================================================

def _next_employee_code(db: Session, company_id: uuid.UUID) -> str:
    settings = get_settings(db, company_id)
    prefix = settings.employee_code_prefix or ""
    highest = 0
    for code in db.scalars(select(m.Employee.employee_code).where(
            m.Employee.company_id == company_id, m.Employee.employee_code.like(f"{prefix}%"))):
        tail = code[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:0{settings.employee_code_digits}d}"


def _employee_row(e: m.Employee, names: dict, user: User | None = None) -> dict:
    """An employee as the screens show them. The confidential fields (pay
    and bank details) are left out unless the user may see payroll."""
    data = _dict(e)
    if user is None or not _allowed(user, "hrms.payroll.view"):
        for key in m.CONFIDENTIAL_FIELDS:
            data.pop(key, None)
    data["department"] = names["departments"].get(e.department_id)
    data["sub_department"] = names["departments"].get(e.sub_department_id)
    data["designation"] = names["designations"].get(e.designation_id)
    data["shift"] = names["shifts"].get(e.shift_id)
    data["branch"] = names["branches"].get(e.branch_id)
    return data


def _employee_names(db: Session, company_id: uuid.UUID) -> dict:
    return {"departments": _names(db, m.Department, company_id),
            "designations": _names(db, m.Designation, company_id),
            "shifts": _names(db, m.Shift, company_id),
            "branches": _names(db, Branch, company_id)}


def _check_employee(db: Session, company_id: uuid.UUID, e: m.Employee) -> None:
    if e.manager_id and e.manager_id == e.id:
        raise HTTPException(400, "An employee cannot report to themselves.")
    if e.date_of_birth and e.date_of_birth >= e.joining_date:
        raise HTTPException(400, "The date of birth must be before the joining date.")
    if e.probation_end_date and e.probation_end_date < e.joining_date:
        raise HTTPException(400, "Probation cannot end before the joining date.")
    if e.confirmation_date and e.confirmation_date < e.joining_date:
        raise HTTPException(400, "The confirmation date cannot be before the joining date.")
    taken = db.scalar(select(m.Employee.full_name).where(
        m.Employee.company_id == company_id, m.Employee.employee_code == e.employee_code, m.Employee.id != e.id))
    if taken is not None:
        raise HTTPException(409, f"Employee code {e.employee_code} already belongs to {taken}.")
    if e.cnic:
        other = db.scalar(select(m.Employee).where(
            m.Employee.company_id == company_id, m.Employee.cnic == e.cnic, m.Employee.id != e.id,
            m.Employee.status.notin_(m.SEPARATED)))
        if other is not None:
            raise HTTPException(409, f"CNIC {e.cnic} is already registered to {other.employee_code} "
                                     f"{other.full_name}.")
    if e.replacement_employee_id and e.replacement_employee_id == e.id:
        raise HTTPException(400, "An employee cannot be their own replacement.")
    if e.cnic_issue_date and e.cnic_expiry and e.cnic_expiry <= e.cnic_issue_date:
        raise HTTPException(400, "The CNIC expiry date must be after its issue date.")
    if e.resign_notice_start and e.resign_notice_end and e.resign_notice_end < e.resign_notice_start:
        raise HTTPException(400, "The resignation notice cannot end before it starts.")
    for model, value, label in ((m.Department, e.department_id, "Department"),
                                (m.Department, e.sub_department_id, "Sub department"),
                                (m.Designation, e.designation_id, "Designation"),
                                (m.Shift, e.shift_id, "Shift"), (m.Employee, e.manager_id, "Manager"),
                                (m.Employee, e.replacement_employee_id, "Replaced employee"),
                                (Branch, e.branch_id, "Branch"), (Account, e.ledger_account_id, "Ledger account"),
                                (Account, e.wages_account_id, "Wages account")):
        if value is not None:
            _owned(db, model, company_id, value, label)
    if e.sub_department_id:
        sub = db.get(m.Department, e.sub_department_id)
        if sub.parent_id != e.department_id:
            raise HTTPException(400, f"{sub.name} is not a sub department of the chosen department.")


@router.get("/employees")
def list_employees(
    search: str | None = None,
    department_id: uuid.UUID | None = None,
    designation_id: uuid.UUID | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    employment_type: str | None = None,
    sort: str = "employee_code",
    direction: str = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("hrms.employees.view")),
):
    company_id = active_company_id(db)
    base = select(m.Employee).where(m.Employee.company_id == company_id)
    counts = dict(db.execute(select(m.Employee.status, func.count()).where(m.Employee.company_id == company_id)
                             .group_by(m.Employee.status)).all())
    stmt = base
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(m.Employee.full_name.ilike(like), m.Employee.employee_code.ilike(like),
                              m.Employee.cnic.ilike(like), m.Employee.phone.ilike(like)))
    if department_id:
        stmt = stmt.where(m.Employee.department_id == department_id)
    if designation_id:
        stmt = stmt.where(m.Employee.designation_id == designation_id)
    if status_filter:
        stmt = stmt.where(m.Employee.status.in_([x.upper() for x in status_filter]))
    if employment_type:
        stmt = stmt.where(m.Employee.employment_type == employment_type.upper())
    column = getattr(m.Employee, sort, None) if sort in (
        "employee_code", "full_name", "joining_date", "status", "employment_type") else m.Employee.employee_code
    stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc(), m.Employee.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    names = _employee_names(db, company_id)
    return {"items": [_employee_row(e, names, user) for e in rows], "total": total, "page": page,
            "page_size": page_size, "status_counts": counts}


@router.get("/employees/export")
def export_employees(db: Session = Depends(get_db),
                     user: User = Depends(require_permission("hrms.employees.export"))):
    company_id = active_company_id(db)
    names = _employee_names(db, company_id)
    rows = [_employee_row(e, names, user) for e in db.scalars(
        select(m.Employee).where(m.Employee.company_id == company_id).order_by(m.Employee.employee_code))]
    columns = [("employee_code", "Code", 12, None), ("full_name", "Name", 30, None),
               ("father_name", "Father's Name", 26, None), ("department", "Department", 22, None),
               ("sub_department", "Sub Department", 20, None),
               ("designation", "Designation", 22, None), ("grade", "Grade", 9, None),
               ("employment_type", "Type", 13, None),
               ("status", "Status", 12, None), ("joining_date", "Joined", 13, outputs.DATE),
               ("confirmation_date", "Confirmed", 13, outputs.DATE),
               ("cnic", "CNIC", 18, None), ("cnic_expiry", "CNIC Expiry", 13, outputs.DATE),
               ("phone", "Mobile", 16, None), ("email", "Personal Email", 26, None),
               ("official_email", "Official Email", 26, None),
               ("date_of_birth", "Date of Birth", 13, outputs.DATE), ("gender", "Gender", 9, None),
               ("address", "Permanent Address", 36, None), ("eobi_number", "EOBI #", 14, None),
               ("social_security_number", "Social Security #", 16, None),
               ("separation_date", "Left on", 13, outputs.DATE)]
    if _allowed(user, "hrms.payroll.view"):
        columns += [("payment_mode", "Salary Mode", 11, None), ("bank_name", "Bank", 20, None),
                    ("bank_account_number", "Account No.", 22, None), ("iban", "IBAN", 28, None)]
    company = db.get(Company, company_id)
    content = outputs.sheet("Employees", company.name, columns, rows)
    return Response(content=content, media_type=outputs.XLSX, headers={
        "Content-Disposition": f'attachment; filename="employees-{date.today():%Y%m%d}.xlsx"'})


def _salary_dict(db: Session, structure: m.SalaryStructure, components: dict) -> dict:
    return {
        "id": str(structure.id), "effective_from": structure.effective_from,
        "basic_salary": float(structure.basic_salary), "remarks": structure.remarks,
        "lines": [{
            "component_id": str(line.component_id),
            "code": components[line.component_id].code if line.component_id in components else None,
            "name": components[line.component_id].name if line.component_id in components else None,
            "kind": components[line.component_id].kind if line.component_id in components else None,
            "calc_type": line.calc_type, "value": float(line.value),
            "amount": float(payroll.component_amount(line.calc_type, line.value, structure.basic_salary)),
        } for line in structure.lines],
        **payroll.structure_totals(db, structure),
    }


def _loan_dict(loan: m.Loan, employees: dict | None = None) -> dict:
    owed = payroll.loan_outstanding(loan)
    employee = (employees or {}).get(loan.employee_id)
    return {
        **_dict(loan), "outstanding": float(owed), "recovered": float(loan.amount - owed),
        "employee_code": employee.employee_code if employee else None,
        "employee_name": employee.full_name if employee else None,
        "repayments": [{"id": str(r.id), "paid_on": r.paid_on, "amount": float(r.amount), "source": r.source,
                        "is_reversed": r.is_reversed, "notes": r.notes} for r in loan.repayments],
    }


@router.get("/employees/{employee_id}")
def get_employee(employee_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("hrms.employees.view"))):
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    data = _employee_row(e, _employee_names(db, company_id), user)
    manager = db.get(m.Employee, e.manager_id) if e.manager_id else None
    data["manager"] = f"{manager.employee_code} {manager.full_name}" if manager else None
    replaced = db.get(m.Employee, e.replacement_employee_id) if e.replacement_employee_id else None
    data["replacement"] = f"{replaced.employee_code} {replaced.full_name}" if replaced else None
    data["leave_balances"] = leave.balance_rows(db, company_id, date.today().year, [e])
    # Pay is shown only to people who may see payroll.
    data["can_see_pay"] = _allowed(user, "hrms.payroll.view")
    if data["can_see_pay"]:
        components = {c.id: c for c in db.scalars(select(m.SalaryComponent).where(
            m.SalaryComponent.company_id == company_id))}
        structure = payroll.structure_on(db, e.id, date.today())
        data["salary"] = _salary_dict(db, structure, components) if structure else None
        data["loans"] = [_loan_dict(x) for x in db.scalars(
            select(m.Loan).options(selectinload(m.Loan.repayments)).where(m.Loan.employee_id == e.id)
            .order_by(m.Loan.loan_date.desc()))]
    db.commit()            # leave balances may have been created for this year
    return data


@router.post("/employees", status_code=201)
def create_employee(payload: s.EmployeeIn, db: Session = Depends(get_db),
                    ctx: AuditContext = Depends(request_context),
                    user: User = Depends(require_permission("hrms.employees.create"))):
    company_id = active_company_id(db)
    # The id is set now, not at flush, so the duplicate checks can exclude this row.
    e = m.Employee(id=uuid.uuid4(), company_id=company_id, created_by=user.id)
    data = _employee_fields(payload, user)
    gross, income_tax = data.pop("gross_salary", None), data.pop("income_tax", None)
    _apply(e, data)
    e.employee_code = (payload.employee_code or "").strip().upper() or _next_employee_code(db, company_id)
    _check_employee(db, company_id, e)
    db.add(e)
    _flush(db)
    audit.record(db, ctx, action="create", module="hrms", entity="hr_employee", entity_id=e.id,
                 company_id=company_id, new_values=audit.snapshot(e))
    if gross and _allowed(user, "hrms.payroll.edit"):
        _first_salary(db, ctx, company_id, e, gross, income_tax, user)
    _save(db)
    return _employee_row(e, _employee_names(db, company_id), user)


def _employee_fields(payload: s.EmployeeIn, user: User) -> dict:
    """The form's fields, without the confidential ones for a user who may
    not change pay: those keep whatever the record already holds."""
    data = payload.model_dump()
    if not _allowed(user, "hrms.payroll.edit"):
        for key in (*m.CONFIDENTIAL_FIELDS, "gross_salary", "income_tax"):
            data.pop(key, None)
    return data


def _first_salary(db: Session, ctx: AuditContext, company_id: uuid.UUID, e: m.Employee, gross: Decimal,
                  income_tax: Decimal | None, user: User) -> None:
    """Start a new employee's salary structure from the Gross Salary typed on
    the form: the whole amount as the monthly salary, effective from the
    joining date, with income tax as a monthly deduction if one was entered.
    The split into basic and allowances, and every later change, is made on
    the salary structure, which keeps the history."""
    structure = m.SalaryStructure(company_id=company_id, employee_id=e.id, effective_from=e.joining_date,
                                  basic_salary=gross, remarks="Entered with the employee record",
                                  created_by=user.id)
    if income_tax:
        tax = db.scalar(select(m.SalaryComponent).where(
            m.SalaryComponent.company_id == company_id, m.SalaryComponent.code == "TAX"))
        if tax is None:
            raise HTTPException(409, "Income tax was entered, but there is no salary component with the code TAX. "
                                     "Add it in HR Setup → Salary components (or use Add standard lists).")
        structure.lines.append(m.SalaryStructureLine(component_id=tax.id, calc_type=m.FIXED, value=income_tax))
    db.add(structure)
    db.flush()
    audit.record(db, ctx, action="salary_change", module="hrms", entity="hr_salary_structure",
                 entity_id=structure.id, company_id=company_id,
                 new_values={"employee": e.employee_code, "effective_from": e.joining_date,
                             "basic_salary": gross, "income_tax": income_tax})


@router.put("/employees/{employee_id}")
def update_employee(employee_id: uuid.UUID, payload: s.EmployeeIn, db: Session = Depends(get_db),
                    ctx: AuditContext = Depends(request_context),
                    user: User = Depends(require_permission("hrms.employees.edit"))):
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    before = audit.snapshot(e)
    data = _employee_fields(payload, user)
    # Pay is changed on the salary structure once the employee exists.
    data.pop("gross_salary", None)
    data.pop("income_tax", None)
    code = (data.pop("employee_code") or "").strip().upper()
    status = data.pop("status")
    _apply(e, data)
    if code:
        e.employee_code = code
    if e.status not in m.SEPARATED:
        e.status = status                       # leaving and rejoining have their own actions
    if e.separation_date and e.joining_date > e.separation_date:
        raise HTTPException(400, "The joining date cannot be after the date the employee left.")
    _check_employee(db, company_id, e)
    e.updated_by = user.id
    _flush(db)
    old, new = audit.changed(before, audit.snapshot(e))
    if new:
        audit.record(db, ctx, action="update", module="hrms", entity="hr_employee", entity_id=e.id,
                     company_id=company_id, old_values=old, new_values=new)
    _save(db)
    return _employee_row(e, _employee_names(db, company_id), user)


@router.post("/employees/{employee_id}/photo")
def upload_photo(employee_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db),
                 user: User = Depends(require_permission("hrms.employees.edit"))):
    """Attach or replace the employee's photo (JPEG, PNG or WebP)."""
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    e.photo_path = images.save_image(file, EMPLOYEE_PHOTO_DIR, e.id)
    e.updated_by = user.id
    _save(db)
    return {"id": str(e.id), "photo_path": e.photo_path}


@router.delete("/employees/{employee_id}/photo", status_code=204)
def delete_photo(employee_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("hrms.employees.edit"))):
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    images.delete_image(EMPLOYEE_PHOTO_DIR, e.id)
    e.photo_path = None
    e.updated_by = user.id
    _save(db)
    return Response(status_code=204)


@router.post("/employees/{employee_id}/separate")
def separate_employee(employee_id: uuid.UUID, payload: s.SeparationIn, db: Session = Depends(get_db),
                      ctx: AuditContext = Depends(request_context),
                      user: User = Depends(require_permission("hrms.employees.edit"))):
    """Record a resignation or termination. The employee stays on file and
    is paid up to the separation date by that month's payroll."""
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    if e.status in m.SEPARATED:
        raise HTTPException(409, f"{e.full_name} is already recorded as {e.status.lower()}.")
    if payload.separation_date < e.joining_date:
        raise HTTPException(400, "The last working day cannot be before the joining date.")
    e.status, e.separation_date, e.separation_reason = payload.status, payload.separation_date, payload.reason
    e.updated_by = user.id
    audit.record(db, ctx, action="separate", module="hrms", entity="hr_employee", entity_id=e.id,
                 company_id=company_id, new_values={"status": e.status, "separation_date": e.separation_date},
                 reason=payload.reason)
    owed = sum((payroll.loan_outstanding(x) for x in db.scalars(
        select(m.Loan).options(selectinload(m.Loan.repayments)).where(
            m.Loan.employee_id == e.id, m.Loan.status == "ACTIVE"))), Decimal(0))
    _save(db)
    return {**_employee_row(e, _employee_names(db, company_id), user), "outstanding_loans": float(owed)}


@router.post("/employees/{employee_id}/reinstate")
def reinstate_employee(employee_id: uuid.UUID, payload: s.ReasonIn, db: Session = Depends(get_db),
                       ctx: AuditContext = Depends(request_context),
                       user: User = Depends(require_permission("hrms.employees.edit"))):
    """Undo a separation recorded by mistake."""
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    if e.status not in m.SEPARATED:
        raise HTTPException(409, f"{e.full_name} has not left the company.")
    audit.record(db, ctx, action="reinstate", module="hrms", entity="hr_employee", entity_id=e.id,
                 company_id=company_id, old_values={"status": e.status, "separation_date": e.separation_date},
                 reason=payload.reason)
    e.status, e.separation_date, e.separation_reason = "ACTIVE", None, None
    e.resign_notice_start = e.resign_notice_end = None
    e.updated_by = user.id
    _save(db)
    return _employee_row(e, _employee_names(db, company_id), user)


@router.get("/employees/{employee_id}/salary")
def salary_history(employee_id: uuid.UUID, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("hrms.payroll.view"))):
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    components = {c.id: c for c in db.scalars(select(m.SalaryComponent).where(
        m.SalaryComponent.company_id == company_id))}
    return [_salary_dict(db, x, components) for x in db.scalars(
        select(m.SalaryStructure).options(selectinload(m.SalaryStructure.lines))
        .where(m.SalaryStructure.employee_id == e.id).order_by(m.SalaryStructure.effective_from.desc()))]


@router.post("/employees/{employee_id}/salary", status_code=201)
def set_salary(employee_id: uuid.UUID, payload: s.SalaryIn, db: Session = Depends(get_db),
               ctx: AuditContext = Depends(request_context),
               user: User = Depends(require_permission("hrms.payroll.edit"))):
    """Enter a salary structure effective from a date. Saving the same date
    again corrects that entry; a raise is a new, later date. A structure
    cannot start inside a month whose payroll is already approved, because
    that payslip was calculated without it."""
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    used = db.scalar(select(func.max(m.PayrollRun.period_end)).join(m.Payslip, m.Payslip.run_id == m.PayrollRun.id)
                     .where(m.Payslip.employee_id == e.id, m.PayrollRun.status.in_(("APPROVED", "PAID"))))
    if used is not None and payload.effective_from <= used:
        raise HTTPException(409, f"Payroll up to {used:%d-%b-%Y} is already approved for {e.full_name}. "
                                 f"A salary change must take effect after that date.")
    components = {c.id: c for c in db.scalars(select(m.SalaryComponent).where(
        m.SalaryComponent.company_id == company_id))}
    structure = db.scalar(select(m.SalaryStructure).options(selectinload(m.SalaryStructure.lines)).where(
        m.SalaryStructure.employee_id == e.id, m.SalaryStructure.effective_from == payload.effective_from))
    before = None
    if structure is None:
        structure = m.SalaryStructure(company_id=company_id, employee_id=e.id,
                                      effective_from=payload.effective_from, created_by=user.id)
        db.add(structure)
    else:
        before = {"basic_salary": structure.basic_salary,
                  "lines": {str(x.component_id): x.value for x in structure.lines}}
        structure.lines.clear()
        db.flush()                              # old lines go before the new ones arrive
    structure.basic_salary, structure.remarks = payload.basic_salary, payload.remarks
    structure.updated_by = user.id
    seen: set[uuid.UUID] = set()
    for line in payload.lines:
        component_id = _uuid(line.component_id, "salary component")
        if component_id not in components:
            raise HTTPException(404, "One of the salary components no longer exists.")
        if component_id in seen:
            raise HTTPException(400, f"{components[component_id].name} is on the structure twice.")
        if line.calc_type == m.PERCENT_BASIC and line.value > 100:
            raise HTTPException(400, f"{components[component_id].name}: a percentage cannot be over 100.")
        seen.add(component_id)
        if line.value > 0:
            structure.lines.append(m.SalaryStructureLine(component_id=component_id, calc_type=line.calc_type,
                                                         value=line.value))
    db.flush()
    audit.record(db, ctx, action="salary_change" if before is None else "salary_correct", module="hrms",
                 entity="hr_salary_structure", entity_id=structure.id, company_id=company_id, old_values=before,
                 new_values={"employee": e.employee_code, "effective_from": structure.effective_from,
                             "basic_salary": structure.basic_salary,
                             "lines": {str(x.component_id): x.value for x in structure.lines}})
    _save(db)
    return _salary_dict(db, structure, components)


# ======================================================================
# Attendance
# ======================================================================

@router.get("/attendance/daily")
def attendance_daily(work_date: date, department_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("hrms.attendance.view"))):
    company_id = active_company_id(db)
    rows = attendance.daily_sheet(db, company_id, work_date, department_id)
    holiday = db.scalar(select(m.Holiday.name).where(m.Holiday.company_id == company_id,
                                                     m.Holiday.holiday_date == work_date))
    db.commit()
    return {"work_date": work_date, "holiday": holiday, "rows": rows}


@router.put("/attendance/daily")
def attendance_save(payload: s.AttendanceDayIn, db: Session = Depends(get_db),
                    ctx: AuditContext = Depends(request_context),
                    user: User = Depends(require_permission("hrms.attendance.edit"))):
    company_id = active_company_id(db)
    result = attendance.save_daily(db, company_id, payload.work_date,
                                   [e.model_dump() for e in payload.entries], user.id)
    audit.record(db, ctx, action="mark_attendance", module="hrms", entity="hr_attendance",
                 entity_id=payload.work_date.isoformat(), company_id=company_id, new_values=result)
    _save(db)
    return result


@router.get("/attendance/monthly")
def attendance_monthly(year: int = Query(ge=2000, le=2100), month: int = Query(ge=1, le=12),
                       department_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                       user: User = Depends(require_permission("hrms.attendance.view"))):
    company_id = active_company_id(db)
    data = attendance.monthly_sheet(db, company_id, year, month, department_id)
    db.commit()
    return data


SHORT = {m.PRESENT: "P", m.ABSENT: "A", m.LATE: "L", m.HALF_DAY: "HD", m.ON_LEAVE: "LV",
         m.HOLIDAY: "H", m.WEEKLY_OFF: "WO"}


@router.get("/attendance/monthly/export")
def attendance_export(year: int = Query(ge=2000, le=2100), month: int = Query(ge=1, le=12),
                      department_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("hrms.attendance.export"))):
    company_id = active_company_id(db)
    data = attendance.monthly_sheet(db, company_id, year, month, department_id)
    days = data["days"]
    columns = [("employee_code", "Code", 11, None), ("employee_name", "Name", 28, None),
               ("department", "Department", 20, None)]
    columns += [(d, str(int(d[8:])), 4.2, None) for d in days]
    columns += [("present", "Present", 9, outputs.QTY), ("absent", "Absent", 9, outputs.QTY),
                ("late_count", "Late", 7, None), ("paid_leave", "Paid Leave", 9, outputs.QTY),
                ("unpaid_leave", "Unpaid Leave", 9, outputs.QTY), ("holidays", "Holidays", 9, outputs.QTY),
                ("weekly_offs", "Rest Days", 9, outputs.QTY), ("overtime_hours", "OT Hours", 9, outputs.QTY)]
    rows = []
    for row in data["rows"]:
        flat = {k: v for k, v in row.items() if k != "days"}
        for d in days:
            status = row["days"].get(d)
            # "~" marks a working day nobody marked; it prints in lower case.
            flat[d] = "" if not status else (SHORT[status[1:]].lower() if status.startswith("~") else SHORT[status])
        rows.append(flat)
    company = db.get(Company, company_id)
    content = outputs.sheet(f"Attendance {outputs.MONTHS[month - 1]} {year}",
                            f"{company.name} · P present, A absent, L late, HD half day, LV leave, H holiday, "
                            "WO rest day · lower case = not marked, counted by policy", columns, rows)
    db.commit()
    return Response(content=content, media_type=outputs.XLSX, headers={
        "Content-Disposition": f'attachment; filename="attendance-{year}-{month:02d}.xlsx"'})


# ======================================================================
# Leave
# ======================================================================

def _leave_dict(r: m.LeaveRequest, employees: dict, types: dict, users: dict) -> dict:
    e, t = employees.get(r.employee_id), types.get(r.leave_type_id)
    return {**_dict(r), "employee_code": e.employee_code if e else None,
            "employee_name": e.full_name if e else None, "leave_type": t.name if t else None,
            "is_paid": t.is_paid if t else None, "decided_by_name": users.get(r.decided_by)}


def _leave_context(db: Session, company_id: uuid.UUID) -> tuple[dict, dict, dict]:
    employees = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.company_id == company_id))}
    types = {t.id: t for t in db.scalars(select(m.LeaveType).where(m.LeaveType.company_id == company_id))}
    users = dict(db.execute(select(User.id, User.full_name)).all())
    return employees, types, users


@router.get("/leave/requests")
def list_leave(
    status_filter: list[str] = Query(default=[], alias="status"),
    employee_id: uuid.UUID | None = None,
    leave_type_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("hrms.leave.view")),
):
    company_id = active_company_id(db)
    stmt = select(m.LeaveRequest).where(m.LeaveRequest.company_id == company_id)
    counts = dict(db.execute(select(m.LeaveRequest.status, func.count()).where(
        m.LeaveRequest.company_id == company_id).group_by(m.LeaveRequest.status)).all())
    if status_filter:
        stmt = stmt.where(m.LeaveRequest.status.in_([x.upper() for x in status_filter]))
    if employee_id:
        stmt = stmt.where(m.LeaveRequest.employee_id == employee_id)
    if leave_type_id:
        stmt = stmt.where(m.LeaveRequest.leave_type_id == leave_type_id)
    if date_from:
        stmt = stmt.where(m.LeaveRequest.to_date >= date_from)
    if date_to:
        stmt = stmt.where(m.LeaveRequest.from_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(m.LeaveRequest.from_date.desc(), m.LeaveRequest.request_number.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    context = _leave_context(db, company_id)
    return {"items": [_leave_dict(r, *context) for r in rows], "total": total, "page": page,
            "page_size": page_size, "status_counts": counts}


@router.get("/leave/preview")
def preview_leave(employee_id: uuid.UUID, from_date: date, to_date: date, half_day: bool = False,
                  db: Session = Depends(get_db), user: User = Depends(require_permission("hrms.leave.view"))):
    """How many working days a request would charge, before it is saved."""
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, employee_id, "Employee")
    if to_date < from_date:
        return {"days": 0, "working_dates": []}
    days, working = leave.count_days(db, company_id, e, from_date, to_date, half_day)
    db.commit()
    return {"days": float(days), "working_dates": working}


@router.post("/leave/requests", status_code=201)
def create_leave(payload: s.LeaveRequestIn, db: Session = Depends(get_db),
                 ctx: AuditContext = Depends(request_context),
                 user: User = Depends(require_permission("hrms.leave.create"))):
    company_id = active_company_id(db)
    request = leave.create_request(
        db, company_id, employee_id=_uuid(payload.employee_id, "employee"),
        leave_type_id=_uuid(payload.leave_type_id, "leave type"), from_date=payload.from_date,
        to_date=payload.to_date, half_day=payload.half_day, reason=payload.reason, user_id=user.id)
    audit.record(db, ctx, action="create", module="hrms", entity="hr_leave_request", entity_id=request.id,
                 company_id=company_id, new_values=audit.snapshot(request))
    _save(db)
    return _leave_dict(request, *_leave_context(db, company_id))


def _leave_action(name: str, permission: str, action):
    @router.post(f"/leave/requests/{{request_id}}/{name}", name=f"leave_{name}")
    def handler(request_id: uuid.UUID, payload: s.DecisionIn, db: Session = Depends(get_db),
                ctx: AuditContext = Depends(request_context), user: User = Depends(require_permission(permission))):
        company_id = active_company_id(db)
        request = action(db, company_id, request_id, user.id, payload.note)
        audit.record(db, ctx, action=name, module="hrms", entity="hr_leave_request", entity_id=request.id,
                     company_id=company_id, new_values={"status": request.status, "days": request.days},
                     reason=payload.note)
        _save(db)
        return _leave_dict(request, *_leave_context(db, company_id))


_leave_action("approve", "hrms.leave.approve", leave.approve)
_leave_action("reject", "hrms.leave.approve", leave.reject)
_leave_action("cancel", "hrms.leave.cancel", leave.cancel)


@router.get("/leave/balances")
def leave_balances(year: int | None = None, employee_id: uuid.UUID | None = None,
                   department_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("hrms.leave.view"))):
    company_id = active_company_id(db)
    year = year or date.today().year
    stmt = select(m.Employee).where(m.Employee.company_id == company_id,
                                    m.Employee.status.notin_(m.SEPARATED)).order_by(m.Employee.employee_code)
    if employee_id:
        stmt = select(m.Employee).where(m.Employee.company_id == company_id, m.Employee.id == employee_id)
    elif department_id:
        stmt = stmt.where(m.Employee.department_id == department_id)
    rows = leave.balance_rows(db, company_id, year, list(db.scalars(stmt)))
    db.commit()
    return {"year": year, "rows": rows}


@router.put("/leave/balances/{balance_id}")
def update_balance(balance_id: uuid.UUID, payload: s.LeaveBalanceIn, db: Session = Depends(get_db),
                   ctx: AuditContext = Depends(request_context),
                   user: User = Depends(require_permission("hrms.leave.edit"))):
    company_id = active_company_id(db)
    balance = _owned(db, m.LeaveBalance, company_id, balance_id, "Leave balance")
    before = audit.snapshot(balance)
    _apply(balance, payload.model_dump())
    balance.updated_by = user.id
    old, new = audit.changed(before, audit.snapshot(balance))
    if new:
        audit.record(db, ctx, action="update", module="hrms", entity="hr_leave_balance", entity_id=balance.id,
                     company_id=company_id, old_values=old, new_values=new, reason=payload.adjustment_note)
    _save(db)
    return leave.balance_rows(db, company_id, balance.year, [db.get(m.Employee, balance.employee_id)])


# ======================================================================
# Loans and advances
# ======================================================================

@router.get("/loans")
def list_loans(status_filter: list[str] = Query(default=[], alias="status"),
               employee_id: uuid.UUID | None = None, db: Session = Depends(get_db),
               user: User = Depends(require_permission("hrms.loans.view"))):
    company_id = active_company_id(db)
    stmt = select(m.Loan).options(selectinload(m.Loan.repayments)).where(m.Loan.company_id == company_id)
    if status_filter:
        stmt = stmt.where(m.Loan.status.in_([x.upper() for x in status_filter]))
    if employee_id:
        stmt = stmt.where(m.Loan.employee_id == employee_id)
    employees = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.company_id == company_id))}
    rows = [_loan_dict(x, employees) for x in db.scalars(stmt.order_by(m.Loan.loan_date.desc(), m.Loan.loan_number.desc()))]
    active = [r for r in rows if r["status"] == "ACTIVE"]
    return {"items": rows, "total_outstanding": round(sum(r["outstanding"] for r in active), 2),
            "active_count": len(active)}


@router.post("/loans", status_code=201)
def create_loan(payload: s.LoanIn, db: Session = Depends(get_db), ctx: AuditContext = Depends(request_context),
                user: User = Depends(require_permission("hrms.loans.create"))):
    company_id = active_company_id(db)
    e = _owned(db, m.Employee, company_id, _uuid(payload.employee_id, "employee"), "Employee")
    if e.status in m.SEPARATED:
        raise HTTPException(400, f"{e.full_name} has left the company.")
    if payload.installment_amount > payload.amount:
        raise HTTPException(400, "The instalment cannot be more than the amount given.")
    if payload.loan_date < e.joining_date:
        raise HTTPException(400, "The date is before the employee joined.")
    number = next_number(db, company_id, "hr_loan", "HR")
    loan = m.Loan(company_id=company_id, loan_number=f"LN-{int(number):05d}", employee_id=e.id, kind=payload.kind,
                  loan_date=payload.loan_date, amount=payload.amount, installment_amount=payload.installment_amount,
                  recovery_start=payload.recovery_start.replace(day=1), status="ACTIVE", notes=payload.notes,
                  created_by=user.id)
    db.add(loan)
    db.flush()
    audit.record(db, ctx, action="create", module="hrms", entity="hr_loan", entity_id=loan.id,
                 company_id=company_id, new_values=audit.snapshot(loan))
    _save(db)
    return _loan_dict(loan, {e.id: e})


def _loan(db: Session, company_id: uuid.UUID, loan_id: uuid.UUID) -> m.Loan:
    loan = db.scalar(select(m.Loan).options(selectinload(m.Loan.repayments)).where(m.Loan.id == loan_id))
    if loan is None or loan.company_id != company_id:
        raise HTTPException(404, "Loan not found.")
    return loan


@router.post("/loans/{loan_id}/repay")
def repay_loan(loan_id: uuid.UUID, payload: s.RepaymentIn, db: Session = Depends(get_db),
               ctx: AuditContext = Depends(request_context),
               user: User = Depends(require_permission("hrms.loans.edit"))):
    """A repayment made outside payroll: cash handed back, or a final settlement."""
    company_id = active_company_id(db)
    loan = _loan(db, company_id, loan_id)
    owed = payroll.loan_outstanding(loan)
    if loan.status != "ACTIVE":
        raise HTTPException(409, f"Loan {loan.loan_number} is {loan.status}.")
    if payload.amount > owed:
        raise HTTPException(400, f"Only {owed:,.2f} is still owed on {loan.loan_number}.")
    loan.repayments.append(m.LoanRepayment(paid_on=payload.paid_on, amount=payload.amount, source="MANUAL",
                                           notes=payload.notes, created_by=user.id))
    if owed - payload.amount <= 0:
        loan.status = "SETTLED"
    loan.updated_by = user.id
    db.flush()
    audit.record(db, ctx, action="repay", module="hrms", entity="hr_loan", entity_id=loan.id,
                 company_id=company_id, new_values={"amount": payload.amount, "paid_on": payload.paid_on,
                                                    "status": loan.status})
    _save(db)
    return _loan_dict(loan, {loan.employee_id: db.get(m.Employee, loan.employee_id)})


@router.post("/loans/{loan_id}/cancel")
def cancel_loan(loan_id: uuid.UUID, payload: s.ReasonIn, db: Session = Depends(get_db),
                ctx: AuditContext = Depends(request_context),
                user: User = Depends(require_permission("hrms.loans.cancel"))):
    company_id = active_company_id(db)
    loan = _loan(db, company_id, loan_id)
    if loan.status == "CANCELLED":
        raise HTTPException(409, f"Loan {loan.loan_number} is already cancelled.")
    if any(not r.is_reversed for r in loan.repayments):
        raise HTTPException(409, f"Loan {loan.loan_number} has repayments against it, so it cannot be cancelled. "
                                 "Record a repayment for the balance to close it instead.")
    loan.status = "CANCELLED"
    loan.updated_by = user.id
    audit.record(db, ctx, action="cancel", module="hrms", entity="hr_loan", entity_id=loan.id,
                 company_id=company_id, reason=payload.reason)
    _save(db)
    return _loan_dict(loan, {loan.employee_id: db.get(m.Employee, loan.employee_id)})


# ======================================================================
# Payroll
# ======================================================================

def _run_dict(run: m.PayrollRun, users: dict | None = None) -> dict:
    data = _dict(run)
    data["period"] = f"{outputs.MONTHS[run.period_month - 1]} {run.period_year}"
    if users is not None:
        data["approved_by_name"] = users.get(run.approved_by)
        data["paid_by_name"] = users.get(run.paid_by)
    return data


def _payslip_dict(p: m.Payslip, with_lines: bool = True) -> dict:
    data = _dict(p)
    data["warnings"] = [w for w in (p.warnings or "").split("\n") if w]
    if with_lines:
        data["lines"] = [{"id": str(x.id), "code": x.code, "name": x.name, "kind": x.kind,
                          "amount": float(x.amount), "is_manual": x.is_manual} for x in p.lines]
    return data


def _run_detail(db: Session, run: m.PayrollRun) -> dict:
    users = dict(db.execute(select(User.id, User.full_name)).all())
    data = _run_dict(run, users)
    data["payslips"] = [_payslip_dict(p) for p in sorted(run.payslips, key=lambda p: p.employee_code)]
    data["warning_count"] = sum(1 for p in run.payslips if p.warnings)
    return data


@router.get("/payroll/runs")
def list_runs(db: Session = Depends(get_db), user: User = Depends(require_permission("hrms.payroll.view"))):
    company_id = active_company_id(db)
    users = dict(db.execute(select(User.id, User.full_name)).all())
    return [_run_dict(r, users) for r in db.scalars(
        select(m.PayrollRun).where(m.PayrollRun.company_id == company_id)
        .order_by(m.PayrollRun.period_start.desc(), m.PayrollRun.created_at.desc()))]


@router.post("/payroll/runs", status_code=201)
def create_run(payload: s.PayrollRunIn, db: Session = Depends(get_db),
               ctx: AuditContext = Depends(request_context),
               user: User = Depends(require_permission("hrms.payroll.create"))):
    company_id = active_company_id(db)
    run = payroll.generate(db, company_id, payload.year, payload.month, user.id, payload.notes)
    audit.record(db, ctx, action="create", module="hrms", entity="hr_payroll_run", entity_id=run.id,
                 company_id=company_id, new_values={"run_number": run.run_number, "employees": run.employee_count,
                                                    "total_net": run.total_net})
    _save(db)
    return _run_detail(db, payroll.get_run(db, company_id, run.id))


@router.get("/payroll/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db),
            user: User = Depends(require_permission("hrms.payroll.view"))):
    return _run_detail(db, payroll.get_run(db, active_company_id(db), run_id))


@router.post("/payroll/runs/{run_id}/recalculate")
def recalculate_run(run_id: uuid.UUID, db: Session = Depends(get_db),
                    ctx: AuditContext = Depends(request_context),
                    user: User = Depends(require_permission("hrms.payroll.edit"))):
    company_id = active_company_id(db)
    run = payroll.calculate(db, payroll.get_run(db, company_id, run_id), user.id)
    audit.record(db, ctx, action="recalculate", module="hrms", entity="hr_payroll_run", entity_id=run.id,
                 company_id=company_id, new_values={"employees": run.employee_count, "total_net": run.total_net})
    _save(db)
    return _run_detail(db, payroll.get_run(db, company_id, run.id))


@router.post("/payroll/runs/{run_id}/approve")
def approve_run(run_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuditContext = Depends(request_context),
                user: User = Depends(require_permission("hrms.payroll.approve"))):
    company_id = active_company_id(db)
    run = payroll.approve(db, company_id, run_id, user.id)
    audit.record(db, ctx, action="approve", module="hrms", entity="hr_payroll_run", entity_id=run.id,
                 company_id=company_id, new_values={"run_number": run.run_number, "total_net": run.total_net})
    _save(db)
    return _run_detail(db, payroll.get_run(db, company_id, run.id))


@router.post("/payroll/runs/{run_id}/pay")
def pay_run(run_id: uuid.UUID, payload: s.PayIn, db: Session = Depends(get_db),
            ctx: AuditContext = Depends(request_context),
            user: User = Depends(require_permission("hrms.payroll.post"))):
    company_id = active_company_id(db)
    run = payroll.mark_paid(db, company_id, run_id, payload.payment_date, user.id)
    audit.record(db, ctx, action="pay", module="hrms", entity="hr_payroll_run", entity_id=run.id,
                 company_id=company_id, new_values={"payment_date": run.payment_date, "total_net": run.total_net})
    _save(db)
    return _run_detail(db, payroll.get_run(db, company_id, run.id))


@router.post("/payroll/runs/{run_id}/cancel")
def cancel_run(run_id: uuid.UUID, payload: s.ReasonIn, db: Session = Depends(get_db),
               ctx: AuditContext = Depends(request_context),
               user: User = Depends(require_permission("hrms.payroll.cancel"))):
    company_id = active_company_id(db)
    run = payroll.cancel(db, company_id, run_id, payload.reason, user.id)
    audit.record(db, ctx, action="cancel", module="hrms", entity="hr_payroll_run", entity_id=run.id,
                 company_id=company_id, reason=payload.reason)
    _save(db)
    return _run_detail(db, payroll.get_run(db, company_id, run.id))


@router.post("/payroll/payslips/{payslip_id}/lines")
def add_payslip_line(payslip_id: uuid.UUID, payload: s.ManualLineIn, db: Session = Depends(get_db),
                     ctx: AuditContext = Depends(request_context),
                     user: User = Depends(require_permission("hrms.payroll.edit"))):
    company_id = active_company_id(db)
    payslip = payroll.add_manual_line(db, company_id, payslip_id, kind=payload.kind, name=payload.name,
                                      amount=payload.amount, user_id=user.id)
    audit.record(db, ctx, action="add_line", module="hrms", entity="hr_payslip", entity_id=payslip.id,
                 company_id=company_id, new_values=payload.model_dump())
    _save(db)
    return _run_detail(db, payroll.get_run(db, company_id, payslip.run_id))


@router.delete("/payroll/payslips/{payslip_id}/lines/{line_id}")
def remove_payslip_line(payslip_id: uuid.UUID, line_id: uuid.UUID, db: Session = Depends(get_db),
                        ctx: AuditContext = Depends(request_context),
                        user: User = Depends(require_permission("hrms.payroll.edit"))):
    company_id = active_company_id(db)
    payslip = payroll.remove_manual_line(db, company_id, payslip_id, line_id, user.id)
    audit.record(db, ctx, action="remove_line", module="hrms", entity="hr_payslip", entity_id=payslip.id,
                 company_id=company_id, new_values={"line_id": str(line_id)})
    _save(db)
    return _run_detail(db, payroll.get_run(db, company_id, payslip.run_id))


def _pdf(content: bytes, filename: str) -> Response:
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@router.get("/payroll/runs/{run_id}/payslips.pdf")
def run_payslips_pdf(run_id: uuid.UUID, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("hrms.payroll.print"))):
    company_id = active_company_id(db)
    run = payroll.get_run(db, company_id, run_id)
    company = db.get(Company, company_id)
    slips = [_payslip_dict(p) for p in sorted(run.payslips, key=lambda p: p.employee_code)]
    return _pdf(outputs.payslips_pdf(company.name, _dict(run), slips), f"payslips-{run.run_number}.pdf")


@router.get("/payroll/payslips/{payslip_id}/pdf")
def payslip_pdf(payslip_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(require_permission("hrms.payroll.print"))):
    company_id = active_company_id(db)
    payslip = db.scalar(select(m.Payslip).options(selectinload(m.Payslip.lines)).where(m.Payslip.id == payslip_id))
    if payslip is None or payslip.company_id != company_id:
        raise HTTPException(404, "Payslip not found.")
    run = db.get(m.PayrollRun, payslip.run_id)
    company = db.get(Company, company_id)
    return _pdf(outputs.payslips_pdf(company.name, _dict(run), [_payslip_dict(payslip)]),
                f"payslip-{run.run_number}-{payslip.employee_code}.pdf")


@router.get("/payroll/runs/{run_id}/register")
def payroll_register(run_id: uuid.UUID, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("hrms.payroll.export"))):
    """The salary sheet: one row per employee, one column per pay line."""
    company_id = active_company_id(db)
    run = payroll.get_run(db, company_id, run_id)
    slips = sorted(run.payslips, key=lambda p: p.employee_code)
    earning_names, deduction_names = [], []
    for p in slips:
        for line in p.lines:
            target = earning_names if line.kind == m.EARNING else deduction_names
            # Loan and unpaid-day lines carry detail in their name; group them by code.
            label = {"LOAN": "Loan / Advance", "UNPAID": "Unpaid Days", "LATE": "Late Arrivals",
                     "OT": "Overtime"}.get(line.code, line.name)
            if label not in target:
                target.append(label)
    columns = [("employee_code", "Code", 11, None), ("employee_name", "Name", 28, None),
               ("department", "Department", 20, None), ("designation", "Designation", 20, None),
               ("present_days", "Present", 9, outputs.QTY), ("unpaid_days", "Unpaid Days", 9, outputs.QTY)]
    columns += [(f"e:{n}", n, 14, outputs.MONEY) for n in earning_names]
    columns += [("total_earnings", "Total Earnings", 15, outputs.MONEY)]
    columns += [(f"d:{n}", n, 14, outputs.MONEY) for n in deduction_names]
    columns += [("total_deductions", "Total Deductions", 15, outputs.MONEY), ("net_pay", "Net Pay", 15, outputs.MONEY)]
    rows, totals = [], {}
    for p in slips:
        row = _payslip_dict(p, with_lines=False)
        for line in p.lines:
            label = {"LOAN": "Loan / Advance", "UNPAID": "Unpaid Days", "LATE": "Late Arrivals",
                     "OT": "Overtime"}.get(line.code, line.name)
            key = ("e:" if line.kind == m.EARNING else "d:") + label
            row[key] = row.get(key, 0) + float(line.amount)
        rows.append(row)
        for key, _label, _width, fmt in columns:
            if fmt == outputs.MONEY and isinstance(row.get(key), (int, float)):
                totals[key] = round(totals.get(key, 0) + row[key], 2)
    company = db.get(Company, company_id)
    period = f"{outputs.MONTHS[run.period_month - 1]} {run.period_year}"
    content = outputs.sheet(f"Salary Sheet {period}", f"{company.name} · {run.run_number} · {run.status}",
                            columns, rows, totals)
    return Response(content=content, media_type=outputs.XLSX, headers={
        "Content-Disposition": f'attachment; filename="salary-sheet-{run.run_number}.xlsx"'})


@router.get("/payroll/runs/{run_id}/bank-sheet")
def bank_sheet(run_id: uuid.UUID, db: Session = Depends(get_db),
               user: User = Depends(require_permission("hrms.payroll.export"))):
    """Who to pay and how: the bank transfer list, with cash and cheque
    payments listed after it."""
    company_id = active_company_id(db)
    run = payroll.get_run(db, company_id, run_id)
    order = {"BANK": 0, "CHEQUE": 1, "CASH": 2}
    slips = sorted((p for p in run.payslips if p.net_pay > 0),
                   key=lambda p: (order.get(p.payment_mode, 9), p.employee_code))
    rows = [{**_payslip_dict(p, with_lines=False), "missing": "" if p.payment_mode != "BANK"
             or p.bank_account_number else "No account on file"} for p in slips]
    columns = [("employee_code", "Code", 11, None), ("employee_name", "Name", 28, None),
               ("payment_mode", "Paid by", 10, None), ("bank_name", "Bank", 24, None),
               ("bank_account_title", "Account Title", 28, None), ("bank_account_number", "Account / IBAN", 30, None),
               ("net_pay", "Net Pay", 15, outputs.MONEY), ("missing", "Note", 20, None)]
    company = db.get(Company, company_id)
    period = f"{outputs.MONTHS[run.period_month - 1]} {run.period_year}"
    content = outputs.sheet(f"Salary Payments {period}", f"{company.name} · {run.run_number} · {run.status}",
                            columns, rows, {"net_pay": round(sum(r["net_pay"] for r in rows), 2)})
    return Response(content=content, media_type=outputs.XLSX, headers={
        "Content-Disposition": f'attachment; filename="salary-payments-{run.run_number}.xlsx"'})


# ======================================================================
# Dashboard
# ======================================================================

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_permission("hrms.module.view"))):
    company_id = active_company_id(db)
    today = date.today()
    month_start, month_end = month_bounds(today.year, today.month)
    employees = list(db.scalars(select(m.Employee).where(m.Employee.company_id == company_id)))
    current = [e for e in employees if e.status == "ACTIVE" and attendance.employed_on(e, today)]
    departments = _names(db, m.Department, company_id)

    by_department: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for e in current:
        by_department[departments.get(e.department_id) or "No department"] = (
            by_department.get(departments.get(e.department_id) or "No department", 0) + 1)
        by_type[e.employment_type] = by_type.get(e.employment_type, 0) + 1

    marks = dict(db.execute(select(m.Attendance.status, func.count()).where(
        m.Attendance.company_id == company_id, m.Attendance.work_date == today)
        .group_by(m.Attendance.status)).all())
    marked = sum(marks.values())
    marked_ids = set(db.scalars(select(m.Attendance.employee_id).where(
        m.Attendance.company_id == company_id, m.Attendance.work_date == today)))
    # People exempt from attendance are never "not marked".
    not_marked = sum(1 for e in current if e.id not in marked_ids and not e.attendance_exempt)

    def brief(e: m.Employee, **extra) -> dict:
        return {"id": str(e.id), "code": e.employee_code, "name": e.full_name,
                "department": departments.get(e.department_id), **extra}

    current_by_id = {e.id: e for e in current}
    on_leave = [brief(current_by_id[employee_id], leave_type=name, until=until)
                for employee_id, name, until in db.execute(
                    select(m.LeaveRequest.employee_id, m.LeaveType.name, m.LeaveRequest.to_date)
                    .join(m.LeaveType, m.LeaveType.id == m.LeaveRequest.leave_type_id)
                    .where(m.LeaveRequest.company_id == company_id, m.LeaveRequest.status == "APPROVED",
                           m.LeaveRequest.from_date <= today, m.LeaveRequest.to_date >= today))
                if employee_id in current_by_id]

    def birthday_this_month(e: m.Employee) -> bool:
        return bool(e.date_of_birth and e.date_of_birth.month == today.month)

    can_see_pay = _allowed(user, "hrms.payroll.view")
    last_run = db.scalar(select(m.PayrollRun).where(
        m.PayrollRun.company_id == company_id, m.PayrollRun.status != "CANCELLED")
        .order_by(m.PayrollRun.period_start.desc()).limit(1)) if can_see_pay else None
    loans = list(db.scalars(select(m.Loan).options(selectinload(m.Loan.repayments)).where(
        m.Loan.company_id == company_id, m.Loan.status == "ACTIVE"))) if can_see_pay else []
    without_salary = 0
    if can_see_pay:
        with_salary = set(db.scalars(select(m.SalaryStructure.employee_id).where(
            m.SalaryStructure.company_id == company_id, m.SalaryStructure.effective_from <= today)))
        without_salary = sum(1 for e in current if e.id not in with_salary)

    return {
        "as_of": today,
        "headcount": len(current),
        "total_on_file": len(employees),
        "by_department": sorted(({"name": k, "count": v} for k, v in by_department.items()),
                                key=lambda x: -x["count"]),
        "by_employment_type": sorted(({"name": k, "count": v} for k, v in by_type.items()),
                                     key=lambda x: -x["count"]),
        "today": {"marked": marked, "unmarked": not_marked,
                  "present": marks.get(m.PRESENT, 0) + marks.get(m.LATE, 0), "late": marks.get(m.LATE, 0),
                  "absent": marks.get(m.ABSENT, 0), "half_day": marks.get(m.HALF_DAY, 0),
                  "on_leave": marks.get(m.ON_LEAVE, 0)},
        "on_leave_today": on_leave,
        "pending_leave_requests": db.scalar(select(func.count()).select_from(m.LeaveRequest).where(
            m.LeaveRequest.company_id == company_id, m.LeaveRequest.status == "PENDING")) or 0,
        "joined_this_month": [brief(e, date=e.joining_date) for e in employees
                              if month_start <= e.joining_date <= month_end],
        "left_this_month": [brief(e, date=e.separation_date) for e in employees
                            if e.separation_date and month_start <= e.separation_date <= month_end],
        "probation_ending": sorted((brief(e, date=e.probation_end_date) for e in current
                                    if e.probation_end_date and e.confirmation_date is None
                                    and e.probation_end_date <= today + timedelta(days=30)),
                                   key=lambda x: x["date"]),
        "cnic_expiring": sorted((brief(e, date=e.cnic_expiry) for e in current
                                 if e.cnic_expiry and e.cnic_expiry <= today + timedelta(days=60)),
                                key=lambda x: x["date"]),
        "birthdays_this_month": sorted((brief(e, date=e.date_of_birth, day=e.date_of_birth.day)
                                        for e in current if birthday_this_month(e)), key=lambda x: x["day"]),
        "can_see_pay": can_see_pay,
        "last_payroll": ({"id": str(last_run.id), "run_number": last_run.run_number, "status": last_run.status,
                          "period": f"{outputs.MONTHS[last_run.period_month - 1]} {last_run.period_year}",
                          "total_net": float(last_run.total_net), "employees": last_run.employee_count}
                         if last_run else None),
        "loans_outstanding": round(float(sum((payroll.loan_outstanding(x) for x in loans), Decimal(0))), 2),
        "active_loans": len(loans),
        "employees_without_salary": without_salary,
        "setup_needed": not departments,
    }
