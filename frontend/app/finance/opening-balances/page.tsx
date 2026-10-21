"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Check, Download, Plus, Upload } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { JournalView } from "@/components/finance/JournalView";
import {
  Button, Card, EmptyState, ErrorNote, PageHeader, ReasonDialog, Spinner, StatusBadge,
} from "@/components/finance/ui";
import { api } from "@/lib/api";
import {
  download, drcr, errorText, fmtDate, fmtDateTime, money, moneyOrBlank, uploadForm, useFinance,
  useFinanceContext,
} from "@/lib/finance";

/* ---------------------------------------------------------------- types */

interface Line {
  id: string; row_number: number; account_code: string | null; account_name: string | null;
  debit: number; credit: number; party_code: string | null; party_name: string | null;
  item_code: string | null; location_name: string | null; quantity: number | null; unit_cost: number | null;
  amount: number | null; reference: string | null; document_date: string | null; due_date: string | null;
  bank_name: string | null; bank_account_number: string | null; statement_balance: number | null;
  uncleared_deposits: number | null; uncleared_payments: number | null; branch_code: string | null;
  errors: string[]; resolved: boolean;
}
interface Batch {
  id: string; batch_number: string; status: string; financial_year: string | null;
  financial_year_id: string; cutover_date: string; source_document: string | null; notes: string | null;
  prepared_by: string | null; created_at: string; validated_at: string | null;
  approved_by: string | null; approved_at: string | null; posted_by: string | null; posted_at: string | null;
  completed_by: string | null; completed_at: string | null;
  journal: { id: string; journal_number: string } | null;
  total_debit: number; total_credit: number;
  lines: Record<string, number>; errors: Record<string, number>;
  imports?: { schedule: string; file_name: string; rows: number; imported_at: string; file_hash: string }[];
  schedules?: Record<string, Line[]>;
}
interface PreviewData {
  lines: { account_code: string; account_name: string; description: string; debit: number; credit: number; party: string | null; quantity: number | null }[];
  total_debit: number; total_credit: number; balanced: boolean;
  schedules: Record<string, { rows: number; errors: number; total: number }>;
  tie_out: { account_code: string; account_name: string; schedule: string; trial_balance: number; schedule_total: number; difference: number }[];
}
interface Recon {
  available: boolean; can_complete: boolean; blocking: string[];
  rows: { category: string; label: string; legacy_balance: number | null; erp_balance: number; difference: number | null; explanation: string | null; status: string }[];
  subledgers: { subledger: string; control_account_balance: number; subledger_total: number; difference: number }[];
}

const SCHEDULE_LABEL: Record<string, string> = {
  GL: "Trial balance", AR: "Customers", AP: "Suppliers", INVENTORY: "Inventory", BANK: "Banks",
};
const STEPS = ["Import", "Validate", "Preview", "Approve", "Post", "Reconcile", "Complete"];
const STEP_OF: Record<string, number> = { DRAFT: 1, VALIDATED: 3, APPROVED: 4, POSTED: 5, COMPLETED: 7, CANCELLED: 0 };

/* ---------------------------------------------------------------- list */

function OpeningScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const batchId = params.get("batch");
  const batches = useFinance<Batch[]>(batchId ? null : "/finance/opening-balances");
  const [creating, setCreating] = useState(false);

  if (batchId) return <BatchDetail id={batchId} onBack={() => router.push("/finance/opening-balances")} />;

  return (
    <AppShell title="Opening Balances">
      <PageHeader title="Opening Balances"
        subtitle="The accountant's approved position at the cut-over date. Nothing is derived from the old ERP's sales orders or stock counts.">
        <Button onClick={() => download("/finance/opening-balances/template", "opening-balance-template.xlsx")}>
          <Download size={14} /> Template
        </Button>
        <Button tone="primary" onClick={() => setCreating(true)}><Plus size={14} /> New batch</Button>
      </PageHeader>

      <Card className="mb-5">
        <ol className="m-0 grid list-none grid-cols-4 gap-4 p-5 text-[12.3px] max-lg:grid-cols-2 max-sm:grid-cols-1">
          {[
            ["1. Prepare", "From the old ERP: signed closing trial balance, customer and supplier schedules, item-wise stock valuation, bank balances."],
            ["2. Import & validate", "Fill the template and upload it. Every code must already exist; the schedules must tie to the trial balance."],
            ["3. Approve & post", "An approver checks the preview; posting creates one balanced opening journal at the cut-over date."],
            ["4. Reconcile & lock", "Enter the legacy figures per category. The batch completes only when every difference is zero or explained."],
          ].map(([title, text]) => (
            <li key={title}><div className="mb-1 font-semibold">{title}</div><div className="text-muted">{text}</div></li>
          ))}
        </ol>
      </Card>

      <Card title="Batches">
        {batches.loading && <Spinner />}
        <ErrorNote message={batches.error} />
        {!batches.loading && (batches.data ?? []).length === 0 && (
          <EmptyState>No opening batch yet. Download the template, then create a batch for the cut-over date.</EmptyState>
        )}
        {(batches.data ?? []).length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                <GridTh>Batch</GridTh><GridTh>Cut-over</GridTh><GridTh>Year</GridTh><GridTh>Source</GridTh>
                <GridTh numeric>Debit</GridTh><GridTh numeric>Credit</GridTh><GridTh>Status</GridTh><GridTh>Prepared by</GridTh>
              </tr></thead>
              <tbody>
                {(batches.data ?? []).map((b, i) => (
                  <tr key={b.id} className={`${gridRowClass(i)} cursor-pointer`}
                      onClick={() => router.push(`/finance/opening-balances?batch=${b.id}`)}>
                    <td className={gridCellClass(false, "font-medium text-primary")}>{b.batch_number}</td>
                    <td className={gridCellClass()}>{fmtDate(b.cutover_date)}</td>
                    <td className={gridCellClass()}>{b.financial_year}</td>
                    <td className={gridCellClass(false, "max-w-[260px] truncate text-muted")}>{b.source_document}</td>
                    <td className={gridCellClass(true)}>{money(b.total_debit)}</td>
                    <td className={gridCellClass(true)}>{money(b.total_credit)}</td>
                    <td className={gridCellClass()}><StatusBadge status={b.status} /></td>
                    <td className={gridCellClass(false, "text-muted")}>{b.prepared_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {creating && <NewBatch onClose={() => setCreating(false)}
        onSaved={(id) => { setCreating(false); router.push(`/finance/opening-balances?batch=${id}`); }} />}
    </AppShell>
  );
}

function NewBatch({ onClose, onSaved }: { onClose: () => void; onSaved: (id: string) => void }) {
  const { data: ctx } = useFinanceContext();
  const current = ctx?.financial_years.find((y) => y.is_current);
  const [fy, setFy] = useState("");
  const [cutover, setCutover] = useState("");
  const [branch, setBranch] = useState("");
  const [source, setSource] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (current && !fy) { setFy(current.id); setCutover(current.start_date); }
  }, [current, fy]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const batch = await api.post<Batch>("/finance/opening-balances", {
        financial_year_id: fy, cutover_date: cutover, branch_id: branch || null,
        source_document: source.trim() || null, notes: notes.trim() || null,
      });
      onSaved(batch.id);
    } catch (err) {
      setError(errorText(err, "Could not create the batch."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="New opening balance batch" open width="md" saving={saving} error={error}
           onClose={onClose} onSave={save} saveLabel="Create batch">
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <Field label="Financial year" required>
          <Select value={fy} placeholder="Choose…"
            onChange={(e) => { setFy(e.target.value); setCutover(ctx?.financial_years.find((y) => y.id === e.target.value)?.start_date ?? ""); }}
            options={(ctx?.financial_years ?? []).map((y) => ({ value: y.id, label: `FY ${y.name}` }))} />
        </Field>
        <Field label="Cut-over date" required>
          <TextInput type="date" value={cutover} onChange={(e) => setCutover(e.target.value)} />
        </Field>
        <Field label="Branch">
          <Select value={branch} placeholder="Whole company" onChange={(e) => setBranch(e.target.value)}
            options={(ctx?.branches ?? []).map((b) => ({ value: b.id, label: b.name }))} />
        </Field>
        <Field label="Source document">
          <TextInput value={source} onChange={(e) => setSource(e.target.value)}
            placeholder="Legacy TB signed 30-06-2026 by …" />
        </Field>
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Notes"><TextArea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        </div>
      </div>
      <p className="mb-0 mt-3 text-[11px] text-faint">
        The cut-over date must be inside the chosen year and its period must be open. It is usually the first day of the year.
      </p>
    </Modal>
  );
}

/* ---------------------------------------------------------------- detail */

function BatchDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [problems, setProblems] = useState<string[] | null>(null);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [tab, setTab] = useState("GL");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [viewJournal, setViewJournal] = useState<string | null>(null);
  const [schedule, setSchedule] = useState("");
  const file = useRef<HTMLInputElement>(null);

  const load = async () => {
    try {
      const data = await api.get<Batch>(`/finance/opening-balances/${id}`);
      setBatch(data);
      if (["VALIDATED", "APPROVED", "POSTED", "COMPLETED"].includes(data.status)) {
        setPreview(await api.get<PreviewData>(`/finance/opening-balances/${id}/preview`));
      } else setPreview(null);
    } catch (err) {
      setError(errorText(err, "Could not load the batch."));
    }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (step: string) => {
    setBusy(step);
    setError(null);
    try {
      if (step === "validate") {
        const result = await api.post<{ passed: boolean; problems: string[]; batch: Batch }>(
          `/finance/opening-balances/${id}/validate`, {});
        setProblems(result.problems);
      } else {
        await api.post(`/finance/opening-balances/${id}/${step}`, {});
      }
      await load();
    } catch (err) {
      setError(errorText(err, `Could not ${step} the batch.`));
    } finally {
      setBusy(null);
    }
  };

  const upload = async (picked: File) => {
    setBusy("import");
    setError(null);
    setProblems(null);
    try {
      const form = new FormData();
      form.append("file", picked);
      if (schedule) form.append("schedule", schedule);
      await uploadForm(`/finance/opening-balances/${id}/import`, form);
      await load();
    } catch (err) {
      setError(errorText(err, "The import failed."));
    } finally {
      setBusy(null);
      if (file.current) file.current.value = "";
    }
  };

  if (!batch) return <AppShell title="Opening Balances"><ErrorNote message={error} /><Spinner /></AppShell>;

  const editable = ["DRAFT", "VALIDATED"].includes(batch.status);
  const step = STEP_OF[batch.status] ?? 0;
  const rows = batch.schedules?.[tab] ?? [];

  return (
    <AppShell title={`Opening ${batch.batch_number}`}>
      <PageHeader title={`Opening balances ${batch.batch_number}`}
        subtitle={`Cut-over ${fmtDate(batch.cutover_date)} · FY ${batch.financial_year}${batch.source_document ? ` · ${batch.source_document}` : ""}`}>
        <Button onClick={onBack}><ArrowLeft size={14} /> All batches</Button>
        <StatusBadge status={batch.status} />
      </PageHeader>

      <ol className="mb-5 flex list-none flex-wrap gap-1.5 p-0">
        {STEPS.map((s, i) => {
          const done = step > i + 1 || batch.status === "COMPLETED";
          const current = step === i + 1 && batch.status !== "COMPLETED";
          return (
            <li key={s} className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-medium
                                    ${done ? "bg-success/15 text-success" : current ? "bg-sky/15 text-sky" : "bg-surface text-faint"}`}>
              {done ? <Check size={12} /> : <span className="w-3 text-center">{i + 1}</span>} {s}
            </li>
          );
        })}
      </ol>
      <ErrorNote message={error} />

      {/* ---- import */}
      <Card title="1 · Import schedules" className="mb-5" action={editable ? <>
        <select className="rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px]" value={schedule}
          onChange={(e) => setSchedule(e.target.value)} title="Only needed for a CSV file">
          <option value="">Workbook (all sheets)</option>
          {Object.entries(SCHEDULE_LABEL).map(([k, v]) => <option key={k} value={k}>CSV: {v}</option>)}
        </select>
        <input ref={file} type="file" accept=".xlsx,.csv" className="hidden"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <Button tone="primary" busy={busy === "import"} onClick={() => file.current?.click()}><Upload size={14} /> Upload file</Button>
      </> : undefined}>
        <div className="flex flex-wrap gap-1.5 border-b border-line px-5 py-2.5">
          {Object.entries(SCHEDULE_LABEL).map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)}
              className={`rounded-lg px-3 py-1.5 text-[12.3px] font-medium ${tab === key ? "bg-primary/15 text-primary" : "text-muted hover:bg-hover"}`}>
              {label} <span className="text-faint">{batch.lines[key] ?? 0}</span>
              {(batch.errors[key] ?? 0) > 0 && <span className="ml-1 rounded-full bg-rose/15 px-1.5 text-[10.5px] text-rose">{batch.errors[key]}</span>}
            </button>
          ))}
        </div>
        {rows.length === 0 ? (
          <EmptyState>No {SCHEDULE_LABEL[tab].toLowerCase()} rows imported.</EmptyState>
        ) : <ScheduleTable schedule={tab} rows={rows} />}
        {(batch.imports ?? []).length > 0 && (
          <p className="m-0 border-t border-line px-5 py-2.5 text-[11.5px] text-faint">
            Last import: {batch.imports![0].file_name} · {fmtDateTime(batch.imports![0].imported_at)} · SHA-256 {batch.imports![0].file_hash}…
          </p>
        )}
      </Card>

      {/* ---- validate */}
      <Card title="2 · Validate" className="mb-5" action={editable ?
        <Button tone="soft" busy={busy === "validate"} onClick={() => act("validate")}>Run validation</Button> : undefined}>
        <div className="px-5 py-4 text-[12.8px]">
          {batch.validated_at && batch.status !== "DRAFT" && (
            <p className="m-0 text-primary">Passed validation {fmtDateTime(batch.validated_at)}. Debits {money(batch.total_debit)} = credits {money(batch.total_credit)}.</p>
          )}
          {problems && problems.length > 0 && (
            <ul className="m-0 space-y-1 pl-5 text-rose">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
          )}
          {!problems && batch.status === "DRAFT" && <p className="m-0 text-muted">Import the schedules, then run validation.</p>}
        </div>
      </Card>

      {/* ---- preview */}
      {preview && (
        <Card title="3 · Preview of the opening journal" className="mb-5"
          action={<span className={`text-[12.5px] font-medium ${preview.balanced ? "text-success" : "text-rose"}`}>
            {preview.balanced ? "Balanced" : "Not balanced"} · {money(preview.total_debit)} / {money(preview.total_credit)}
          </span>}>
          <div className="grid grid-cols-2 gap-0 max-lg:grid-cols-1">
            <div className="max-h-[420px] overflow-auto border-r border-line">
              <table className="w-full border-collapse text-left">
                <thead><tr className="border-b border-line">
                  <GridTh>Account</GridTh><GridTh>Detail</GridTh><GridTh numeric>Debit</GridTh><GridTh numeric>Credit</GridTh>
                </tr></thead>
                <tbody>
                  {preview.lines.map((l, i) => (
                    <tr key={i} className={gridRowClass(i)}>
                      <td className={gridCellClass()}><b>{l.account_code}</b> <span className="text-muted">{l.account_name}</span></td>
                      <td className={gridCellClass(false, "text-muted")}>{l.party ?? l.description}</td>
                      <td className={gridCellClass(true)}>{moneyOrBlank(l.debit)}</td>
                      <td className={gridCellClass(true)}>{moneyOrBlank(l.credit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <div className="px-5 pb-1 pt-3 text-[12px] font-semibold">Control accounts against their schedules</div>
              <table className="w-full border-collapse text-left">
                <thead><tr className="border-b border-line">
                  <GridTh>Account</GridTh><GridTh numeric>Trial balance</GridTh><GridTh numeric>Schedule</GridTh><GridTh numeric>Difference</GridTh>
                </tr></thead>
                <tbody>
                  {preview.tie_out.map((t, i) => (
                    <tr key={t.account_code} className={gridRowClass(i)}>
                      <td className={gridCellClass()}>{t.account_code} {t.account_name}</td>
                      <td className={gridCellClass(true)}>{drcr(t.trial_balance)}</td>
                      <td className={gridCellClass(true)}>{drcr(t.schedule_total)}</td>
                      <td className={gridCellClass(true, t.difference === 0 ? "text-success" : "text-rose")}>{money(t.difference)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </Card>
      )}

      {/* ---- approve & post */}
      <Card title="4 · Approve and post" className="mb-5">
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 text-[12.8px]">
          {batch.status === "VALIDATED" && <Button tone="soft" busy={busy === "approve"} onClick={() => act("approve")}>Approve batch</Button>}
          {batch.status === "APPROVED" && <Button tone="primary" busy={busy === "post"} onClick={() => act("post")}>Post opening journal</Button>}
          {["DRAFT", "VALIDATED", "APPROVED"].includes(batch.status) && <Button tone="danger" onClick={() => setCancelling(true)}>Cancel batch</Button>}
          <span className="text-muted">
            {batch.approved_by && <>Approved by {batch.approved_by} {fmtDateTime(batch.approved_at)}. </>}
            {batch.posted_by && <>Posted by {batch.posted_by} {fmtDateTime(batch.posted_at)} as </>}
          </span>
          {batch.journal && (
            <button onClick={() => setViewJournal(batch.journal!.id)} className="font-medium text-primary hover:underline">
              {batch.journal.journal_number}
            </button>
          )}
          {batch.status === "DRAFT" && <span className="text-faint">Validate the batch first.</span>}
        </div>
      </Card>

      {/* ---- reconcile */}
      {["POSTED", "COMPLETED"].includes(batch.status) && (
        <Reconciliation id={id} completed={batch.status === "COMPLETED"} completedBy={batch.completed_by}
          completedAt={batch.completed_at} onCompleted={load} />
      )}

      <ReasonDialog open={cancelling} title={`Cancel ${batch.batch_number}`} confirmLabel="Cancel batch"
        onClose={() => setCancelling(false)}
        onConfirm={async (reason) => { await api.post(`/finance/opening-balances/${id}/cancel`, { reason }); await load(); }} />
      {viewJournal && <JournalView journalId={viewJournal} onClose={() => setViewJournal(null)} onOpen={setViewJournal} />}
    </AppShell>
  );
}

function ScheduleTable({ schedule, rows }: { schedule: string; rows: Line[] }) {
  const columns: { label: string; numeric?: boolean; value: (l: Line) => React.ReactNode }[] = {
    GL: [
      { label: "Account", value: (l: Line) => `${l.account_code ?? ""} ${l.account_name ?? ""}` },
      { label: "Branch", value: (l: Line) => l.branch_code ?? "" },
      { label: "Debit", numeric: true, value: (l: Line) => moneyOrBlank(l.debit) },
      { label: "Credit", numeric: true, value: (l: Line) => moneyOrBlank(l.credit) },
    ],
    AR: [
      { label: "Customer", value: (l: Line) => `${l.party_code ?? ""} ${l.party_name ?? ""}` },
      { label: "Invoice", value: (l: Line) => l.reference ?? "" },
      { label: "Date", value: (l: Line) => fmtDate(l.document_date) },
      { label: "Due", value: (l: Line) => fmtDate(l.due_date) },
      { label: "Outstanding", numeric: true, value: (l: Line) => money(l.amount) },
    ],
    AP: [
      { label: "Supplier", value: (l: Line) => `${l.party_code ?? ""} ${l.party_name ?? ""}` },
      { label: "Bill", value: (l: Line) => l.reference ?? "" },
      { label: "Date", value: (l: Line) => fmtDate(l.document_date) },
      { label: "Due", value: (l: Line) => fmtDate(l.due_date) },
      { label: "Outstanding", numeric: true, value: (l: Line) => money(l.amount) },
    ],
    INVENTORY: [
      { label: "Item", value: (l: Line) => l.item_code ?? "" },
      { label: "Warehouse", value: (l: Line) => l.location_name ?? "" },
      { label: "Quantity", numeric: true, value: (l: Line) => l.quantity ?? "" },
      { label: "Unit cost", numeric: true, value: (l: Line) => (l.unit_cost != null ? money(l.unit_cost) : "") },
      { label: "Value", numeric: true, value: (l: Line) => money(l.amount) },
    ],
    BANK: [
      { label: "Bank / account", value: (l: Line) => `${l.bank_name ?? ""} ${l.bank_account_number ?? ""}` },
      { label: "GL account", value: (l: Line) => l.account_code ?? "" },
      { label: "Statement", numeric: true, value: (l: Line) => money(l.statement_balance) },
      { label: "+ Uncleared deposits", numeric: true, value: (l: Line) => money(l.uncleared_deposits) },
      { label: "− Uncleared payments", numeric: true, value: (l: Line) => money(l.uncleared_payments) },
      { label: "Book balance", numeric: true, value: (l: Line) => money(l.amount) },
    ],
  }[schedule] ?? [];

  return (
    <div className="max-h-[420px] overflow-auto">
      <table className="w-full min-w-[760px] border-collapse text-left">
        <thead><tr className="border-b border-line">
          <GridTh>Row</GridTh>
          {columns.map((c) => <GridTh key={c.label} numeric={c.numeric}>{c.label}</GridTh>)}
          <GridTh>Check</GridTh>
        </tr></thead>
        <tbody>
          {rows.map((l, i) => (
            <tr key={l.id} className={`${gridRowClass(i)} ${l.errors.length ? "bg-rose/5" : ""}`}>
              <td className={gridCellClass(false, "text-faint")}>{l.row_number}</td>
              {columns.map((c) => <td key={c.label} className={gridCellClass(c.numeric)}>{c.value(l)}</td>)}
              <td className={gridCellClass(false, "text-[12px]")}>
                {l.errors.length ? <span className="text-rose">{l.errors.join(" ")}</span>
                  : <span className="text-primary">OK</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Reconciliation({ id, completed, completedBy, completedAt, onCompleted }: {
  id: string; completed: boolean; completedBy: string | null; completedAt: string | null; onCompleted: () => void;
}) {
  const [data, setData] = useState<Recon | null>(null);
  const [edits, setEdits] = useState<Record<string, { legacy: string; explanation: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const take = (r: Recon) => {
    setData(r);
    setEdits(Object.fromEntries(r.rows.map((row) => [row.category, {
      legacy: row.legacy_balance != null ? String(row.legacy_balance) : "", explanation: row.explanation ?? "",
    }])));
  };
  useEffect(() => {
    api.get<Recon>(`/finance/opening-balances/${id}/reconciliation`).then(take)
      .catch((err) => setError(errorText(err, "Could not load the reconciliation.")));
  }, [id]);

  const save = async () => {
    setBusy("save");
    setError(null);
    try {
      take(await api.put<Recon>(`/finance/opening-balances/${id}/reconciliation`, {
        entries: Object.entries(edits).map(([category, e]) => ({
          category, legacy_balance: e.legacy.replace(/,/g, "") || null, explanation: e.explanation || null,
        })),
      }));
    } catch (err) {
      setError(errorText(err, "Could not save."));
    } finally {
      setBusy(null);
    }
  };

  const complete = async () => {
    setBusy("complete");
    setError(null);
    try {
      await api.post(`/finance/opening-balances/${id}/complete`, {});
      onCompleted();
    } catch (err) {
      setError(errorText(err, "Could not complete."));
    } finally {
      setBusy(null);
    }
  };

  const tone: Record<string, string> = {
    agreed: "text-primary", explained: "text-amber", unexplained: "text-rose", missing: "text-faint",
  };

  return (
    <Card title="5 · Reconcile against the approved legacy balances"
      action={!completed ? <>
        <Button busy={busy === "save"} onClick={save}>Save figures</Button>
        <Button tone="primary" busy={busy === "complete"} disabled={!data?.can_complete} onClick={complete}
          title={data?.can_complete ? "" : "Every category needs a legacy figure, and every difference an explanation"}>
          Complete and lock
        </Button>
      </> : <span className="text-[12.5px] text-primary">Completed by {completedBy} {fmtDateTime(completedAt)}</span>}>
      <ErrorNote message={error} />
      {!data ? <Spinner /> : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                <GridTh>Category</GridTh><GridTh numeric>Legacy balance</GridTh><GridTh numeric>New ERP balance</GridTh>
                <GridTh numeric>Difference</GridTh><GridTh>Explanation</GridTh><GridTh>Status</GridTh>
              </tr></thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={r.category} className={gridRowClass(i)}>
                    <td className={gridCellClass(false, "font-medium")}>{r.label}</td>
                    <td className={gridCellClass(true)}>
                      {completed ? money(r.legacy_balance) : (
                        <input className="w-36 rounded-md border border-line bg-bg px-2 py-1.5 text-right text-[12px] tabular-nums outline-none focus:border-primary"
                          inputMode="decimal" value={edits[r.category]?.legacy ?? ""}
                          onChange={(e) => setEdits((x) => ({ ...x, [r.category]: { ...x[r.category], legacy: e.target.value } }))} />
                      )}
                    </td>
                    <td className={gridCellClass(true)}>{money(r.erp_balance)}</td>
                    <td className={gridCellClass(true, r.difference ? "text-rose" : "")}>{r.difference == null ? "" : money(r.difference)}</td>
                    <td className={gridCellClass()}>
                      {completed ? (r.explanation ?? "") : (
                        <input className="w-full min-w-[220px] rounded-md border border-line bg-bg px-2 py-1.5 text-[12px] outline-none focus:border-primary"
                          value={edits[r.category]?.explanation ?? ""} placeholder={r.difference ? "Required: why the figures differ" : ""}
                          onChange={(e) => setEdits((x) => ({ ...x, [r.category]: { ...x[r.category], explanation: e.target.value } }))} />
                      )}
                    </td>
                    <td className={gridCellClass(false, `text-[12px] font-medium ${tone[r.status]}`)}>{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.subledgers.length > 0 && (
            <div className="border-t border-line px-5 py-3 text-[12px] text-muted">
              {data.subledgers.map((s) => (
                <div key={s.subledger}>
                  {s.subledger}: control account {money(s.control_account_balance)} · sum of parties {money(s.subledger_total)} ·{" "}
                  <span className={s.difference === 0 ? "text-success" : "text-rose"}>
                    {s.difference === 0 ? "agree" : `differ by ${money(s.difference)}`}
                  </span>
                </div>
              ))}
            </div>
          )}
          <p className="m-0 border-t border-line px-5 py-3 text-[11.5px] text-faint">
            Type each legacy figure from the approved closing trial balance of the old system — not from the imported file.
            Liabilities and equity are entered as positive amounts. The batch cannot be completed while any figure is missing
            or any difference is unexplained; once completed it is locked.
          </p>
        </>
      )}
    </Card>
  );
}

export default function OpeningBalancesPage() {
  return <Suspense><OpeningScreen /></Suspense>;
}
