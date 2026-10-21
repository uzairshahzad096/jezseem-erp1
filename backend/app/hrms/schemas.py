from datetime import date, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _days(value: str) -> str:
    days = [d.strip().upper() for d in (value or "").split(",") if d.strip()]
    bad = [d for d in days if d not in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")]
    if bad:
        raise ValueError(f"Unknown day(s): {', '.join(bad)}. Use MON, TUE, WED, THU, FRI, SAT, SUN.")
    return ",".join(dict.fromkeys(days))


class SettingsIn(BaseModel):
    week_off_days: str = "SUN"
    unmarked_day_policy: Literal["PRESENT", "ABSENT"] = "PRESENT"
    salary_days_basis: Literal["CALENDAR", "FIXED_30"] = "CALENDAR"
    hours_per_day: Decimal = Field(default=Decimal("8"), gt=0, le=24)
    overtime_multiplier: Decimal = Field(default=Decimal("0"), ge=0, le=10)
    lates_per_absence: int = Field(default=0, ge=0, le=31)
    employee_code_prefix: str = Field(default="JT-", max_length=10)
    employee_code_digits: int = Field(default=4, ge=1, le=8)

    _check_days = field_validator("week_off_days")(_days)


class CodeName(BaseModel):
    #: Left blank, the code is made from the name when the row is saved.
    code: str | None = Field(default=None, max_length=30)
    name: str = Field(min_length=1, max_length=150)
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def upper(cls, value: str | None) -> str | None:
        return (value or "").strip().upper() or None


class DepartmentIn(CodeName):
    parent_id: str | None = None
    head_id: str | None = None


class DesignationIn(CodeName):
    grade: str | None = None


class ShiftIn(CodeName):
    start_time: time
    end_time: time
    grace_minutes: int = Field(default=0, ge=0, le=240)
    break_minutes: int = Field(default=0, ge=0, le=480)
    working_days: str = "MON,TUE,WED,THU,FRI,SAT"

    _check_days = field_validator("working_days")(_days)


class HolidayIn(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=150)


class LeaveTypeIn(CodeName):
    annual_days: Decimal = Field(default=Decimal("0"), ge=0, le=366)
    is_paid: bool = True
    carry_forward: bool = False
    max_carry_days: Decimal = Field(default=Decimal("0"), ge=0, le=366)
    sort_order: int = 100


class SalaryComponentIn(CodeName):
    kind: Literal["EARNING", "DEDUCTION"]
    calc_type: Literal["FIXED", "PERCENT_BASIC"] = "FIXED"
    default_value: Decimal = Field(default=Decimal("0"), ge=0)
    sort_order: int = 100


class EmployeeIn(BaseModel):
    employee_code: str | None = Field(default=None, max_length=30)
    full_name: str = Field(min_length=1, max_length=200)
    father_name: str | None = None
    gender: Literal["MALE", "FEMALE", "OTHER"] | None = None
    date_of_birth: date | None = None
    marital_status: Literal["SINGLE", "MARRIED", "DIVORCED", "WIDOWED"] | None = None
    blood_group: str | None = Field(default=None, max_length=5)
    cnic: str | None = Field(default=None, max_length=20)
    cnic_expiry: date | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    branch_id: str | None = None
    department_id: str | None = None
    designation_id: str | None = None
    shift_id: str | None = None
    manager_id: str | None = None
    employment_type: Literal["PERMANENT", "PROBATION", "CONTRACT", "INTERN", "DAILY_WAGE"] = "PERMANENT"
    joining_date: date
    probation_end_date: date | None = None
    confirmation_date: date | None = None
    #: Only ACTIVE and INACTIVE are set here; leaving the company has its own action.
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    payment_mode: Literal["BANK", "CASH", "CHEQUE"] = "BANK"
    bank_name: str | None = None
    bank_account_title: str | None = None
    bank_account_number: str | None = None
    iban: str | None = None
    ntn: str | None = None
    eobi_number: str | None = None
    social_security_number: str | None = None
    user_id: str | None = None
    notes: str | None = None

    # Basic information (previous ERP's form)
    replacement_employee_id: str | None = None
    father_occupation: str | None = None
    mother_name: str | None = None
    sub_department_id: str | None = None
    weekly_rest: Weekday | None = None
    orientation_done: bool = False
    orientation_date: date | None = None
    orientation_remarks: str | None = None
    eobi_registered: bool = False
    social_security_registered: bool = False
    attendance_exempt: bool = False
    group_insurance: bool = False
    # Official information
    is_confirmed: bool = False
    vacancy_date: date | None = None
    probation_months: int | None = Field(default=None, ge=0, le=36)
    probation_extend_months: int | None = Field(default=None, ge=0, le=36)
    mobile_allowed: bool = True
    official_email: str | None = None
    grade: str | None = Field(default=None, max_length=30)
    late_allowed: bool = False
    # Personal information
    father_cnic: str | None = Field(default=None, max_length=20)
    cnic_issue_date: date | None = None
    nationality: str | None = None
    birth_place: str | None = None
    phone_landline: str | None = None
    hepatitis_status: str | None = None
    caste: str | None = None
    children_count: int | None = Field(default=None, ge=0, le=50)
    religion: str | None = None
    # Confidential information: ignored unless the user has payroll access
    provident_fund_allowed: bool = False
    overtime_allowed: bool = False
    ledger_account_id: str | None = None
    wages_account_id: str | None = None
    handicap: str | None = None
    mileage: Decimal | None = Field(default=None, ge=0)
    fixed_fuel_amount: Decimal | None = Field(default=None, ge=0)
    taxable_salary: Decimal | None = Field(default=None, ge=0)
    overtime_salary: Decimal | None = Field(default=None, ge=0)
    shift_premium: Decimal | None = Field(default=None, ge=0)
    annual_allowance: bool = False
    resign_notice_start: date | None = None
    resign_notice_end: date | None = None
    temporary_block: bool = False
    #: New employees only: starts the salary structure from the joining date.
    #: Later changes go through the salary structure, which keeps the history.
    gross_salary: Decimal | None = Field(default=None, ge=0)
    income_tax: Decimal | None = Field(default=None, ge=0)


class SeparationIn(BaseModel):
    status: Literal["RESIGNED", "TERMINATED"]
    separation_date: date
    reason: str = Field(min_length=3)


class SalaryLineIn(BaseModel):
    component_id: str
    calc_type: Literal["FIXED", "PERCENT_BASIC"] = "FIXED"
    value: Decimal = Field(ge=0)


class SalaryIn(BaseModel):
    effective_from: date
    basic_salary: Decimal = Field(ge=0)
    remarks: str | None = None
    lines: list[SalaryLineIn] = []


class AttendanceEntryIn(BaseModel):
    employee_id: str
    #: Null clears the mark for that employee.
    status: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    overtime_minutes: int | None = Field(default=None, ge=0, le=1440)
    remarks: str | None = Field(default=None, max_length=255)


class AttendanceDayIn(BaseModel):
    work_date: date
    entries: list[AttendanceEntryIn]


class LeaveRequestIn(BaseModel):
    employee_id: str
    leave_type_id: str
    from_date: date
    to_date: date
    half_day: bool = False
    reason: str | None = None


class DecisionIn(BaseModel):
    note: str | None = None


class LeaveBalanceIn(BaseModel):
    entitled: Decimal = Field(ge=0, le=366)
    carried_forward: Decimal = Field(ge=0, le=366)
    adjustment: Decimal = Field(ge=-366, le=366)
    adjustment_note: str | None = Field(default=None, max_length=255)


class LoanIn(BaseModel):
    employee_id: str
    kind: Literal["ADVANCE", "LOAN"] = "ADVANCE"
    loan_date: date
    amount: Decimal = Field(gt=0)
    installment_amount: Decimal = Field(gt=0)
    #: Any date in the first month to recover from.
    recovery_start: date
    notes: str | None = None


class RepaymentIn(BaseModel):
    paid_on: date
    amount: Decimal = Field(gt=0)
    notes: str | None = Field(default=None, max_length=255)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3)


class PayrollRunIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    notes: str | None = None


class PayIn(BaseModel):
    payment_date: date


class ManualLineIn(BaseModel):
    kind: Literal["EARNING", "DEDUCTION"]
    name: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0)
