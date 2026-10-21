"use client";

import { useState } from "react";
import { Pencil, Plus } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Combobox, Field, Modal, TextInput, Toggle } from "@/components/ui/Modal";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, Card, ErrorNote, PageHeader, Spinner } from "@/components/finance/ui";
import { ARMasterList, ARSettingsPanel } from "@/components/receivables/ARSetup";
import { api } from "@/lib/api";
import { errorText, money, useAccountOptions, useFinance } from "@/lib/finance";

const TABS = [
  ["rules", "Posting rules"],
  ["numbering", "Document numbering"],
  ["centers", "Cost centres"],
  ["receivables", "Receivables"],
  ["terms", "Payment terms"],
  ["methods", "Payment methods"],
  ["tax", "Tax codes"],
] as const;

export default function FinanceSettingsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("rules");
  return (
    <AppShell title="Finance Settings">
      <PageHeader title="Finance Settings" subtitle="Configuration that decides how documents become journal entries." />
      <div className="mb-5 flex gap-1.5">
        {TABS.map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`rounded-lg px-4 py-2 text-[12.8px] font-medium transition-colors
                        ${tab === key ? "bg-primary/15 text-primary" : "bg-surface text-muted hover:text-text"}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === "rules" && <PostingRules />}
      {tab === "numbering" && <Numbering />}
      {tab === "centers" && <CostCentres />}
      {tab === "receivables" && <ARSettingsPanel />}
      {tab === "terms" && <ARMasterList kind="payment-terms" />}
      {tab === "methods" && <ARMasterList kind="payment-methods" />}
      {tab === "tax" && <ARMasterList kind="tax-codes" />}
    </AppShell>
  );
}

/* ---------------------------------------------------------------- posting rules */

interface RuleLine {
  rule_id: string | null; line_key: string; label: string; side: string; required: boolean;
  party: string | null; account_id: string | null; account: string | null; is_active: boolean;
}
interface EventRules { event_code: string; label: string; description: string; explicit_lines: boolean; lines: RuleLine[] }
const SAMPLES: Record<string, Record<string, string>> = {
  SALES_INVOICE_POSTED: { receivable: "1180", revenue: "1000", output_tax: "180" },
  CUSTOMER_RECEIPT_POSTED: { bank_cash: "1000", receivable: "1000" },
  PURCHASE_INVOICE_POSTED: { purchase: "1000", input_tax: "180", payable: "1180" },
  SUPPLIER_PAYMENT_POSTED: { payable: "1000", bank_cash: "1000" },
  STOCK_RECEIPT_POSTED: { inventory: "1000", grni: "1000" },
  STOCK_ISSUE_POSTED: { cogs: "1000", inventory: "1000" },
  EXPENSE_POSTED: { expense: "1000", bank_cash: "1000" },
  DEPRECIATION_POSTED: { depreciation_expense: "1000", accumulated_depreciation: "1000" },
};

interface Preview { lines:{ line_key: string; account_code: string; account_name: string; debit: number; credit: number }[]; balanced: boolean; problem: string | null }

function PostingRules() {
  const rules = useFinance<EventRules[]>("/finance/posting-rules");
  const accountOptions = useAccountOptions();
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ event: string; result: Preview } | null>(null);

  const setAccount = async (line: RuleLine, accountId: string) => {
    if (!line.rule_id) return;
    setError(null);
    try {
      await api.put(`/finance/posting-rules/${line.rule_id}`, { account_id: accountId || null, is_active: true });
      await rules.reload();
    } catch (err) {
      setError(errorText(err, "Could not change the rule."));
    }
  };

  const tryIt = async (event: EventRules) => {
    // A small balanced example per event, only to show which accounts the
    // current rules would hit. Nothing is written.
    const amounts = SAMPLES[event.event_code];
    if (!amounts) return;
    try {
      const result = await api.post<Preview>("/finance/posting/preview", { event_code: event.event_code, amounts });
      setPreview({ event: event.event_code, result });
    } catch (err) {
      setError(errorText(err, "Could not preview."));
    }
  };

  if (rules.loading) return <Spinner />;
  return (
    <div className="space-y-4">
      <ErrorNote message={error ?? rules.error} />
      <p className="m-0 text-[12.5px] text-muted">
        Each accounting event produces a fixed shape of entry; which account every line hits is chosen here.
        Sales, purchasing and inventory will post through these rules as they are connected in later phases.
      </p>
      {(rules.data ?? []).filter((e) => !e.explicit_lines).map((event) => (
        <Card key={event.event_code} title={event.label}
          action={<>
            <code className="text-[11px] text-faint">{event.event_code}</code>
            <Button onClick={() => tryIt(event)}>Preview</Button>
          </>}>
          <p className="m-0 border-b border-line px-5 py-2 text-[12px] text-muted">{event.description}</p>
          <table className="w-full border-collapse text-left">
            <tbody>
              {event.lines.map((line, i) => (
                <tr key={line.line_key} className={gridRowClass(i)}>
                  <td className={gridCellClass(false, "w-20")}>
                    <span className={`rounded px-1.5 py-[1px] text-[10.5px] font-semibold
                                      ${line.side === "debit" ? "bg-sky/10 text-sky" : "bg-violet/10 text-violet"}`}>
                      {line.side === "debit" ? "Dr" : "Cr"}
                    </span>
                  </td>
                  <td className={gridCellClass(false, "w-72")}>
                    {line.label}
                    {!line.required && <span className="ml-1.5 text-[11px] text-faint">optional</span>}
                    {line.party && <span className="ml-1.5 text-[11px] text-faint">· per {line.party}</span>}
                  </td>
                  <td className={gridCellClass()}>
                    <div className="max-w-md">
                      <Combobox value={line.account_id ?? ""} options={accountOptions}
                        placeholder="Not set — postings will be refused"
                        onChange={(v) => setAccount(line, v)} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview?.event === event.event_code && (
            <div className="border-t border-line bg-bg/60 px-5 py-3 text-[12px]">
              <div className="mb-1.5 font-medium">Sample entry (not saved)</div>
              {preview.result.lines.map((l) => (
                <div key={l.line_key} className="flex gap-3 tabular-nums">
                  <span className="w-64">{l.account_code} {l.account_name}</span>
                  <span className="w-28 text-right">{l.debit ? money(l.debit) : ""}</span>
                  <span className="w-28 text-right">{l.credit ? money(l.credit) : ""}</span>
                </div>
              ))}
              {preview.result.problem && <p className="mb-0 mt-1.5 text-rose">{preview.result.problem}</p>}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- numbering */

interface Series {
  id: string; doc_type: string; name: string; prefix: string; padding: number; format: string;
  reset_each_fiscal_year: boolean; per_branch: boolean; is_active: boolean; next_number: string | null;
}

function Numbering() {
  const series = useFinance<Series[]>("/finance/document-series");
  const [editing, setEditing] = useState<Series | null>(null);
  if (series.loading) return <Spinner />;
  return (
    <Card>
      <ErrorNote message={series.error} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line"><GridTh>Edit</GridTh>
              <GridTh>Type</GridTh><GridTh>Document</GridTh><GridTh>Format</GridTh><GridTh>Next number</GridTh>
              <GridTh>Restarts each year</GridTh><GridTh>Per branch</GridTh><GridTh>Active</GridTh>
            </tr>
          </thead>
          <tbody>
            {(series.data ?? []).map((s, i) => (
              <tr key={s.id} className={gridRowClass(i)}>
                <td className={gridCellClass()}>
                  <button onClick={() => setEditing(s)} className="rounded p-1 text-muted hover:bg-primary/10 hover:text-primary" aria-label="Edit">
                    <Pencil size={13} />
                  </button>
                </td>
                <td className={gridCellClass(false, "font-medium")}>{s.doc_type}</td>
                <td className={gridCellClass()}>{s.name}</td>
                <td className={gridCellClass(false, "font-mono text-[12px] text-muted")}>{s.format}</td>
                <td className={gridCellClass(false, "font-mono text-[12px]")}>{s.next_number}</td>
                <td className={gridCellClass()}>{s.reset_each_fiscal_year ? "Yes" : "No"}</td>
                <td className={gridCellClass()}>{s.per_branch ? "Yes" : "No"}</td>
                <td className={gridCellClass()}>{s.is_active ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="m-0 px-5 py-3 text-[11.5px] text-faint">
        Tokens: {"{prefix}"}, {"{seq}"}, {"{fy}"} (financial year) and {"{branch}"} (branch code, required when numbering per branch).
        Journal numbers are unique within a financial year.
      </p>
      {editing && <SeriesForm series={editing} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); series.reload(); }} />}
    </Card>
  );
}

function SeriesForm({ series, onClose, onSaved }: { series: Series; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ name: series.name, prefix: series.prefix, padding: String(series.padding), format: series.format });
  const [reset, setReset] = useState(series.reset_each_fiscal_year);
  const [perBranch, setPerBranch] = useState(series.per_branch);
  const [active, setActive] = useState(series.is_active);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const sample = form.format
    .replace("{prefix}", form.prefix).replace("{seq}", "1".padStart(Number(form.padding) || 1, "0"))
    .replace("{fy}", "2026-27").replace("{branch}", "HO");

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.put(`/finance/document-series/${series.id}`, {
        ...form, padding: Number(form.padding), reset_each_fiscal_year: reset, per_branch: perBranch, is_active: active,
      });
      onSaved();
    } catch (err) {
      setError(errorText(err, "Could not save."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`Numbering — ${series.doc_type}`} open width="md" saving={saving} error={error} onClose={onClose} onSave={save}>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <Field label="Name" required><TextInput value={form.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Prefix" required><TextInput value={form.prefix} onChange={(e) => set("prefix", e.target.value)} /></Field>
        <Field label="Digits"><TextInput type="number" min={1} max={12} value={form.padding} onChange={(e) => set("padding", e.target.value)} /></Field>
        <Field label="Format"><TextInput value={form.format} onChange={(e) => set("format", e.target.value)} /></Field>
        <Toggle label="Restart each financial year" checked={reset} onChange={setReset} />
        <Toggle label="Separate numbers per branch" checked={perBranch} onChange={setPerBranch} />
        <Toggle label="Active" checked={active} onChange={setActive} />
        <div className="self-end text-[12.5px]"><span className="text-faint">Example </span><b className="font-mono">{sample}</b></div>
      </div>
    </Modal>
  );
}

/* ---------------------------------------------------------------- cost centres */

interface Center { id: string; code: string; name: string; is_active: boolean }

function CostCentres() {
  const centers = useFinance<Center[]>("/finance/cost-centers");
  const [editing, setEditing] = useState<Center | "new" | null>(null);
  if (centers.loading) return <Spinner />;
  return (
    <Card title="Cost centres" action={<Button tone="primary" onClick={() => setEditing("new")}><Plus size={14} /> Add</Button>}>
      <ErrorNote message={centers.error} />
      {(centers.data ?? []).length === 0 ? (
        <p className="px-5 py-6 text-[12.5px] text-faint">
          None yet. Cost centres (Head Office, Sales, Warehouse, Import…) can be tagged on journal lines.
        </p>
      ) : (
        <table className="w-full border-collapse text-left">
          <thead><tr className="border-b border-line"><GridTh>Edit</GridTh><GridTh>Code</GridTh><GridTh>Name</GridTh><GridTh>Active</GridTh></tr></thead>
          <tbody>
            {(centers.data ?? []).map((c, i) => (
              <tr key={c.id} className={gridRowClass(i)}>
                <td className={gridCellClass()}>
                  <button onClick={() => setEditing(c)} className="rounded p-1 text-muted hover:bg-primary/10 hover:text-primary" aria-label="Edit">
                    <Pencil size={13} />
                  </button>
                </td>
                <td className={gridCellClass(false, "font-medium")}>{c.code}</td>
                <td className={gridCellClass()}>{c.name}</td>
                <td className={gridCellClass()}>{c.is_active ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editing && <CenterForm center={editing === "new" ? null : editing} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); centers.reload(); }} />}
    </Card>
  );
}

function CenterForm({ center, onClose, onSaved }: { center: Center | null; onClose: () => void; onSaved: () => void }) {
  const [code, setCode] = useState(center?.code ?? "");
  const [name, setName] = useState(center?.name ?? "");
  const [active, setActive] = useState(center?.is_active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const body = { code: code.trim(), name: name.trim(), is_active: active };
      if (center) await api.put(`/finance/cost-centers/${center.id}`, body);
      else await api.post("/finance/cost-centers", body);
      onSaved();
    } catch (err) {
      setError(errorText(err, "Could not save."));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal title={center ? `Cost centre ${center.code}` : "New cost centre"} open width="sm" saving={saving}
           error={error} onClose={onClose} onSave={save}>
      <div className="space-y-4">
        <Field label="Code" required><TextInput value={code} onChange={(e) => setCode(e.target.value)} placeholder="HO" /></Field>
        <Field label="Name" required><TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="Head Office" /></Field>
        <Toggle label="Active" checked={active} onChange={setActive} />
      </div>
    </Modal>
  );
}
