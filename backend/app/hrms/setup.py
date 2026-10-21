"""
HR settings and the standard starting lists.

`install_defaults` adds names only: departments, designations, a general
shift, leave types and salary components. Every amount it adds is zero and
every leave entitlement is a starting figure the company is expected to
review, so nothing is paid or deducted until someone has entered a value.
"""

import uuid
from datetime import time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.hrms import models as m

DEPARTMENTS = [("ADMIN", "Administration"), ("ACC", "Accounts & Finance"), ("SALES", "Sales"),
               ("STORE", "Store & Inventory"), ("TECH", "Technical / Service")]
DESIGNATIONS = [("MGR", "Manager"), ("ACCT", "Accountant"), ("SEXEC", "Sales Executive"),
                ("STORE", "Store Keeper"), ("TECH", "Technician"), ("DRV", "Driver"), ("OB", "Office Boy")]
#: (code, name, annual days, paid). REQUIRES BUSINESS CONFIRMATION: the days
#: are common practice, not this company's policy. They are editable in Setup.
LEAVE_TYPES = [("AL", "Annual Leave", 14, True), ("CL", "Casual Leave", 10, True),
               ("SL", "Sick Leave", 8, True), ("UL", "Unpaid Leave", 0, False)]
#: (code, name, kind). Amounts are entered per employee; none is assumed.
COMPONENTS = [("HRA", "House Rent Allowance", m.EARNING), ("CONV", "Conveyance Allowance", m.EARNING),
              ("MED", "Medical Allowance", m.EARNING), ("UTIL", "Utilities Allowance", m.EARNING),
              ("TAX", "Income Tax", m.DEDUCTION), ("EOBI", "EOBI Contribution", m.DEDUCTION),
              ("PF", "Provident Fund", m.DEDUCTION)]


def get_settings(db: Session, company_id: uuid.UUID) -> m.HRSettings:
    settings = db.scalar(select(m.HRSettings).where(m.HRSettings.company_id == company_id))
    if settings is None:
        settings = m.HRSettings(
            company_id=company_id, week_off_days="SUN", unmarked_day_policy="PRESENT",
            salary_days_basis="CALENDAR", hours_per_day=Decimal("8"), overtime_multiplier=Decimal("0"),
            lates_per_absence=0, employee_code_prefix="JT-", employee_code_digits=4)
        db.add(settings)
        db.flush()
    return settings


def install_defaults(db: Session, company_id: uuid.UUID) -> dict:
    """Add whatever standard rows are missing. Safe to run again."""
    added = {"departments": 0, "designations": 0, "shifts": 0, "leave_types": 0, "salary_components": 0}
    get_settings(db, company_id)

    def missing(model, code: str) -> bool:
        return db.scalar(select(model.id).where(model.company_id == company_id, model.code == code)) is None

    for code, name in DEPARTMENTS:
        if missing(m.Department, code):
            db.add(m.Department(company_id=company_id, code=code, name=name))
            added["departments"] += 1
    for code, name in DESIGNATIONS:
        if missing(m.Designation, code):
            db.add(m.Designation(company_id=company_id, code=code, name=name))
            added["designations"] += 1
    if missing(m.Shift, "GEN"):
        db.add(m.Shift(company_id=company_id, code="GEN", name="General (9 to 6)", start_time=time(9, 0),
                       end_time=time(18, 0), grace_minutes=15, break_minutes=60,
                       working_days="MON,TUE,WED,THU,FRI,SAT"))
        added["shifts"] += 1
    for order, (code, name, days, paid) in enumerate(LEAVE_TYPES):
        if missing(m.LeaveType, code):
            db.add(m.LeaveType(company_id=company_id, code=code, name=name, annual_days=Decimal(days),
                               is_paid=paid, sort_order=(order + 1) * 10))
            added["leave_types"] += 1
    for order, (code, name, kind) in enumerate(COMPONENTS):
        if missing(m.SalaryComponent, code):
            db.add(m.SalaryComponent(company_id=company_id, code=code, name=name, kind=kind,
                                     calc_type=m.FIXED, default_value=Decimal("0"), sort_order=(order + 1) * 10))
            added["salary_components"] += 1
    db.flush()
    return added
