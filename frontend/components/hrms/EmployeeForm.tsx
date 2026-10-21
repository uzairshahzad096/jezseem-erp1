"use client";

import { useEffect, useRef, useState } from "react";
import { ImagePlus, X } from "lucide-react";
import { Field, Modal, Select, TextInput, Toggle } from "@/components/ui/Modal";
import { EmployeePicker } from "@/components/hrms/ui";
import { api } from "@/lib/api";
import { useAccountOptions } from "@/lib/finance";
import { errorText, fmtDate, label, mediaUrl, money, todayIso, type EmployeeDetail, type Employee, type Lookups } from "@/lib/hrms";

/**
 * The employee form, laid out as the previous ERP had it: Basic, Official,
 * Personal and Confidential information. The Confidential tab is shown only
 * to users with payroll access.
 */

type Value = string | boolean;
type Form = Record<string, Value>;
type Tab = "basic" | "official" | "personal" | "confidential";

const TEXT_FIELDS = [
  "employee_code", "full_name", "father_name", "father_occupation", "mother_name", "replacement_employee_id",
  "department_id", "sub_department_id", "designation_id", "weekly_rest", "shift_id", "manager_id", "branch_id",
  "orientation_date", "orientation_remarks", "eobi_number", "social_security_number", "address", "city", "user_id",
  "confirmation_date", "vacancy_date", "joining_date", "employment_type", "probation_months", "probation_extend_months",
  "probation_end_date", "official_email", "grade",
  "father_cnic", "cnic", "cnic_issue_date", "cnic_expiry", "ntn", "emergency_contact_name", "emergency_contact_phone",
  "nationality", "date_of_birth", "birth_place", "gender", "phone", "phone_landline", "email", "blood_group",
  "hepatitis_status", "marital_status", "caste", "children_count", "religion",
  "payment_mode", "bank_name", "bank_account_title", "bank_account_number", "iban", "ledger_account_id",
  "wages_account_id", "handicap", "mileage", "fixed_fuel_amount", "taxable_salary", "overtime_salary", "shift_premium",
  "resign_notice_start", "resign_notice_end", "notes",
] as const;
const FLAGS = [
  "orientation_done", "eobi_registered", "social_security_registered", "attendance_exempt", "group_insurance",
  "is_confirmed", "mobile_allowed", "late_allowed", "provident_fund_allowed", "overtime_allowed", "annual_allowance",
  "temporary_block",
] as const;
const CONFIDENTIAL = [
  "provident_fund_allowed", "overtime_allowed", "payment_mode", "bank_name", "bank_account_title", "bank_account_number",
  "iban", "ledger_account_id", "wages_account_id", "handicap", "mileage", "fixed_fuel_amount", "taxable_salary",
  "overtime_salary", "shift_premium", "annual_allowance",
];
const NUMBERS = ["probation_months", "probation_extend_months", "children_count", "mileage", "fixed_fuel_amount",
                 "taxable_salary", "overtime_salary", "shift_premium"];

const WEEKDAYS: [string, string][] = [["MON", "Monday"], ["TUE", "Tuesday"], ["WED", "Wednesday"], ["THU", "Thursday"],
                                      ["FRI", "Friday"], ["SAT", "Saturday"], ["SUN", "Sunday"]];
const MONTHS: [string, string][] = [["1", "1 month"], ["2", "2 months"], ["3", "3 months"], ["4", "4 months"],
                                    ["5", "5 months"], ["6", "6 months"], ["9", "9 months"], ["12", "12 months"]];
const YES_NO: [string, string][] = [["yes", "YES"], ["no", "NO"]];

const pick = (pairs: [string, string][]) => pairs.map(([value, text]) => ({ value, label: text }));

/** 3520212345671 -> 35202-1234567-1 as it is typed. */
const formatCnic = (raw: string): string => {
  const digits = raw.replace(/\D/g, "").slice(0, 13);
  return [digits.slice(0, 5), digits.slice(5, 12), digits.slice(12)].filter(Boolean).join("-");
};

/** 2026-03-01 + 3 months -> 2026-06-01 */
const addMonths = (iso: string, months: number): string => {
  const d = new Date(`${iso}T12:00:00`);
  d.setMonth(d.getMonth() + months);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function Check({ label: text, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-[12.5px]">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-primary" />
      {text}
    </label>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line">
      <h4 className="m-0 border-b border-line px-4 py-2.5 text-[13px] font-semibold">{title}</h4>
      <div className="grid grid-cols-2 gap-4 px-4 py-4 max-sm:grid-cols-1">{children}</div>
    </div>
  );
}

export function EmployeeForm({ employee, lookups, onClose, onSaved }: {
  employee: (Employee & Partial<EmployeeDetail>) | null; lookups: Lookups | null; onClose: () => void; onSaved: (saved: Employee) => void;
}) {
  const canPay = Boolean(lookups?.can_see_pay);
  const canEditPay = Boolean(lookups?.can_edit_pay);
  const accountOptions = useAccountOptions();
  const left = employee ? ["RESIGNED", "TERMINATED"].includes(employee.status) : false;

  const [f, setF] = useState<Form>(() => {
    const source = (employee ?? {}) as unknown as Record<string, unknown>;
    const start: Form = {};
    for (const key of TEXT_FIELDS) start[key] = source[key] == null ? "" : String(source[key]);
    for (const key of FLAGS) start[key] = Boolean(source[key]);
    start.active = employee ? employee.status !== "INACTIVE" : true;
    Object.assign(start, { gross_salary: "", income_tax: "", separation_type: "", quit_date: "", separation_reason: "" });
    if (!employee) {
      Object.assign(start, {
        employment_type: "PERMANENT", payment_mode: "CASH", joining_date: todayIso(), mobile_allowed: true,
        nationality: "Pakistani", religion: "MUSLIM", hepatitis_status: "Negative", gender: "MALE",
        weekly_rest: (lookups?.week_off_days ?? "SUN").split(",")[0] || "SUN",
      });
    }
    return start;
  });
  const [tab, setTab] = useState<Tab>("basic");
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(mediaUrl(employee?.photo_path));
  const [removePhoto, setRemovePhoto] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const str = (key: string) => String(f[key] ?? "");
  const on = (key: string) => Boolean(f[key]);
  const set = (key: string, value: Value) => setF((x) => ({ ...x, [key]: value }));

  // The probation end follows the joining date and the two periods; it can
  // still be typed over afterwards.
  const probationKey = `${str("joining_date")}|${str("probation_months")}|${str("probation_extend_months")}`;
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) { firstRun.current = false; return; }
    const months = (Number(str("probation_months")) || 0) + (Number(str("probation_extend_months")) || 0);
    if (str("joining_date") && months > 0) set("probation_end_date", addMonths(str("joining_date"), months));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [probationKey]);

  useEffect(() => {
    if (!photo) return;
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  const active = (rows: { id: string; name: string; is_active?: boolean }[] | undefined, current: string) =>
    (rows ?? []).filter((r) => r.is_active !== false || r.id === current).map((r) => ({ value: r.id, label: r.name }));
  const mainDepartments = (lookups?.departments ?? []).filter((d) => !d.parent_id || d.id === str("department_id"));
  const subDepartments = (lookups?.departments ?? []).filter((d) => d.parent_id && d.parent_id === str("department_id"));
  const grades = [...new Set((lookups?.designations ?? []).map((d) => d.grade).filter(Boolean) as string[])];

  /** The first thing still missing, with the tab it is on. Stars follow the previous ERP. */
  const missing = (): [Tab, string] | null => {
    const need = (tabName: Tab, key: string, text: string): [Tab, string] | null => (str(key).trim() ? null : [tabName, text]);
    const checks: ([Tab, string] | null)[] = [
      need("basic", "full_name", "Enter the employee's name."),
      need("basic", "father_name", "Enter the father's name."),
      need("basic", "department_id", "Choose the department."),
      subDepartments.length > 0 ? need("basic", "sub_department_id", "Choose the sub department.") : null,
      need("basic", "designation_id", "Choose the designation."),
      need("basic", "weekly_rest", "Choose the weekly rest day."),
      need("basic", "shift_id", (lookups?.shifts ?? []).length ? "Choose the shift." : "No shift exists yet. Add one in HR Setup → Shifts."),
      on("orientation_done") ? need("basic", "orientation_date", "Enter the orientation date.") : null,
      need("basic", "address", "Enter the permanent address."),
      need("official", "joining_date", "Enter the joining date."),
      on("is_confirmed") ? need("official", "confirmation_date", "Enter the confirmation date.") : null,
      str("employment_type") === "PROBATION" ? need("official", "probation_months", "Choose the probation period.") : null,
      str("employment_type") === "PROBATION" ? need("official", "probation_end_date", "Enter the probation end date.") : null,
      need("personal", "father_cnic", "Enter the father's CNIC."),
      need("personal", "cnic", "Enter the CNIC."),
      need("personal", "cnic_issue_date", "Enter the CNIC issue date."),
      need("personal", "cnic_expiry", "Enter the CNIC expiry date."),
      need("personal", "date_of_birth", "Enter the date of birth."),
      need("personal", "gender", "Choose the gender."),
      need("personal", "marital_status", "Choose the marital status."),
      !employee && canEditPay ? need("confidential", "gross_salary", "Enter the gross salary.") : null,
    ];
    for (const key of ["cnic", "father_cnic"]) {
      if (str(key) && str(key).replace(/\D/g, "").length !== 13) return ["personal", "A CNIC has 13 digits."];
    }
    const leaving = [str("separation_type"), str("quit_date"), str("separation_reason").trim()].filter(Boolean).length;
    if (leaving > 0 && leaving < 3) return ["confidential", "To record the employee leaving, fill in the separation type, quit date and reason."];
    return checks.find(Boolean) ?? null;
  };

  const save = async () => {
    const problem = missing();
    if (problem) { setTab(problem[0]); setError(problem[1]); return; }
    setSaving(true); setError(null);
    try {
      const body: Record<string, unknown> = {};
      for (const key of TEXT_FIELDS) body[key] = str(key) === "" ? null : NUMBERS.includes(key) ? Number(str(key)) : str(key);
      for (const key of FLAGS) body[key] = on(key);
      // Without payroll access these were never loaded; leaving them out
      // keeps what the record holds (the server ignores them anyway).
      if (!canEditPay) for (const key of CONFIDENTIAL) delete body[key];
      body.status = on("active") ? "ACTIVE" : "INACTIVE";
      if (!employee && canEditPay) {
        body.gross_salary = Number(str("gross_salary")) || null;
        body.income_tax = Number(str("income_tax")) || null;
      }
      const saved = employee
        ? await api.put<Employee>(`/hrms/employees/${employee.id}`, body)
        : await api.post<Employee>("/hrms/employees", body);
      // The record is saved; the steps after it report their own problem
      // rather than making the whole save look as if it failed.
      try {
        if (photo) await api.upload(`/hrms/employees/${saved.id}/photo`, photo);
        else if (removePhoto && employee?.photo_path) await api.del(`/hrms/employees/${saved.id}/photo`);
        if (!left && str("separation_type") && str("quit_date")) {
          await api.post(`/hrms/employees/${saved.id}/separate`, {
            status: str("separation_type"), separation_date: str("quit_date"), reason: str("separation_reason").trim() });
        }
      } catch (err) {
        window.alert(`${saved.employee_code} ${saved.full_name} was saved, but: ${errorText(err, "a follow-up step failed.")}`);
      }
      onSaved(saved);
    } catch (err) { setError(errorText(err, "Could not save the employee.")); } finally { setSaving(false); }
  };

  const text = (key: string, caption: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}, required = false) => (
    <Field label={caption} required={required}>
      <TextInput value={str(key)} onChange={(e) => set(key, e.target.value)} {...extra} />
    </Field>
  );
  const amount = (key: string, caption: string, required = false, disabled = false) => (
    <Field label={caption} required={required}>
      <TextInput value={str(key)} inputMode="decimal" placeholder="0" disabled={disabled}
        onChange={(e) => set(key, e.target.value.replace(/[^\d.]/g, ""))} />
    </Field>
  );
  const choose = (key: string, caption: string, options: { value: string; label: string }[], placeholder = "—", required = false, disabled = false) => (
    <Field label={caption} required={required}>
      <Select value={str(key)} placeholder={placeholder} disabled={disabled} onChange={(e) => set(key, e.target.value)} options={options} />
    </Field>
  );
  const yesNo = (key: string, caption: string, required = false, disabled = false) => (
    <Field label={caption} required={required}>
      <select value={on(key) ? "yes" : "no"} disabled={disabled} onChange={(e) => set(key, e.target.value === "yes")}
        className="w-full rounded-lg border border-line bg-bg px-3.5 py-2.5 text-[13px] outline-none focus:border-primary disabled:opacity-60">
        {YES_NO.map(([value, caption2]) => <option key={value} value={value}>{caption2}</option>)}
      </select>
    </Field>
  );
  const cnic = (key: string, caption: string) => (
    <Field label={caption} required>
      <TextInput value={str(key)} inputMode="numeric" placeholder="99999-9999999-9" onChange={(e) => set(key, formatCnic(e.target.value))} />
    </Field>
  );

  const tabs: [Tab, string][] = [["basic", "Basic Information"], ["official", "Official Information"], ["personal", "Personal Information"]];
  if (canPay) tabs.push(["confidential", "Confidential Information"]);
  const grid = "grid grid-cols-3 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1";
  const lockPay = !canEditPay;

  return (
    <Modal title={employee ? `Edit ${employee.employee_code} ${employee.full_name}` : "New employee"} open width="lg"
      saving={saving} error={error} onClose={onClose} onSave={save} saveLabel={employee ? "Save changes" : "Add employee"}>
      <div className="mb-5 flex flex-wrap gap-5 border-b border-line">
        {tabs.map(([key, caption]) => (
          <button key={key} type="button" onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-0.5 pb-2.5 text-[13.5px] transition-colors
                        ${tab === key ? "border-primary font-semibold text-primary" : "border-transparent text-muted hover:text-text"}`}>
            {caption}
          </button>
        ))}
      </div>

      {tab === "basic" && (
        <div className="flex gap-5 max-md:flex-col">
          <div className="min-w-0 flex-1 space-y-4">
            <div className={grid}>
              <Field label={employee ? "Employee Code" : "Employee Code (automatic)"}>
                <TextInput value={str("employee_code")} placeholder={employee ? "" : lookups?.next_employee_code ?? "Numbered automatically"}
                  onChange={(e) => set("employee_code", e.target.value.toUpperCase())} />
              </Field>
              {text("full_name", "Employee Name", {}, true)}
              <Field label="Replacement Code">
                <EmployeePicker includeLeft value={str("replacement_employee_id")} onChange={(id) => set("replacement_employee_id", id)}
                  lookups={lookups ? { ...lookups, employees: lookups.employees.filter((e) => e.id !== employee?.id) } : null}
                  placeholder="Employee this person replaces" />
              </Field>
              {text("father_name", "Father Name", {}, true)}
              {text("father_occupation", "Father Occupation")}
              {text("mother_name", "Mother Name")}
              <Field label="Department" required>
                <Select value={str("department_id")} placeholder="Choose…"
                  onChange={(e) => setF((x) => ({ ...x, department_id: e.target.value, sub_department_id: "" }))}
                  options={active(mainDepartments, str("department_id"))} />
              </Field>
              {choose("sub_department_id", "Sub Department", active(subDepartments, str("sub_department_id")),
                str("department_id") ? (subDepartments.length ? "Choose…" : "None under this department") : "Choose the department first",
                subDepartments.length > 0, subDepartments.length === 0)}
              {choose("designation_id", "Designation", active(lookups?.designations, str("designation_id")), "Choose…", true)}
              {choose("weekly_rest", "Weekly Rest", pick(WEEKDAYS), "Choose…", true)}
              {choose("shift_id", "Shift", active(lookups?.shifts, str("shift_id")), "Choose…", true)}
              <Field label="Reporting To">
                <EmployeePicker value={str("manager_id")} onChange={(id) => set("manager_id", id)}
                  lookups={lookups ? { ...lookups, employees: lookups.employees.filter((e) => e.id !== employee?.id) } : null}
                  placeholder="Nobody" />
              </Field>
            </div>
            <div className="flex flex-wrap items-center gap-x-7 gap-y-3 py-1">
              <Check label="Orientation" checked={on("orientation_done")} onChange={(v) => set("orientation_done", v)} />
              <Check label="EOBI" checked={on("eobi_registered")} onChange={(v) => set("eobi_registered", v)} />
              <Check label="Social Security" checked={on("social_security_registered")} onChange={(v) => set("social_security_registered", v)} />
              <Check label="Exempt for Attendance" checked={on("attendance_exempt")} onChange={(v) => set("attendance_exempt", v)} />
              <Check label="Group Insurance" checked={on("group_insurance")} onChange={(v) => set("group_insurance", v)} />
              {!left && (
                <label className="ml-auto flex items-center gap-2.5 text-[12.5px]">Status
                  <button type="button" role="switch" aria-checked={on("active")} onClick={() => set("active", !on("active"))}
                    title={on("active") ? "Active" : "Inactive: left out of attendance and payroll"}
                    className={`relative h-6 w-11 rounded-full transition-colors ${on("active") ? "bg-primary" : "bg-line"}`}>
                    <span className={`absolute left-0 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${on("active") ? "translate-x-[22px]" : "translate-x-0.5"}`} />
                  </button>
                </label>
              )}
            </div>
            <div className={grid}>
              {text("orientation_date", "Orientation Date", { type: "date", disabled: !on("orientation_done") }, on("orientation_done"))}
              {text("eobi_number", "EOBI #", { disabled: !on("eobi_registered") })}
              {text("social_security_number", "Social Security #", { disabled: !on("social_security_registered") })}
            </div>
            <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
              {text("orientation_remarks", "Orientation Remarks")}
              {text("address", "Permanent Address", {}, true)}
            </div>
            <div className={grid}>
              {text("city", "City")}
              {choose("branch_id", "Branch", active(lookups?.branches, str("branch_id")), "None")}
              {choose("user_id", "ERP Login", (lookups?.users ?? []).map((u) => ({ value: u.id, label: `${u.username} — ${u.name}` })), "No login")}
            </div>
          </div>

          <div className="w-[190px] flex-shrink-0 max-md:w-full">
            <button type="button" onClick={() => fileInput.current?.click()}
              className="flex h-[210px] w-full items-center justify-center overflow-hidden rounded-xl border border-dashed border-line bg-bg hover:border-primary">
              {preview && !removePhoto
                // eslint-disable-next-line @next/next/no-img-element
                ? <img src={preview} alt="Employee" className="h-full w-full object-cover" />
                : <span className="flex flex-col items-center gap-2 text-faint"><ImagePlus size={46} strokeWidth={1.3} /><span className="text-[11.5px]">Add photo</span></span>}
            </button>
            <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
              onChange={(e) => { const file = e.target.files?.[0]; if (file) { setPhoto(file); setRemovePhoto(false); } e.target.value = ""; }} />
            <div className="mt-1.5 flex items-center text-[11px] text-faint">
              <span>JPEG, PNG or WebP</span>
              {preview && !removePhoto && (
                <button type="button" onClick={() => { setPhoto(null); setPreview(null); setRemovePhoto(true); }}
                  className="ml-auto flex items-center gap-1 text-rose hover:underline"><X size={11} /> Remove</button>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === "official" && (
        <div className="space-y-4">
          <div className={grid}>
            {yesNo("is_confirmed", "Confirmation")}
            {text("confirmation_date", "Confirmation Date", { type: "date" }, on("is_confirmed"))}
            {text("vacancy_date", "Vacancy Date", { type: "date" })}
            {text("joining_date", "Joining Date", { type: "date" }, true)}
            {choose("employment_type", "Employee Type", pick([["PERMANENT", "PERMANENT"], ["PROBATION", "PROBATION"], ["CONTRACT", "CONTRACT"],
              ["INTERN", "INTERN"], ["DAILY_WAGE", "DAILY WAGE"]]), "Choose…", true)}
            {choose("probation_months", "Probation Period", pick(MONTHS), "None", str("employment_type") === "PROBATION")}
            {choose("probation_extend_months", "Probation Extend", pick(MONTHS), "None")}
            {text("probation_end_date", "Probation End Date", { type: "date" }, str("employment_type") === "PROBATION")}
            {yesNo("mobile_allowed", "Mobile Allow")}
            {text("official_email", "Official Email", { type: "email" })}
            <Field label="Employee Grade">
              <TextInput value={str("grade")} list="hr-grades" onChange={(e) => set("grade", e.target.value)} />
              <datalist id="hr-grades">{grades.map((g) => <option key={g} value={g} />)}</datalist>
            </Field>
          </div>
          <Toggle label="Late Allow" checked={on("late_allowed")} onChange={(v) => set("late_allowed", v)} />
          <p className="m-0 text-[11.5px] leading-relaxed text-faint">
            The probation end date is worked out from the joining date and the two periods, and can be typed over.
            With Late Allow on, late arrivals are still recorded but never cost this employee a day&apos;s pay.
          </p>
        </div>
      )}

      {tab === "personal" && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1">
            {cnic("father_cnic", "Father CNIC")}
            {cnic("cnic", "CNIC")}
            {text("cnic_issue_date", "CNIC Issue Date", { type: "date" }, true)}
            {text("cnic_expiry", "CNIC Expire Date", { type: "date" }, true)}
          </div>
          <div className={grid}>
            {text("ntn", "National Tax No")}
            {text("emergency_contact_phone", "Emergency No", { inputMode: "tel" })}
            <Field label="Nationality">
              <TextInput value={str("nationality")} list="hr-nationalities" onChange={(e) => set("nationality", e.target.value)} />
              <datalist id="hr-nationalities">{["Pakistani", "Afghan", "Bangladeshi", "Chinese", "Other"].map((n) => <option key={n} value={n} />)}</datalist>
            </Field>
            {text("date_of_birth", "Date Of Birth", { type: "date" }, true)}
            {text("birth_place", "Birth Place")}
            {choose("gender", "Gender", pick([["MALE", "Male"], ["FEMALE", "Female"], ["OTHER", "Other"]]), "Choose…", true)}
            {text("phone", "Mobile No", { inputMode: "tel", placeholder: "0300-1234567" })}
            {text("phone_landline", "Phone No", { inputMode: "tel", placeholder: "041-1234567" })}
            {text("email", "Personal Email", { type: "email" })}
            {choose("blood_group", "Blood Group", ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"].map((g) => ({ value: g, label: g })))}
            {choose("hepatitis_status", "Hepatitis", ["Negative", "Hepatitis B", "Hepatitis C", "Not tested"].map((h) => ({ value: h, label: h })))}
            {choose("marital_status", "Marital Status", pick([["SINGLE", "Single"], ["MARRIED", "Married"], ["DIVORCED", "Divorced"], ["WIDOWED", "Widowed"]]), "Choose…", true)}
            {text("caste", "Cast")}
            {text("children_count", "No. Of Children", { type: "number", min: 0 })}
            {choose("religion", "Religion", ["MUSLIM", "CHRISTIAN", "HINDU", "SIKH", "OTHER"].map((r) => ({ value: r, label: r })))}
            {text("emergency_contact_name", "Emergency Contact Name")}
          </div>
        </div>
      )}

      {tab === "confidential" && canPay && (
        <div className="space-y-4">
          {lockPay && (
            <p className="m-0 rounded-lg bg-amber/10 px-4 py-2.5 text-[12.5px]">
              You can see this tab but not change it: changing pay details needs the payroll edit permission.
            </p>
          )}
          <div className="grid grid-cols-[1.12fr_0.82fr_1.12fr] gap-4 max-lg:grid-cols-1">
            <Group title="Salary Detail">
              {yesNo("provident_fund_allowed", "Provident Fund Allow", true, lockPay)}
              {yesNo("overtime_allowed", "Overtime Allow", true, lockPay)}
              {choose("payment_mode", "Salary Mode", pick([["CASH", "CASH"], ["BANK", "BANK"], ["CHEQUE", "CHEQUE"]]), "Choose…", true, lockPay)}
              {text("bank_name", "Bank ABR", { disabled: lockPay, placeholder: "HBL, MCB, Meezan…" })}
              {text("bank_account_title", "Account Title", { disabled: lockPay })}
              {text("bank_account_number", "Account Number", { disabled: lockPay })}
              <div className="col-span-2 max-sm:col-span-1">{text("iban", "IBAN", { disabled: lockPay, placeholder: "PK00XXXX0000000000000000" })}</div>
              {choose("ledger_account_id", "Ledger Account", accountOptions, "None", false, lockPay)}
              {choose("wages_account_id", "Wages Account", accountOptions, "None", false, lockPay)}
              {text("handicap", "Handicap", { disabled: lockPay })}
              {employee ? (
                <Field label="Income Tax">
                  <TextInput disabled title="Deducted each month"
                    value={money((employee.salary?.lines ?? []).find((l) => l.code === "TAX")?.amount ?? 0)} />
                </Field>
              ) : amount("income_tax", "Income Tax", false, lockPay)}
              {amount("mileage", "Milage", false, lockPay)}
              {amount("fixed_fuel_amount", "Fixed Fuel Amount", false, lockPay)}
            </Group>

            <Group title="Salary Breakup">
              {employee ? (
                <Field label="Gross Salary">
                  <TextInput disabled value={employee.salary ? money(employee.salary.gross) : "Not entered"} />
                </Field>
              ) : amount("gross_salary", "Gross Salary", true, lockPay)}
              {amount("taxable_salary", "Taxable Salary", false, lockPay)}
              {amount("overtime_salary", "Overtime Salary", false, lockPay)}
              {amount("shift_premium", "Shift Premium", false, lockPay)}
              <div className="col-span-2 max-sm:col-span-1">
                <Check label="Annual Allowance" checked={on("annual_allowance")} onChange={(v) => !lockPay && set("annual_allowance", v)} />
              </div>
              <p className="col-span-2 m-0 text-[11.5px] leading-relaxed text-faint max-sm:col-span-1">
                {employee
                  ? "Gross salary and income tax are changed from the profile's Salary structure button, so every change keeps its date."
                  : "The gross salary becomes the employee's monthly salary from the joining date; income tax is deducted each month."}
              </p>
            </Group>

            <Group title="Resign Dismissed Detail">
              {text("resign_notice_start", "Resign Start", { type: "date" })}
              {text("resign_notice_end", "Resign End", { type: "date" })}
              {left ? (
                <>
                  <Field label="Separation Type"><TextInput disabled value={label(employee?.status)} /></Field>
                  <Field label="Quit Date"><TextInput disabled value={fmtDate(employee?.separation_date)} /></Field>
                </>
              ) : (
                <>
                  {choose("separation_type", "Separation Type", pick([["RESIGNED", "Resigned"], ["TERMINATED", "Dismissed / terminated"]]), "Still employed")}
                  {text("quit_date", "Quit Date", { type: "date" })}
                </>
              )}
              {yesNo("temporary_block", "Temporary Block")}
              <div className="col-span-2 max-sm:col-span-1">
                {left
                  ? <Field label="Reason"><TextInput disabled value={employee?.separation_reason ?? ""} /></Field>
                  : text("separation_reason", "Reason")}
              </div>
              <p className="col-span-2 m-0 text-[11.5px] leading-relaxed text-faint max-sm:col-span-1">
                {left ? "This employee has left. To undo it, use Reinstate on the profile."
                  : "Filling in the separation type, quit date and reason records the employee as having left on that date."}
              </p>
            </Group>
          </div>
        </div>
      )}
    </Modal>
  );
}
