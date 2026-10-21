"use client";

import { useEffect, useMemo, useState } from "react";
import { CalendarCheck, CalendarClock, CalendarX, Check, Plus, X } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, Select, TextArea, TextInput, Toggle } from "@/components/ui/Modal";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, Card, EmptyState, ErrorNote, PageHeader, ReasonDialog, Spinner } from "@/components/finance/ui";
import { EmployeePicker, HrBadge, Tabs, Tile, selectClass } from "@/components/hrms/ui";
import { api } from "@/lib/api";
import {
  days, errorText, fmtDate, todayIso, useHr, type LeaveBalance, type LeaveRequest, type Lookups,
} from "@/lib/hrms";

interface Listing { items: LeaveRequest[]; total: number; page: number; page_size: number; status_counts: Record<string, number> }
const PAGE_SIZE = 25;

export default function LeavePage() {
  const lookups = useHr<Lookups>("/hrms/lookups");
  const [tab, setTab] = useState<"requests" | "balances">("requests");
  const [pending, setPending] = useState(0);
  return (
    <AppShell title="Leave">
      <PageHeader title="Leave" subtitle="Requests, approvals and each employee's balance for the year." />
      <Tabs tabs={[["requests", "Requests", pending], ["balances", "Balances"]] as const} value={tab} onChange={setTab} />
      {tab === "requests" ? <Requests lookups={lookups.data} onPending={setPending} /> : <Balances lookups={lookups.data} />}
    </AppShell>
  );
}

/* ---------------------------------------------------------------- requests */

function Requests({ lookups, onPending }: { lookups: Lookups | null; onPending: (n: number) => void }) {
  const [status, setStatus] = useState("PENDING");
  const [employee, setEmployee] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [action, setAction] = useState<{ kind: "approve" | "reject" | "cancel"; request: LeaveRequest } | null>(null);

  const qs = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
  if (status) qs.set("status", status);
  if (employee) qs.set("employee_id", employee);
  const list = useHr<Listing>(`/hrms/leave/requests?${qs}`);
  const counts = list.data?.status_counts ?? {};
  useEffect(() => { onPending(counts.PENDING ?? 0); }, [counts.PENDING, onPending]);
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE));
  const pick = (next: string) => { setStatus((s) => (s === next ? "" : next)); setPage(1); };

  const titles = { approve: "Approve leave", reject: "Reject leave", cancel: "Cancel leave" };
  const notes = {
    approve: "The days are written into attendance as leave and taken off the balance.",
    reject: "The request is closed and nothing is taken off the balance.",
    cancel: "For an approved request, the leave days are removed from attendance and returned to the balance.",
  };

  return (
    <>
      <div className="mb-5 grid grid-cols-4 gap-[18px] max-xl:grid-cols-2 max-sm:grid-cols-1">
        <Tile icon={CalendarClock} label="Waiting for a decision" value={counts.PENDING ?? 0} tone="amber" active={status === "PENDING"} onClick={() => pick("PENDING")} />
        <Tile icon={CalendarCheck} label="Approved" value={counts.APPROVED ?? 0} tone="green" active={status === "APPROVED"} onClick={() => pick("APPROVED")} />
        <Tile icon={CalendarX} label="Rejected" value={counts.REJECTED ?? 0} tone="rose" active={status === "REJECTED"} onClick={() => pick("REJECTED")} />
        <Tile icon={X} label="Cancelled" value={counts.CANCELLED ?? 0} tone="plain" active={status === "CANCELLED"} onClick={() => pick("CANCELLED")} />
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.data?.total ?? 0} noun="Request" onReset={() => { setStatus("PENDING"); setEmployee(""); setPage(1); }}
          resettable={status !== "PENDING" || Boolean(employee)}>
          <Button tone="primary" onClick={() => setCreating(true)}><Plus size={14} /> New leave request</Button>
        </GridHeader>
        <div className="flex flex-wrap items-center gap-2.5 px-5 pb-4 pt-2">
          <div className="w-[280px]"><EmployeePicker lookups={lookups} value={employee} includeLeft
            onChange={(id) => { setEmployee(id); setPage(1); }} placeholder="All employees" /></div>
          <select className={selectClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">Any status</option>
            {["PENDING", "APPROVED", "REJECTED", "CANCELLED"].map((s) => <option key={s} value={s}>{s.charAt(0) + s.slice(1).toLowerCase()}</option>)}
          </select>
        </div>
        <div className="px-5"><ErrorNote message={list.error} /></div>

        {list.loading && !list.data ? <Spinner /> : (list.data?.items ?? []).length === 0 ? (
          <EmptyState>{status === "PENDING" ? "No requests are waiting for a decision." : "No leave requests match these filters."}</EmptyState>
        ) : (
          <div className="overflow-x-auto border-t border-line">
            <table className="w-full min-w-[1000px] border-collapse text-left">
              <thead><tr className="border-b border-line"><GridTh>Actions</GridTh>
                <GridTh>Request</GridTh><GridTh>Employee</GridTh><GridTh>Leave</GridTh><GridTh>From</GridTh><GridTh>To</GridTh>
                <GridTh numeric>Days</GridTh><GridTh>Reason</GridTh><GridTh>Status</GridTh>
              </tr></thead>
              <tbody>
                {(list.data?.items ?? []).map((r, i) => (
                  <tr key={r.id} className={gridRowClass(i)}>
                    <td className={gridCellClass()}>
                      <div className="flex gap-1.5">
                        {r.status === "PENDING" && <>
                          <Button tone="soft" onClick={() => setAction({ kind: "approve", request: r })}><Check size={13} /> Approve</Button>
                          <Button tone="danger" onClick={() => setAction({ kind: "reject", request: r })}>Reject</Button>
                        </>}
                        {(r.status === "PENDING" || r.status === "APPROVED") &&
                          <Button onClick={() => setAction({ kind: "cancel", request: r })}>Cancel</Button>}
                      </div>
                    </td>
                    <td className={gridCellClass(false, "font-medium")}>{r.request_number}</td>
                    <td className={gridCellClass()}>{r.employee_name}<span className="block text-[10.5px] text-faint">{r.employee_code}</span></td>
                    <td className={gridCellClass()}>{r.leave_type}{r.is_paid === false && <span className="ml-1.5 text-[10.5px] text-rose">unpaid</span>}</td>
                    <td className={gridCellClass(false, "whitespace-nowrap")}>{fmtDate(r.from_date)}</td>
                    <td className={gridCellClass(false, "whitespace-nowrap")}>{fmtDate(r.to_date)}</td>
                    <td className={gridCellClass(true, "font-semibold")}>{days(r.days)}{r.half_day && <span className="ml-1 text-[10.5px] font-normal text-faint">half</span>}</td>
                    <td className={gridCellClass(false, "max-w-[260px] text-muted")}>
                      {r.reason}
                      {r.decision_note && <span className="block text-[11px] text-faint">Decision: {r.decision_note}</span>}
                    </td>
                    <td className={gridCellClass()}>
                      <HrBadge status={r.status} />
                      {r.decided_by_name && <span className="block text-[10.5px] text-faint">{r.decided_by_name}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && (
          <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3 text-[12.5px] text-muted">
            <Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <span>Page {page} of {pages}</span>
            <Button disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        )}
      </section>

      {creating && <RequestForm lookups={lookups} onClose={() => setCreating(false)} onSaved={() => { setCreating(false); list.reload(); }} />}
      {action && (
        <ReasonDialog open title={`${titles[action.kind]} — ${action.request.request_number}`} confirmLabel={titles[action.kind]}
          required={action.kind !== "approve"} label={action.kind === "approve" ? "Note (optional)" : "Reason"}
          onClose={() => setAction(null)}
          onConfirm={async (note) => {
            await api.post(`/hrms/leave/requests/${action.request.id}/${action.kind}`, { note: note || null });
            await list.reload();
          }}>
          <p className="m-0 text-[12.5px]">
            <b>{action.request.employee_name}</b> · {action.request.leave_type} · {fmtDate(action.request.from_date)} to{" "}
            {fmtDate(action.request.to_date)} · {days(action.request.days)} day(s)
          </p>
          <p className="m-0 text-[12px] text-muted">{notes[action.kind]}</p>
        </ReasonDialog>
      )}
    </>
  );
}

function RequestForm({ lookups, onClose, onSaved }: { lookups: Lookups | null; onClose: () => void; onSaved: () => void }) {
  const [employee, setEmployee] = useState("");
  const [type, setType] = useState("");
  const [from, setFrom] = useState(todayIso());
  const [to, setTo] = useState(todayIso());
  const [half, setHalf] = useState(false);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const year = Number(from.slice(0, 4)) || new Date().getFullYear();
  const balances = useHr<{ rows: LeaveBalance[] }>(employee ? `/hrms/leave/balances?year=${year}&employee_id=${employee}` : null);
  const preview = useHr<{ days: number }>(employee && from && to && to >= from
    ? `/hrms/leave/preview?employee_id=${employee}&from_date=${from}&to_date=${to}&half_day=${half}` : null);
  const balance = balances.data?.rows.find((b) => b.leave_type_id === type);
  const needed = preview.data?.days ?? 0;
  const free = balance ? balance.available - balance.pending : null;
  const short = Boolean(balance?.is_paid && free !== null && needed > free);

  const save = async () => {
    if (!employee) { setError("Choose the employee."); return; }
    if (!type) { setError("Choose the type of leave."); return; }
    setSaving(true); setError(null);
    try {
      await api.post("/hrms/leave/requests", { employee_id: employee, leave_type_id: type, from_date: from,
                                                 to_date: half ? from : to, half_day: half, reason: reason || null });
      onSaved();
    } catch (err) { setError(errorText(err, "Could not save the request.")); } finally { setSaving(false); }
  };

  return (
    <Modal title="New leave request" open width="md" saving={saving} error={error} onClose={onClose} onSave={save} saveLabel="Submit request">
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Employee" required><EmployeePicker lookups={lookups} value={employee} onChange={setEmployee} /></Field>
        </div>
        <Field label="Type of leave" required>
          <Select value={type} placeholder="Choose…" onChange={(e) => setType(e.target.value)}
            options={(lookups?.leave_types ?? []).filter((t) => t.is_active !== false)
              .map((t) => ({ value: t.id, label: `${t.name}${t.is_paid ? "" : " (unpaid)"}` }))} />
        </Field>
        <Toggle label="Half day" checked={half} onChange={(v) => { setHalf(v); if (v) setTo(from); }} />
        <Field label={half ? "Date" : "From"} required>
          <TextInput type="date" value={from} onChange={(e) => { setFrom(e.target.value); if (half || e.target.value > to) setTo(e.target.value); }} />
        </Field>
        {!half && <Field label="To" required><TextInput type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>}
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Reason"><TextArea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        </div>
      </div>

      {employee && (
        <div className={`mt-4 rounded-xl px-4 py-3 text-[12.5px] ${short ? "bg-rose/10" : "bg-hover/60"}`}>
          <div>This request charges <b>{days(needed)}</b> working day(s). Weekly rest days and holidays in the range are free.</div>
          {balance && balance.is_paid && (
            <div className={short ? "mt-1 text-rose" : "mt-1 text-muted"}>
              {balance.leave_type}: {days(balance.available)} left for {year}{balance.pending ? `, ${days(balance.pending)} of it in pending requests` : ""}.
              {short && " Not enough: use unpaid leave for the rest, or adjust the balance."}
            </div>
          )}
          {balance && !balance.is_paid && <div className="mt-1 text-muted">Unpaid leave: these days are deducted from the month&apos;s salary.</div>}
        </div>
      )}
    </Modal>
  );
}

/* ---------------------------------------------------------------- balances */

function Balances({ lookups }: { lookups: Lookups | null }) {
  const [year, setYear] = useState(new Date().getFullYear());
  const [department, setDepartment] = useState("");
  const data = useHr<{ year: number; rows: LeaveBalance[] }>(`/hrms/leave/balances?year=${year}${department ? `&department_id=${department}` : ""}`);
  const [editing, setEditing] = useState<LeaveBalance | null>(null);

  const { types, employees } = useMemo(() => {
    const typeMap = new Map<string, { id: string; name: string; paid: boolean }>();
    const byEmployee = new Map<string, { code: string; name: string; cells: Record<string, LeaveBalance> }>();
    for (const b of data.data?.rows ?? []) {
      typeMap.set(b.leave_type_id, { id: b.leave_type_id, name: b.leave_type, paid: b.is_paid });
      const row = byEmployee.get(b.employee_id) ?? { code: b.employee_code, name: b.employee_name, cells: {} };
      row.cells[b.leave_type_id] = b;
      byEmployee.set(b.employee_id, row);
    }
    return { types: [...typeMap.values()], employees: [...byEmployee.entries()] };
  }, [data.data]);

  return (
    <Card title={`Leave balances — ${year}`}
      action={<>
        <select className={selectClass} value={department} onChange={(e) => setDepartment(e.target.value)}>
          <option value="">All departments</option>
          {(lookups?.departments ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <input type="number" className={`${selectClass} w-[90px]`} min={2000} max={2100} value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
      </>}>
      <div className="px-5 pt-4"><ErrorNote message={data.error} /></div>
      {data.loading && !data.data ? <Spinner /> : employees.length === 0 ? (
        <EmptyState>{types.length === 0 && (lookups?.leave_types ?? []).length === 0
          ? "No leave types are set up yet. Add them in HR Setup." : "No current employees to show."}</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-left">
            <thead><tr className="border-b border-line">
              <GridTh>Employee</GridTh>
              {types.map((t) => <GridTh key={t.id} numeric>{t.name}</GridTh>)}
            </tr></thead>
            <tbody>
              {employees.map(([id, row], i) => (
                <tr key={id} className={gridRowClass(i)}>
                  <td className={gridCellClass()}><span className="font-medium">{row.name}</span>
                    <span className="block text-[10.5px] text-faint">{row.code}</span></td>
                  {types.map((t) => {
                    const b = row.cells[t.id];
                    if (!b) return <td key={t.id} className={gridCellClass(true, "text-faint")}>—</td>;
                    return (
                      <td key={t.id} className={gridCellClass(true)}>
                        <button onClick={() => setEditing(b)} title="Adjust this balance"
                          className="rounded px-1.5 py-0.5 text-right hover:bg-primary/10">
                          {t.paid ? (
                            <>
                              <span className={`text-[13.5px] font-semibold ${b.available <= 0 ? "text-rose" : ""}`}>{days(b.available)}</span>
                              <span className="text-[11px] text-faint"> / {days(b.entitled + b.carried_forward + b.adjustment)}</span>
                              <span className="block text-[10.5px] text-faint">{days(b.used)} used{b.pending ? ` · ${days(b.pending)} pending` : ""}</span>
                            </>
                          ) : (
                            <>
                              <span className="text-[13.5px] font-semibold">{days(b.used)}</span>
                              <span className="block text-[10.5px] text-faint">taken</span>
                            </>
                          )}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="m-0 border-t border-line px-5 py-3 text-[11.5px] leading-relaxed text-faint">
        Each figure is days left out of the year&apos;s total (entitlement + carried forward + adjustment). Days used are the approved
        requests, so they change only by approving or cancelling a request. Click a figure to change an entitlement or add an adjustment.
      </p>
      {editing && <BalanceForm balance={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); data.reload(); }} />}
    </Card>
  );
}

function BalanceForm({ balance, onClose, onSaved }: { balance: LeaveBalance; onClose: () => void; onSaved: () => void }) {
  const [entitled, setEntitled] = useState(String(balance.entitled));
  const [carried, setCarried] = useState(String(balance.carried_forward));
  const [adjustment, setAdjustment] = useState(String(balance.adjustment));
  const [note, setNote] = useState(balance.adjustment_note ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const total = (Number(entitled) || 0) + (Number(carried) || 0) + (Number(adjustment) || 0);

  const save = async () => {
    setSaving(true); setError(null);
    try {
      await api.put(`/hrms/leave/balances/${balance.id}`, { entitled: Number(entitled) || 0, carried_forward: Number(carried) || 0,
                                                             adjustment: Number(adjustment) || 0, adjustment_note: note || null });
      onSaved();
    } catch (err) { setError(errorText(err, "Could not save the balance.")); } finally { setSaving(false); }
  };

  return (
    <Modal title={`${balance.leave_type} ${balance.year} — ${balance.employee_name}`} open width="sm" saving={saving} error={error}
      onClose={onClose} onSave={save}>
      <div className="space-y-4">
        <Field label="Entitlement for the year (days)"><TextInput type="number" min={0} step="0.5" value={entitled} onChange={(e) => setEntitled(e.target.value)} /></Field>
        <Field label="Carried forward from last year"><TextInput type="number" min={0} step="0.5" value={carried} onChange={(e) => setCarried(e.target.value)} /></Field>
        <Field label="Adjustment (+ to grant, − to take away)"><TextInput type="number" step="0.5" value={adjustment} onChange={(e) => setAdjustment(e.target.value)} /></Field>
        <Field label="Why the adjustment"><TextInput value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <p className="m-0 rounded-lg bg-hover/60 px-3.5 py-2.5 text-[12.5px]">
          Total {days(total)} − used {days(balance.used)} = <b>{days(total - balance.used)}</b> day(s) left.
        </p>
      </div>
    </Modal>
  );
}
