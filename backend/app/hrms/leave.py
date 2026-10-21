"""
Leave: yearly entitlements and requests.

    available = entitled + carried forward + adjustment − approved days

Days used are never stored on the balance; they are the approved requests of
that calendar year. A request charges working days only (weekly rest days
and holidays inside the range are free), and approving it writes the LEAVE
days into attendance so payroll sees them without anyone marking twice.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.numbering import next_number
from app.hrms import models as m
from app.hrms.attendance import employed_on
from app.hrms.calendar import WorkCalendar, assert_month_open, days_between
from app.hrms.setup import get_settings

ZERO = Decimal(0)


def _used(db: Session, employee_id: uuid.UUID, leave_type_id: uuid.UUID, year: int, status: str,
          exclude: uuid.UUID | None = None) -> Decimal:
    stmt = select(func.coalesce(func.sum(m.LeaveRequest.days), 0)).where(
        m.LeaveRequest.employee_id == employee_id, m.LeaveRequest.leave_type_id == leave_type_id,
        m.LeaveRequest.status == status, func.extract("year", m.LeaveRequest.from_date) == year)
    if exclude:
        stmt = stmt.where(m.LeaveRequest.id != exclude)
    return Decimal(db.scalar(stmt) or 0)


def ensure_balances(db: Session, company_id: uuid.UUID, employee: m.Employee, year: int) -> list[m.LeaveBalance]:
    """The employee's balance rows for a year, created from the leave types
    the first time they are needed. Unused days carry forward only for types
    that allow it, up to that type's limit."""
    types = list(db.scalars(select(m.LeaveType).where(
        m.LeaveType.company_id == company_id, m.LeaveType.is_active.is_(True)).order_by(m.LeaveType.sort_order)))
    existing = {b.leave_type_id: b for b in db.scalars(select(m.LeaveBalance).where(
        m.LeaveBalance.employee_id == employee.id, m.LeaveBalance.year == year))}
    for leave_type in types:
        if leave_type.id in existing:
            continue
        carried = ZERO
        if leave_type.carry_forward:
            previous = db.scalar(select(m.LeaveBalance).where(
                m.LeaveBalance.employee_id == employee.id, m.LeaveBalance.leave_type_id == leave_type.id,
                m.LeaveBalance.year == year - 1))
            if previous is not None:
                left = (previous.entitled + previous.carried_forward + previous.adjustment
                        - _used(db, employee.id, leave_type.id, year - 1, "APPROVED"))
                carried = max(ZERO, min(left, leave_type.max_carry_days))
        balance = m.LeaveBalance(company_id=company_id, employee_id=employee.id, leave_type_id=leave_type.id,
                                 year=year, entitled=leave_type.annual_days, carried_forward=carried,
                                 adjustment=ZERO)
        db.add(balance)
        existing[leave_type.id] = balance
    db.flush()
    return [existing[t.id] for t in types if t.id in existing]


def balance_rows(db: Session, company_id: uuid.UUID, year: int, employees: list[m.Employee]) -> list[dict]:
    types = {t.id: t for t in db.scalars(select(m.LeaveType).where(m.LeaveType.company_id == company_id))}
    rows = []
    for e in employees:
        for b in ensure_balances(db, company_id, e, year):
            leave_type = types[b.leave_type_id]
            used = _used(db, e.id, b.leave_type_id, year, "APPROVED")
            pending = _used(db, e.id, b.leave_type_id, year, "PENDING")
            total = b.entitled + b.carried_forward + b.adjustment
            rows.append({
                "id": str(b.id), "employee_id": str(e.id), "employee_code": e.employee_code,
                "employee_name": e.full_name, "leave_type_id": str(b.leave_type_id),
                "leave_type": leave_type.name, "leave_code": leave_type.code, "is_paid": leave_type.is_paid,
                "year": year, "entitled": float(b.entitled), "carried_forward": float(b.carried_forward),
                "adjustment": float(b.adjustment), "adjustment_note": b.adjustment_note,
                "used": float(used), "pending": float(pending), "available": float(total - used),
            })
    return rows


def count_days(db: Session, company_id: uuid.UUID, employee: m.Employee, start: date, end: date,
               half_day: bool) -> tuple[Decimal, list[date]]:
    """Working days charged by a request, and which days they are."""
    cal = WorkCalendar(db, company_id, start, end, get_settings(db, company_id))
    working = [d for d in days_between(start, end) if cal.is_working_day(employee, d)]
    if half_day:
        return (Decimal("0.5") if working else ZERO), working
    return Decimal(len(working)), working


def _validate(db: Session, company_id: uuid.UUID, employee: m.Employee, leave_type: m.LeaveType,
              start: date, end: date, half_day: bool, exclude: uuid.UUID | None = None) -> Decimal:
    if end < start:
        raise HTTPException(400, "The leave cannot end before it starts.")
    if start.year != end.year:
        raise HTTPException(400, "A request cannot cross into another year, because each year has its own "
                                 "leave balance. Enter one request up to 31 December and another from 1 January.")
    if half_day and start != end:
        raise HTTPException(400, "A half day is a single date: set From and To to the same day.")
    if not employed_on(employee, start) or not employed_on(employee, end):
        raise HTTPException(400, f"{employee.full_name} is not employed for the whole of that period.")
    days, _ = count_days(db, company_id, employee, start, end, half_day)
    if days <= 0:
        raise HTTPException(400, "Those dates are all weekly rest days or holidays, so no leave is needed.")
    clash = db.scalar(select(m.LeaveRequest.request_number).where(
        m.LeaveRequest.employee_id == employee.id, m.LeaveRequest.status.in_(("PENDING", "APPROVED")),
        m.LeaveRequest.from_date <= end, m.LeaveRequest.to_date >= start,
        *([m.LeaveRequest.id != exclude] if exclude else [])))
    if clash:
        raise HTTPException(409, f"{employee.full_name} already has leave request {clash} over those dates.")
    if leave_type.is_paid:
        balance = next((b for b in ensure_balances(db, company_id, employee, start.year)
                        if b.leave_type_id == leave_type.id), None)
        total = (balance.entitled + balance.carried_forward + balance.adjustment) if balance else ZERO
        taken = (_used(db, employee.id, leave_type.id, start.year, "APPROVED", exclude)
                 + _used(db, employee.id, leave_type.id, start.year, "PENDING", exclude))
        if days > total - taken:
            raise HTTPException(409, (
                f"{employee.full_name} has {total - taken:g} day(s) of {leave_type.name} left for {start.year} "
                f"(including requests still pending) and this request needs {days:g}. Use unpaid leave for "
                "the rest, or adjust the balance."))
    return days


def create_request(db: Session, company_id: uuid.UUID, *, employee_id: uuid.UUID, leave_type_id: uuid.UUID,
                   from_date: date, to_date: date, half_day: bool, reason: str | None,
                   user_id: uuid.UUID | None) -> m.LeaveRequest:
    employee = db.get(m.Employee, employee_id)
    leave_type = db.get(m.LeaveType, leave_type_id)
    if employee is None or employee.company_id != company_id:
        raise HTTPException(404, "Employee not found.")
    if leave_type is None or leave_type.company_id != company_id or not leave_type.is_active:
        raise HTTPException(404, "Leave type not found.")
    days = _validate(db, company_id, employee, leave_type, from_date, to_date, half_day)
    number = next_number(db, company_id, "hr_leave_request", "HR")
    request = m.LeaveRequest(
        company_id=company_id, request_number=f"LV-{int(number):05d}", employee_id=employee.id,
        leave_type_id=leave_type.id, from_date=from_date, to_date=to_date, half_day=half_day, days=days,
        reason=reason, status="PENDING", created_by=user_id)
    db.add(request)
    db.flush()
    return request


def _get(db: Session, company_id: uuid.UUID, request_id: uuid.UUID) -> m.LeaveRequest:
    request = db.get(m.LeaveRequest, request_id)
    if request is None or request.company_id != company_id:
        raise HTTPException(404, "Leave request not found.")
    return request


def _decide(request: m.LeaveRequest, status: str, user_id: uuid.UUID | None, note: str | None) -> None:
    request.status = status
    request.decided_by = user_id
    request.decided_at = datetime.now(timezone.utc)
    request.decision_note = note or None
    request.updated_by = user_id


def _months(db: Session, company_id: uuid.UUID, start: date, end: date) -> None:
    for day in {date(d.year, d.month, 1) for d in days_between(start, end)}:
        assert_month_open(db, company_id, day)


def approve(db: Session, company_id: uuid.UUID, request_id: uuid.UUID, user_id: uuid.UUID | None,
            note: str | None = None) -> m.LeaveRequest:
    request = _get(db, company_id, request_id)
    if request.status != "PENDING":
        raise HTTPException(409, f"Request {request.request_number} is {request.status}, not pending.")
    employee = db.get(m.Employee, request.employee_id)
    leave_type = db.get(m.LeaveType, request.leave_type_id)
    _months(db, company_id, request.from_date, request.to_date)
    # Counted again now: a holiday may have been added since it was entered.
    request.days = _validate(db, company_id, employee, leave_type, request.from_date, request.to_date,
                             request.half_day, exclude=request.id)
    _, working = count_days(db, company_id, employee, request.from_date, request.to_date, request.half_day)
    existing = {r.work_date: r for r in db.scalars(select(m.Attendance).where(
        m.Attendance.employee_id == employee.id, m.Attendance.work_date >= request.from_date,
        m.Attendance.work_date <= request.to_date))}
    for day in working:
        record = existing.get(day)
        if record is None:
            record = m.Attendance(company_id=company_id, employee_id=employee.id, work_date=day,
                                  created_by=user_id)
            db.add(record)
        record.status = m.ON_LEAVE
        record.check_in = record.check_out = None
        record.worked_minutes = record.late_minutes = record.overtime_minutes = 0
        record.leave_request_id = request.id
        record.remarks = f"{leave_type.name} {request.request_number}"
        record.updated_by = user_id
    _decide(request, "APPROVED", user_id, note)
    db.flush()
    return request


def reject(db: Session, company_id: uuid.UUID, request_id: uuid.UUID, user_id: uuid.UUID | None,
           note: str | None) -> m.LeaveRequest:
    request = _get(db, company_id, request_id)
    if request.status != "PENDING":
        raise HTTPException(409, f"Request {request.request_number} is {request.status}, not pending.")
    if not (note or "").strip():
        raise HTTPException(400, "Give a reason for rejecting the request.")
    _decide(request, "REJECTED", user_id, note)
    db.flush()
    return request


def cancel(db: Session, company_id: uuid.UUID, request_id: uuid.UUID, user_id: uuid.UUID | None,
           note: str | None) -> m.LeaveRequest:
    """Withdraw a pending request, or take back an approved one. Taking back
    an approved request removes its days from attendance and returns them to
    the balance."""
    request = _get(db, company_id, request_id)
    if request.status not in ("PENDING", "APPROVED"):
        raise HTTPException(409, f"Request {request.request_number} is already {request.status}.")
    if request.status == "APPROVED":
        _months(db, company_id, request.from_date, request.to_date)
        for record in db.scalars(select(m.Attendance).where(m.Attendance.leave_request_id == request.id)):
            db.delete(record)
    _decide(request, "CANCELLED", user_id, note)
    db.flush()
    return request
