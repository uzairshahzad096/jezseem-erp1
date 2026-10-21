"""
Payroll: a monthly run with one payslip per employee.

How a payslip is worked out, in the order it prints:

    Basic salary                       from the salary structure in force at month end
  + Allowances                         the structure's earning components
  + Overtime                           hours x (basic / (days x hours per day)) x multiplier,
                                       for employees with Overtime Allow switched on
  + Manual additions                   bonus, arrears… typed on the draft
  = Total earnings

    Deductions                         the structure's deduction components (tax, EOBI…)
  + Unpaid days                        days x (gross / days in month)
  + Late arrivals                      one day's pay per N lates, if the rule is on and the
                                       employee does not have Late Allow
  + Loan / advance instalments         never more than what is still owed
  + Manual deductions
  = Total deductions

    Net pay = total earnings − total deductions

"Gross" is basic plus allowances. Unpaid days are absences, unpaid leave,
half of each half day, and days in the month before joining or after
leaving. "Days" is the days in the month, or 30 when the company uses a
fixed 30-day basis.

A run is DRAFT until approved. A draft can be recalculated as often as
needed; manual lines survive. Approving records the loan recoveries and
locks the month's attendance and leave. Cancelling an approved run reverses
those recoveries. A paid run is final.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.hrms import models as m
from app.hrms.attendance import MonthSummary, employees_for, resolve_month
from app.hrms.calendar import month_bounds
from app.hrms.setup import get_settings

ZERO = Decimal(0)
CENT = Decimal("0.01")
HALF = Decimal("0.5")

# Print order of the lines on a payslip.
ORDER_BASIC, ORDER_EARNING, ORDER_OVERTIME, ORDER_MANUAL_EARNING = 10, 20, 60, 70
ORDER_DEDUCTION, ORDER_UNPAID, ORDER_LATE, ORDER_LOAN, ORDER_MANUAL_DEDUCTION = 110, 150, 155, 160, 170


def q(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def structure_on(db: Session, employee_id: uuid.UUID, on: date) -> m.SalaryStructure | None:
    """The salary structure in force on a date: the latest one that has started."""
    return db.scalar(select(m.SalaryStructure).options(selectinload(m.SalaryStructure.lines)).where(
        m.SalaryStructure.employee_id == employee_id, m.SalaryStructure.effective_from <= on)
        .order_by(m.SalaryStructure.effective_from.desc()).limit(1))


def component_amount(calc_type: str, value: Decimal, basic: Decimal) -> Decimal:
    return q(basic * value / 100) if calc_type == m.PERCENT_BASIC else q(value)


def structure_totals(db: Session, structure: m.SalaryStructure | None) -> dict:
    """Basic, allowances, deductions and gross for a structure, for display."""
    if structure is None:
        return {"basic": 0.0, "allowances": 0.0, "deductions": 0.0, "gross": 0.0, "net": 0.0}
    kinds = dict(db.execute(select(m.SalaryComponent.id, m.SalaryComponent.kind).where(
        m.SalaryComponent.id.in_([line.component_id for line in structure.lines] or [uuid.uuid4()]))).all())
    allowances = deductions = ZERO
    for line in structure.lines:
        amount = component_amount(line.calc_type, line.value, structure.basic_salary)
        if kinds.get(line.component_id) == m.EARNING:
            allowances += amount
        else:
            deductions += amount
    gross = structure.basic_salary + allowances
    return {"basic": float(structure.basic_salary), "allowances": float(allowances),
            "deductions": float(deductions), "gross": float(gross), "net": float(gross - deductions)}


def loan_outstanding(loan: m.Loan) -> Decimal:
    return loan.amount - sum((r.amount for r in loan.repayments if not r.is_reversed), ZERO)


# ------------------------------------------------------------------ calculation

def _build_payslip(db: Session, payslip: m.Payslip, employee: m.Employee, summary: MonthSummary,
                   run: m.PayrollRun, settings: m.HRSettings, components: dict, names: dict) -> None:
    manual = [line for line in payslip.lines if line.is_manual]
    payslip.lines = manual                      # computed lines are rebuilt from scratch
    warnings: list[str] = []
    days_in_period = (run.period_end - run.period_start).days + 1
    basis = Decimal(30) if settings.salary_days_basis == "FIXED_30" else Decimal(days_in_period)

    payslip.employee_code, payslip.employee_name = employee.employee_code, employee.full_name
    payslip.department = names["departments"].get(employee.department_id)
    payslip.designation = names["designations"].get(employee.designation_id)
    payslip.payment_mode = employee.payment_mode
    payslip.bank_name, payslip.bank_account_title = employee.bank_name, employee.bank_account_title
    payslip.bank_account_number = employee.iban or employee.bank_account_number

    structure = structure_on(db, employee.id, run.period_end)
    basic = structure.basic_salary if structure else ZERO
    if structure is None:
        warnings.append("No salary structure: nothing is paid until one is entered.")

    def add(code: str, name: str, kind: str, amount: Decimal, order: int, loan_id=None) -> Decimal:
        amount = q(amount)
        if amount > 0:
            payslip.lines.append(m.PayslipLine(code=code, name=name, kind=kind, amount=amount,
                                               sort_order=order, loan_id=loan_id))
        return max(amount, ZERO)

    gross = add("BASIC", "Basic Salary", m.EARNING, basic, ORDER_BASIC)
    fixed_deductions = ZERO
    for line in sorted(structure.lines if structure else [],
                       key=lambda x: components[x.component_id].sort_order if x.component_id in components else 0):
        component = components.get(line.component_id)
        if component is None:
            continue
        amount = component_amount(line.calc_type, line.value, basic)
        if component.kind == m.EARNING:
            gross += add(component.code, component.name, m.EARNING, amount, ORDER_EARNING)
        else:
            fixed_deductions += add(component.code, component.name, m.DEDUCTION, amount, ORDER_DEDUCTION)

    overtime_hours = (Decimal(summary.overtime_minutes) / 60).quantize(CENT)
    if overtime_hours > 0 and not employee.overtime_allowed:
        warnings.append(f"{overtime_hours:g} overtime hour(s) recorded but not paid: Overtime Allow is No on "
                        "the employee's record.")
    elif overtime_hours > 0 and settings.overtime_multiplier > 0 and basic > 0:
        hourly = basic / (basis * settings.hours_per_day)
        add("OT", f"Overtime ({overtime_hours:g} h x {settings.overtime_multiplier:g})", m.EARNING,
            overtime_hours * hourly * settings.overtime_multiplier, ORDER_OVERTIME)
    elif overtime_hours > 0 and settings.overtime_multiplier == 0:
        warnings.append(f"{overtime_hours:g} overtime hour(s) recorded but not paid: the overtime rate in "
                        "HR Settings is 0.")

    unpaid = summary.absent + summary.unpaid_leave + summary.not_employed
    per_day = gross / basis if basis else ZERO
    if unpaid > 0:
        parts = [(summary.absent, "absent"), (summary.unpaid_leave, "unpaid leave"),
                 (summary.not_employed, "not employed")]
        detail = ", ".join(f"{days:g} {label}" for days, label in parts if days > 0)
        add("UNPAID", f"Unpaid days ({detail})", m.DEDUCTION, min(per_day * unpaid, gross), ORDER_UNPAID)
    late_days = ZERO
    if (settings.lates_per_absence > 0 and summary.late_count >= settings.lates_per_absence
            and not employee.late_allowed):
        late_days = Decimal(summary.late_count // settings.lates_per_absence)
        add("LATE", f"Late arrivals ({summary.late_count} late = {late_days:g} day)", m.DEDUCTION,
            per_day * late_days, ORDER_LATE)

    loans = db.scalars(select(m.Loan).options(selectinload(m.Loan.repayments)).where(
        m.Loan.employee_id == employee.id, m.Loan.status == "ACTIVE",
        m.Loan.recovery_start <= run.period_end).order_by(m.Loan.loan_date))
    for loan in loans:
        owed = loan_outstanding(loan)
        if owed > 0:
            label = "Advance" if loan.kind == "ADVANCE" else "Loan"
            add("LOAN", f"{label} recovery {loan.loan_number}", m.DEDUCTION,
                min(loan.installment_amount, owed), ORDER_LOAN, loan_id=loan.id)

    payslip.days_in_period = days_in_period
    payslip.present_days, payslip.absent_days = summary.present, summary.absent
    payslip.paid_leave_days, payslip.unpaid_leave_days = summary.paid_leave, summary.unpaid_leave
    payslip.holidays, payslip.weekly_offs = summary.holidays, summary.weekly_offs
    payslip.not_employed_days, payslip.unmarked_days = summary.not_employed, summary.unmarked
    payslip.late_count = summary.late_count
    payslip.unpaid_days = unpaid + late_days
    payslip.overtime_hours = overtime_hours
    payslip.basic_salary, payslip.gross_salary = q(basic), q(gross)
    if summary.unmarked > 0:
        counted = "absent" if settings.unmarked_day_policy == "ABSENT" else "present"
        warnings.append(f"{summary.unmarked:g} working day(s) have no attendance and were counted as {counted}.")
    _total(payslip, warnings)


def _total(payslip: m.Payslip, warnings: list[str] | None = None) -> None:
    earnings = sum((line.amount for line in payslip.lines if line.kind == m.EARNING), ZERO)
    deductions = sum((line.amount for line in payslip.lines if line.kind == m.DEDUCTION), ZERO)
    payslip.total_earnings, payslip.total_deductions = q(earnings), q(deductions)
    payslip.net_pay = q(earnings - deductions)
    if warnings is None:
        warnings = [w for w in (payslip.warnings or "").split("\n") if w and not w.startswith("Net pay")]
    if payslip.net_pay < 0:
        warnings.append("Net pay is negative: the deductions are more than the earnings.")
    payslip.warnings = "\n".join(warnings) or None


def _total_run(run: m.PayrollRun) -> None:
    run.employee_count = len(run.payslips)
    run.total_earnings = q(sum((p.total_earnings for p in run.payslips), ZERO))
    run.total_deductions = q(sum((p.total_deductions for p in run.payslips), ZERO))
    run.total_net = q(sum((p.net_pay for p in run.payslips), ZERO))


def calculate(db: Session, run: m.PayrollRun, user_id: uuid.UUID | None) -> m.PayrollRun:
    """(Re)build every payslip of a draft run from today's data."""
    if run.status != "DRAFT":
        raise HTTPException(409, f"Payroll {run.run_number} is {run.status}; only a draft can be recalculated.")
    company_id = run.company_id
    settings = get_settings(db, company_id)
    employees = employees_for(db, company_id, run.period_start, run.period_end)
    summaries = resolve_month(db, company_id, run.period_start, run.period_end, employees)
    components = {c.id: c for c in db.scalars(select(m.SalaryComponent).where(
        m.SalaryComponent.company_id == company_id))}
    names = {
        "departments": dict(db.execute(select(m.Department.id, m.Department.name)
                                       .where(m.Department.company_id == company_id)).all()),
        "designations": dict(db.execute(select(m.Designation.id, m.Designation.name)
                                        .where(m.Designation.company_id == company_id)).all()),
    }
    existing = {p.employee_id: p for p in run.payslips}
    wanted = {e.id for e in employees}
    for employee_id, payslip in existing.items():
        if employee_id not in wanted:
            run.payslips.remove(payslip)
    for employee in employees:
        payslip = existing.get(employee.id)
        if payslip is None:
            payslip = m.Payslip(company_id=company_id, employee_id=employee.id, created_by=user_id,
                                employee_code=employee.employee_code, employee_name=employee.full_name)
            run.payslips.append(payslip)
        _build_payslip(db, payslip, employee, summaries[employee.id], run, settings, components, names)
        payslip.updated_by = user_id
    _total_run(run)
    run.updated_by = user_id
    db.flush()
    return run


def get_run(db: Session, company_id: uuid.UUID, run_id: uuid.UUID) -> m.PayrollRun:
    run = db.scalar(select(m.PayrollRun).options(
        selectinload(m.PayrollRun.payslips).selectinload(m.Payslip.lines)).where(m.PayrollRun.id == run_id))
    if run is None or run.company_id != company_id:
        raise HTTPException(404, "Payroll run not found.")
    return run


def generate(db: Session, company_id: uuid.UUID, year: int, month: int, user_id: uuid.UUID | None,
             notes: str | None = None, today: date | None = None) -> m.PayrollRun:
    start, end = month_bounds(year, month)
    today = today or date.today()
    if start > today:
        raise HTTPException(400, f"{start:%B %Y} has not started yet.")
    live = db.scalar(select(m.PayrollRun).where(
        m.PayrollRun.company_id == company_id, m.PayrollRun.period_year == year,
        m.PayrollRun.period_month == month, m.PayrollRun.status != "CANCELLED"))
    if live is not None:
        raise HTTPException(409, f"Payroll {live.run_number} already exists for {start:%B %Y} ({live.status}).")
    earlier = db.scalar(select(func.count()).select_from(m.PayrollRun).where(
        m.PayrollRun.company_id == company_id, m.PayrollRun.period_year == year,
        m.PayrollRun.period_month == month)) or 0
    number = f"PR-{year}-{month:02d}" + (f"-{earlier + 1}" if earlier else "")
    run = m.PayrollRun(company_id=company_id, run_number=number, period_year=year, period_month=month,
                       period_start=start, period_end=end, status="DRAFT", notes=notes, created_by=user_id)
    db.add(run)
    db.flush()
    calculate(db, run, user_id)
    if not run.payslips:
        raise HTTPException(400, f"No employee was employed in {start:%B %Y}, so there is nothing to pay.")
    return run


# ------------------------------------------------------------------ manual lines

def _draft_payslip(db: Session, company_id: uuid.UUID, payslip_id: uuid.UUID) -> tuple[m.Payslip, m.PayrollRun]:
    payslip = db.scalar(select(m.Payslip).options(selectinload(m.Payslip.lines)).where(m.Payslip.id == payslip_id))
    if payslip is None or payslip.company_id != company_id:
        raise HTTPException(404, "Payslip not found.")
    run = get_run(db, company_id, payslip.run_id)
    if run.status != "DRAFT":
        raise HTTPException(409, f"Payroll {run.run_number} is {run.status}; its payslips can no longer change.")
    return payslip, run


def add_manual_line(db: Session, company_id: uuid.UUID, payslip_id: uuid.UUID, *, kind: str, name: str,
                    amount: Decimal, user_id: uuid.UUID | None) -> m.Payslip:
    payslip, run = _draft_payslip(db, company_id, payslip_id)
    if kind not in (m.EARNING, m.DEDUCTION):
        raise HTTPException(400, "A line is either an EARNING or a DEDUCTION.")
    if q(amount) <= 0:
        raise HTTPException(400, "Enter an amount greater than zero.")
    if not name.strip():
        raise HTTPException(400, "Say what the amount is for: it prints on the payslip.")
    payslip.lines.append(m.PayslipLine(
        code="ADJ", name=name.strip(), kind=kind, amount=q(amount), is_manual=True,
        sort_order=ORDER_MANUAL_EARNING if kind == m.EARNING else ORDER_MANUAL_DEDUCTION))
    payslip.updated_by = user_id
    _total(payslip)
    _total_run(run)
    db.flush()
    return payslip


def remove_manual_line(db: Session, company_id: uuid.UUID, payslip_id: uuid.UUID, line_id: uuid.UUID,
                       user_id: uuid.UUID | None) -> m.Payslip:
    payslip, run = _draft_payslip(db, company_id, payslip_id)
    line = next((x for x in payslip.lines if x.id == line_id), None)
    if line is None:
        raise HTTPException(404, "Line not found.")
    if not line.is_manual:
        raise HTTPException(409, "Only lines typed in by hand can be removed. Calculated lines follow the "
                                 "salary structure, attendance and loans: change those and recalculate.")
    payslip.lines.remove(line)
    payslip.updated_by = user_id
    _total(payslip)
    _total_run(run)
    db.flush()
    return payslip


# ------------------------------------------------------------------ workflow

def approve(db: Session, company_id: uuid.UUID, run_id: uuid.UUID, user_id: uuid.UUID | None) -> m.PayrollRun:
    run = get_run(db, company_id, run_id)
    if run.status != "DRAFT":
        raise HTTPException(409, f"Payroll {run.run_number} is {run.status}, not a draft.")
    negative = [p.employee_name for p in run.payslips if p.net_pay < 0]
    if negative:
        raise HTTPException(409, "Net pay is negative for " + ", ".join(negative[:5])
                            + ". Reduce the deductions (for example the loan instalment) before approving.")
    for payslip in run.payslips:
        for line in payslip.lines:
            if line.loan_id is None:
                continue
            loan = db.scalar(select(m.Loan).options(selectinload(m.Loan.repayments))
                             .where(m.Loan.id == line.loan_id))
            owed = loan_outstanding(loan)
            if loan.status != "ACTIVE" or line.amount > owed:
                raise HTTPException(409, f"Loan {loan.loan_number} changed after this payroll was calculated "
                                         f"(still owed: {owed:,.2f}). Recalculate the run, then approve.")
            loan.repayments.append(m.LoanRepayment(
                paid_on=run.period_end, amount=line.amount, source="PAYROLL", payslip_id=payslip.id,
                notes=f"Payroll {run.run_number}", created_by=user_id))
            if owed - line.amount <= 0:
                loan.status = "SETTLED"
    run.status = "APPROVED"
    run.approved_by, run.approved_at = user_id, datetime.now(timezone.utc)
    run.updated_by = user_id
    db.flush()
    return run


def mark_paid(db: Session, company_id: uuid.UUID, run_id: uuid.UUID, payment_date: date,
              user_id: uuid.UUID | None) -> m.PayrollRun:
    run = get_run(db, company_id, run_id)
    if run.status != "APPROVED":
        raise HTTPException(409, f"Payroll {run.run_number} is {run.status}; approve it before paying.")
    run.status = "PAID"
    run.payment_date = payment_date
    run.paid_by, run.paid_at = user_id, datetime.now(timezone.utc)
    run.updated_by = user_id
    db.flush()
    return run


def cancel(db: Session, company_id: uuid.UUID, run_id: uuid.UUID, reason: str,
           user_id: uuid.UUID | None) -> m.PayrollRun:
    run = get_run(db, company_id, run_id)
    if run.status == "PAID":
        raise HTTPException(409, f"Payroll {run.run_number} has been paid and is final.")
    if run.status == "CANCELLED":
        raise HTTPException(409, f"Payroll {run.run_number} is already cancelled.")
    if not (reason or "").strip():
        raise HTTPException(400, "Give a reason for cancelling the payroll run.")
    if run.status == "APPROVED":
        payslip_ids = [p.id for p in run.payslips]
        for repayment in db.scalars(select(m.LoanRepayment).where(
                m.LoanRepayment.payslip_id.in_(payslip_ids), m.LoanRepayment.is_reversed.is_(False))):
            repayment.is_reversed = True
            repayment.notes = f"{repayment.notes or ''} (reversed: run cancelled)".strip()
            loan = db.get(m.Loan, repayment.loan_id)
            if loan.status == "SETTLED":
                loan.status = "ACTIVE"
    run.status = "CANCELLED"
    run.cancel_reason = reason.strip()
    run.updated_by = user_id
    db.flush()
    return run
