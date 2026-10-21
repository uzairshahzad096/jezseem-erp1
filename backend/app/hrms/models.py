"""
HRMS: the people side of the ERP.

    setup        departments, designations, shifts, holidays, leave types,
                 salary components, HR settings
    employees    the employee master and each employee's salary structure
    attendance   one row per employee per day
    leave        entitlements per year and leave requests
    loans        advances and loans, recovered through payroll
    payroll      a monthly run with one payslip per employee

Three rules shape the tables:

- Nothing that can be derived is stored as an editable balance. Leave used is
  the sum of approved requests; a loan's outstanding is its amount less its
  repayments.
- A payslip is a snapshot. It copies the employee's name, department and
  every amount at the time of the run, so changing a salary later never
  rewrites a month that was already paid.
- Rates are configuration, never code. No tax slab, EOBI figure or overtime
  rate is hard-coded: they are salary components and settings that the
  company enters.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, Time,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base

MONEY = Numeric(18, 2)
DAYS = Numeric(6, 2)

# Employee
EMPLOYMENT_TYPES = ["PERMANENT", "PROBATION", "CONTRACT", "INTERN", "DAILY_WAGE"]
EMPLOYEE_STATUSES = ["ACTIVE", "INACTIVE", "RESIGNED", "TERMINATED"]
SEPARATED = ("RESIGNED", "TERMINATED")
PAYMENT_MODES = ["BANK", "CASH", "CHEQUE"]

# Attendance
PRESENT, ABSENT, LATE, HALF_DAY, ON_LEAVE, HOLIDAY, WEEKLY_OFF = (
    "PRESENT", "ABSENT", "LATE", "HALF_DAY", "LEAVE", "HOLIDAY", "WEEKLY_OFF")
ATTENDANCE_STATUSES = [PRESENT, ABSENT, LATE, HALF_DAY, ON_LEAVE, HOLIDAY, WEEKLY_OFF]

# Salary components
EARNING, DEDUCTION = "EARNING", "DEDUCTION"
FIXED, PERCENT_BASIC = "FIXED", "PERCENT_BASIC"

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _company() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)


def _fk(target: str, nullable: bool = True, **kw) -> Mapped:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, **kw), nullable=nullable, index=True)


# --------------------------------------------------------------------- setup

class HRSettings(UUIDPKMixin, AuditMixin, Base):
    """One row per company: the policies payroll and attendance follow."""

    __tablename__ = "hr_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, unique=True)
    #: Weekly rest days for employees without a shift, e.g. "SUN" or "SAT,SUN".
    week_off_days: Mapped[str] = mapped_column(String(40), default="SUN", nullable=False)
    #: A working day with no attendance entry counts as PRESENT or ABSENT in payroll.
    unmarked_day_policy: Mapped[str] = mapped_column(String(10), default="PRESENT", nullable=False)
    #: CALENDAR: a day's pay is the month's salary / days in that month. FIXED_30: always / 30.
    salary_days_basis: Mapped[str] = mapped_column(String(12), default="CALENDAR", nullable=False)
    hours_per_day: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=8, nullable=False)
    #: Overtime pay = hours x hourly basic x this. 0 means overtime is recorded but not paid.
    overtime_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    #: This many late arrivals in a month cost one day's pay. 0 switches the rule off.
    lates_per_absence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: New employees are numbered prefix + a counter: JT-0001, JT-0002…
    employee_code_prefix: Mapped[str] = mapped_column(String(10), default="JT-", nullable=False)
    employee_code_digits: Mapped[int] = mapped_column(Integer, default=4, nullable=False)


class Department(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_departments"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_hr_department_code"),)

    company_id: Mapped[uuid.UUID] = _company()
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = _fk("hr_departments.id")
    head_id: Mapped[uuid.UUID | None] = _fk("hr_employees.id", use_alter=True, name="fk_hr_department_head")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Designation(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_designations"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_hr_designation_code"),)

    company_id: Mapped[uuid.UUID] = _company()
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Shift(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_shifts"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_hr_shift_code"),)

    company_id: Mapped[uuid.UUID] = _company()
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    #: Arriving within this many minutes of the start is still on time.
    grace_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    working_days: Mapped[str] = mapped_column(String(40), default="MON,TUE,WED,THU,FRI,SAT", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Holiday(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_holidays"
    __table_args__ = (UniqueConstraint("company_id", "holiday_date", name="uq_hr_holiday_date"),)

    company_id: Mapped[uuid.UUID] = _company()
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)


class LeaveType(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_leave_types"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_hr_leave_type_code"),)

    company_id: Mapped[uuid.UUID] = _company()
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    #: Days granted each calendar year. 0 with is_paid False is plain unpaid leave.
    annual_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    carry_forward: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_carry_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class SalaryComponent(UUIDPKMixin, AuditMixin, Base):
    """An allowance or deduction that can sit on a salary structure. Basic
    salary, overtime, unpaid days and loan recovery are not components: the
    payroll run works those out itself."""

    __tablename__ = "hr_salary_components"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_hr_salary_component_code"),)

    company_id: Mapped[uuid.UUID] = _company()
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)             # EARNING / DEDUCTION
    calc_type: Mapped[str] = mapped_column(String(16), default=FIXED, nullable=False)
    default_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


# --------------------------------------------------------------------- employees

class Employee(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_employees"
    __table_args__ = (UniqueConstraint("company_id", "employee_code", name="uq_hr_employee_code"),)

    company_id: Mapped[uuid.UUID] = _company()
    branch_id: Mapped[uuid.UUID | None] = _fk("branches.id")
    employee_code: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    father_name: Mapped[str | None] = mapped_column(String(200))
    gender: Mapped[str | None] = mapped_column(String(10))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    marital_status: Mapped[str | None] = mapped_column(String(20))
    blood_group: Mapped[str | None] = mapped_column(String(5))
    cnic: Mapped[str | None] = mapped_column(String(20), index=True)
    cnic_expiry: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(40))

    department_id: Mapped[uuid.UUID | None] = _fk("hr_departments.id")
    designation_id: Mapped[uuid.UUID | None] = _fk("hr_designations.id")
    shift_id: Mapped[uuid.UUID | None] = _fk("hr_shifts.id")
    manager_id: Mapped[uuid.UUID | None] = _fk("hr_employees.id")
    employment_type: Mapped[str] = mapped_column(String(20), default="PERMANENT", nullable=False)
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    probation_end_date: Mapped[date | None] = mapped_column(Date)
    confirmation_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False, index=True)
    separation_date: Mapped[date | None] = mapped_column(Date)
    separation_reason: Mapped[str | None] = mapped_column(Text)

    payment_mode: Mapped[str] = mapped_column(String(10), default="BANK", nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(150))
    bank_account_title: Mapped[str | None] = mapped_column(String(200))
    bank_account_number: Mapped[str | None] = mapped_column(String(60))
    iban: Mapped[str | None] = mapped_column(String(40))
    ntn: Mapped[str | None] = mapped_column(String(30))
    eobi_number: Mapped[str | None] = mapped_column(String(30))
    social_security_number: Mapped[str | None] = mapped_column(String(30))

    #: The ERP login this person uses, if any.
    user_id: Mapped[uuid.UUID | None] = _fk("users.id")
    notes: Mapped[str | None] = mapped_column(Text)

    # ---- Fields carried over from the previous ERP's employee form ----
    # Basic information
    #: The former employee whose position this person fills.
    replacement_employee_id: Mapped[uuid.UUID | None] = _fk("hr_employees.id")
    father_occupation: Mapped[str | None] = mapped_column(String(150))
    mother_name: Mapped[str | None] = mapped_column(String(200))
    #: A department whose parent is `department_id`.
    sub_department_id: Mapped[uuid.UUID | None] = _fk("hr_departments.id")
    #: This employee's own weekly rest day (MON…SUN). Overrides the shift's
    #: working days and the company's rest days.
    weekly_rest: Mapped[str | None] = mapped_column(String(3))
    orientation_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    orientation_date: Mapped[date | None] = mapped_column(Date)
    orientation_remarks: Mapped[str | None] = mapped_column(Text)
    eobi_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    social_security_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Does not clock in: a working day without a mark is always present.
    attendance_exempt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    group_insurance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Storage key of the photo under UPLOAD_DIR ("employees/<uuid>.jpg").
    photo_path: Mapped[str | None] = mapped_column(String(255))

    # Official information
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vacancy_date: Mapped[date | None] = mapped_column(Date)
    probation_months: Mapped[int | None] = mapped_column(Integer)
    probation_extend_months: Mapped[int | None] = mapped_column(Integer)
    mobile_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    official_email: Mapped[str | None] = mapped_column(String(255))
    grade: Mapped[str | None] = mapped_column(String(30))
    #: Late arrivals are recorded but never cost this employee a day's pay.
    late_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Personal information
    father_cnic: Mapped[str | None] = mapped_column(String(20))
    cnic_issue_date: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(60))
    birth_place: Mapped[str | None] = mapped_column(String(100))
    phone_landline: Mapped[str | None] = mapped_column(String(40))
    hepatitis_status: Mapped[str | None] = mapped_column(String(20))
    caste: Mapped[str | None] = mapped_column(String(60))
    children_count: Mapped[int | None] = mapped_column(Integer)
    religion: Mapped[str | None] = mapped_column(String(40))

    # Confidential information (shown and changed only with payroll access)
    provident_fund_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Overtime hours are paid only to employees with this switched on.
    overtime_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ledger_account_id: Mapped[uuid.UUID | None] = _fk("accounts.id")
    wages_account_id: Mapped[uuid.UUID | None] = _fk("accounts.id")
    handicap: Mapped[str | None] = mapped_column(String(100))
    mileage: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fixed_fuel_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    taxable_salary: Mapped[Decimal | None] = mapped_column(MONEY)
    overtime_salary: Mapped[Decimal | None] = mapped_column(MONEY)
    shift_premium: Mapped[Decimal | None] = mapped_column(MONEY)
    annual_allowance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Resignation / dismissal detail (the quit date is `separation_date`)
    resign_notice_start: Mapped[date | None] = mapped_column(Date)
    resign_notice_end: Mapped[date | None] = mapped_column(Date)
    temporary_block: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


#: Employee fields only people with payroll access may see or change.
CONFIDENTIAL_FIELDS = (
    "provident_fund_allowed", "overtime_allowed", "payment_mode", "bank_name", "bank_account_title",
    "bank_account_number", "iban", "ledger_account_id", "wages_account_id", "handicap", "mileage",
    "fixed_fuel_amount", "taxable_salary", "overtime_salary", "shift_premium", "annual_allowance",
)


class SalaryStructure(UUIDPKMixin, AuditMixin, Base):
    """What an employee is paid from a date onward. A raise is a new row,
    never an edit, so every past month can still be explained."""

    __tablename__ = "hr_salary_structures"
    __table_args__ = (UniqueConstraint("employee_id", "effective_from", name="uq_hr_salary_effective"),)

    company_id: Mapped[uuid.UUID] = _company()
    employee_id: Mapped[uuid.UUID] = _fk("hr_employees.id", nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    basic_salary: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["SalaryStructureLine"]] = relationship(
        back_populates="structure", cascade="all, delete-orphan")


class SalaryStructureLine(UUIDPKMixin, Base):
    __tablename__ = "hr_salary_structure_lines"
    __table_args__ = (UniqueConstraint("structure_id", "component_id", name="uq_hr_salary_line_component"),)

    structure_id: Mapped[uuid.UUID] = _fk("hr_salary_structures.id", nullable=False)
    component_id: Mapped[uuid.UUID] = _fk("hr_salary_components.id", nullable=False)
    calc_type: Mapped[str] = mapped_column(String(16), default=FIXED, nullable=False)
    #: Rupees for FIXED, a percentage of basic for PERCENT_BASIC.
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)

    structure: Mapped["SalaryStructure"] = relationship(back_populates="lines")


# --------------------------------------------------------------------- attendance

class Attendance(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_attendance"
    __table_args__ = (UniqueConstraint("employee_id", "work_date", name="uq_hr_attendance_day"),)

    company_id: Mapped[uuid.UUID] = _company()
    employee_id: Mapped[uuid.UUID] = _fk("hr_employees.id", nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    check_in: Mapped[time | None] = mapped_column(Time)
    check_out: Mapped[time | None] = mapped_column(Time)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Set when the row was written by an approved leave request.
    leave_request_id: Mapped[uuid.UUID | None] = _fk("hr_leave_requests.id")
    remarks: Mapped[str | None] = mapped_column(String(255))


# --------------------------------------------------------------------- leave

class LeaveBalance(UUIDPKMixin, AuditMixin, Base):
    """An employee's entitlement for one leave type in one calendar year.
    Days used are not stored here: they are the approved requests."""

    __tablename__ = "hr_leave_balances"
    __table_args__ = (UniqueConstraint("employee_id", "leave_type_id", "year", name="uq_hr_leave_balance"),)

    company_id: Mapped[uuid.UUID] = _company()
    employee_id: Mapped[uuid.UUID] = _fk("hr_employees.id", nullable=False)
    leave_type_id: Mapped[uuid.UUID] = _fk("hr_leave_types.id", nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    entitled: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    carried_forward: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    adjustment: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    adjustment_note: Mapped[str | None] = mapped_column(String(255))


class LeaveRequest(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_leave_requests"
    __table_args__ = (UniqueConstraint("company_id", "request_number", name="uq_hr_leave_request_number"),)

    company_id: Mapped[uuid.UUID] = _company()
    request_number: Mapped[str] = mapped_column(String(30), nullable=False)
    employee_id: Mapped[uuid.UUID] = _fk("hr_employees.id", nullable=False)
    leave_type_id: Mapped[uuid.UUID] = _fk("hr_leave_types.id", nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    half_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Working days in the range: weekly rest days and holidays are not charged.
    days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="PENDING", nullable=False, index=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------- loans

class Loan(UUIDPKMixin, AuditMixin, Base):
    """A salary advance or a loan, recovered by an instalment on each payslip."""

    __tablename__ = "hr_loans"
    __table_args__ = (UniqueConstraint("company_id", "loan_number", name="uq_hr_loan_number"),)

    company_id: Mapped[uuid.UUID] = _company()
    loan_number: Mapped[str] = mapped_column(String(30), nullable=False)
    employee_id: Mapped[uuid.UUID] = _fk("hr_employees.id", nullable=False)
    kind: Mapped[str] = mapped_column(String(10), default="ADVANCE", nullable=False)   # ADVANCE / LOAN
    loan_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    installment_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    #: First payroll month that recovers an instalment (the 1st of that month).
    recovery_start: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    repayments: Mapped[list["LoanRepayment"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan", order_by="LoanRepayment.paid_on")


class LoanRepayment(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_loan_repayments"

    loan_id: Mapped[uuid.UUID] = _fk("hr_loans.id", nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    source: Mapped[str] = mapped_column(String(10), default="PAYROLL", nullable=False)  # PAYROLL / MANUAL
    payslip_id: Mapped[uuid.UUID | None] = _fk("hr_payslips.id")
    #: A cancelled payroll run reverses its recoveries rather than deleting them.
    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255))

    loan: Mapped["Loan"] = relationship(back_populates="repayments")


# --------------------------------------------------------------------- payroll

class PayrollRun(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_payroll_runs"
    __table_args__ = (
        # One live run per month; a cancelled run does not block a fresh one.
        Index("uq_hr_payroll_month", "company_id", "period_year", "period_month",
              unique=True, postgresql_where=text("status <> 'CANCELLED'")),
    )

    company_id: Mapped[uuid.UUID] = _company()
    run_number: Mapped[str] = mapped_column(String(30), nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="DRAFT", nullable=False, index=True)
    employee_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_earnings: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    total_deductions: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    total_net: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_date: Mapped[date | None] = mapped_column(Date)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    payslips: Mapped[list["Payslip"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Payslip.employee_code")


class Payslip(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "hr_payslips"
    __table_args__ = (UniqueConstraint("run_id", "employee_id", name="uq_hr_payslip_employee"),)

    company_id: Mapped[uuid.UUID] = _company()
    run_id: Mapped[uuid.UUID] = _fk("hr_payroll_runs.id", nullable=False)
    employee_id: Mapped[uuid.UUID] = _fk("hr_employees.id", nullable=False)
    # Snapshot of the employee as they were when the run was made.
    employee_code: Mapped[str] = mapped_column(String(30), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(150))
    designation: Mapped[str | None] = mapped_column(String(150))
    payment_mode: Mapped[str] = mapped_column(String(10), default="BANK", nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(150))
    bank_account_title: Mapped[str | None] = mapped_column(String(200))
    bank_account_number: Mapped[str | None] = mapped_column(String(60))

    days_in_period: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    present_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    absent_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    paid_leave_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    unpaid_leave_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    holidays: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    weekly_offs: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    #: Days in the month before the joining date or after the separation date.
    not_employed_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    #: Working days with no attendance entry, counted by the unmarked-day policy.
    unmarked_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    late_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unpaid_days: Mapped[Decimal] = mapped_column(DAYS, default=0, nullable=False)
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0, nullable=False)

    basic_salary: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    gross_salary: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    total_earnings: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    total_deductions: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    net_pay: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    #: Things a reviewer should look at: no salary structure, negative net pay…
    warnings: Mapped[str | None] = mapped_column(Text)

    run: Mapped["PayrollRun"] = relationship(back_populates="payslips")
    lines: Mapped[list["PayslipLine"]] = relationship(
        back_populates="payslip", cascade="all, delete-orphan", order_by="PayslipLine.sort_order")


class PayslipLine(UUIDPKMixin, Base):
    __tablename__ = "hr_payslip_lines"

    payslip_id: Mapped[uuid.UUID] = _fk("hr_payslips.id", nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)             # EARNING / DEDUCTION
    amount: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    #: Typed in on the draft (bonus, arrears, a one-off deduction). Kept when the run is recalculated.
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    loan_id: Mapped[uuid.UUID | None] = _fk("hr_loans.id")
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    payslip: Mapped["Payslip"] = relationship(back_populates="lines")
