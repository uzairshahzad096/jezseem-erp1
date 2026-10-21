"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Plus, Trash2, XCircle } from "lucide-react";
import { ListScreen, Pill, dmy, dmyTime, type ListColumn } from "@/components/calibration/ListScreen";
import { Combobox, Field, Modal, Select, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { API, errorText, money, opts, orNull, todayIso, useCustomers, useLookups, useOptions } from "@/lib/calibration";

interface Invoice {
  id: string;
  invoice_number: string;
  invoice_date: string;
  due_date: string | null;
  customer_id: string;
  customer_name: string | null;
  contract_id: string | null;
  contract_number: string | null;
  service_type: string;
  period_from: string | null;
  period_to: string | null;
  customer_po_number: string | null;
  currency: string;
  exchange_rate: number | null;
  payment_terms: string | null;
  remarks: string | null;
  status: string;
  in_ledger: boolean;
  excluding_tax_value: number;
  sales_tax_value: number;
  net_receivable: number;
  description: string;
  updated_at: string;
  lines?: { customer_machine_id: string | null; description: string; quantity: number; unit_price: number;
            discount_percent: number; tax_percent: number }[];
}

interface Line { customer_machine_id: string; description: string; quantity: string; unit_price: string; discount_percent: string; tax_percent: string }
interface Draft {
  customer_id: string; contract_id: string; service_type: string; period_from: string; period_to: string; currency: string;
  remarks: string; lines: { description: string; quantity: number; unit_price: number; discount_percent: number; tax_percent: number }[];
}

const EMPTY = {
  invoice_date: todayIso(), due_date: "", customer_id: "", contract_id: "", service_type: "Maintenance",
  period_from: "", period_to: "", customer_po_number: "", currency: "PKR", exchange_rate: "", payment_terms: "", remarks: "",
};
const emptyLine = (): Line => ({ customer_machine_id: "", description: "", quantity: "1", unit_price: "", discount_percent: "", tax_percent: "" });
const num = (v: string) => Number(v || 0);
const round = (n: number) => Math.round(n * 100) / 100;

function lineFigures(l: Line) {
  const gross = round(num(l.quantity) * num(l.unit_price));
  const taxable = round(gross - round(gross * num(l.discount_percent) / 100));
  const tax = round(taxable * num(l.tax_percent) / 100);
  return { taxable, tax, net: round(taxable + tax) };
}

const COLUMNS: ListColumn<Invoice>[] = [
  { key: "invoice_number", label: "Invoice Number", render: (r) => <span className="whitespace-nowrap font-medium">{r.invoice_number}</span> },
  { key: "invoice_date", label: "Invoice Date", render: (r) => dmy(r.invoice_date) },
  { key: "customer_name", label: "Customer" },
  { key: "service_type", label: "Service Type" },
  { key: "contract_number", label: "Contract" },
  { key: "period", label: "Period", value: (r) => r.period_from ?? "",
    render: (r) => (r.period_from ? <span className="whitespace-nowrap">{dmy(r.period_from)} – {dmy(r.period_to)}</span> : "") },
  { key: "description", label: "Description", render: (r) => <span className="line-clamp-2 max-w-[280px]">{r.description}</span> },
  { key: "excluding_tax_value", label: "Value excl. Tax", numeric: true, render: (r) => money(r.excluding_tax_value) },
  { key: "sales_tax_value", label: "Sales Tax", numeric: true, render: (r) => money(r.sales_tax_value) },
  { key: "net_receivable", label: "Total", numeric: true, render: (r) => <b>{money(r.net_receivable)}</b> },
  { key: "currency", label: "Currency" },
  { key: "status", label: "Status", render: (r) => <Pill value={r.status} /> },
  { key: "in_ledger", label: "In Ledger", value: (r) => (r.in_ledger ? "Yes" : "No"), render: (r) => (r.in_ledger ? "Yes" : "No") },
  { key: "updated_at", label: "Last Updated", render: (r) => dmyTime(r.updated_at) },
];

export default function ServiceInvoicesPage() {
  const lookups = useLookups();
  const customers = useCustomers();
  const [editing, setEditing] = useState<Invoice | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const contracts = useOptions<{ id: string; contract_number: string; contract_status: string; reference: string | null }>(
    form.customer_id ? `${API}/contracts?customer_id=${form.customer_id}` : null,
    (c) => `${c.contract_number}${c.reference ? ` (${c.reference})` : ""} — ${c.contract_status}`);
  const machines = useOptions<{ id: string; label: string }>(
    form.customer_id ? `${API}/customer-machines?customer_id=${form.customer_id}` : null, (m) => m.label);
  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const setLine = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const locked = editing?.status === "Posted";

  const totals = useMemo(() => lines.reduce((t, l) => {
    const f = lineFigures(l);
    return { value: t.value + f.taxable, tax: t.tax + f.tax, net: t.net + f.net };
  }, { value: 0, tax: 0, net: 0 }), [lines]);

  const fromDraft = (d: Draft) => {
    setEditing(null);
    setForm({ ...EMPTY, customer_id: d.customer_id, contract_id: d.contract_id, service_type: d.service_type,
              period_from: d.period_from, period_to: d.period_to, currency: d.currency, remarks: d.remarks });
    setLines(d.lines.map((l) => ({ customer_machine_id: "", description: l.description, quantity: String(l.quantity),
      unit_price: String(l.unit_price), discount_percent: l.discount_percent ? String(l.discount_percent) : "",
      tax_percent: l.tax_percent ? String(l.tax_percent) : "" })));
    setError(null);
    setOpen(true);
  };

  /** Billing a contract: ?contract=<id> opens the next period's invoice, filled in. */
  const billContract = async (id: string) => {
    try { fromDraft(await api.get<Draft>(`${API}/contracts/${id}/next-invoice`)); }
    catch (err) { alert(errorText(err, "Could not prepare the invoice.")); }
  };
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("contract");
    if (id) { billContract(id); window.history.replaceState(null, "", window.location.pathname); }
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const show = async (row: Invoice | null) => {
    setError(null);
    if (!row) { setEditing(null); setForm({ ...EMPTY }); setLines([emptyLine()]); setOpen(true); return; }
    try {
      const inv = await api.get<Invoice>(`${API}/invoices/${row.id}`);
      setEditing(inv);
      setForm({
        invoice_date: inv.invoice_date, due_date: inv.due_date ?? "", customer_id: inv.customer_id,
        contract_id: inv.contract_id ?? "", service_type: inv.service_type, period_from: inv.period_from ?? "",
        period_to: inv.period_to ?? "", customer_po_number: inv.customer_po_number ?? "", currency: inv.currency,
        exchange_rate: inv.currency !== "PKR" && inv.exchange_rate ? String(inv.exchange_rate) : "",
        payment_terms: inv.payment_terms ?? "", remarks: inv.remarks ?? "",
      });
      setLines((inv.lines ?? []).map((l) => ({
        customer_machine_id: l.customer_machine_id ?? "", description: l.description, quantity: String(l.quantity),
        unit_price: String(l.unit_price), discount_percent: l.discount_percent ? String(l.discount_percent) : "",
        tax_percent: l.tax_percent ? String(l.tax_percent) : "" })));
      setOpen(true);
    } catch (err) { alert(errorText(err, "Could not open the invoice.")); }
  };

  const save = async (post: boolean) => {
    if (!form.customer_id) { setError("Choose the customer."); return; }
    if (!form.invoice_date) { setError("Enter the invoice date."); return; }
    const filled = lines.filter((l) => l.description.trim());
    if (!filled.length) { setError("Add at least one line."); return; }
    if (post && !(totals.net > 0)) { setError("The invoice total must be above zero to post it."); return; }
    if (form.currency !== "PKR" && !(num(form.exchange_rate) > 0)) { setError(`Enter the ${form.currency} exchange rate.`); return; }
    setSaving(true); setError(null);
    const body = {
      invoice_date: form.invoice_date, due_date: form.due_date || null, customer_id: form.customer_id,
      contract_id: form.contract_id || null, service_type: form.service_type, period_from: form.period_from || null,
      period_to: form.period_to || null, customer_po_number: orNull(form.customer_po_number), currency: form.currency,
      exchange_rate: form.currency === "PKR" ? null : form.exchange_rate, payment_terms: orNull(form.payment_terms),
      remarks: orNull(form.remarks), post,
      lines: filled.map((l) => ({ customer_machine_id: l.customer_machine_id || null, description: l.description.trim(),
        quantity: l.quantity || "0", unit_price: l.unit_price || "0", discount_percent: l.discount_percent || "0",
        tax_percent: l.tax_percent || "0" })),
    };
    try {
      if (editing) {
        await api.put(`${API}/invoices/${editing.id}`, body);
        if (post && editing.status === "Draft") await api.post(`${API}/invoices/${editing.id}/post`, {});
      } else await api.post(`${API}/invoices`, body);
      setOpen(false); setReload((n) => n + 1);
    } catch (err) { setError(errorText(err, "Could not save the invoice.")); } finally { setSaving(false); }
  };

  const act = async (row: Invoice, action: "post" | "cancel", reload: () => void) => {
    const question = action === "post"
      ? `Post ${row.invoice_number} to ${row.customer_name}'s ledger?`
      : `Cancel ${row.invoice_number}?${row.in_ledger ? " Its ledger entry will be reversed." : ""}`;
    if (!confirm(question)) return;
    try { await api.post(`${API}/invoices/${row.id}/${action}`, {}); reload(); }
    catch (err) { alert(errorText(err, `Could not ${action} the invoice.`)); }
  };

  const remove = async () => {
    if (!editing || !confirm(`Delete draft ${editing.invoice_number}?`)) return;
    try { await api.del(`${API}/invoices/${editing.id}`); setOpen(false); setReload((n) => n + 1); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  return (
    <ListScreen<Invoice>
      title="Invoices" subtitle="Calibration, maintenance and service invoices. Posting one bills the customer: it goes into their ledger, AR aging and Payment Receipts."
      endpoint={`${API}/invoices`} storageKey="calibration.invoices" columns={COLUMNS}
      onCreate={() => show(null)} onEdit={show} reloadKey={reload}
      printPath={(r) => (r.status === "Cancelled" ? null : `${API}/invoices/${r.id}/print.pdf`)}
      rowActions={(r, reload) => (
        <>
          {r.status === "Draft" && (
            <button onClick={() => act(r, "post", reload)} title="Post to the customer's ledger"
              className="flex items-center gap-1 whitespace-nowrap rounded-md bg-primary/10 px-2 py-1 text-[10.5px] font-medium text-primary hover:bg-primary/20">
              <CheckCircle2 size={11} /> Post
            </button>
          )}
          {r.status !== "Cancelled" && (
            <button onClick={() => act(r, "cancel", reload)} title="Cancel this invoice"
              className="flex items-center gap-1 whitespace-nowrap rounded-md bg-rose/10 px-2 py-1 text-[10.5px] font-medium text-rose hover:bg-rose/20">
              <XCircle size={11} /> Cancel
            </button>
          )}
        </>
      )}
      empty="No service invoices yet."
      footnote="A draft prints as a proforma. A posted invoice is Dr customer, Cr 4200 Sales - Services (and Output Sales Tax where charged); its amounts can no longer be edited — cancel it and enter a new one.">
      <Modal title={editing ? `Invoice ${editing.invoice_number}${locked ? " (posted)" : ""}` : "Service Invoice"} open={open}
        saving={saving} error={error} width="xl" onClose={() => setOpen(false)}
        onSave={() => save(false)} saveLabel={editing ? "Apply Changes" : "Save Draft"}
        onAlt={locked ? undefined : () => save(true)} altLabel="Save & Post"
        onDelete={editing?.status === "Draft" ? remove : undefined} deleteLabel="Delete">
        {locked && (
          <p className="mb-4 mt-0 rounded-lg bg-amber/10 px-3 py-2 text-[12px] text-amber">
            This invoice is in the ledger. You can change its references and remarks; to change the customer, date or amounts, cancel it and enter a new one.
          </p>
        )}
        <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
          <div className="col-span-2 max-md:col-span-1">
            <Field label="Customer" required>
              <Combobox value={form.customer_id} options={customers} disabled={locked}
                onChange={(v) => setForm((f) => ({ ...f, customer_id: v, contract_id: "" }))} placeholder="Search customer…" />
            </Field>
          </div>
          <Field label="Service Type" required>
            <Select value={form.service_type} placeholder="- Select -" options={opts(lookups?.service_types)} onChange={(e) => set("service_type", e.target.value)} />
          </Field>
          <Field label="Invoice Date" required>
            <TextInput type="date" value={form.invoice_date} disabled={locked} onChange={(e) => set("invoice_date", e.target.value)} />
          </Field>
          <Field label="Due Date">
            <TextInput type="date" value={form.due_date} onChange={(e) => set("due_date", e.target.value)} />
          </Field>
          <Field label="Customer PO #">
            <TextInput value={form.customer_po_number} onChange={(e) => set("customer_po_number", e.target.value)} />
          </Field>
          <Field label="Contract">
            <Combobox value={form.contract_id} options={[{ value: "", label: "No contract" }, ...contracts.options]}
              onChange={(v) => set("contract_id", v)} placeholder={form.customer_id ? "No contract" : "Choose the customer first"}
              disabled={!form.customer_id} />
          </Field>
          <Field label="Period From">
            <TextInput type="date" value={form.period_from} onChange={(e) => set("period_from", e.target.value)} />
          </Field>
          <Field label="Period To">
            <TextInput type="date" value={form.period_to} onChange={(e) => set("period_to", e.target.value)} />
          </Field>
          <Field label="Currency">
            <Select value={form.currency} placeholder="PKR" disabled={locked} options={opts(["PKR", "USD", "EUR"])} onChange={(e) => set("currency", e.target.value || "PKR")} />
          </Field>
          <Field label="Exchange Rate">
            <TextInput inputMode="decimal" value={form.exchange_rate} disabled={locked || form.currency === "PKR"}
              onChange={(e) => set("exchange_rate", e.target.value.replace(/[^\d.]/g, ""))} />
          </Field>
          <Field label="Payment Terms">
            <TextInput value={form.payment_terms} onChange={(e) => set("payment_terms", e.target.value)} />
          </Field>
        </div>

        <div className="mt-5 overflow-hidden rounded-lg border border-line">
          <div className="flex items-center bg-sky/80 px-4 py-2.5 text-[13px] font-semibold text-white">
            Invoice Lines
            {!locked && (
              <button onClick={() => setLines((ls) => [...ls, emptyLine()])} className="ml-auto flex items-center gap-1 rounded-md bg-white/20 px-2 py-1 text-[11.5px] hover:bg-white/30">
                <Plus size={12} /> Add
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left text-[12.5px]">
              <thead><tr className="border-b border-line text-[11.5px] text-muted">
                <th className="w-10 px-2 py-2" /><th className="w-56 px-2 py-2">Machine</th><th className="px-2 py-2">Description *</th>
                <th className="w-20 px-2 py-2">Qty</th><th className="w-28 px-2 py-2">Rate</th><th className="w-20 px-2 py-2">Disc %</th>
                <th className="w-20 px-2 py-2">Tax %</th><th className="w-28 px-2 py-2 text-right">Amount</th>
              </tr></thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i} className="border-b border-line last:border-0">
                    <td className="px-2 py-1.5">{!locked && (
                      <button onClick={() => setLines((ls) => ls.length > 1 ? ls.filter((_, j) => j !== i) : [emptyLine()])}
                        aria-label="Remove" className="text-rose"><Trash2 size={14} /></button>)}</td>
                    <td className="px-2 py-1.5">
                      <Combobox value={l.customer_machine_id} options={machines.options} disabled={!form.customer_id}
                        onChange={(v) => setLine(i, { customer_machine_id: v,
                          ...(!l.description ? { description: machines.rows.find((m) => m.id === v)?.label ?? "" } : {}) })}
                        placeholder="Optional" emptyMessage="No machines recorded for this customer." />
                    </td>
                    <td className="px-2 py-1.5"><TextInput value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} /></td>
                    {(["quantity", "unit_price", "discount_percent", "tax_percent"] as const).map((k) => (
                      <td key={k} className="px-2 py-1.5">
                        <TextInput inputMode="decimal" value={l[k]} disabled={locked}
                          onChange={(e) => setLine(i, { [k]: e.target.value.replace(/[^\d.]/g, "") })} />
                      </td>
                    ))}
                    <td className="px-2 py-1.5 text-right tabular-nums">{money(lineFigures(l).net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex justify-end gap-8 border-t border-line bg-hover/40 px-4 py-2.5 text-[12.5px]">
            <span>Value excl. tax <b className="tabular-nums">{money(totals.value)}</b></span>
            <span>Sales tax <b className="tabular-nums">{money(totals.tax)}</b></span>
            <span>Total <b className="tabular-nums">{form.currency} {money(totals.net)}</b></span>
          </div>
        </div>

        <div className="mt-4">
          <Field label="Remarks (printed)">
            <TextInput value={form.remarks} onChange={(e) => set("remarks", e.target.value)} />
          </Field>
        </div>
      </Modal>
    </ListScreen>
  );
}
