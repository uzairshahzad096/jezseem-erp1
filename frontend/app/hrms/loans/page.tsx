"use client";

import { Fragment, useState } from "react";
import { Banknote, ChevronDown, ChevronRight, HandCoins, Plus } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, EmptyState, ErrorNote, PageHeader, ReasonDialog, Spinner } from "@/components/finance/ui";
import { EmployeePicker, HrBadge, Tile, selectClass } from "@/components/hrms/ui";
import { api } from "@/lib/api";
import { errorText, fmtDate, label, money, todayIso, useHr, type Loan, type Lookups } from "@/lib/hrms";

interface Listing { items: Loan[]; total_outstanding: number; active_count: number }

export default function LoansPage() {
  const lookups = useHr<Lookups>("/hrms/lookups");
  const [status, setStatus] = useState("ACTIVE");
  const list = useHr<Listing>(`/hrms/loans${status ? `?status=${status}` : ""}`);
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [repaying, setRepaying] = useState<Loan | null>(null);
  const [cancelling, setCancelling] = useState<Loan | null>(null);
  const rows = list.data?.items ?? [];

  return (
    <AppShell title="Loans & Advances">
      <PageHeader title="Loans & Advances" subtitle="Money given to employees and recovered from their salary, one instalment per payroll.">
        <Button tone="primary" onClick={() => setCreating(true)}><Plus size={14} /> New loan or advance</Button>
      </PageHeader>
      <ErrorNote message={list.error} />

      <div className="mb-5 grid grid-cols-3 gap-[18px] max-lg:grid-cols-1">
        <Tile icon={HandCoins} label="Active loans and advances" value={list.data?.active_count ?? 0} tone="amber" />
        <Tile icon={Banknote} label="Still to be recovered" value={`PKR ${money(list.data?.total_outstanding ?? 0)}`} tone="rose"
          note={status === "ACTIVE" ? undefined : "active loans in this list"} />
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={rows.length} noun="Loan" onReset={() => setStatus("ACTIVE")} resettable={status !== "ACTIVE"}>
          <select className={selectClass} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="ACTIVE">Active</option><option value="SETTLED">Settled</option>
            <option value="CANCELLED">Cancelled</option><option value="">All</option>
          </select>
        </GridHeader>
        {list.loading && !list.data ? <Spinner /> : rows.length === 0 ? (
          <EmptyState>{status === "ACTIVE" ? "No loan or advance is being recovered." : "Nothing to show."}</EmptyState>
        ) : (
          <div className="mt-3 overflow-x-auto border-t border-line">
            <table className="w-full min-w-[980px] border-collapse text-left">
              <thead><tr className="border-b border-line"><GridTh>Actions</GridTh>
                <GridTh> </GridTh><GridTh>Number</GridTh><GridTh>Employee</GridTh><GridTh>Type</GridTh><GridTh>Given on</GridTh>
                <GridTh numeric>Amount</GridTh><GridTh numeric>Instalment</GridTh><GridTh numeric>Recovered</GridTh>
                <GridTh numeric>Still owed</GridTh><GridTh>Status</GridTh>
              </tr></thead>
              <tbody>
                {rows.map((loan, i) => (
                  <Fragment key={loan.id}>
                    <tr className={gridRowClass(i)}>
                      <td className={gridCellClass()}>
                        {loan.status === "ACTIVE" && (
                          <div className="flex gap-1.5">
                            <Button tone="soft" onClick={() => setRepaying(loan)}>Repayment</Button>
                            {loan.recovered === 0 && <Button tone="danger" onClick={() => setCancelling(loan)}>Cancel</Button>}
                          </div>
                        )}
                      </td>
                      <td className={gridCellClass()}>
                        <button onClick={() => setOpen(open === loan.id ? null : loan.id)} aria-label="Show repayments" className="text-muted hover:text-primary">
                          {open === loan.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                      </td>
                      <td className={gridCellClass(false, "whitespace-nowrap font-medium")}>{loan.loan_number}</td>
                      <td className={gridCellClass(false, "whitespace-nowrap")}>{loan.employee_name}<span className="block text-[10.5px] text-faint">{loan.employee_code}</span></td>
                      <td className={gridCellClass()}>{label(loan.kind)}</td>
                      <td className={gridCellClass(false, "whitespace-nowrap")}>{fmtDate(loan.loan_date)}
                        <span className="block text-[10.5px] text-faint">recovery from {fmtDate(loan.recovery_start).slice(3)}</span></td>
                      <td className={gridCellClass(true)}>{money(loan.amount)}</td>
                      <td className={gridCellClass(true, "text-muted")}>{money(loan.installment_amount)}</td>
                      <td className={gridCellClass(true, "text-muted")}>{money(loan.recovered)}</td>
                      <td className={gridCellClass(true, `font-semibold ${loan.outstanding > 0 ? "text-rose" : "text-faint"}`)}>{money(loan.outstanding)}</td>
                      <td className={gridCellClass()}><HrBadge status={loan.status} /></td>
                    </tr>
                    {open === loan.id && (
                      <tr className="border-b border-line bg-hover/40">
                        <td /><td />
                        <td colSpan={10} className="px-4 py-3 text-[12.3px]">
                          {loan.notes && <p className="m-0 mb-2 text-muted">{loan.notes}</p>}
                          {loan.repayments.length === 0 ? <span className="text-faint">Nothing recovered yet.</span> : (
                            <table className="border-collapse">
                              <tbody>
                                {loan.repayments.map((r) => (
                                  <tr key={r.id} className={r.is_reversed ? "text-faint line-through" : ""}>
                                    <td className="py-0.5 pr-6">{fmtDate(r.paid_on)}</td>
                                    <td className="py-0.5 pr-6 text-right tabular-nums">{money(r.amount)}</td>
                                    <td className="py-0.5 pr-6">{r.source === "PAYROLL" ? "From salary" : "Paid directly"}</td>
                                    <td className="py-0.5 text-muted">{r.notes}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="m-0 border-t border-line px-5 py-3 text-[11.5px] leading-relaxed text-faint">
          Each payroll run deducts one instalment (never more than what is still owed) and records it here when the run is approved.
          “Repayment” is for money paid back outside payroll. This screen tracks what employees owe; it does not post to the
          accounting ledger.
        </p>
      </section>

      {creating && <LoanForm lookups={lookups.data} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); list.reload(); }} />}
      {repaying && <RepayForm loan={repaying} onClose={() => setRepaying(null)} onSaved={() => { setRepaying(null); list.reload(); }} />}
      {cancelling && (
        <ReasonDialog open title={`Cancel ${cancelling.loan_number}`} confirmLabel="Cancel loan" onClose={() => setCancelling(null)}
          onConfirm={async (reason) => { await api.post(`/hrms/loans/${cancelling.id}/cancel`, { reason }); await list.reload(); }}>
          <p className="m-0 text-[12.5px] text-muted">
            For an entry made by mistake. Nothing has been recovered on it yet, so it is simply closed.
          </p>
        </ReasonDialog>
      )}
    </AppShell>
  );
}

function LoanForm({ lookups, onClose, onSaved }: { lookups: Lookups | null; onClose: () => void; onSaved: () => void }) {
  const today = todayIso();
  const [employee, setEmployee] = useState("");
  const [kind, setKind] = useState("ADVANCE");
  const [on, setOn] = useState(today);
  const [amount, setAmount] = useState("");
  const [installment, setInstallment] = useState("");
  const [start, setStart] = useState(today.slice(0, 7));
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const months = Number(amount) > 0 && Number(installment) > 0 ? Math.ceil(Number(amount) / Number(installment)) : 0;

  const save = async () => {
    if (!employee) { setError("Choose the employee."); return; }
    if (!(Number(amount) > 0)) { setError("Enter the amount given."); return; }
    if (!(Number(installment) > 0)) { setError("Enter the monthly instalment."); return; }
    setSaving(true); setError(null);
    try {
      await api.post("/hrms/loans", { employee_id: employee, kind, loan_date: on, amount: Number(amount),
                                      installment_amount: Number(installment), recovery_start: `${start}-01`, notes: notes || null });
      onSaved();
    } catch (err) { setError(errorText(err, "Could not save.")); } finally { setSaving(false); }
  };

  return (
    <Modal title="New loan or advance" open width="md" saving={saving} error={error} onClose={onClose} onSave={save}>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Employee" required><EmployeePicker lookups={lookups} value={employee} onChange={setEmployee} /></Field>
        </div>
        <Field label="Type" required>
          <Select value={kind} placeholder="Choose…" onChange={(e) => setKind(e.target.value || "ADVANCE")}
            options={[{ value: "ADVANCE", label: "Salary advance" }, { value: "LOAN", label: "Loan" }]} />
        </Field>
        <Field label="Given on" required><TextInput type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Amount given" required>
          <TextInput inputMode="decimal" value={amount} placeholder="0"
            onChange={(e) => { const v = e.target.value.replace(/[^\d.]/g, ""); setAmount(v); if (kind === "ADVANCE") setInstallment(v); }} />
        </Field>
        <Field label="Instalment per payroll" required>
          <TextInput inputMode="decimal" value={installment} placeholder="0" onChange={(e) => setInstallment(e.target.value.replace(/[^\d.]/g, ""))} />
        </Field>
        <Field label="Recover from the payroll of" required><TextInput type="month" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <div className="flex items-end pb-2 text-[12.5px] text-muted">
          {months > 0 && <span>Recovered over <b>{months}</b> payroll{months === 1 ? "" : "s"}.</span>}
        </div>
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Notes"><TextArea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  );
}

function RepayForm({ loan, onClose, onSaved }: { loan: Loan; onClose: () => void; onSaved: () => void }) {
  const [on, setOn] = useState(todayIso());
  const [amount, setAmount] = useState(String(loan.outstanding));
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true); setError(null);
    try { await api.post(`/hrms/loans/${loan.id}/repay`, { paid_on: on, amount: Number(amount), notes: notes || null }); onSaved(); }
    catch (err) { setError(errorText(err, "Could not record the repayment.")); } finally { setSaving(false); }
  };

  return (
    <Modal title={`Repayment — ${loan.loan_number} ${loan.employee_name ?? ""}`} open width="sm" saving={saving} error={error}
      onClose={onClose} onSave={save} saveLabel="Record repayment">
      <div className="space-y-4">
        <p className="m-0 text-[12.5px] text-muted">Still owed: <b className="text-text">PKR {money(loan.outstanding)}</b></p>
        <Field label="Paid back on" required><TextInput type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Amount" required><TextInput inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} /></Field>
        <Field label="Notes"><TextInput value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Cash returned, final settlement…" /></Field>
      </div>
    </Modal>
  );
}
