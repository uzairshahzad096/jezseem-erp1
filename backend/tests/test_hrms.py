"""HRMS: setup, employees, attendance, leave, loans and payroll.

September 2026 is the test month: 30 days, starting on a Tuesday, with
Sundays on the 6th, 13th, 20th and 27th.
"""

import io
from datetime import date, time
from decimal import Decimal as D

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import select

from app.hrms import attendance, leave, payroll
from app.hrms import models as m
from app.hrms.setup import get_settings, install_defaults
from tests.conftest import make_user

SEP = (2026, 9)


def employee(world, code="E1", joined=date(2025, 1, 1), **kw) -> m.Employee:
    e = m.Employee(company_id=world.company.id, employee_code=code, full_name=f"Employee {code}",
                   joining_date=joined, status="ACTIVE", employment_type="PERMANENT", payment_mode="BANK", **kw)
    world.db.add(e)
    world.db.flush()
    return e


def salary(world, e, basic, effective=date(2025, 1, 1), **components) -> m.SalaryStructure:
    """components: CODE=amount, using the standard component list."""
    by_code = {c.code: c for c in world.db.scalars(select(m.SalaryComponent).where(
        m.SalaryComponent.company_id == world.company.id))}
    structure = m.SalaryStructure(company_id=world.company.id, employee_id=e.id, effective_from=effective,
                                  basic_salary=D(basic))
    structure.lines = [m.SalaryStructureLine(component_id=by_code[code].id, calc_type=m.FIXED, value=D(amount))
                       for code, amount in components.items()]
    world.db.add(structure)
    world.db.flush()
    return structure


def mark(world, e, day, status, check_in=None, check_out=None):
    return attendance.save_daily(world.db, world.company.id, day, [
        {"employee_id": str(e.id), "status": status, "check_in": check_in, "check_out": check_out}], None)


@pytest.fixture
def hr(world, db):
    install_defaults(db, world.company.id)
    return world


def leave_type(hr, code):
    return hr.db.scalar(select(m.LeaveType).where(m.LeaveType.company_id == hr.company.id, m.LeaveType.code == code))


# ------------------------------------------------------------------ setup

def test_defaults_add_names_but_no_amounts(hr, db):
    components = list(db.scalars(select(m.SalaryComponent).where(m.SalaryComponent.company_id == hr.company.id)))
    assert {c.code for c in components} == {"HRA", "CONV", "MED", "UTIL", "TAX", "EOBI", "PF"}
    assert all(c.default_value == 0 for c in components)          # no rate is ever assumed
    settings = get_settings(db, hr.company.id)
    assert settings.overtime_multiplier == 0 and settings.lates_per_absence == 0
    again = install_defaults(db, hr.company.id)                   # safe to run twice
    assert set(again.values()) == {0}


# ------------------------------------------------------------------ attendance

def test_clock_times_give_late_and_overtime(hr, db):
    shift = db.scalar(select(m.Shift).where(m.Shift.company_id == hr.company.id))   # 09:00-18:00, 15 min grace, 60 break
    assert attendance.work_figures(shift, m.PRESENT, time(9, 10), time(18, 0)) == (m.PRESENT, 470, 0, 0)
    assert attendance.work_figures(shift, m.PRESENT, time(9, 40), time(18, 0)) == (m.LATE, 440, 40, 0)
    assert attendance.work_figures(shift, m.PRESENT, time(9, 0), time(20, 0)) == (m.PRESENT, 600, 0, 120)
    assert attendance.work_figures(shift, m.PRESENT, time(9, 0), None) == (m.PRESENT, 0, 0, 0)   # nothing guessed


def test_month_is_marks_plus_calendar(hr, db):
    e = employee(hr)
    db.add(m.Holiday(company_id=hr.company.id, holiday_date=date(2026, 9, 9), name="Test holiday"))
    db.flush()
    mark(hr, e, date(2026, 9, 1), m.ABSENT)
    mark(hr, e, date(2026, 9, 2), m.HALF_DAY)
    mark(hr, e, date(2026, 9, 3), m.PRESENT)
    s = attendance.resolve_month(db, hr.company.id, date(2026, 9, 1), date(2026, 9, 30), [e])[e.id]
    assert (s.weekly_offs, s.holidays) == (4, 1)                  # four Sundays, one holiday
    assert s.absent == D("1.5") and s.half_days == 1
    assert s.unmarked == 22 and s.present == D("23.5")            # unmarked working days count as present
    assert s.days[date(2026, 9, 6)] == m.WEEKLY_OFF and s.days[date(2026, 9, 4)] == "~PRESENT"

    get_settings(db, hr.company.id).unmarked_day_policy = "ABSENT"
    db.flush()
    s = attendance.resolve_month(db, hr.company.id, date(2026, 9, 1), date(2026, 9, 30), [e])[e.id]
    assert s.absent == D("23.5") and s.present == D("1.5")


def test_attendance_refuses_what_it_should(hr, db):
    e = employee(hr, joined=date(2026, 9, 10))
    with pytest.raises(HTTPException, match="not employed"):
        mark(hr, e, date(2026, 9, 5), m.PRESENT)
    with pytest.raises(HTTPException, match="leave request"):
        mark(hr, e, date(2026, 9, 11), m.ON_LEAVE)
    with pytest.raises(HTTPException, match="future"):
        mark(hr, e, date(2099, 1, 1), m.PRESENT)
    mark(hr, e, date(2026, 9, 11), m.PRESENT)
    assert mark(hr, e, date(2026, 9, 11), None) == {"saved": 0, "cleared": 1, "skipped_leave": 0}


# ------------------------------------------------------------------ leave

def test_leave_charges_working_days_and_writes_attendance(hr, db):
    e = employee(hr)
    annual = leave_type(hr, "AL")
    # Fri 4 Sep to Tue 8 Sep: Sunday the 6th is free, so four days.
    request = leave.create_request(db, hr.company.id, employee_id=e.id, leave_type_id=annual.id,
                                   from_date=date(2026, 9, 4), to_date=date(2026, 9, 8), half_day=False,
                                   reason="Family", user_id=None)
    assert request.days == 4 and request.status == "PENDING" and request.request_number == "LV-00001"
    balance = leave.balance_rows(db, hr.company.id, 2026, [e])[0]
    assert (balance["entitled"], balance["pending"], balance["used"], balance["available"]) == (14, 4, 0, 14)

    leave.approve(db, hr.company.id, request.id, hr.admin.id)
    days = {r.work_date: r.status for r in db.scalars(select(m.Attendance).where(m.Attendance.employee_id == e.id))}
    assert days == {date(2026, 9, d): m.ON_LEAVE for d in (4, 5, 7, 8)}
    assert leave.balance_rows(db, hr.company.id, 2026, [e])[0]["available"] == 10
    # A leave day is changed by cancelling the request, not on the attendance sheet.
    assert mark(hr, e, date(2026, 9, 4), m.PRESENT)["skipped_leave"] == 1

    leave.cancel(db, hr.company.id, request.id, hr.admin.id, "Plans changed")
    assert db.scalar(select(m.Attendance).where(m.Attendance.employee_id == e.id)) is None
    assert leave.balance_rows(db, hr.company.id, 2026, [e])[0]["available"] == 14


def test_leave_rules(hr, db):
    e = employee(hr)
    casual, unpaid = leave_type(hr, "CL"), leave_type(hr, "UL")

    def ask(start, end, kind=casual, half=False):
        return leave.create_request(db, hr.company.id, employee_id=e.id, leave_type_id=kind.id, from_date=start,
                                    to_date=end, half_day=half, reason=None, user_id=None)

    with pytest.raises(HTTPException, match="rest days or holidays"):
        ask(date(2026, 9, 6), date(2026, 9, 6))                    # a Sunday
    with pytest.raises(HTTPException, match="another year"):
        ask(date(2026, 12, 30), date(2027, 1, 2))
    with pytest.raises(HTTPException, match="single date"):
        ask(date(2026, 9, 1), date(2026, 9, 2), half=True)
    with pytest.raises(HTTPException, match="left for 2026"):
        ask(date(2026, 9, 1), date(2026, 9, 15))                   # 12 working days against 10
    first = ask(date(2026, 9, 1), date(2026, 9, 3))
    with pytest.raises(HTTPException, match="already has leave request"):
        ask(date(2026, 9, 3), date(2026, 9, 4))
    assert ask(date(2026, 9, 14), date(2026, 9, 14), half=True).days == D("0.5")
    # Unpaid leave has no balance to run out of.
    assert ask(date(2026, 10, 1), date(2026, 10, 30), kind=unpaid).days == 26
    with pytest.raises(HTTPException, match="reason"):
        leave.reject(db, hr.company.id, first.id, None, "")
    assert leave.reject(db, hr.company.id, first.id, None, "Short staffed").status == "REJECTED"


# ------------------------------------------------------------------ payroll

def test_payslip_arithmetic(hr, db):
    e = employee(hr, department_id=None)
    salary(hr, e, 30000, HRA=12000, TAX=1000)
    mark(hr, e, date(2026, 9, 1), m.ABSENT)
    mark(hr, e, date(2026, 9, 2), m.ABSENT)
    loan = m.Loan(company_id=hr.company.id, loan_number="LN-T1", employee_id=e.id, kind="ADVANCE",
                  loan_date=date(2026, 8, 20), amount=D(8000), installment_amount=D(5000),
                  recovery_start=date(2026, 9, 1), status="ACTIVE")
    db.add(loan)
    db.flush()

    run = payroll.generate(db, hr.company.id, *SEP, hr.admin.id)
    slip = run.payslips[0]
    lines = {x.code: x.amount for x in slip.lines}
    # Gross 42,000 over 30 days = 1,400 a day; two days absent = 2,800.
    assert lines == {"BASIC": 30000, "HRA": 12000, "TAX": 1000, "UNPAID": 2800, "LOAN": 5000}
    assert (slip.gross_salary, slip.total_earnings, slip.total_deductions, slip.net_pay) == (42000, 42000, 8800, 33200)
    assert slip.absent_days == 2 and slip.unpaid_days == 2 and "no attendance" in slip.warnings
    assert (run.status, run.run_number, run.total_net) == ("DRAFT", "PR-2026-09", 33200)

    # A manual line survives recalculation; calculated lines cannot be removed.
    payroll.add_manual_line(db, hr.company.id, slip.id, kind=m.EARNING, name="Eid bonus", amount=D(5000), user_id=None)
    payroll.calculate(db, run, None)
    assert run.payslips[0].net_pay == 38200 and any(x.is_manual for x in run.payslips[0].lines)
    basic_line = next(x for x in run.payslips[0].lines if x.code == "BASIC")
    with pytest.raises(HTTPException, match="typed in by hand"):
        payroll.remove_manual_line(db, hr.company.id, slip.id, basic_line.id, None)

    payroll.approve(db, hr.company.id, run.id, hr.admin.id)
    db.refresh(loan)
    assert payroll.loan_outstanding(loan) == 3000 and loan.status == "ACTIVE"
    # Approved payroll locks the month's attendance and leave.
    with pytest.raises(HTTPException, match="already approved"):
        mark(hr, e, date(2026, 9, 3), m.ABSENT)
    with pytest.raises(HTTPException, match="only a draft"):
        payroll.calculate(db, run, None)
    with pytest.raises(HTTPException, match="already exists"):
        payroll.generate(db, hr.company.id, *SEP, None)

    # Cancelling gives the recovery back; the month can then be run again.
    payroll.cancel(db, hr.company.id, run.id, "Wrong attendance", hr.admin.id)
    db.refresh(loan)
    assert payroll.loan_outstanding(loan) == 8000
    again = payroll.generate(db, hr.company.id, *SEP, None)
    assert again.run_number == "PR-2026-09-2" and again.payslips[0].net_pay == 33200
    payroll.approve(db, hr.company.id, again.id, None)
    payroll.mark_paid(db, hr.company.id, again.id, date(2026, 10, 1), None)
    with pytest.raises(HTTPException, match="final"):
        payroll.cancel(db, hr.company.id, again.id, "Too late", None)


def test_loan_instalment_never_exceeds_what_is_owed(hr, db):
    e = employee(hr)
    salary(hr, e, 50000)
    loan = m.Loan(company_id=hr.company.id, loan_number="LN-T2", employee_id=e.id, kind="LOAN",
                  loan_date=date(2026, 8, 1), amount=D(3000), installment_amount=D(5000) - D(3000) + D(1000),
                  recovery_start=date(2026, 9, 1), status="ACTIVE")
    loan.repayments = [m.LoanRepayment(paid_on=date(2026, 8, 25), amount=D(1000), source="MANUAL")]
    db.add(loan)
    db.flush()
    run = payroll.generate(db, hr.company.id, *SEP, None)
    assert next(x.amount for x in run.payslips[0].lines if x.code == "LOAN") == 2000     # owed 2,000, instalment 3,000
    payroll.approve(db, hr.company.id, run.id, None)
    db.refresh(loan)
    assert loan.status == "SETTLED" and payroll.loan_outstanding(loan) == 0


def test_joiner_leaver_unpaid_leave_overtime_and_lates(hr, db):
    settings = get_settings(db, hr.company.id)
    settings.overtime_multiplier, settings.lates_per_absence = D(2), 3
    shift = db.scalar(select(m.Shift).where(m.Shift.company_id == hr.company.id))
    joiner = employee(hr, "J1", joined=date(2026, 9, 16), shift_id=shift.id, overtime_allowed=True)   # 15 days not employed
    leaver = employee(hr, "L1")
    leaver.status, leaver.separation_date = "RESIGNED", date(2026, 9, 20)          # 10 days not employed
    nobody = employee(hr, "N1")                                                    # no salary structure
    gone = employee(hr, "G1")
    gone.status, gone.separation_date = "RESIGNED", date(2026, 8, 31)              # left before the month
    salary(hr, joiner, 30000, effective=date(2026, 9, 16))
    salary(hr, leaver, 60000)
    db.flush()
    for day in (16, 17, 18):
        mark(hr, joiner, date(2026, 9, day), m.PRESENT, "09:30", "20:00")           # late, 2 h overtime each
    unpaid = leave_type(hr, "UL")
    request = leave.create_request(db, hr.company.id, employee_id=leaver.id, leave_type_id=unpaid.id,
                                   from_date=date(2026, 9, 1), to_date=date(2026, 9, 2), half_day=False,
                                   reason=None, user_id=None)
    leave.approve(db, hr.company.id, request.id, None)

    run = payroll.generate(db, hr.company.id, *SEP, None)
    slips = {p.employee_code: p for p in run.payslips}
    assert set(slips) == {"J1", "L1", "N1"}                                         # G1 is not in the month

    j = {x.code: x.amount for x in slips["J1"].lines}
    # Hourly basic 30,000 / (30 x 8) = 125; 4.5 h x 125 x 2 = 1,125. (10:30 worked less a 1 h break = 9:30, 1:30 over.)
    assert slips["J1"].overtime_hours == D("4.5") and j["OT"] == 1125
    assert j["UNPAID"] == 15000 and j["LATE"] == 1000 and slips["J1"].late_count == 3
    assert slips["J1"].net_pay == 30000 + 1125 - 15000 - 1000

    l = {x.code: x.amount for x in slips["L1"].lines}
    assert l["UNPAID"] == 24000 and slips["L1"].unpaid_leave_days == 2 and slips["L1"].not_employed_days == 10
    assert slips["N1"].net_pay == 0 and "No salary structure" in slips["N1"].warnings


def test_employee_switches_from_the_old_erp_form(hr, db):
    """Weekly Rest, Exempt for Attendance, Overtime Allow and Late Allow."""
    settings = get_settings(db, hr.company.id)
    settings.overtime_multiplier, settings.lates_per_absence, settings.unmarked_day_policy = D(2), 3, "ABSENT"
    shift = db.scalar(select(m.Shift).where(m.Shift.company_id == hr.company.id))
    friday = employee(hr, "F1", weekly_rest="FRI", attendance_exempt=True)          # rests on Friday, never clocks in
    worker = employee(hr, "W1", shift_id=shift.id, late_allowed=True)               # overtime_allowed is off
    salary(hr, friday, 30000)
    salary(hr, worker, 30000)
    for day in attendance.days_between(date(2026, 9, 1), date(2026, 9, 30)):
        if day.weekday() != 6:
            mark(hr, worker, day, m.PRESENT, "09:30", "20:00")                      # late every day, 1.5 h over

    months = attendance.resolve_month(db, hr.company.id, date(2026, 9, 1), date(2026, 9, 30), [friday, worker])
    f = months[friday.id]
    # Four Fridays in September 2026 (4, 11, 18, 25); Sundays are working days for this employee.
    assert f.weekly_offs == 4 and f.days[date(2026, 9, 6)] == m.PRESENT and f.days[date(2026, 9, 4)] == m.WEEKLY_OFF
    assert (f.present, f.absent, f.unmarked) == (26, 0, 0)                          # exempt: present, not "unmarked"

    run = payroll.generate(db, hr.company.id, *SEP, None)
    slips = {p.employee_code: p for p in run.payslips}
    assert slips["F1"].net_pay == 30000 and slips["F1"].warnings is None
    w = {x.code for x in slips["W1"].lines}
    assert "OT" not in w and "LATE" not in w and slips["W1"].net_pay == 30000       # hours and lates recorded, not charged
    assert slips["W1"].late_count == 26 and "Overtime Allow is No" in slips["W1"].warnings


def test_negative_net_pay_blocks_approval(hr, db):
    e = employee(hr)
    salary(hr, e, 1000, TAX=5000)
    run = payroll.generate(db, hr.company.id, *SEP, None)
    assert run.payslips[0].net_pay == -4000 and "negative" in run.payslips[0].warnings
    with pytest.raises(HTTPException, match="Net pay is negative"):
        payroll.approve(db, hr.company.id, run.id, None)


# ------------------------------------------------------------------ API

@pytest.fixture
def api(client, hr, monkeypatch):
    import app.hrms.router as hr_router
    monkeypatch.setattr(hr_router, "active_company_id", lambda db: hr.company.id)
    return client


def test_employee_api(api, hr, db):
    department = api.post("/api/v1/hrms/departments", json={"code": "qa", "name": "Quality"}).json()
    assert department["code"] == "QA"
    assert api.post("/api/v1/hrms/departments", json={"code": "QA", "name": "Again"}).status_code == 409
    # Left blank, the code comes from the name: a bracketed abbreviation,
    # initials, or the start of a single word, numbered if already taken.
    made = [api.post("/api/v1/hrms/departments", json={"name": name}).json()["code"] for name in (
        "INFORMATION TECHNOLOGY (IT)", "Human Resources", "Research and Development", "Marketing", "Hire & Rent", "Quality (QA)")]
    assert made == ["IT", "HR", "RD", "MARKE", "HR2", "QA2"]
    edited = api.put(f"/api/v1/hrms/departments/{department['id']}", json={"name": "Quality Control"}).json()
    assert (edited["code"], edited["name"]) == ("QA", "Quality Control")      # a blank code keeps the old one

    body = {"full_name": "Ali Raza", "joining_date": "2026-01-05", "cnic": "35202-1234567-1",
            "department_id": department["id"], "bank_name": "HBL", "bank_account_number": "001234"}
    first = api.post("/api/v1/hrms/employees", json=body)
    assert first.status_code == 201, first.text
    assert first.json()["employee_code"] == "JT-0001" and first.json()["department"] == "Quality Control"
    duplicate = api.post("/api/v1/hrms/employees", json={**body, "full_name": "Someone Else"})
    assert duplicate.status_code == 409 and "already registered to JT-0001" in duplicate.json()["detail"]
    second = api.post("/api/v1/hrms/employees", json={"full_name": "Sara Khan", "joining_date": "2026-02-01"}).json()
    assert second["employee_code"] == "JT-0002"
    # A department in use cannot be deleted.
    assert api.delete(f"/api/v1/hrms/departments/{department['id']}").status_code == 409

    employee_id = first.json()["id"]
    component = next(c for c in api.get("/api/v1/hrms/lookups").json()["salary_components"] if c["code"] == "HRA")
    pay = api.post(f"/api/v1/hrms/employees/{employee_id}/salary", json={
        "effective_from": "2026-01-05", "basic_salary": 40000,
        "lines": [{"component_id": component["id"], "calc_type": "PERCENT_BASIC", "value": 45}]})
    assert pay.status_code == 201 and (pay.json()["gross"], pay.json()["allowances"]) == (58000, 18000)
    detail = api.get(f"/api/v1/hrms/employees/{employee_id}").json()
    assert detail["salary"]["gross"] == 58000 and len(detail["leave_balances"]) == 4

    listing = api.get("/api/v1/hrms/employees?search=ali").json()
    assert listing["total"] == 1 and listing["status_counts"] == {"ACTIVE": 2}
    left = api.post(f"/api/v1/hrms/employees/{employee_id}/separate", json={
        "status": "RESIGNED", "separation_date": "2026-09-30", "reason": "Moving abroad"})
    assert left.status_code == 200 and left.json()["status"] == "RESIGNED"
    # The CNIC is free again once its holder has left.
    assert api.post("/api/v1/hrms/employees", json={**body, "full_name": "Rehired"}).status_code == 201


def test_employee_form_fields_from_the_old_erp(api, hr, db):
    parent = api.post("/api/v1/hrms/departments", json={"name": "Operations"}).json()
    child = api.post("/api/v1/hrms/departments", json={"name": "Dispatch", "parent_id": parent["id"]}).json()
    other = api.post("/api/v1/hrms/departments", json={"name": "Finance"}).json()
    # Two levels only: no sub department of a sub department, and a
    # department that has sub departments cannot become one itself.
    deeper = api.post("/api/v1/hrms/departments", json={"name": "Night Dispatch", "parent_id": child["id"]})
    assert deeper.status_code == 400 and "itself a sub department" in deeper.json()["detail"]
    demote = api.put(f"/api/v1/hrms/departments/{parent['id']}", json={"name": "Operations", "parent_id": other["id"]})
    assert demote.status_code == 400 and "sub departments of its own" in demote.json()["detail"]
    assert api.delete(f"/api/v1/hrms/departments/{parent['id']}").status_code == 409      # still has Dispatch under it
    body = {
        "full_name": "Zain Abbas", "father_name": "Abbas Ali", "father_occupation": "Teacher", "mother_name": "Saima",
        "department_id": parent["id"], "sub_department_id": child["id"], "weekly_rest": "FRI",
        "orientation_done": True, "orientation_date": "2026-03-02", "orientation_remarks": "Completed",
        "eobi_registered": True, "eobi_number": "E-991", "group_insurance": True, "attendance_exempt": True,
        "address": "House 4, Street 9, Faisalabad",
        "joining_date": "2026-03-01", "employment_type": "PROBATION", "probation_months": 3,
        "probation_extend_months": 1, "probation_end_date": "2026-07-01", "is_confirmed": False,
        "vacancy_date": "2026-02-10", "mobile_allowed": False, "official_email": "zain@jezseem.com", "grade": "G-3",
        "late_allowed": True,
        "father_cnic": "33100-1111111-1", "cnic": "33100-2222222-3", "cnic_issue_date": "2020-01-15",
        "cnic_expiry": "2030-01-15", "nationality": "Pakistani", "date_of_birth": "1995-05-20",
        "birth_place": "Lahore", "gender": "MALE", "phone": "0300-1234567", "phone_landline": "041-2345678",
        "hepatitis_status": "Negative", "marital_status": "MARRIED", "caste": "Rajput", "children_count": 2,
        "religion": "MUSLIM",
        "provident_fund_allowed": True, "overtime_allowed": True, "payment_mode": "CASH", "handicap": "None",
        "mileage": 12.5, "fixed_fuel_amount": 8000, "taxable_salary": 70000, "overtime_salary": 0,
        "shift_premium": 1500, "annual_allowance": True, "gross_salary": 80000, "income_tax": 2500,
    }
    wrong = api.post("/api/v1/hrms/employees", json={**body, "sub_department_id": other["id"]})
    assert wrong.status_code == 400 and "not a sub department" in wrong.json()["detail"]
    created = api.post("/api/v1/hrms/employees", json=body)
    assert created.status_code == 201, created.text
    e = created.json()
    for key in ("father_occupation", "weekly_rest", "grade", "religion", "children_count", "probation_months",
                "official_email", "shift_premium", "fixed_fuel_amount"):
        assert e[key] == body[key], key
    assert e["sub_department"] == "Dispatch" and e["attendance_exempt"] and e["overtime_allowed"]

    # Gross Salary on a new employee starts the salary structure from the joining date.
    detail = api.get(f"/api/v1/hrms/employees/{e['id']}").json()
    assert (detail["salary"]["effective_from"], detail["salary"]["gross"], detail["salary"]["deductions"]) == (
        "2026-03-01", 80000, 2500)
    # ...and is not a second place to change pay afterwards.
    api.put(f"/api/v1/hrms/employees/{e['id']}", json={**body, "gross_salary": 999999})
    assert api.get(f"/api/v1/hrms/employees/{e['id']}").json()["salary"]["gross"] == 80000

    # Photo: stored on disk, replaced or removed through the same record.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    photo = api.post(f"/api/v1/hrms/employees/{e['id']}/photo", files={"file": ("me.png", png, "image/png")})
    assert photo.status_code == 200 and photo.json()["photo_path"] == f"employees/{e['id']}.png"
    assert api.post(f"/api/v1/hrms/employees/{e['id']}/photo",
                    files={"file": ("x.png", b"not an image", "image/png")}).status_code == 400
    assert api.delete(f"/api/v1/hrms/employees/{e['id']}/photo").status_code == 204

    # Without payroll access the confidential fields are neither shown nor changed.
    clerk = make_user(db, codes=["hrms.module.view", "hrms.employees.view", "hrms.employees.edit"], company=hr.company)
    api.state["user"] = clerk
    seen = api.get(f"/api/v1/hrms/employees/{e['id']}").json()
    assert "shift_premium" not in seen and "bank_name" not in seen and "payment_mode" not in seen
    assert seen["father_occupation"] == "Teacher"
    changed = api.put(f"/api/v1/hrms/employees/{e['id']}", json={**body, "shift_premium": 1, "caste": "Jutt"})
    assert changed.status_code == 200
    api.state["user"] = hr.admin
    after = api.get(f"/api/v1/hrms/employees/{e['id']}").json()
    assert after["shift_premium"] == 1500 and after["caste"] == "Jutt"


def test_payroll_api_and_downloads(api, hr, db):
    e = employee(hr, bank_name="MCB", bank_account_number="998877")
    salary(hr, e, 30000, HRA=12000)
    saved = api.put("/api/v1/hrms/attendance/daily", json={"work_date": "2026-09-01", "entries": [
        {"employee_id": str(e.id), "status": "ABSENT"}]})
    assert saved.status_code == 200 and saved.json()["saved"] == 1
    sheet = api.get("/api/v1/hrms/attendance/monthly?year=2026&month=9").json()
    assert sheet["rows"][0]["absent"] == 1 and sheet["rows"][0]["days"]["2026-09-06"] == "WEEKLY_OFF"

    run = api.post("/api/v1/hrms/payroll/runs", json={"year": 2026, "month": 9})
    assert run.status_code == 201, run.text
    run = run.json()
    assert run["total_net"] == 40600 and run["payslips"][0]["lines"][0]["code"] == "BASIC"
    slip_id = run["payslips"][0]["id"]
    added = api.post(f"/api/v1/hrms/payroll/payslips/{slip_id}/lines",
                     json={"kind": "DEDUCTION", "name": "Uniform", "amount": 600}).json()
    assert added["total_net"] == 40000

    assert api.get(f"/api/v1/hrms/payroll/payslips/{slip_id}/pdf").content[:4] == b"%PDF"
    assert api.get(f"/api/v1/hrms/payroll/runs/{run['id']}/payslips.pdf").content[:4] == b"%PDF"
    register = load_workbook(io.BytesIO(api.get(f"/api/v1/hrms/payroll/runs/{run['id']}/register").content))
    headers = [c.value for c in register.active[4]]
    assert headers[-1] == "Net Pay" and "Uniform" in headers and "Unpaid Days" in headers
    assert api.get(f"/api/v1/hrms/payroll/runs/{run['id']}/bank-sheet").content[:2] == b"PK"
    assert api.get("/api/v1/hrms/attendance/monthly/export?year=2026&month=9").content[:2] == b"PK"
    assert api.get("/api/v1/hrms/employees/export").content[:2] == b"PK"

    assert api.post(f"/api/v1/hrms/payroll/runs/{run['id']}/approve").json()["status"] == "APPROVED"
    locked = api.put("/api/v1/hrms/attendance/daily", json={"work_date": "2026-09-02", "entries": [
        {"employee_id": str(e.id), "status": "ABSENT"}]})
    assert locked.status_code == 409
    raise_in_month = api.post(f"/api/v1/hrms/employees/{e.id}/salary",
                              json={"effective_from": "2026-09-15", "basic_salary": 99999, "lines": []})
    assert raise_in_month.status_code == 409 and "after that date" in raise_in_month.json()["detail"]
    paid = api.post(f"/api/v1/hrms/payroll/runs/{run['id']}/pay", json={"payment_date": "2026-10-01"}).json()
    assert paid["status"] == "PAID"
    dashboard = api.get("/api/v1/hrms/dashboard").json()
    assert dashboard["headcount"] == 1 and dashboard["last_payroll"]["run_number"] == "PR-2026-09"


def test_leave_and_loan_api(api, hr, db):
    e = employee(hr)
    types = {t["code"]: t["id"] for t in api.get("/api/v1/hrms/lookups").json()["leave_types"]}
    preview = api.get(f"/api/v1/hrms/leave/preview?employee_id={e.id}&from_date=2026-09-04&to_date=2026-09-08").json()
    assert preview["days"] == 4
    request = api.post("/api/v1/hrms/leave/requests", json={
        "employee_id": str(e.id), "leave_type_id": types["SL"], "from_date": "2026-09-04", "to_date": "2026-09-08"})
    assert request.status_code == 201, request.text
    approved = api.post(f"/api/v1/hrms/leave/requests/{request.json()['id']}/approve", json={}).json()
    assert approved["status"] == "APPROVED" and approved["decided_by_name"]
    balances = api.get(f"/api/v1/hrms/leave/balances?year=2026&employee_id={e.id}").json()["rows"]
    sick = next(b for b in balances if b["leave_code"] == "SL")
    assert (sick["used"], sick["available"]) == (4, 4)
    adjusted = api.put(f"/api/v1/hrms/leave/balances/{sick['id']}", json={
        "entitled": 8, "carried_forward": 0, "adjustment": 2, "adjustment_note": "Granted by MD"}).json()
    assert next(b for b in adjusted if b["leave_code"] == "SL")["available"] == 6

    loan = api.post("/api/v1/hrms/loans", json={
        "employee_id": str(e.id), "kind": "LOAN", "loan_date": "2026-09-10", "amount": 30000,
        "installment_amount": 10000, "recovery_start": "2026-10-15"})
    assert loan.status_code == 201 and loan.json()["recovery_start"] == "2026-10-01"
    loan_id = loan.json()["id"]
    assert api.post(f"/api/v1/hrms/loans/{loan_id}/repay", json={"paid_on": "2026-09-20", "amount": 40000}).status_code == 400
    repaid = api.post(f"/api/v1/hrms/loans/{loan_id}/repay", json={"paid_on": "2026-09-20", "amount": 30000}).json()
    assert repaid["status"] == "SETTLED" and repaid["outstanding"] == 0
    assert api.post(f"/api/v1/hrms/loans/{loan_id}/cancel", json={"reason": "Entered twice"}).status_code == 409
    assert api.get("/api/v1/hrms/loans?status=ACTIVE").json()["items"] == []


def test_permissions_are_enforced(api, hr, db):
    e = employee(hr)
    salary(hr, e, 30000)
    clerk = make_user(db, codes=["hrms.module.view", "hrms.employees.view", "hrms.attendance.view"], company=hr.company)
    api.state["user"] = clerk
    assert api.get("/api/v1/hrms/employees").status_code == 200
    detail = api.get(f"/api/v1/hrms/employees/{e.id}").json()
    assert detail["can_see_pay"] is False and "salary" not in detail      # pay is hidden without payroll access
    assert api.get("/api/v1/hrms/dashboard").json()["last_payroll"] is None
    for method, path, body in [
        ("post", "/api/v1/hrms/employees", {"full_name": "X", "joining_date": "2026-01-01"}),
        ("get", f"/api/v1/hrms/employees/{e.id}/salary", None),
        ("put", "/api/v1/hrms/attendance/daily", {"work_date": "2026-09-01", "entries": []}),
        ("get", "/api/v1/hrms/payroll/runs", None),
        ("post", "/api/v1/hrms/payroll/runs", {"year": 2026, "month": 9}),
        ("post", "/api/v1/hrms/departments", {"code": "X", "name": "X"}),
        ("get", "/api/v1/hrms/loans", None),
        ("put", "/api/v1/hrms/settings", {}),
    ]:
        response = getattr(api, method)(path, json=body) if body is not None else getattr(api, method)(path)
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
