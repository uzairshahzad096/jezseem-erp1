"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle, ArrowLeft, Banknote, Calculator, Check, FileSpreadsheet, FileText, MinusCircle, Play, Trash2, Users,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, Select, TextInput } from "@/components/ui/Modal";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, Card, EmptyState, ErrorNote, PageHeader, ReasonDialog, Spinner } from "@/components/finance/ui";
import { Fact, HrBadge, Tile } from "@/components/hrms/ui";
import { api } from "@/lib/api";
import {
  MONTH_NAMES, days, download, errorText, fmtDate, fmtDateTime, label, money, todayIso, useHr,
  type PayrollRun, type PayrollRunDetail, type Payslip,
} from "@/lib/hrms";

export default function PayrollPage() {
  const [runId, setRunId] = useState<string | null>(null);
  // /hrms/payroll?run=<id> opens that run, for links from the dashboard.
  useEffect(() => { const id = new URLSearchParams(window.location.search).get("run"); if (id) setRunId(id); }, []);
  return (
    <AppShell title="Payroll">
      {runId ? <RunView id={runId} onBack={() => setRunId(null)} /> : <RunList onOpen={setRunId} />}
    </AppShell>
  );
}

/* ---------------------------------------------------------------- runs */

function RunList({ onOpen }: { onOpen: (id: string) => void }) {
  const runs = useHr<PayrollRun[]>("/hrms/payroll/runs");
  const [creating, setCreating] = useState(false);
  const rows = runs.data ?? [];

  return (
    <>
      <PageHeader title="Payroll" subtitle="One run per month: calculate, review, approve, pay.">
        <Button tone="primary" onClick={() => setCreating(true)}><Play size={14} /> Run payroll</Button>
      </PageHeader>
      <ErrorNote message={runs.error} />
      <Card title="Payroll runs">
        {runs.loading && !runs.data ? <Spinner /> : rows.length === 0 ? (
          <EmptyState>
            No payroll has been run yet. Enter each employee&apos;s salary structure on their profile, then use “Run payroll”.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                <GridTh>Run</GridTh><GridTh>Month</GridTh><GridTh numeric>Employees</GridTh><GridTh numeric>Earnings</GridTh>
                <GridTh numeric>Deductions</GridTh><GridTh numeric>Net pay</GridTh><GridTh>Status</GridTh><GridTh>Approved / paid</GridTh>
              </tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.id} onClick={() => onOpen(r.id)} className={`${gridRowClass(i)} cursor-pointer`}>
                    <td className={gridCellClass(false, "font-medium text-primary")}>{r.run_number}</td>
                    <td className={gridCellClass(false, "font-medium")}>{r.period}</td>
                    <td className={gridCellClass(true)}>{r.employee_count}</td>
                    <td className={gridCellClass(true, "text-muted")}>{money(r.total_earnings)}</td>
                    <td className={gridCellClass(true, "text-muted")}>{money(r.total_deductions)}</td>
                    <td className={gridCellClass(true, "font-semibold")}>{money(r.total_net)}</td>
                    <td className={gridCellClass()}><HrBadge status={r.status} /></td>
                    <td className={gridCellClass(false, "text-[12px] text-muted")}>
                      {r.status === "PAID" ? `Paid ${fmtDate(r.payment_date)}${r.paid_by_name ? ` · ${r.paid_by_name}` : ""}`
                        : r.approved_at ? `Approved ${fmtDate(r.approved_at)}${r.approved_by_name ? ` · ${r.approved_by_name}` : ""}`
                        : r.status === "CANCELLED" ? r.cancel_reason : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {creating && <NewRun existing={rows} onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); onOpen(id); }} />}
    </>
  );
}

function NewRun({ existing, onClose, onCreated }: { existing: PayrollRun[]; onClose: () => void; onCreated: (id: string) => void }) {
  const now = new Date();
  // Suggest the earliest month that has no live run: usually the month just ended.
  const taken = new Set(existing.filter((r) => r.status !== "CANCELLED").map((r) => `${r.period_year}-${r.period_month}`));
  const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const suggest = taken.has(`${previous.getFullYear()}-${previous.getMonth() + 1}`) ? now : previous;
  const [year, setYear] = useState(suggest.getFullYear());
  const [month, setMonth] = useState(suggest.getMonth() + 1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const exists = taken.has(`${year}-${month}`);
  const unfinished = year === now.getFullYear() && month === now.getMonth() + 1;

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const run = await api.post<PayrollRunDetail>("/hrms/payroll/runs", { year, month });
      onCreated(run.id);
    } catch (err) { setError(errorText(err, "Could not run the payroll.")); } finally { setSaving(false); }
  };

  return (
    <Modal title="Run payroll" open width="sm" saving={saving} error={error} onClose={onClose} onSave={save} saveLabel="Calculate">
      <div className="grid grid-cols-2 gap-4">
        <Field label="Month" required>
          <Select value={String(month)} placeholder="Choose…" onChange={(e) => setMonth(Number(e.target.value) || month)}
            options={MONTH_NAMES.map((name, i) => ({ value: String(i + 1), label: name }))} />
        </Field>
        <Field label="Year" required>
          <TextInput type="number" min={2000} max={2100} value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
        </Field>
      </div>
      {exists && <p className="mb-0 mt-3 text-[12.5px] text-rose">A payroll run already exists for this month.</p>}
      {unfinished && !exists && (
        <p className="mb-0 mt-3 rounded-lg bg-amber/10 px-3.5 py-2.5 text-[12.5px]">
          This month is not over. Days that have not happened yet are paid in full; recalculate before approving if anything changes.
        </p>
      )}
      <p className="mb-0 mt-3 text-[11.5px] leading-relaxed text-faint">
        This creates a draft: one payslip for everyone employed in the month, from their salary structure, attendance, leave and
        loans. Nothing is final until the run is approved.
      </p>
    </Modal>
  );
}

/* ---------------------------------------------------------------- one run */

function RunView({ id, onBack }: { id: string; onBack: () => void }) {
  const run = useHr<PayrollRunDetail>(`/hrms/payroll/runs/${id}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [slipId, setSlipId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"cancel" | "pay" | "approve" | null>(null);
  const [onlyWarnings, setOnlyWarnings] = useState(false);
  const r = run.data;

  const act = async (name: string, job: () => Promise<unknown>) => {
    setBusy(name); setError(null);
    try { const result = await job(); if (result && typeof result === "object" && "payslips" in result) run.setData(result as PayrollRunDetail); }
    catch (err) { setError(errorText(err, "The action failed.")); } finally { setBusy(null); }
  };
  const file = (name: string, path: string, fallback: string) => act(name, () => download(path, fallback));

  if (!r) return <><BackLink onBack={onBack} /><ErrorNote message={run.error} />{run.loading && <Spinner />}</>;
  const slips = onlyWarnings ? r.payslips.filter((p) => p.warnings.length) : r.payslips;
  const slip = r.payslips.find((p) => p.id === slipId) ?? null;
  const draft = r.status === "DRAFT";

  return (
    <>
      <BackLink onBack={onBack} />
      <PageHeader title={`Payroll — ${r.period}`}
        subtitle={<>{r.run_number} · {fmtDate(r.period_start)} to {fmtDate(r.period_end)} · <HrBadge status={r.status} /></>}>
        <Button busy={busy === "sheet"} onClick={() => file("sheet", `/hrms/payroll/runs/${id}/register`, "salary-sheet.xlsx")}>
          <FileSpreadsheet size={14} /> Salary sheet</Button>
        <Button busy={busy === "bank"} onClick={() => file("bank", `/hrms/payroll/runs/${id}/bank-sheet`, "salary-payments.xlsx")}>
          <Banknote size={14} /> Payment list</Button>
        <Button busy={busy === "pdf"} onClick={() => file("pdf", `/hrms/payroll/runs/${id}/payslips.pdf`, "payslips.pdf")}>
          <FileText size={14} /> All payslips</Button>
        {draft && <Button tone="soft" busy={busy === "recalc"} onClick={() => act("recalc", () => api.post(`/hrms/payroll/runs/${id}/recalculate`, {}))}
          title="Rebuilds every payslip from today's salary structures, attendance, leave and loans. Lines typed in by hand are kept.">
          <Calculator size={14} /> Recalculate</Button>}
        {draft && <Button tone="primary" onClick={() => setDialog("approve")}><Check size={14} /> Approve</Button>}
        {r.status === "APPROVED" && <Button tone="primary" onClick={() => setDialog("pay")}><Banknote size={14} /> Mark as paid</Button>}
        {(draft || r.status === "APPROVED") && <Button tone="danger" onClick={() => setDialog("cancel")}>Cancel run</Button>}
      </PageHeader>
      <ErrorNote message={error} />

      {r.status === "CANCELLED" && (
        <p className="mb-4 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">Cancelled: {r.cancel_reason}</p>
      )}
      {r.status === "APPROVED" && (
        <p className="mb-4 rounded-lg bg-primary/10 px-4 py-3 text-[12.8px]">
          Approved {fmtDateTime(r.approved_at)}{r.approved_by_name ? ` by ${r.approved_by_name}` : ""}. The month&apos;s attendance and
          leave are locked. Pay the salaries from the payment list, then mark the run as paid.
        </p>
      )}
      {r.status === "PAID" && (
        <p className="mb-4 rounded-lg bg-sky/10 px-4 py-3 text-[12.8px]">
          Paid on {fmtDate(r.payment_date)}{r.paid_by_name ? ` · recorded by ${r.paid_by_name}` : ""}. This run is final.
        </p>
      )}

      <div className="mb-5 grid grid-cols-4 gap-[18px] max-xl:grid-cols-2 max-sm:grid-cols-1">
        <Tile icon={Users} label="Employees" value={r.employee_count} tone="sky" />
        <Tile icon={Banknote} label="Total earnings" value={money(r.total_earnings)} tone="green" />
        <Tile icon={MinusCircle} label="Total deductions" value={money(r.total_deductions)} tone="rose" />
        <Tile icon={Banknote} label="Net pay" value={`PKR ${money(r.total_net)}`} tone="violet" />
      </div>

      {r.warning_count > 0 && (
        <button onClick={() => setOnlyWarnings((v) => !v)}
          className="mb-4 flex w-full items-center gap-2 rounded-lg border border-amber/40 bg-amber/10 px-4 py-3 text-left text-[12.8px]">
          <AlertTriangle size={15} className="text-amber" />
          <span><b>{r.warning_count}</b> payslip(s) have something to check before {draft ? "approving" : "paying"}.</span>
          <span className="ml-auto text-primary">{onlyWarnings ? "Show all" : "Show only these"}</span>
        </button>
      )}

      <Card title="Payslips">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1040px] border-collapse text-left">
            <thead><tr className="border-b border-line">
              <GridTh>Code</GridTh><GridTh>Employee</GridTh><GridTh>Department</GridTh><GridTh numeric>Present</GridTh>
              <GridTh numeric>Unpaid days</GridTh><GridTh numeric>Gross</GridTh><GridTh numeric>Earnings</GridTh>
              <GridTh numeric>Deductions</GridTh><GridTh numeric>Net pay</GridTh><GridTh>Paid by</GridTh>
            </tr></thead>
            <tbody>
              {slips.map((p, i) => (
                <tr key={p.id} onClick={() => setSlipId(p.id)} className={`${gridRowClass(i)} cursor-pointer`}>
                  <td className={gridCellClass(false, "font-medium text-primary")}>{p.employee_code}</td>
                  <td className={gridCellClass(false, "font-medium")}>
                    <span className="flex items-center gap-1.5">{p.employee_name}
                      {p.warnings.length > 0 && <span title={p.warnings.join("\n")}><AlertTriangle size={13} className="text-amber" /></span>}</span>
                    {p.designation && <span className="block text-[10.5px] font-normal text-faint">{p.designation}</span>}
                  </td>
                  <td className={gridCellClass(false, "text-muted")}>{p.department ?? "—"}</td>
                  <td className={gridCellClass(true)}>{days(p.present_days)}</td>
                  <td className={gridCellClass(true, p.unpaid_days ? "text-rose" : "text-faint")}>{days(p.unpaid_days)}</td>
                  <td className={gridCellClass(true, "text-muted")}>{money(p.gross_salary)}</td>
                  <td className={gridCellClass(true)}>{money(p.total_earnings)}</td>
                  <td className={gridCellClass(true)}>{money(p.total_deductions)}</td>
                  <td className={gridCellClass(true, `font-semibold ${p.net_pay < 0 ? "text-rose" : ""}`)}>{money(p.net_pay)}</td>
                  <td className={gridCellClass(false, "text-muted")}>{label(p.payment_mode)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="m-0 border-t border-line px-5 py-3 text-[11.5px] leading-relaxed text-faint">
          Click a row for the full payslip. Gross is basic plus allowances. Unpaid days are absences, unpaid leave, half of each
          half day, and days before joining or after leaving; each costs gross ÷ days in the month.
          Payroll records what is owed and paid; it does not post to the accounting ledger.
        </p>
      </Card>

      {slip && <PayslipView slip={slip} run={r} onClose={() => setSlipId(null)} onChanged={(next) => run.setData(next)} />}
      {dialog === "approve" && (
        <Modal title={`Approve payroll — ${r.period}`} open width="sm" saving={busy === "approve"} error={error}
          onClose={() => setDialog(null)} saveLabel="Approve payroll"
          onSave={async () => { await act("approve", () => api.post(`/hrms/payroll/runs/${id}/approve`, {})); setDialog(null); }}>
          <p className="m-0 text-[12.8px]"><b>{r.employee_count}</b> payslip(s), net pay <b>PKR {money(r.total_net)}</b>.</p>
          <ul className="mb-0 mt-3 list-disc space-y-1 pl-5 text-[12.5px] text-muted">
            <li>The figures are fixed: the run can no longer be recalculated or edited.</li>
            <li>Loan and advance instalments on the payslips are recorded as recovered.</li>
            <li>Attendance and leave for {r.period} are locked.</li>
          </ul>
          {r.warning_count > 0 && <p className="mb-0 mt-3 text-[12.5px] text-amber">{r.warning_count} payslip(s) still carry a warning.</p>}
        </Modal>
      )}
      {dialog === "pay" && <PayDialog run={r} onClose={() => setDialog(null)} onPaid={(next) => { run.setData(next); setDialog(null); }} />}
      {dialog === "cancel" && (
        <ReasonDialog open title={`Cancel ${r.run_number}`} confirmLabel="Cancel run" onClose={() => setDialog(null)}
          onConfirm={async (reason) => { run.setData(await api.post<PayrollRunDetail>(`/hrms/payroll/runs/${id}/cancel`, { reason })); }}>
          <p className="m-0 text-[12.5px] text-muted">
            The run is kept on record as cancelled, and {r.period} can be run again.
            {r.status === "APPROVED" && " Its loan recoveries are reversed and the month's attendance and leave are unlocked."}
          </p>
        </ReasonDialog>
      )}
    </>
  );
}

function BackLink({ onBack }: { onBack: () => void }) {
  return (
    <button onClick={onBack} className="mb-3 flex items-center gap-1.5 text-[12.5px] text-muted hover:text-primary">
      <ArrowLeft size={14} /> All payroll runs
    </button>
  );
}

function PayDialog({ run, onClose, onPaid }: { run: PayrollRunDetail; onClose: () => void; onPaid: (next: PayrollRunDetail) => void }) {
  const [on, setOn] = useState(todayIso());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setSaving(true); setError(null);
    try { onPaid(await api.post<PayrollRunDetail>(`/hrms/payroll/runs/${run.id}/pay`, { payment_date: on })); }
    catch (err) { setError(errorText(err, "Could not mark the run as paid.")); } finally { setSaving(false); }
  };
  return (
    <Modal title={`Mark as paid — ${run.period}`} open width="sm" saving={saving} error={error} onClose={onClose} onSave={save} saveLabel="Mark as paid">
      <div className="space-y-4">
        <p className="m-0 text-[12.8px]">Net pay <b>PKR {money(run.total_net)}</b> to {run.employee_count} employee(s).</p>
        <Field label="Salaries were paid on" required><TextInput type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <p className="m-0 text-[11.5px] text-faint">A paid run is final and cannot be cancelled.</p>
      </div>
    </Modal>
  );
}

/* ---------------------------------------------------------------- payslip */

function PayslipView({ slip, run, onClose, onChanged }: {
  slip: Payslip; run: PayrollRunDetail; onClose: () => void; onChanged: (next: PayrollRunDetail) => void;
}) {
  const draft = run.status === "DRAFT";
  const [kind, setKind] = useState<"EARNING" | "DEDUCTION">("EARNING");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const call = async (job: () => Promise<PayrollRunDetail | void>) => {
    setBusy(true); setError(null);
    try { const next = await job(); if (next) onChanged(next); }
    catch (err) { setError(errorText(err, "The action failed.")); } finally { setBusy(false); }
  };
  const add = () => {
    if (!name.trim() || !(Number(amount) > 0)) { setError("Enter what the amount is for, and the amount."); return; }
    call(async () => {
      const next = await api.post<PayrollRunDetail>(`/hrms/payroll/payslips/${slip.id}/lines`, { kind, name: name.trim(), amount: Number(amount) });
      setName(""); setAmount("");
      return next;
    });
  };
  // This DELETE answers with the run and its updated totals, not an empty body.
  const remove = (lineId: string) => call(async () =>
    (await api.del(`/hrms/payroll/payslips/${slip.id}/lines/${lineId}`)) as unknown as PayrollRunDetail);

  const column = (title: string, side: "EARNING" | "DEDUCTION", total: number) => (
    <div>
      <div className="mb-1 text-[11.5px] font-semibold text-muted">{title}</div>
      {slip.lines.filter((l) => l.kind === side).map((l) => (
        <div key={l.id} className="flex items-baseline gap-2 border-b border-line py-1.5 text-[12.8px]">
          <span className="flex-1">{l.name}{l.is_manual && <span className="ml-1.5 rounded bg-hover px-1 text-[10px] text-faint">manual</span>}</span>
          <span className="tabular-nums">{money(l.amount)}</span>
          {draft && l.is_manual && (
            <button onClick={() => remove(l.id)} aria-label="Remove" className="text-faint hover:text-rose"><Trash2 size={12} /></button>
          )}
        </div>
      ))}
      {slip.lines.filter((l) => l.kind === side).length === 0 && <div className="border-b border-line py-1.5 text-[12.5px] text-faint">None</div>}
      <div className="flex items-baseline gap-2 py-1.5 text-[12.8px] font-semibold">
        <span className="flex-1">Total</span><span className="tabular-nums">{money(total)}</span>
      </div>
    </div>
  );

  return (
    <Modal title={`Payslip — ${slip.employee_code} ${slip.employee_name} — ${run.period}`} open width="md" error={error} onClose={onClose}>
      <div className="space-y-4">
        {slip.warnings.length > 0 && (
          <ul className="m-0 list-none space-y-1 rounded-lg bg-amber/10 px-4 py-3 text-[12.5px]">
            {slip.warnings.map((w) => <li key={w} className="flex gap-2"><AlertTriangle size={13} className="mt-[3px] flex-shrink-0 text-amber" />{w}</li>)}
          </ul>
        )}
        <div className="grid grid-cols-4 gap-x-4 gap-y-3 rounded-xl bg-hover/60 px-4 py-3 max-sm:grid-cols-2">
          <Fact label="Department">{slip.department}</Fact>
          <Fact label="Designation">{slip.designation}</Fact>
          <Fact label="Paid by">{label(slip.payment_mode)}</Fact>
          <Fact label="Account">{[slip.bank_name, slip.bank_account_number].filter(Boolean).join(" ")}</Fact>
          <Fact label="Days in month">{slip.days_in_period}</Fact>
          <Fact label="Present">{days(slip.present_days)}</Fact>
          <Fact label="Paid / unpaid leave">{days(slip.paid_leave_days)} / {days(slip.unpaid_leave_days)}</Fact>
          <Fact label="Absent">{days(slip.absent_days)}</Fact>
          <Fact label="Holidays / rest days">{days(slip.holidays)} / {days(slip.weekly_offs)}</Fact>
          <Fact label="Not employed">{days(slip.not_employed_days)}</Fact>
          <Fact label="Late arrivals">{slip.late_count}</Fact>
          <Fact label="Overtime hours">{days(slip.overtime_hours)}</Fact>
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-4 max-sm:grid-cols-1">
          {column("Earnings", "EARNING", slip.total_earnings)}
          {column("Deductions", "DEDUCTION", slip.total_deductions)}
        </div>
        <div className={`flex items-center rounded-xl border px-4 py-3 ${slip.net_pay < 0 ? "border-rose/50" : "border-line"}`}>
          <span className="flex-1 text-[13px] font-semibold">Net pay</span>
          <span className={`text-[19px] font-bold tabular-nums ${slip.net_pay < 0 ? "text-rose" : "text-success"}`}>PKR {money(slip.net_pay)}</span>
        </div>

        {draft && (
          <div className="rounded-xl border border-line px-4 py-3">
            <div className="mb-2 text-[11.5px] font-semibold text-muted">Add a one-off amount (bonus, arrears, fine…)</div>
            <div className="flex flex-wrap items-center gap-2">
              <select value={kind} onChange={(e) => setKind(e.target.value as "EARNING" | "DEDUCTION")}
                className="rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] outline-none focus:border-primary">
                <option value="EARNING">Earning</option><option value="DEDUCTION">Deduction</option>
              </select>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="What it is for"
                className="min-w-[160px] flex-1 rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] outline-none focus:border-primary" />
              <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} placeholder="Amount" inputMode="decimal"
                className="w-[120px] rounded-lg border border-line bg-bg px-3 py-2 text-right text-[12.5px] outline-none focus:border-primary" />
              <Button tone="soft" busy={busy} onClick={add}>Add</Button>
            </div>
            <p className="mb-0 mt-2 text-[11px] text-faint">
              Calculated lines change by correcting the salary structure, attendance, leave or loan and recalculating the run.
            </p>
          </div>
        )}
        <div className="flex justify-end">
          <Button busy={busy} onClick={() => call(() => download(`/hrms/payroll/payslips/${slip.id}/pdf`, `payslip-${slip.employee_code}.pdf`))}>
            <FileText size={14} /> Payslip PDF
          </Button>
        </div>
      </div>
    </Modal>
  );
}
