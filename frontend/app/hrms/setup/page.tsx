"use client";

import { useEffect, useState } from "react";
import { Pencil, Plus, Sparkles } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, Select, TextInput, Toggle } from "@/components/ui/Modal";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, Card, EmptyState, ErrorNote, PageHeader, Spinner } from "@/components/finance/ui";
import { HrBadge, Tabs } from "@/components/hrms/ui";
import { api } from "@/lib/api";
import { errorText, fmtDate, label, useHr, type Lookups } from "@/lib/hrms";

const TABS = [
  ["departments", "Departments"], ["sub-departments", "Sub departments"], ["designations", "Designations"], ["shifts", "Shifts"],
  ["holidays", "Holidays"], ["leave-types", "Leave types"], ["salary-components", "Salary components"],
  ["settings", "HR settings"],
] as const;
type Tab = (typeof TABS)[number][0];
type Row = Record<string, unknown>;

const WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];

/** Column and form definitions for each setup list. */
type FieldDef = {
  key: string; label: string; kind?: "text" | "number" | "time" | "date" | "toggle" | "days" | "select";
  required?: boolean; options?: [string, string][]; numeric?: boolean; hideInGrid?: boolean;
  show?: (value: unknown, row: Row) => React.ReactNode;
};

const yesNo = (v: unknown) => (v ? "Yes" : "");

type ListDef = {
  title: string; note?: string; fresh: Row; fields: FieldDef[];
  /** The endpoint, where it differs from the tab's own name. */
  api?: string;
  /** Which of the endpoint's rows belong on this tab. */
  only?: (row: Row) => boolean;
  empty?: string;
};

// Departments and sub departments are one table: a sub department is a
// department that is part of another. Each gets its own tab, as the previous
// ERP had them.
const DEFS: Record<Exclude<Tab, "settings">, ListDef> = {
  departments: {
    title: "Departments", fresh: { code: "", name: "", parent_id: null, head_id: null, is_active: true },
    only: (row) => !row.parent_id,
    fields: [{ key: "name", label: "Department", required: true }, { key: "code", label: "Code" },
             { key: "head_id", label: "Head of department", kind: "select" }],
  },
  "sub-departments": {
    title: "Sub departments", api: "departments", only: (row) => Boolean(row.parent_id),
    fresh: { code: "", name: "", parent_id: null, head_id: null, is_active: true },
    empty: "No sub departments yet. Add one and choose the department it belongs to.",
    note: "A sub department belongs to one department. On the employee form, Sub Department lists the ones under the chosen department.",
    fields: [{ key: "name", label: "Sub Department", required: true },
             { key: "parent_id", label: "Department", kind: "select", required: true },
             { key: "code", label: "Code" }, { key: "head_id", label: "Head", kind: "select" }],
  },
  designations: {
    title: "Designations", fresh: { code: "", name: "", grade: "", is_active: true },
    fields: [{ key: "code", label: "Code" }, { key: "name", label: "Name", required: true },
             { key: "grade", label: "Grade" }],
  },
  shifts: {
    title: "Shifts",
    note: "Arriving within the grace period still counts as on time. Days that are not working days are the shift's weekly rest days.",
    fresh: { code: "", name: "", start_time: "09:00", end_time: "18:00", grace_minutes: 15, break_minutes: 60,
             working_days: "MON,TUE,WED,THU,FRI,SAT", is_active: true },
    fields: [{ key: "code", label: "Code" }, { key: "name", label: "Name", required: true },
             { key: "start_time", label: "Starts", kind: "time", required: true },
             { key: "end_time", label: "Ends", kind: "time", required: true },
             { key: "grace_minutes", label: "Grace (min)", kind: "number", numeric: true },
             { key: "break_minutes", label: "Break (min)", kind: "number", numeric: true },
             { key: "working_days", label: "Working days", kind: "days",
               show: (v) => String(v ?? "").split(",").map((d) => d.charAt(0) + d.slice(1).toLowerCase()).join(" ") }],
  },
  holidays: {
    title: "Holidays", note: "A holiday is a paid day off for everyone and is never charged to a leave balance.",
    fresh: { holiday_date: "", name: "" },
    fields: [{ key: "holiday_date", label: "Date", kind: "date", required: true, show: (v) => fmtDate(String(v)) },
             { key: "name", label: "Holiday", required: true }],
  },
  "leave-types": {
    title: "Leave types",
    note: "Days per year is each employee's entitlement for a calendar year. Changing it affects years whose balances have not been created yet; existing balances are adjusted on the Leave screen.",
    fresh: { code: "", name: "", annual_days: 0, is_paid: true, carry_forward: false, max_carry_days: 0, sort_order: 100, is_active: true },
    fields: [{ key: "code", label: "Code" }, { key: "name", label: "Name", required: true },
             { key: "annual_days", label: "Days per year", kind: "number", numeric: true },
             { key: "is_paid", label: "Paid", kind: "toggle", show: yesNo },
             { key: "carry_forward", label: "Carries forward", kind: "toggle", show: yesNo },
             { key: "max_carry_days", label: "Max carried days", kind: "number", numeric: true },
             { key: "sort_order", label: "Sort order", kind: "number", hideInGrid: true }],
  },
  "salary-components": {
    title: "Salary components",
    note: "Allowances and deductions that can be put on an employee's salary structure. Basic salary, overtime, unpaid days and loan recovery are worked out by payroll and are not listed here. The default is only what the salary form starts from; the amount is set per employee.",
    fresh: { code: "", name: "", kind: "EARNING", calc_type: "FIXED", default_value: 0, sort_order: 100, is_active: true },
    fields: [{ key: "code", label: "Code" }, { key: "name", label: "Name", required: true },
             { key: "kind", label: "Type", kind: "select", options: [["EARNING", "Earning (allowance)"], ["DEDUCTION", "Deduction"]],
               show: (v) => <HrBadge status={String(v)} /> },
             { key: "calc_type", label: "Calculated as", kind: "select",
               options: [["FIXED", "Fixed amount"], ["PERCENT_BASIC", "% of basic salary"]],
               show: (v) => (v === "PERCENT_BASIC" ? "% of basic" : "Fixed amount") },
             { key: "default_value", label: "Default", kind: "number", numeric: true },
             { key: "sort_order", label: "Sort order", kind: "number", hideInGrid: true }],
  },
};

export default function HrSetupPage() {
  const [tab, setTab] = useState<Tab>("departments");
  const lookups = useHr<Lookups>("/hrms/lookups");
  const [installing, setInstalling] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const install = async () => {
    setInstalling(true); setError(null); setMessage(null);
    try {
      const added = await api.post<Record<string, number>>("/hrms/setup/install-defaults", {});
      const total = Object.values(added).reduce((a, b) => a + b, 0);
      setMessage(total ? `Added ${Object.entries(added).filter(([, n]) => n).map(([k, n]) => `${n} ${k.replace("_", " ")}`).join(", ")}.`
        : "The standard lists are already in place.");
      setVersion((v) => v + 1);
      lookups.reload();
    } catch (err) { setError(errorText(err, "Could not add the standard lists.")); } finally { setInstalling(false); }
  };

  return (
    <AppShell title="HR Setup">
      <PageHeader title="HR Setup" subtitle="The lists and policies the rest of HR is built on.">
        <Button tone="soft" busy={installing} onClick={install}
          title="Adds the usual departments, designations, a general shift, leave types and salary components that are missing. Amounts are left at zero.">
          <Sparkles size={14} /> Add standard lists
        </Button>
      </PageHeader>
      <ErrorNote message={error} />
      {message && <p className="mb-4 rounded-lg bg-primary/10 px-4 py-3 text-[12.8px] text-primary">{message}</p>}
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === "settings" ? <SettingsPanel /> : <MasterList key={`${tab}-${version}`} path={tab} lookups={lookups.data} onChanged={lookups.reload} />}
    </AppShell>
  );
}

function MasterList({ path, lookups, onChanged }: { path: Exclude<Tab, "settings">; lookups: Lookups | null; onChanged: () => void }) {
  const def = DEFS[path];
  const list = useHr<Row[]>(`/hrms/${def.api ?? path}`);
  const rows = (list.data ?? []).filter((row) => !def.only || def.only(row));
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const hasActive = "is_active" in def.fresh;
  const columns = def.fields.filter((f) => !f.hideInGrid);

  const nameOf = (key: string, id: unknown): string => {
    if (!id) return "";
    if (key === "parent_id") return lookups?.departments.find((d) => d.id === id)?.name ?? "";
    if (key === "head_id") { const e = lookups?.employees.find((x) => x.id === id); return e ? `${e.code} ${e.name}` : ""; }
    return String(id);
  };
  const cell = (f: FieldDef, row: Row): React.ReactNode => {
    const v = row[f.key];
    if (f.show) return f.show(v, row);
    if (f.kind === "select" && !f.options) return nameOf(f.key, v);
    return v == null || v === "" ? "" : String(v);
  };

  return (
    <Card title={def.title} action={<Button tone="primary" onClick={() => setEditing("new")}><Plus size={14} /> Add</Button>}>
      <ErrorNote message={list.error} />
      {list.loading ? <Spinner /> : rows.length === 0 ? (
        <EmptyState>{def.empty ?? "Nothing here yet. Add one, or use “Add standard lists” above."}</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left">
            <thead><tr className="border-b border-line"><GridTh>Edit</GridTh>
              {columns.map((f) => <GridTh key={f.key} numeric={f.numeric}>{f.label}</GridTh>)}
              {hasActive && <GridTh>Active</GridTh>}
            </tr></thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={String(row.id)} className={gridRowClass(i)}>
                  <td className={gridCellClass()}>
                    <button onClick={() => setEditing(row)} aria-label="Edit"
                      className="rounded p-1 text-muted hover:bg-primary/10 hover:text-primary"><Pencil size={13} /></button>
                  </td>
                  {columns.map((f, n) => (
                    <td key={f.key} className={gridCellClass(f.numeric, n === 0 ? "font-medium" : "")}>{cell(f, row)}</td>
                  ))}
                  {hasActive && <td className={gridCellClass()}>{row.is_active ? "Yes" : <span className="text-faint">No</span>}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {def.note && <p className="m-0 border-t border-line px-5 py-3 text-[11.5px] leading-relaxed text-faint">{def.note}</p>}
      {editing && <MasterForm path={path} row={editing === "new" ? null : editing} lookups={lookups}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload(); onChanged(); }} />}
    </Card>
  );
}

function MasterForm({ path, row, lookups, onClose, onSaved }: {
  path: Exclude<Tab, "settings">; row: Row | null; lookups: Lookups | null; onClose: () => void; onSaved: () => void;
}) {
  const def = DEFS[path];
  const [f, setF] = useState<Row>(row ?? def.fresh);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: string, v: unknown) => setF((x) => ({ ...x, [k]: v }));
  const str = (k: string) => (f[k] == null ? "" : String(f[k]));
  const hasActive = "is_active" in def.fresh;

  const optionsFor = (field: FieldDef): { value: string; label: string }[] => {
    if (field.options) return field.options.map(([value, text]) => ({ value, label: text }));
    // Only a main department can have sub departments.
    if (field.key === "parent_id") return (lookups?.departments ?? []).filter((d) => d.id !== f.id && !d.parent_id).map((d) => ({ value: d.id, label: d.name }));
    if (field.key === "head_id") return (lookups?.employees ?? []).filter((e) => e.status === "ACTIVE").map((e) => ({ value: e.id, label: `${e.code} ${e.name}` }));
    return [];
  };

  const endpoint = `/hrms/${def.api ?? path}`;
  const save = async () => {
    const blank = def.fields.find((field) => field.required && !str(field.key).trim());
    if (blank) { setError(`${blank.label} is required.`); return; }
    setSaving(true); setError(null);
    try {
      const body: Row = {};
      for (const key of Object.keys(def.fresh)) body[key] = f[key] === "" ? null : f[key];
      if (row) await api.put(`${endpoint}/${row.id}`, body); else await api.post(endpoint, body);
      onSaved();
    } catch (err) { setError(errorText(err, "Could not save.")); } finally { setSaving(false); }
  };
  const remove = async () => {
    if (!row || !window.confirm("Delete this entry? It can only be deleted if nothing uses it.")) return;
    setSaving(true); setError(null);
    try { await api.del(`${endpoint}/${row.id}`); onSaved(); }
    catch (err) { setError(errorText(err, "Could not delete.")); } finally { setSaving(false); }
  };

  return (
    <Modal title={row ? `Edit ${str("name") || str("code")}` : `Add to ${def.title.toLowerCase()}`} open width="md"
      saving={saving} error={error} onClose={onClose} onSave={save} onDelete={row ? remove : undefined}>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        {def.fields.map((field) => {
          if (field.kind === "toggle") {
            return <Toggle key={field.key} label={field.label} checked={Boolean(f[field.key])} onChange={(v) => set(field.key, v)} />;
          }
          if (field.kind === "days") {
            const chosen = str(field.key).split(",").filter(Boolean);
            return (
              <div key={field.key} className="col-span-2 max-sm:col-span-1">
                <Field label={field.label}>
                  <div className="flex flex-wrap gap-1.5">
                    {WEEKDAYS.map((d) => {
                      const on = chosen.includes(d);
                      return (
                        <button key={d} type="button"
                          onClick={() => set(field.key, WEEKDAYS.filter((x) => (x === d ? !on : chosen.includes(x))).join(","))}
                          className={`rounded-lg px-3 py-1.5 text-[12px] font-medium ${on ? "bg-primary/15 text-primary" : "bg-hover text-faint"}`}>
                          {d.charAt(0) + d.slice(1).toLowerCase()}
                        </button>
                      );
                    })}
                  </div>
                </Field>
              </div>
            );
          }
          if (field.kind === "select") {
            return (
              <Field key={field.key} label={field.label} required={field.required}>
                <Select value={str(field.key)} placeholder={field.options ? "Choose…" : "None"}
                  onChange={(e) => set(field.key, e.target.value || null)} options={optionsFor(field)} />
              </Field>
            );
          }
          return (
            <Field key={field.key} label={field.label} required={field.required}>
              <TextInput type={field.kind === "number" ? "number" : field.kind ?? "text"} min={field.kind === "number" ? 0 : undefined}
                value={str(field.key)}
                // A code left blank is made from the name when the row is saved.
                placeholder={field.key === "code" && !row ? "Automatic — or type your own" : undefined}
                onChange={(e) => set(field.key, field.kind === "number" ? (e.target.value === "" ? 0 : Number(e.target.value))
                  : field.key === "code" ? e.target.value.toUpperCase() : e.target.value)} />
            </Field>
          );
        })}
        {hasActive && <Toggle label="Active" checked={Boolean(f.is_active)} onChange={(v) => set("is_active", v)} />}
      </div>
    </Modal>
  );
}

interface Settings {
  week_off_days: string; unmarked_day_policy: string; salary_days_basis: string; hours_per_day: number;
  overtime_multiplier: number; lates_per_absence: number; employee_code_prefix: string; employee_code_digits: number;
}

function SettingsPanel() {
  const settings = useHr<Settings>("/hrms/settings");
  const [f, setF] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (settings.data) setF(settings.data); }, [settings.data]);
  if (!f) return <Spinner />;
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setF({ ...f, [k]: v });
  const off = f.week_off_days.split(",").filter(Boolean);

  const save = async () => {
    setSaving(true); setError(null); setMessage(null);
    try { await api.put("/hrms/settings", f); setMessage("Saved."); settings.reload(); }
    catch (err) { setError(errorText(err, "Could not save.")); } finally { setSaving(false); }
  };
  const example = `${f.employee_code_prefix}${"1".padStart(Math.max(1, f.employee_code_digits), "0")}`;

  return (
    <Card title="HR settings" action={<Button tone="primary" busy={saving} onClick={save}>Save</Button>}>
      <div className="grid grid-cols-2 gap-x-6 gap-y-5 px-5 py-5 max-md:grid-cols-1">
        <div className="col-span-2 max-md:col-span-1">
          <ErrorNote message={error} />
          {message && <p className="m-0 text-[12.5px] text-primary">{message}</p>}
        </div>
        <Field label="Weekly rest days (for employees without a shift)">
          <div className="flex flex-wrap gap-1.5">
            {WEEKDAYS.map((d) => {
              const on = off.includes(d);
              return (
                <button key={d} type="button"
                  onClick={() => set("week_off_days", WEEKDAYS.filter((x) => (x === d ? !on : off.includes(x))).join(","))}
                  className={`rounded-lg px-3 py-1.5 text-[12px] font-medium ${on ? "bg-primary/15 text-primary" : "bg-hover text-faint"}`}>
                  {label(d)}
                </button>
              );
            })}
          </div>
        </Field>
        <Field label="A working day with no attendance entry counts as">
          <Select value={f.unmarked_day_policy} placeholder="Choose…" onChange={(e) => set("unmarked_day_policy", e.target.value || "PRESENT")}
            options={[{ value: "PRESENT", label: "Present (paid) — attendance is marked by exception" },
                      { value: "ABSENT", label: "Absent (unpaid) — attendance is marked every day" }]} />
        </Field>
        <Field label="One day's pay is the monthly salary divided by">
          <Select value={f.salary_days_basis} placeholder="Choose…" onChange={(e) => set("salary_days_basis", e.target.value || "CALENDAR")}
            options={[{ value: "CALENDAR", label: "The days in that month (28 to 31)" }, { value: "FIXED_30", label: "30, every month" }]} />
        </Field>
        <Field label="Working hours per day (for the hourly overtime rate)">
          <TextInput type="number" min={1} max={24} step="0.5" value={f.hours_per_day} onChange={(e) => set("hours_per_day", Number(e.target.value))} />
        </Field>
        <Field label="Overtime is paid at … times the hourly basic rate (0 = recorded, not paid)">
          <TextInput type="number" min={0} max={10} step="0.25" value={f.overtime_multiplier} onChange={(e) => set("overtime_multiplier", Number(e.target.value))} />
        </Field>
        <Field label="Late arrivals that cost one day's pay (0 = no deduction for lateness)">
          <TextInput type="number" min={0} max={31} value={f.lates_per_absence} onChange={(e) => set("lates_per_absence", Number(e.target.value))} />
        </Field>
        <Field label="Employee code prefix">
          <TextInput value={f.employee_code_prefix} onChange={(e) => set("employee_code_prefix", e.target.value.toUpperCase())} />
        </Field>
        <Field label={`Digits in the employee code (next codes look like ${example})`}>
          <TextInput type="number" min={1} max={8} value={f.employee_code_digits} onChange={(e) => set("employee_code_digits", Number(e.target.value))} />
        </Field>
      </div>
      <p className="m-0 border-t border-line px-5 py-3 text-[11.5px] leading-relaxed text-faint">
        These are company policy, not system rules: no overtime rate, tax or lateness penalty applies until it is set here
        or on a salary structure. Changes affect payroll runs calculated afterwards; approved runs keep their figures.
      </p>
    </Card>
  );
}
