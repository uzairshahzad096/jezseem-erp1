# HRMS: what it does and the rules it follows

Written for whoever runs HR and payroll in the ERP, and for the developer who
maintains it. The screens are under **HRMS** in the sidebar; the code is in
`backend/app/hrms` and `frontend/app/hrms`.

## The screens

| Screen | What it is for |
|---|---|
| Dashboard | Headcount, today's attendance, what needs attention, last payroll |
| Employees | The employee file: personal, job, bank details, salary structure, leaving |
| Attendance | Mark a day for everyone; review a month |
| Leave | Requests, approvals, and each employee's balance for the year |
| Loans & Advances | Money given to employees and how it is being recovered |
| Payroll | One run per month: calculate, review, approve, pay |
| HR Setup | Departments, designations, shifts, holidays, leave types, salary components, HR settings |

## Getting started

1. **HR Setup → Add standard lists.** Adds the usual departments, designations,
   one general shift (9 to 6, Monday to Saturday), four leave types and seven
   salary components. Every amount is zero. Edit or delete what does not fit.
2. **HR Setup → HR settings.** Decide the weekly rest day, whether an unmarked
   working day counts as present or absent, the overtime rate and the lateness
   rule.
3. **Employees → New employee** for each person, then **Salary structure** on
   their profile.
4. Mark attendance and enter leave as the month goes.
5. **Payroll → Run payroll** after the month ends.

## Rules

### Nothing is assumed about money

No tax slab, EOBI amount, overtime rate or lateness penalty is built in. Income
tax, EOBI and provident fund are salary components whose amount is entered on
each employee's salary structure. Overtime is recorded but not paid until an
overtime rate is set. Lateness costs nothing until the rule is switched on.

### The employee form

The form follows the previous ERP: **Basic**, **Official**, **Personal** and
**Confidential** information, with the photo on the Basic tab. Required fields
are the ones the previous ERP starred.

- **Employee code** is numbered automatically (JT-0001, JT-0002…); the prefix
  and digits are in HR settings.
- **Sub Department** lists the departments whose "Part of" is the chosen
  department (set in HR Setup → Departments).
- **Weekly Rest** is the employee's own rest day. It comes before the shift's
  working days and the company's rest days.
- **Exempt for Attendance**: a working day without a mark is always present,
  and the employee is never listed as "not marked".
- **Late Allow**: late arrivals are recorded but never cost a day's pay.
- **Overtime Allow**: overtime hours are paid only when this is Yes.
- **Probation End Date** is worked out from the joining date plus the
  probation period and extension, and can be typed over.
- **Confidential tab** is shown only with `hrms.payroll.view` and changed only
  with `hrms.payroll.edit`. Without them the fields are neither sent to the
  browser nor changed by a save.
- **Gross Salary and Income Tax** on a *new* employee start the salary
  structure from the joining date (the gross as the monthly salary, the tax as
  a monthly deduction). Afterwards they are read-only on the form and changed
  through Salary structure, so there is one place pay is changed and every
  change keeps its date.
- **Separation Type, Quit Date and Reason**, filled in together, record the
  employee as having left on that date.

Stored for the record but **not used in any calculation yet**: Provident Fund
Allow, Group Insurance, Mobile Allow, Temporary Block, Handicap, Milage, Fixed
Fuel Amount, Taxable Salary, Overtime Salary, Shift Premium, Annual Allowance,
Ledger Account and Wages Account. What each should do in payroll or accounting
is for the business to confirm.

### Salary structure

- Basic salary plus any components, each a fixed amount or a percentage of basic.
- A raise is a **new entry with a later date**; earlier entries stay as history.
- Saving the same date again corrects that entry.
- A structure cannot start inside a month whose payroll is already approved.
- The structure in force **on the last day of the month** is used for the whole
  month. A mid-month raise is not split; add the difference as arrears on the
  payslip if it should apply to part of the month.
- Salary is visible only to users with the `hrms.payroll.view` permission.

### Attendance

- One mark per employee per day: Present, Late, Half day, Absent, Holiday, Rest day.
- Holidays and weekly rest days need no marking; the calendar knows them.
- With clock times entered, arriving after the shift's grace period becomes
  **Late** automatically, and time worked beyond the shift is overtime.
  Overtime is only counted when both clock-in and clock-out are entered.
- Leave is never marked on the attendance sheet; it comes from approved leave
  requests.
- An employee marked **Inactive** is left out of attendance and payroll.

### Leave

- `available = entitlement + carried forward + adjustment − approved days`
- A request charges **working days only**: weekly rest days and holidays inside
  the range are free.
- A paid request cannot exceed the balance (pending requests count against it).
  Unpaid leave has no limit and is deducted from salary.
- Approving writes the leave days into attendance. Cancelling an approved
  request removes them and returns the days.
- A request cannot cross a year end, because each year has its own balance.
- Balances are created per calendar year from the leave types the first time
  they are needed. Unused days carry forward only for types set to carry
  forward, up to that type's limit.

### Payroll

How a payslip is worked out:

```
  Basic salary
+ Allowances                 from the salary structure
+ Overtime                   hours × (basic ÷ (days × hours per day)) × overtime rate
+ Manual additions           bonus, arrears… typed on the draft
= Total earnings

  Deductions                 from the salary structure (tax, EOBI…)
+ Unpaid days                days × (gross ÷ days)
+ Late arrivals              one day's pay per N lates, if the rule is on
+ Loan / advance instalment  never more than what is still owed
+ Manual deductions
= Total deductions

  Net pay = total earnings − total deductions
```

- **Gross** is basic plus allowances.
- **Unpaid days** are absences, unpaid leave, half of each half day, and days in
  the month before the joining date or after the last working day.
- **Days** is the days in the month, or 30 if HR settings say so.
- A working day nobody marked follows the HR setting (present or absent) and is
  flagged on the payslip so it can be seen.
- Days of the month that have not happened yet are paid in full.

The run's life:

| Status | What can happen |
|---|---|
| Draft | Recalculate as often as needed (manual lines are kept), add one-off lines, approve, cancel |
| Approved | Figures fixed. Loan instalments recorded as recovered. The month's attendance and leave are locked. Mark as paid, or cancel |
| Paid | Final |
| Cancelled | Kept on record. An approved run's loan recoveries are reversed and the month unlocked; the month can be run again |

A run with a negative net pay on any payslip cannot be approved.

### Loans and advances

- Outstanding = amount − repayments. It is never stored as an editable balance.
- Each payroll deducts one instalment from the recovery start month onward.
- "Repayment" records money paid back outside payroll.
- A loan with repayments cannot be cancelled; settle it instead.

## Downloads

| File | From |
|---|---|
| Employees (Excel) | Employees → Export to Excel |
| Monthly attendance (Excel) | Attendance → Monthly sheet → Excel |
| Salary sheet (Excel): one row per employee, one column per pay line | Payroll run → Salary sheet |
| Payment list (Excel): bank transfers first, then cheque and cash | Payroll run → Payment list |
| Payslips (PDF): one or all | Payroll run → All payslips, or a payslip → Payslip PDF |

## Permissions

`hrms.module.view` opens the module. Each area has its own codes:
`hrms.employees.*`, `hrms.attendance.*`, `hrms.leave.*`, `hrms.loans.*`,
`hrms.payroll.*`, `hrms.setup.*`.

| To do this | Needs |
|---|---|
| See salary structures, payslips and loans | `hrms.payroll.view` (loans: `hrms.loans.view`) |
| Change a salary structure, recalculate a run, add a payslip line | `hrms.payroll.edit` |
| Run payroll / approve / mark paid / cancel | `hrms.payroll.create` / `.approve` / `.post` / `.cancel` |
| Approve or reject leave | `hrms.leave.approve` |
| Change setup lists and HR settings | `hrms.setup.edit` |

Every change to an employee, salary, leave decision, loan or payroll run is
written to the audit log (`Security → Audit Logs`, module `hrms`).

## Not in this version

- **Accounting.** Payroll and loans do not post to the general ledger. How
  salaries should post (which expense and payable accounts, and whether
  advances use account 1160 Advances to Employees) is an open accounting
  decision, listed in `docs/finance/00-finance-discovery.md`.
- **Biometric import.** Attendance is marked on screen; there is no import
  from an attendance machine yet.
- **Employee self-service.** Leave is entered by HR on the employee's behalf.
- **Income tax calculation, final settlement, gratuity and documents.** Tax is
  an amount entered per employee; nothing is computed from slabs.

## Decisions for the business to confirm

- Leave entitlements added by "Add standard lists" (14 annual, 10 casual,
  8 sick) are common practice, not this company's policy.
- The weekly rest day (Sunday) and the general shift's hours.
- Whether an unmarked day is present (default) or absent.
- The overtime rate and the lateness rule, both off by default.
