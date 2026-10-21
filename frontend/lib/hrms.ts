"use client";

import { useFinance } from "@/lib/finance";

export { download, errorText, fmtDate, fmtDateTime, money } from "@/lib/finance";

/** GET an HR endpoint with loading / error state and a reload. */
export const useHr = useFinance;

/* ---------------------------------------------------------------- types */

export interface Option { id: string; code: string; name: string; is_active?: boolean }

export interface Lookups {
  /** The code the next new employee gets if none is typed: JT-0001, JT-0002… */
  next_employee_code: string;
  can_see_pay: boolean;
  can_edit_pay: boolean;
  /** The company's weekly rest day(s), e.g. "SUN": the default for a new employee. */
  week_off_days: string;
  departments: (Option & { parent_id: string | null })[];
  designations: (Option & { grade: string | null })[];
  shifts: Option[];
  leave_types: (Option & { is_paid: boolean; annual_days: number })[];
  salary_components: (Option & { kind: "EARNING" | "DEDUCTION"; calc_type: CalcType; default_value: number })[];
  branches: Option[];
  employees: { id: string; code: string; name: string; status: string }[];
  users: { id: string; username: string; name: string }[];
}

export type CalcType = "FIXED" | "PERCENT_BASIC";

export interface Employee {
  id: string;
  employee_code: string;
  full_name: string;
  father_name: string | null;
  gender: string | null;
  date_of_birth: string | null;
  marital_status: string | null;
  blood_group: string | null;
  cnic: string | null;
  cnic_expiry: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  city: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  branch_id: string | null;
  department_id: string | null;
  designation_id: string | null;
  shift_id: string | null;
  manager_id: string | null;
  employment_type: string;
  joining_date: string;
  probation_end_date: string | null;
  confirmation_date: string | null;
  status: "ACTIVE" | "INACTIVE" | "RESIGNED" | "TERMINATED";
  separation_date: string | null;
  separation_reason: string | null;
  payment_mode: string;
  bank_name: string | null;
  bank_account_title: string | null;
  bank_account_number: string | null;
  iban: string | null;
  ntn: string | null;
  eobi_number: string | null;
  social_security_number: string | null;
  user_id: string | null;
  notes: string | null;
  department: string | null;
  designation: string | null;
  shift: string | null;
  branch: string | null;
  // Fields carried over from the previous ERP's form
  replacement_employee_id: string | null;
  father_occupation: string | null;
  mother_name: string | null;
  sub_department_id: string | null;
  sub_department: string | null;
  weekly_rest: string | null;
  orientation_done: boolean;
  orientation_date: string | null;
  orientation_remarks: string | null;
  eobi_registered: boolean;
  social_security_registered: boolean;
  attendance_exempt: boolean;
  group_insurance: boolean;
  photo_path: string | null;
  is_confirmed: boolean;
  vacancy_date: string | null;
  probation_months: number | null;
  probation_extend_months: number | null;
  mobile_allowed: boolean;
  official_email: string | null;
  grade: string | null;
  late_allowed: boolean;
  father_cnic: string | null;
  cnic_issue_date: string | null;
  nationality: string | null;
  birth_place: string | null;
  phone_landline: string | null;
  hepatitis_status: string | null;
  caste: string | null;
  children_count: number | null;
  religion: string | null;
  resign_notice_start: string | null;
  resign_notice_end: string | null;
  temporary_block: boolean;
  // Confidential: present only for users with payroll access
  provident_fund_allowed?: boolean;
  overtime_allowed?: boolean;
  ledger_account_id?: string | null;
  wages_account_id?: string | null;
  handicap?: string | null;
  mileage?: number | null;
  fixed_fuel_amount?: number | null;
  taxable_salary?: number | null;
  overtime_salary?: number | null;
  shift_premium?: number | null;
  annual_allowance?: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

/** Where the browser loads an uploaded file from, given its storage key. */
export const mediaUrl = (key: string | null | undefined): string | null =>
  key ? `${API_BASE.replace(/\/api\/v1\/?$/, "")}/media/${key}` : null;

export interface SalaryLine {
  component_id: string; code: string | null; name: string | null; kind: "EARNING" | "DEDUCTION" | null;
  calc_type: CalcType; value: number; amount: number;
}

export interface Salary {
  id: string; effective_from: string; basic_salary: number; remarks: string | null; lines: SalaryLine[];
  basic: number; allowances: number; deductions: number; gross: number; net: number;
}

export interface LeaveBalance {
  id: string; employee_id: string; employee_code: string; employee_name: string; leave_type_id: string;
  leave_type: string; leave_code: string; is_paid: boolean; year: number; entitled: number;
  carried_forward: number; adjustment: number; adjustment_note: string | null; used: number;
  pending: number; available: number;
}

export interface Loan {
  id: string; loan_number: string; employee_id: string; employee_code: string | null;
  employee_name: string | null; kind: "ADVANCE" | "LOAN"; loan_date: string; amount: number;
  installment_amount: number; recovery_start: string; status: "ACTIVE" | "SETTLED" | "CANCELLED";
  notes: string | null; outstanding: number; recovered: number;
  repayments: { id: string; paid_on: string; amount: number; source: string; is_reversed: boolean; notes: string | null }[];
}

export interface EmployeeDetail extends Employee {
  manager: string | null;
  replacement: string | null;
  leave_balances: LeaveBalance[];
  can_see_pay: boolean;
  salary?: Salary | null;
  loans?: Loan[];
}

export interface LeaveRequest {
  id: string; request_number: string; employee_id: string; employee_code: string | null;
  employee_name: string | null; leave_type_id: string; leave_type: string | null; is_paid: boolean | null;
  from_date: string; to_date: string; half_day: boolean; days: number; reason: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED" | "CANCELLED"; decided_by_name: string | null;
  decided_at: string | null; decision_note: string | null; created_at: string;
}

export interface PayslipLine {
  id: string; code: string; name: string; kind: "EARNING" | "DEDUCTION"; amount: number; is_manual: boolean;
}

export interface Payslip {
  id: string; employee_id: string; employee_code: string; employee_name: string; department: string | null;
  designation: string | null; payment_mode: string; bank_name: string | null; bank_account_number: string | null;
  days_in_period: number; present_days: number; absent_days: number; paid_leave_days: number;
  unpaid_leave_days: number; holidays: number; weekly_offs: number; not_employed_days: number;
  unmarked_days: number; late_count: number; unpaid_days: number; overtime_hours: number;
  basic_salary: number; gross_salary: number; total_earnings: number; total_deductions: number;
  net_pay: number; warnings: string[]; lines: PayslipLine[];
}

export interface PayrollRun {
  id: string; run_number: string; period: string; period_year: number; period_month: number;
  period_start: string; period_end: string; status: "DRAFT" | "APPROVED" | "PAID" | "CANCELLED";
  employee_count: number; total_earnings: number; total_deductions: number; total_net: number;
  approved_by_name: string | null; approved_at: string | null; paid_by_name: string | null;
  paid_at: string | null; payment_date: string | null; cancel_reason: string | null; notes: string | null;
}

export interface PayrollRunDetail extends PayrollRun { payslips: Payslip[]; warning_count: number }

/* ---------------------------------------------------------------- display */

const TONE: Record<string, string> = {
  ACTIVE: "bg-success/15 text-success",
  INACTIVE: "bg-hover text-muted",
  RESIGNED: "bg-amber/15 text-amber",
  TERMINATED: "bg-rose/10 text-rose",
  PENDING: "bg-amber/15 text-amber",
  APPROVED: "bg-success/15 text-success",
  REJECTED: "bg-rose/10 text-rose",
  CANCELLED: "bg-hover text-faint",
  DRAFT: "bg-hover text-muted",
  PAID: "bg-sky/15 text-sky",
  SETTLED: "bg-sky/15 text-sky",
  EARNING: "bg-success/15 text-success",
  DEDUCTION: "bg-rose/10 text-rose",
};

export const hrTone = (status: string) => TONE[status] ?? "bg-hover text-muted";

/** PERMANENT -> Permanent, DAILY_WAGE -> Daily wage. */
export const label = (value: string | null | undefined): string =>
  value ? value.charAt(0) + value.slice(1).toLowerCase().replace(/_/g, " ") : "—";

export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];

export const todayIso = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};

/** 1.5 -> "1.5", 2 -> "2". */
export const days = (n: number | null | undefined): string =>
  typeof n === "number" ? String(Math.round(n * 100) / 100) : "0";

/** Attendance statuses as the sheet shows them. A leading "~" (a working day
 *  nobody marked, counted by the company's policy) is shown faded. */
export const ATTENDANCE: Record<string, { short: string; name: string; tone: string }> = {
  PRESENT: { short: "P", name: "Present", tone: "bg-success/15 text-success" },
  LATE: { short: "L", name: "Late", tone: "bg-amber/20 text-amber" },
  HALF_DAY: { short: "HD", name: "Half day", tone: "bg-violet/15 text-violet" },
  ABSENT: { short: "A", name: "Absent", tone: "bg-rose/15 text-rose" },
  LEAVE: { short: "LV", name: "On leave", tone: "bg-sky/15 text-sky" },
  HOLIDAY: { short: "H", name: "Holiday", tone: "bg-hover text-muted" },
  WEEKLY_OFF: { short: "WO", name: "Rest day", tone: "bg-hover text-faint" },
};
