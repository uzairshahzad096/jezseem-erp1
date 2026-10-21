"use client";

import { useEffect, useState } from "react";
import { Pencil, Plus } from "lucide-react";
import { Field, Modal, Select, TextArea, TextInput, Toggle } from "@/components/ui/Modal";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, Card, ErrorNote, Spinner } from "@/components/finance/ui";
import { api } from "@/lib/api";
import { errorText, fmtDate, useAccountOptions, useFinance } from "@/lib/finance";
import type { ARSettings, PaymentMethod, PaymentTerm, TaxCode } from "@/lib/receivables";

/** Company-level receivables policy. */
export function ARSettingsPanel() {
  const settings = useFinance<ARSettings>("/ar/settings");
  const { data: terms } = useFinance<PaymentTerm[]>("/ar/payment-terms");
  const [form, setForm] = useState<ARSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (settings.data) setForm(settings.data); }, [settings.data]);
  if (!form) return <Spinner />;

  const save = async () => {
    setSaving(true); setError(null); setMessage(null);
    try {
      await api.put("/ar/settings", {
        credit_limit_policy: form.credit_limit_policy, sales_order_cutoff_date: form.sales_order_cutoff_date || null,
        allow_quotation_invoice: form.allow_quotation_invoice, default_payment_term_id: form.default_payment_term_id || null,
        aging_buckets: form.aging_buckets });
      setMessage("Saved.");
      settings.reload();
    } catch (err) { setError(errorText(err, "Could not save.")); } finally { setSaving(false); }
  };

  return (
    <Card title="Receivables policy" action={<Button tone="primary" busy={saving} onClick={save}>Save</Button>}>
      <div className="grid grid-cols-2 gap-5 px-5 py-5 max-md:grid-cols-1">
        <ErrorNote message={error} />
        {message && <p className="m-0 text-[12.5px] text-primary">{message}</p>}
        <Field label="When an invoice exceeds the customer's credit limit">
          <Select value={form.credit_limit_policy} placeholder="Warn" onChange={(e) => setForm({ ...form, credit_limit_policy: e.target.value || "WARN" })}
            options={[{ value: "NONE", label: "Do nothing" }, { value: "WARN", label: "Warn, allow posting" },
                      { value: "APPROVAL", label: "Require credit approval before posting" }, { value: "BLOCK", label: "Block the invoice" }]} />
        </Field>
        <Field label="Default payment terms (customers without their own)">
          <Select value={form.default_payment_term_id ?? ""} placeholder="None" onChange={(e) => setForm({ ...form, default_payment_term_id: e.target.value || null })}
            options={(terms ?? []).map((t) => ({ value: t.id, label: t.name }))} />
        </Field>
        <Field label="Sales orders before this date cannot be invoiced">
          <TextInput type="date" value={form.sales_order_cutoff_date ?? ""} onChange={(e) => setForm({ ...form, sales_order_cutoff_date: e.target.value || null })} />
        </Field>
        <Field label="Aging buckets (days, comma separated)">
          <TextInput value={form.aging_buckets} onChange={(e) => setForm({ ...form, aging_buckets: e.target.value })} />
        </Field>
        <Toggle label="Allow invoicing straight from an approved quotation" checked={form.allow_quotation_invoice}
          onChange={(v) => setForm({ ...form, allow_quotation_invoice: v })} />
        <p className="m-0 text-[11.5px] leading-snug text-faint">
          The cut-off keeps the old ERP&apos;s sales orders out of receivables: balances from before go-live enter through
          Opening Balances as an accountant-approved customer schedule, never by invoicing old orders.
        </p>
      </div>
    </Card>
  );
}

type Kind = "payment-terms" | "payment-methods" | "tax-codes";

/** List + add/edit for the three receivables master tables. */
export function ARMasterList({ kind }: { kind: Kind }) {
  const list = useFinance<(PaymentTerm | PaymentMethod | TaxCode)[]>(`/ar/${kind}`);
  const accountOptions = useAccountOptions();
  const [editing, setEditing] = useState<Record<string, unknown> | "new" | null>(null);
  if (list.loading) return <Spinner />;
  const title = { "payment-terms": "Payment terms", "payment-methods": "Payment methods", "tax-codes": "Tax codes" }[kind];
  const accountName = (id: unknown) => accountOptions.find((a) => a.value === id)?.label ?? "";

  return (
    <Card title={title} action={<Button tone="primary" onClick={() => setEditing("new")}><Plus size={14} /> Add</Button>}>
      <ErrorNote message={list.error} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[700px] border-collapse text-left">
          <thead><tr className="border-b border-line"><GridTh>Edit</GridTh>
            <GridTh>Code</GridTh><GridTh>Name</GridTh>
            {kind === "payment-terms" && <><GridTh numeric>Days</GridTh><GridTh>Cash</GridTh></>}
            {kind === "payment-methods" && <><GridTh>Kind</GridTh><GridTh>Default account</GridTh><GridTh>Reference required</GridTh></>}
            {kind === "tax-codes" && <><GridTh>Type</GridTh><GridTh numeric>Rate %</GridTh><GridTh>Liability account</GridTh><GridTh>Effective</GridTh></>}
            <GridTh>Active</GridTh>
          </tr></thead>
          <tbody>
            {(list.data ?? []).map((row, i) => {
              const r = row as unknown as Record<string, unknown>;
              return (
                <tr key={String(r.id)} className={gridRowClass(i)}>
                  <td className={gridCellClass()}>
                    <button onClick={() => setEditing(r)} aria-label="Edit" className="rounded p-1 text-muted hover:bg-primary/10 hover:text-primary"><Pencil size={13} /></button>
                  </td>
                  <td className={gridCellClass(false, "font-medium")}>{String(r.code)}</td>
                  <td className={gridCellClass()}>{String(r.name)}</td>
                  {kind === "payment-terms" && <><td className={gridCellClass(true)}>{String(r.days)}</td><td className={gridCellClass()}>{r.is_cash ? "Yes" : ""}</td></>}
                  {kind === "payment-methods" && <><td className={gridCellClass()}>{String(r.kind)}</td>
                    <td className={gridCellClass(false, "text-muted")}>{accountName(r.default_account_id)}</td>
                    <td className={gridCellClass()}>{r.requires_reference ? "Yes" : ""}</td></>}
                  {kind === "tax-codes" && <><td className={gridCellClass()}>{String(r.tax_type)}</td>
                    <td className={gridCellClass(true)}>{String(r.rate)}</td>
                    <td className={gridCellClass(false, "text-muted")}>{r.output_account_id ? accountName(r.output_account_id) : "Posting rule default"}</td>
                    <td className={gridCellClass(false, "text-muted")}>{r.effective_from ? fmtDate(String(r.effective_from)) : "—"} → {r.effective_to ? fmtDate(String(r.effective_to)) : "open"}</td></>}
                  <td className={gridCellClass()}>{r.is_active ? "Yes" : "No"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {kind === "tax-codes" && (
        <p className="m-0 px-5 py-3 text-[11.5px] text-faint">
          Rates are configuration, never code. When a rate changes, end-date the old code and add a new one so documents keep the rate that applied on their date.
        </p>
      )}
      {editing && <MasterForm kind={kind} row={editing === "new" ? null : editing} accountOptions={accountOptions}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload(); }} />}
    </Card>
  );
}

function MasterForm({ kind, row, accountOptions, onClose, onSaved }: {
  kind: Kind; row: Record<string, unknown> | null; accountOptions: { value: string; label: string }[];
  onClose: () => void; onSaved: () => void;
}) {
  const [f, setF] = useState<Record<string, unknown>>(row ?? {
    code: "", name: "", is_active: true, sort_order: 100,
    ...(kind === "payment-terms" ? { days: 30, is_cash: false } : {}),
    ...(kind === "payment-methods" ? { kind: "BANK", requires_reference: true, default_account_id: null } : {}),
    ...(kind === "tax-codes" ? { tax_type: "SALES_TAX", rate: 0, output_account_id: null, effective_from: null, effective_to: null, description: "" } : {}),
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: string, v: unknown) => setF((x) => ({ ...x, [k]: v }));
  const str = (k: string) => (f[k] == null ? "" : String(f[k]));

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const body = { ...f };
      delete body.id;
      for (const k of ["default_account_id", "output_account_id", "effective_from", "effective_to"]) if (body[k] === "") body[k] = null;
      if (row) await api.put(`/ar/${kind}/${row.id}`, body); else await api.post(`/ar/${kind}`, body);
      onSaved();
    } catch (err) { setError(errorText(err, "Could not save.")); } finally { setSaving(false); }
  };

  return (
    <Modal title={row ? `Edit ${str("code")}` : "Add"} open width="md" saving={saving} error={error} onClose={onClose} onSave={save}>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <Field label="Code" required><TextInput value={str("code")} onChange={(e) => set("code", e.target.value.toUpperCase())} /></Field>
        <Field label="Name" required><TextInput value={str("name")} onChange={(e) => set("name", e.target.value)} /></Field>
        {kind === "payment-terms" && <>
          <Field label="Days until due"><TextInput type="number" value={str("days")} onChange={(e) => set("days", Number(e.target.value))} /></Field>
          <Toggle label="Cash term" checked={Boolean(f.is_cash)} onChange={(v) => set("is_cash", v)} />
        </>}
        {kind === "payment-methods" && <>
          <Field label="Kind"><Select value={str("kind")} placeholder="Choose…" onChange={(e) => set("kind", e.target.value)}
            options={["CASH", "BANK", "CHEQUE", "ONLINE", "OTHER"].map((k) => ({ value: k, label: k }))} /></Field>
          <Field label="Default cash / bank account"><Select value={str("default_account_id")} placeholder="None"
            onChange={(e) => set("default_account_id", e.target.value || null)} options={accountOptions} /></Field>
          <Toggle label="Reference / cheque number required" checked={Boolean(f.requires_reference)} onChange={(v) => set("requires_reference", v)} />
        </>}
        {kind === "tax-codes" && <>
          <Field label="Type"><Select value={str("tax_type")} placeholder="Choose…" onChange={(e) => set("tax_type", e.target.value)}
            options={[["SALES_TAX", "Sales tax"], ["EXEMPT", "Exempt"], ["ZERO_RATED", "Zero-rated"], ["OTHER", "Other"]].map(([v, l]) => ({ value: v, label: l }))} /></Field>
          <Field label="Rate %"><TextInput inputMode="decimal" value={str("rate")} onChange={(e) => set("rate", e.target.value)} /></Field>
          <Field label="Liability account (blank = posting rule)"><Select value={str("output_account_id")} placeholder="Posting rule default"
            onChange={(e) => set("output_account_id", e.target.value || null)} options={accountOptions} /></Field>
          <Field label="Effective from"><TextInput type="date" value={str("effective_from")} onChange={(e) => set("effective_from", e.target.value || null)} /></Field>
          <Field label="Effective to"><TextInput type="date" value={str("effective_to")} onChange={(e) => set("effective_to", e.target.value || null)} /></Field>
          <div className="col-span-2 max-sm:col-span-1"><Field label="Description"><TextArea rows={2} value={str("description")} onChange={(e) => set("description", e.target.value)} /></Field></div>
        </>}
        <Field label="Sort order"><TextInput type="number" value={str("sort_order")} onChange={(e) => set("sort_order", Number(e.target.value))} /></Field>
        <Toggle label="Active" checked={Boolean(f.is_active)} onChange={(v) => set("is_active", v)} />
      </div>
    </Modal>
  );
}
