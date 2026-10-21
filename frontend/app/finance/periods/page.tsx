"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, TextInput, Toggle } from "@/components/ui/Modal";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, Card, ErrorNote, PageHeader, ReasonDialog, Spinner, StatusBadge } from "@/components/finance/ui";
import { api } from "@/lib/api";
import { errorText, fmtDate, fmtDateTime, useFinance } from "@/lib/finance";

interface Period {
  id: string; period_number: number; name: string; period_start: string; period_end: string;
  status: "OPEN" | "CLOSED" | "LOCKED"; closed_at: string | null; closed_by: string | null;
  locked_at: string | null; locked_by: string | null; posted_journals: number;
}
interface Year {
  id: string; name: string; start_date: string; end_date: string; is_current: boolean; periods: Period[];
}

type Action = { kind: "close" | "reopen" | "lock"; period: Period };

export default function PeriodsPage() {
  const years = useFinance<Year[]>("/finance/financial-years");
  const [action, setAction] = useState<Action | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (path: string, body: unknown = {}) => {
    setError(null);
    try {
      await api.post(path, body);
      await years.reload();
    } catch (err) {
      setError(errorText(err, "The action failed."));
    }
  };

  const titles = {
    close: "Close period", reopen: "Reopen period", lock: "Lock period",
  };
  const notes = {
    close: "Postings dated in this month will be refused. Unposted journals in the period must be posted or cancelled first.",
    reopen: "The period will accept postings again. The reason is kept in the audit log.",
    lock: "Locking is permanent: the period can never be reopened, by anyone. Lock a month once it is audited.",
  };

  return (
    <AppShell title="Accounting Periods">
      <PageHeader title="Accounting Periods"
        subtitle="Monthly periods inside each financial year. Only an OPEN period accepts postings.">
        <Button tone="primary" onClick={() => setCreating(true)}><Plus size={14} /> New financial year</Button>
      </PageHeader>
      <ErrorNote message={error ?? years.error} />
      {years.loading && <Spinner />}

      <div className="space-y-5">
        {(years.data ?? []).map((y) => (
          <Card key={y.id}
            title={`FY ${y.name}  ·  ${fmtDate(y.start_date)} – ${fmtDate(y.end_date)}`}
            action={<>
              {y.is_current ? <span className="rounded-full bg-primary/15 px-2.5 py-[3px] text-[11px] font-semibold text-primary">CURRENT</span>
                : <Button onClick={() => run(`/finance/financial-years/${y.id}/set-current`)}>Make current</Button>}
              {y.periods.length === 0 && (
                <Button tone="soft" onClick={() => run(`/finance/financial-years/${y.id}/generate-periods`)}>Generate periods</Button>
              )}
            </>}>
            {y.periods.length === 0 ? (
              <p className="px-5 py-6 text-[12.5px] text-faint">No periods yet — generate them to start posting in this year.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-line"><GridTh>Actions</GridTh>
                      <GridTh>#</GridTh><GridTh>Period</GridTh><GridTh>From</GridTh><GridTh>To</GridTh>
                      <GridTh>Status</GridTh><GridTh numeric>Posted journals</GridTh><GridTh>Closed / locked</GridTh>
                    </tr>
                  </thead>
                  <tbody>
                    {y.periods.map((p, i) => (
                      <tr key={p.id} className={gridRowClass(i)}>
                        <td className={gridCellClass()}>
                          <div className="flex gap-1.5">
                            {p.status === "OPEN" && <Button onClick={() => setAction({ kind: "close", period: p })}>Close</Button>}
                            {p.status === "CLOSED" && <>
                              <Button onClick={() => setAction({ kind: "reopen", period: p })}>Reopen</Button>
                              <Button tone="danger" onClick={() => setAction({ kind: "lock", period: p })}>Lock</Button>
                            </>}
                          </div>
                        </td>
                        <td className={gridCellClass(false, "text-faint")}>{p.period_number}</td>
                        <td className={gridCellClass(false, "font-medium")}>{p.name}</td>
                        <td className={gridCellClass()}>{fmtDate(p.period_start)}</td>
                        <td className={gridCellClass()}>{fmtDate(p.period_end)}</td>
                        <td className={gridCellClass()}><StatusBadge status={p.status} /></td>
                        <td className={gridCellClass(true)}>{p.posted_journals}</td>
                        <td className={gridCellClass(false, "text-[12px] text-muted")}>
                          {p.locked_at ? `Locked ${fmtDateTime(p.locked_at)} · ${p.locked_by ?? ""}`
                            : p.closed_at && p.status !== "OPEN" ? `Closed ${fmtDateTime(p.closed_at)} · ${p.closed_by ?? ""}` : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        ))}
      </div>

      {action && (
        <ReasonDialog open title={`${titles[action.kind]} — ${action.period.name}`}
          confirmLabel={titles[action.kind]} required={action.kind === "reopen"}
          label={action.kind === "reopen" ? "Reason for reopening" : "Note (optional)"}
          onClose={() => setAction(null)}
          onConfirm={async (reason) => {
            await api.post(`/finance/periods/${action.period.id}/${action.kind}`, { reason: reason || null });
            await years.reload();
          }}>
          <p className="m-0 text-[12.5px] text-muted">{notes[action.kind]}</p>
        </ReasonDialog>
      )}
      {creating && <NewYear onClose={() => setCreating(false)} onSaved={() => { setCreating(false); years.reload(); }} />}
    </AppShell>
  );
}

function NewYear({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const now = new Date();
  const startYear = now.getMonth() >= 6 ? now.getFullYear() + 1 : now.getFullYear();
  const [name, setName] = useState(`${startYear}-${String(startYear + 1).slice(2)}`);
  const [start, setStart] = useState(`${startYear}-07-01`);
  const [end, setEnd] = useState(`${startYear + 1}-06-30`);
  const [current, setCurrent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.post("/finance/financial-years", { name, start_date: start, end_date: end, make_current: current });
      onSaved();
    } catch (err) {
      setError(errorText(err, "Could not create the year."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="New financial year" open width="md" saving={saving} error={error}
           onClose={onClose} onSave={save} saveLabel="Create year and periods">
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <Field label="Name" required><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Toggle label="Make this the current year" checked={current} onChange={setCurrent} />
        <Field label="Starts" required><TextInput type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="Ends" required><TextInput type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      </div>
      <p className="mb-0 mt-3 text-[11px] text-faint">
        July–June is suggested because it is the usual Pakistani financial year; any dates can be used.
        Monthly periods are created automatically.
      </p>
    </Modal>
  );
}
