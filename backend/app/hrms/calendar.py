"""
Which days an employee is expected at work.

A day is a rest day when it is not one of the working days of the employee's
shift (or, without a shift, when it is one of the company's weekly off days),
and a holiday when it is in the holiday list. Everything else is a working
day. Attendance, leave and payroll all ask this one module, so a leave
request and the payslip that follows it always count the same days.
"""

import calendar as _calendar
import uuid
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.hrms import models as m


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, _calendar.monthrange(year, month)[1])


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def weekday_code(day: date) -> str:
    return m.WEEKDAYS[day.weekday()]


class WorkCalendar:
    """Holidays and rest days for a company over a date range, loaded once."""

    def __init__(self, db: Session, company_id: uuid.UUID, start: date, end: date,
                 settings: m.HRSettings):
        self.holidays: dict[date, str] = dict(db.execute(
            select(m.Holiday.holiday_date, m.Holiday.name).where(
                m.Holiday.company_id == company_id, m.Holiday.holiday_date >= start,
                m.Holiday.holiday_date <= end)).all())
        self.company_off = {d.strip().upper() for d in (settings.week_off_days or "").split(",") if d.strip()}
        self.shifts: dict[uuid.UUID, m.Shift] = {
            s.id: s for s in db.scalars(select(m.Shift).where(m.Shift.company_id == company_id))}

    def shift_of(self, employee: m.Employee) -> m.Shift | None:
        return self.shifts.get(employee.shift_id) if employee.shift_id else None

    def is_weekly_off(self, employee: m.Employee, day: date) -> bool:
        # An employee's own weekly rest day comes first, then the shift's
        # working days, then the company's rest days.
        if employee.weekly_rest:
            return weekday_code(day) == employee.weekly_rest
        shift = self.shift_of(employee)
        if shift is not None:
            working = {d.strip().upper() for d in (shift.working_days or "").split(",") if d.strip()}
            return weekday_code(day) not in working
        return weekday_code(day) in self.company_off

    def is_holiday(self, day: date) -> bool:
        return day in self.holidays

    def is_working_day(self, employee: m.Employee, day: date) -> bool:
        return not self.is_holiday(day) and not self.is_weekly_off(employee, day)

    def default_status(self, employee: m.Employee, day: date) -> str | None:
        """What a day is when nobody has marked it: a holiday, a rest day, or
        (None) an ordinary working day."""
        if self.is_holiday(day):
            return m.HOLIDAY
        if self.is_weekly_off(employee, day):
            return m.WEEKLY_OFF
        return None


def assert_month_open(db: Session, company_id: uuid.UUID, day: date) -> None:
    """Attendance and leave feed the payslip, so once a month's payroll is
    approved its days cannot change underneath it."""
    locked = db.scalar(select(m.PayrollRun.run_number).where(
        m.PayrollRun.company_id == company_id, m.PayrollRun.period_year == day.year,
        m.PayrollRun.period_month == day.month, m.PayrollRun.status.in_(("APPROVED", "PAID"))))
    if locked:
        raise HTTPException(409, f"Payroll {locked} for {day:%B %Y} is already approved, so its attendance "
                                 "and leave are locked. Cancel the payroll run first to change them.")
