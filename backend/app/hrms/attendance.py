"""
Attendance: one row per employee per day.

Only what was actually marked is stored. A holiday or weekly rest day needs
no row: the calendar already knows it. `resolve_month` puts the two together
and is what the monthly sheet and the payroll run both read, so the sheet
on screen is exactly what gets paid.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.hrms import models as m
from app.hrms.calendar import WorkCalendar, assert_month_open, days_between
from app.hrms.setup import get_settings

HALF = Decimal("0.5")


def employed_on(employee: m.Employee, day: date) -> bool:
    return employee.joining_date <= day and (employee.separation_date is None or day <= employee.separation_date)


def employees_for(db: Session, company_id: uuid.UUID, start: date, end: date,
                  department_id: uuid.UUID | None = None) -> list[m.Employee]:
    """Everyone employed for at least one day of the range."""
    stmt = select(m.Employee).where(
        m.Employee.company_id == company_id, m.Employee.joining_date <= end,
        or_(m.Employee.separation_date.is_(None), m.Employee.separation_date >= start),
        m.Employee.status != "INACTIVE")
    if department_id:
        stmt = stmt.where(m.Employee.department_id == department_id)
    return list(db.scalars(stmt.order_by(m.Employee.employee_code)))


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def work_figures(shift: m.Shift | None, status: str, check_in: time | None,
                 check_out: time | None) -> tuple[str, int, int, int]:
    """(status, worked, late, overtime) in minutes, from the clock times.

    Arriving after the shift's grace period turns PRESENT into LATE. Overtime
    is time worked beyond the shift's own length, and only counts when both
    times are entered: nothing is guessed from a missing clock-out.
    """
    worked = late = overtime = 0
    if check_in and check_out:
        worked = _minutes(check_out) - _minutes(check_in)
        if worked < 0:                      # a shift that runs past midnight
            worked += 24 * 60
        if shift and worked > shift.break_minutes:
            worked -= shift.break_minutes
    if shift and check_in and status in (m.PRESENT, m.LATE):
        behind = _minutes(check_in) - _minutes(shift.start_time)
        late = behind if behind > shift.grace_minutes else 0
        status = m.LATE if late else m.PRESENT
    if shift and worked:
        scheduled = _minutes(shift.end_time) - _minutes(shift.start_time)
        if scheduled < 0:
            scheduled += 24 * 60
        scheduled -= shift.break_minutes
        overtime = max(0, worked - scheduled)
    return status, worked, late, overtime


def daily_sheet(db: Session, company_id: uuid.UUID, day: date,
                department_id: uuid.UUID | None = None) -> list[dict]:
    cal = WorkCalendar(db, company_id, day, day, get_settings(db, company_id))
    employees = [e for e in employees_for(db, company_id, day, day, department_id) if employed_on(e, day)]
    records = {r.employee_id: r for r in db.scalars(select(m.Attendance).where(
        m.Attendance.company_id == company_id, m.Attendance.work_date == day))}
    rows = []
    for e in employees:
        r = records.get(e.id)
        shift = cal.shift_of(e)
        rows.append({
            "employee_id": str(e.id), "employee_code": e.employee_code, "employee_name": e.full_name,
            "department_id": str(e.department_id) if e.department_id else None,
            "shift": shift.name if shift else None,
            "exempt": e.attendance_exempt,
            "marked": r is not None,
            "status": r.status if r else None,
            # What the day is if left alone: HOLIDAY, WEEKLY_OFF or a working day (null).
            "default_status": cal.default_status(e, day),
            "check_in": r.check_in.strftime("%H:%M") if r and r.check_in else None,
            "check_out": r.check_out.strftime("%H:%M") if r and r.check_out else None,
            "worked_minutes": r.worked_minutes if r else 0,
            "late_minutes": r.late_minutes if r else 0,
            "overtime_minutes": r.overtime_minutes if r else 0,
            "from_leave": bool(r and r.leave_request_id),
            "remarks": r.remarks if r else None,
        })
    return rows


def _time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:5], "%H:%M").time()
    except ValueError:
        raise HTTPException(400, f"'{value}' is not a time. Use HH:MM, for example 09:15.")


def save_daily(db: Session, company_id: uuid.UUID, day: date, entries: list[dict],
               user_id: uuid.UUID | None) -> dict:
    """Mark a day for many employees at once. An entry with no status clears
    that employee's mark."""
    if day > date.today():
        raise HTTPException(400, "Attendance cannot be marked for a future date.")
    assert_month_open(db, company_id, day)
    cal = WorkCalendar(db, company_id, day, day, get_settings(db, company_id))
    employees = {e.id: e for e in db.scalars(select(m.Employee).where(m.Employee.company_id == company_id))}
    records = {r.employee_id: r for r in db.scalars(select(m.Attendance).where(
        m.Attendance.company_id == company_id, m.Attendance.work_date == day))}
    saved = cleared = skipped = 0
    for entry in entries:
        employee = employees.get(uuid.UUID(str(entry["employee_id"])))
        if employee is None:
            raise HTTPException(404, "One of the employees on the sheet no longer exists.")
        if not employed_on(employee, day):
            raise HTTPException(400, f"{employee.full_name} was not employed on {day:%d-%b-%Y}.")
        record = records.get(employee.id)
        status = (entry.get("status") or "").upper() or None
        if record is not None and record.leave_request_id:
            # The day belongs to an approved leave request; it changes by
            # cancelling the request, so the leave balance stays right.
            skipped += 1
            continue
        if status is None:
            if record is not None:
                db.delete(record)
                cleared += 1
            continue
        if status not in m.ATTENDANCE_STATUSES:
            raise HTTPException(400, f"'{status}' is not an attendance status.")
        if status == m.ON_LEAVE:
            raise HTTPException(400, f"Leave for {employee.full_name} is recorded by approving a leave request, "
                                     "so it is charged to the right leave balance.")
        check_in, check_out = _time(entry.get("check_in")), _time(entry.get("check_out"))
        if status in (m.ABSENT, m.HOLIDAY, m.WEEKLY_OFF):
            check_in = check_out = None
        status, worked, late, overtime = work_figures(cal.shift_of(employee), status, check_in, check_out)
        if entry.get("overtime_minutes") is not None:
            overtime = max(0, int(entry["overtime_minutes"]))
        if record is None:
            record = m.Attendance(company_id=company_id, employee_id=employee.id, work_date=day, created_by=user_id)
            db.add(record)
        record.status, record.check_in, record.check_out = status, check_in, check_out
        record.worked_minutes, record.late_minutes, record.overtime_minutes = worked, late, overtime
        record.remarks = (entry.get("remarks") or None)
        record.updated_by = user_id
        saved += 1
    db.flush()
    return {"saved": saved, "cleared": cleared, "skipped_leave": skipped}


@dataclass
class MonthSummary:
    """One employee's month, as payroll will count it."""

    days: dict[date, str | None] = field(default_factory=dict)   # None = not employed that day
    present: Decimal = Decimal(0)
    absent: Decimal = Decimal(0)
    half_days: int = 0
    late_count: int = 0
    paid_leave: Decimal = Decimal(0)
    unpaid_leave: Decimal = Decimal(0)
    holidays: Decimal = Decimal(0)
    weekly_offs: Decimal = Decimal(0)
    not_employed: Decimal = Decimal(0)
    unmarked: Decimal = Decimal(0)
    overtime_minutes: int = 0

    def as_dict(self) -> dict:
        return {
            "present": float(self.present), "absent": float(self.absent), "half_days": self.half_days,
            "late_count": self.late_count, "paid_leave": float(self.paid_leave),
            "unpaid_leave": float(self.unpaid_leave), "holidays": float(self.holidays),
            "weekly_offs": float(self.weekly_offs), "not_employed": float(self.not_employed),
            "unmarked": float(self.unmarked), "overtime_hours": round(self.overtime_minutes / 60, 2),
        }


def resolve_month(db: Session, company_id: uuid.UUID, start: date, end: date,
                  employees: list[m.Employee]) -> dict[uuid.UUID, MonthSummary]:
    """Every employee's status for every day of the range.

    A marked day is what was marked. An unmarked day is a holiday or rest day
    if the calendar says so, and otherwise follows the company's unmarked-day
    policy (PRESENT or ABSENT) and is counted as `unmarked` so it can be seen.
    A half day counts half present and half absent, unless it is half a day
    of approved leave, which counts half present and half leave.
    """
    settings = get_settings(db, company_id)
    cal = WorkCalendar(db, company_id, start, end, settings)
    ids = [e.id for e in employees]
    records: dict[tuple[uuid.UUID, date], m.Attendance] = {}
    if ids:
        for r in db.scalars(select(m.Attendance).where(
                m.Attendance.employee_id.in_(ids), m.Attendance.work_date >= start,
                m.Attendance.work_date <= end)):
            records[(r.employee_id, r.work_date)] = r
    leave_ids = {r.leave_request_id for r in records.values() if r.leave_request_id}
    paid_by_request: dict[uuid.UUID, bool] = {}
    half_requests: set[uuid.UUID] = set()
    if leave_ids:
        for request_id, is_paid, half in db.execute(
                select(m.LeaveRequest.id, m.LeaveType.is_paid, m.LeaveRequest.half_day)
                .join(m.LeaveType, m.LeaveType.id == m.LeaveRequest.leave_type_id)
                .where(m.LeaveRequest.id.in_(leave_ids))):
            paid_by_request[request_id] = is_paid
            if half:
                half_requests.add(request_id)

    today = date.today()
    result: dict[uuid.UUID, MonthSummary] = {}
    for e in employees:
        s = MonthSummary()
        for day in days_between(start, end):
            if not employed_on(e, day):
                s.days[day] = None
                s.not_employed += 1
                continue
            r = records.get((e.id, day))
            if r is None:
                status = cal.default_status(e, day)
                if status is None:
                    if day > today:
                        # Not happened yet: neither present nor absent.
                        s.days[day] = ""
                        continue
                    if e.attendance_exempt:
                        # Does not clock in: present unless marked otherwise.
                        status = m.PRESENT
                        s.days[day] = status
                    else:
                        status = m.ABSENT if settings.unmarked_day_policy == "ABSENT" else m.PRESENT
                        s.unmarked += 1
                        s.days[day] = f"~{status}"      # "~" marks an assumed status
                else:
                    s.days[day] = status
            else:
                status = r.status
                s.days[day] = status
                s.overtime_minutes += r.overtime_minutes

            if status in (m.PRESENT, m.LATE):
                s.present += 1
                s.late_count += status == m.LATE
            elif status == m.ABSENT:
                s.absent += 1
            elif status == m.HALF_DAY:
                s.half_days += 1
                s.present += HALF
                s.absent += HALF
            elif status == m.ON_LEAVE:
                amount = HALF if (r and r.leave_request_id in half_requests) else Decimal(1)
                paid = paid_by_request.get(r.leave_request_id, True) if r else True
                if paid:
                    s.paid_leave += amount
                else:
                    s.unpaid_leave += amount
                s.present += Decimal(1) - amount
            elif status == m.HOLIDAY:
                s.holidays += 1
            elif status == m.WEEKLY_OFF:
                s.weekly_offs += 1
        result[e.id] = s
    return result


def monthly_sheet(db: Session, company_id: uuid.UUID, year: int, month: int,
                  department_id: uuid.UUID | None = None) -> dict:
    from app.hrms.calendar import month_bounds
    start, end = month_bounds(year, month)
    employees = employees_for(db, company_id, start, end, department_id)
    summaries = resolve_month(db, company_id, start, end, employees)
    departments = dict(db.execute(select(m.Department.id, m.Department.name)
                                  .where(m.Department.company_id == company_id)).all())
    return {
        "year": year, "month": month, "days": [d.isoformat() for d in days_between(start, end)],
        "rows": [{
            "employee_id": str(e.id), "employee_code": e.employee_code, "employee_name": e.full_name,
            "department": departments.get(e.department_id),
            "days": {d.isoformat(): status for d, status in summaries[e.id].days.items()},
            **summaries[e.id].as_dict(),
        } for e in employees],
    }
