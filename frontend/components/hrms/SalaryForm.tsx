"use client";

import { useMemo, useState } from "react";
import { Field, Modal, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { errorText, fmtDate, money, todayIso, useHr, type CalcType, type Lookups, type Salary } from "@/lib/hrms";

interface Row { component_id: string; code: string; name: string; kind: "EARNING" | "DEDUCTION"; calc_type: CalcType; value: string }

const cell = "rounded-md border border-line bg-bg px-2 py-1.5 text-[12.5px] outline-none focus:border-primary";

/**
 * Enter an employee's salary from a date onward. Every active component is
 * listed; one left at zero is simply not part of the structure.
 */
export function SalaryForm({ employee, lookups, current, onClose, onSaved }: {
  employee: { id: string; employee_code: string; full_name: string; joining_date: string };
  lookups: Lookups | null; current: Salary | null; onClose: () => void; onSaved: () => void;
}) {
  const history = useHr<Salary[]>(`/hrms/employees/${employee.id}/salary`);
  const [effective, setEffective] = useState(current ? todayIso().slice(0, 8) + "01" : employee.joining_date);
  const [basic, setBasic] = useState(current ? String(current.basic_salary) : "");
  const [remarks, setRemarks] = useState("");
  const [rows, setRows] = useState<Row[]>(() => (lookups?.salary_components ?? [])
    .filter((c) => c.is_active !== false || current?.lines.some((l) => l.component_id === c.id))
    .map((c) => {
      const line = current?.lines.find((l) => l.component_id === c.id);
      return { component_id: c.id, code: c.code, name: c.name, kind: c.kind,
               calc_type: line?.calc_type ?? c.calc_type,
               value: line ? String(line.value) : (c.default_value ? String(c.default_value) : "") };
    }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const totals = useMemo(() => {
    const b = Number(basic) || 0;
    const amount = (r: Row) => (r.calc_type === "PERCENT_BASIC" ? (b * (Number(r.value) || 0)) / 100 : Number(r.value) || 0);
    const allowances = rows.filter((r) => r.kind === "EARNING").reduce((sum, r) => sum + amount(r), 0);
    const deductions = rows.filter((r) => r.kind === "DEDUCTION").reduce((sum, r) => sum + amount(r), 0);
    return { amount, allowances, deductions, gross: b + allowances, net: b + allowances - deductions };
  }, [basic, rows]);

  const setRow = (id: string, patch: Partial<Row>) =>
    setRows((all) => all.map((r) => (r.component_id === id ? { ...r, ...patch } : r)));

  const save = async () => {
    if (!effective) { setError("Enter the date this salary takes effect."); return; }
    if (basic === "" || Number(basic) < 0) { setError("Enter the basic salary."); return; }
    setSaving(true); setError(null);
    try {
      await api.post(`/hrms/employees/${employee.id}/salary`, {
        effective_from: effective, basic_salary: Number(basic), remarks: remarks || null,
        lines: rows.filter((r) => Number(r.value) > 0)
          .map((r) => ({ component_id: r.component_id, calc_type: r.calc_type, value: Number(r.value) })),
      });
      onSaved();
    } catch (err) { setError(errorText(err, "Could not save the salary.")); } finally { setSaving(false); }
  };

  const group = (kind: "EARNING" | "DEDUCTION", title: string) => {
    const list = rows.filter((r) => r.kind === kind);
    if (list.length === 0) return null;
    return (
      <>
        <tr><td colSpan={4} className="px-1 pb-1 pt-3 text-[11.5px] font-semibold text-muted">{title}</td></tr>
        {list.map((r) => (
          <tr key={r.component_id}>
            <td className="py-1 pr-2 text-[12.8px]">{r.name} <span className="text-faint">{r.code}</span></td>
            <td className="py-1 pr-2">
              <select className={`${cell} w-full`} value={r.calc_type} onChange={(e) => setRow(r.component_id, { calc_type: e.target.value as CalcType })}>
                <option value="FIXED">Fixed amount</option>
                <option value="PERCENT_BASIC">% of basic</option>
              </select>
            </td>
            <td className="py-1 pr-2">
              <input className={`${cell} w-full text-right`} inputMode="decimal" value={r.value} placeholder="0"
                onChange={(e) => setRow(r.component_id, { value: e.target.value.replace(/[^\d.]/g, "") })} />
            </td>
            <td className="py-1 text-right text-[12.8px] tabular-nums">{money(totals.amount(r))}</td>
          </tr>
        ))}
      </>
    );
  };

  return (
    <Modal title={`Salary structure — ${employee.employee_code} ${employee.full_name}`} open width="md" saving={saving} error={error}
      onClose={onClose} onSave={save} saveLabel="Save salary">
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <Field label="Effective from" required>
          <TextInput type="date" value={effective} onChange={(e) => setEffective(e.target.value)} />
        </Field>
        <Field label="Basic salary (per month)" required>
          <TextInput inputMode="decimal" value={basic} placeholder="0" onChange={(e) => setBasic(e.target.value.replace(/[^\d.]/g, ""))} />
        </Field>
      </div>

      <table className="mt-2 w-full border-collapse">
        <thead><tr className="text-left text-[11px] text-faint">
          <th className="font-medium"> </th><th className="w-[150px] font-medium">Calculated as</th>
          <th className="w-[120px] text-right font-medium">Amount or %</th><th className="w-[120px] text-right font-medium">Per month</th>
        </tr></thead>
        <tbody>
          {group("EARNING", "Allowances")}
          {group("DEDUCTION", "Deductions")}
        </tbody>
      </table>
      {rows.length === 0 && (
        <p className="mt-3 text-[12px] text-faint">No salary components are set up yet. Add them in HR Setup → Salary components.</p>
      )}

      <div className="mt-4 grid grid-cols-4 gap-3 rounded-xl bg-hover/60 px-4 py-3 text-[12.5px] max-sm:grid-cols-2">
        <div><div className="text-[11px] text-faint">Basic</div><b className="tabular-nums">{money(Number(basic) || 0)}</b></div>
        <div><div className="text-[11px] text-faint">Gross (basic + allowances)</div><b className="tabular-nums">{money(totals.gross)}</b></div>
        <div><div className="text-[11px] text-faint">Deductions</div><b className="tabular-nums text-rose">{money(totals.deductions)}</b></div>
        <div><div className="text-[11px] text-faint">Net for a full month</div><b className="tabular-nums text-primary">{money(totals.net)}</b></div>
      </div>

      <div className="mt-4">
        <Field label="Remarks (why it changed)">
          <TextInput value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Annual increment, promotion…" />
        </Field>
      </div>
      <p className="mb-0 mt-3 text-[11.5px] leading-relaxed text-faint">
        A raise is a new entry with a later date; earlier entries stay as history. Saving with the same date as an existing
        entry corrects that entry. A salary cannot start inside a month whose payroll is already approved.
        Income tax and other statutory deductions are entered here per employee: the system does not assume any rate.
      </p>

      {(history.data ?? []).length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <div className="mb-1.5 text-[11.5px] font-semibold text-muted">History</div>
          <table className="w-full border-collapse text-[12.3px]">
            <tbody>
              {(history.data ?? []).map((h) => (
                <tr key={h.id} className="border-b border-line last:border-0">
                  <td className="py-1.5">From {fmtDate(h.effective_from)}</td>
                  <td className="py-1.5 text-right tabular-nums">Basic {money(h.basic)}</td>
                  <td className="py-1.5 text-right tabular-nums">Gross {money(h.gross)}</td>
                  <td className="py-1.5 pl-3 text-faint">{h.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}
