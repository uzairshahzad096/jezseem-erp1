"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FilePlus2, Plus, Trash2 } from "lucide-react";
import { ListScreen, Pill, dmy, dmyTime, yesNo, type ListColumn } from "@/components/calibration/ListScreen";
import { Combobox, Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { API, errorText, money, opts, orNull, todayIso, useCustomers, useLookups, useOptions } from "@/lib/calibration";

interface Contract {
  id: string;
  contract_number: string;
  reference: string | null;
  contract_date: string;
  customer_id: string;
  customer_name: string | null;
  contract_type: string;
  division: string | null;
  start_date: string;
  end_date: string | null;
  billing_frequency: string;
  currency: string;
  charge_amount: number;
  tax_applicable: boolean;
  tax_percent: number;
  without_tax_deduction: boolean;
  response_hours: number | null;
  spare_parts_by: string | null;
  service_coverage: string | null;
  additional_terms: string | null;
  contract_status: string;
  contract_owner: string | null;
  remarks: string | null;
  equipment: string;
  updated_at: string;
  lines?: { customer_machine_id: string | null; description: string; service_type: string | null;
            quantity: number; remarks: string | null }[];
  invoices?: { id: string; invoice_number: string; invoice_date: string; period_from: string | null;
               period_to: string | null; status: string; net_receivable: number }[];
}

interface Line { customer_machine_id: string; description: string; service_type: string; quantity: string; remarks: string }
interface Machine { id: string; label: string; machine_category: string | null; model_number: string | null }

const COVERAGE = "Routine maintenance including inspection and necessary adjustments.";

const EMPTY = {
  reference: "", contract_date: todayIso(), customer_id: "", contract_type: "MAINTENANCE", division: "",
  start_date: todayIso(), end_date: "", billing_frequency: "MONTHLY", currency: "PKR", charge_amount: "",
  tax_applicable: "No", tax_percent: "", without_tax_deduction: "Yes", response_hours: "24",
  spare_parts_by: "Customer", service_coverage: COVERAGE, additional_terms: "", contract_status: "DRAFT",
  contract_owner: "", remarks: "",
};
const emptyLine = (): Line => ({ customer_machine_id: "", description: "", service_type: "", quantity: "1", remarks: "" });

const COLUMNS: ListColumn<Contract>[] = [
  { key: "contract_number", label: "Contract Number", render: (r) => <span className="whitespace-nowrap font-medium">{r.contract_number}</span> },
  { key: "customer_name", label: "Customer" },
  { key: "contract_date", label: "Contract Date", render: (r) => dmy(r.contract_date) },
  { key: "start_date", label: "Start Date", render: (r) => dmy(r.start_date) },
  { key: "end_date", label: "End Date", render: (r) => dmy(r.end_date) },
  { key: "billing_frequency", label: "Billing Frequency" },
  { key: "charge_amount", label: "Charges", numeric: true, render: (r) => money(r.charge_amount) },
  { key: "currency", label: "Currency" },
  { key: "tax_applicable", label: "Tax Applicable", value: (r) => yesNo(r.tax_applicable), render: (r) => yesNo(r.tax_applicable) },
  { key: "contract_status", label: "Contract Status", render: (r) => <Pill value={r.contract_status} /> },
  { key: "contract_owner", label: "Contract Owner" },
  { key: "equipment", label: "Equipment" },
  { key: "updated_at", label: "Last Updated", render: (r) => dmyTime(r.updated_at) },
];

export default function ContractsPage() {
  const router = useRouter();
  const lookups = useLookups();
  const customers = useCustomers();
  const [editing, setEditing] = useState<Contract | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const machines = useOptions<Machine>(form.customer_id ? `${API}/customer-machines?customer_id=${form.customer_id}` : null,
    (m) => m.label);
  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const setLine = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  const show = async (row: Contract | null) => {
    setError(null);
    if (!row) { setEditing(null); setForm({ ...EMPTY }); setLines([emptyLine()]); setOpen(true); return; }
    try {
      const c = await api.get<Contract>(`${API}/contracts/${row.id}`);
      setEditing(c);
      setForm({
        reference: c.reference ?? "", contract_date: c.contract_date, customer_id: c.customer_id,
        contract_type: c.contract_type, division: c.division ?? "", start_date: c.start_date, end_date: c.end_date ?? "",
        billing_frequency: c.billing_frequency, currency: c.currency, charge_amount: String(c.charge_amount),
        tax_applicable: c.tax_applicable ? "Yes" : "No", tax_percent: c.tax_percent ? String(c.tax_percent) : "",
        without_tax_deduction: c.without_tax_deduction ? "Yes" : "No",
        response_hours: c.response_hours != null ? String(c.response_hours) : "", spare_parts_by: c.spare_parts_by ?? "",
        service_coverage: c.service_coverage ?? "", additional_terms: c.additional_terms ?? "",
        contract_status: c.contract_status, contract_owner: c.contract_owner ?? "", remarks: c.remarks ?? "",
      });
      setLines(c.lines?.length ? c.lines.map((l) => ({
        customer_machine_id: l.customer_machine_id ?? "", description: l.description, service_type: l.service_type ?? "",
        quantity: String(l.quantity), remarks: l.remarks ?? "" })) : [emptyLine()]);
      setOpen(true);
    } catch (err) { alert(errorText(err, "Could not open the contract.")); }
  };

  const save = async () => {
    if (!form.customer_id) { setError("Choose the customer."); return; }
    if (!form.contract_date || !form.start_date) { setError("Enter the contract date and start date."); return; }
    if (!(Number(form.charge_amount) >= 0) || form.charge_amount === "") { setError("Enter the charges per billing period."); return; }
    if (form.tax_applicable === "Yes" && !(Number(form.tax_percent) > 0)) { setError("Enter the sales tax %."); return; }
    if (!lines.some((l) => l.description.trim())) { setError("Add the equipment the contract covers."); return; }
    setSaving(true); setError(null);
    const body = {
      reference: orNull(form.reference), contract_date: form.contract_date, customer_id: form.customer_id,
      contract_type: form.contract_type, division: orNull(form.division), start_date: form.start_date,
      end_date: form.end_date || null, billing_frequency: form.billing_frequency, currency: form.currency || "PKR",
      charge_amount: form.charge_amount || "0", tax_applicable: form.tax_applicable === "Yes",
      tax_percent: form.tax_percent || "0", without_tax_deduction: form.without_tax_deduction === "Yes",
      response_hours: form.response_hours ? Number(form.response_hours) : null, spare_parts_by: orNull(form.spare_parts_by),
      service_coverage: orNull(form.service_coverage), additional_terms: orNull(form.additional_terms),
      contract_status: form.contract_status, contract_owner: orNull(form.contract_owner), remarks: orNull(form.remarks),
      lines: lines.filter((l) => l.description.trim()).map((l) => ({
        customer_machine_id: l.customer_machine_id || null, description: l.description.trim(),
        service_type: orNull(l.service_type), quantity: l.quantity || "1", remarks: orNull(l.remarks) })),
    };
    try {
      if (editing) await api.put(`${API}/contracts/${editing.id}`, body);
      else await api.post(`${API}/contracts`, body);
      setOpen(false); setReload((n) => n + 1);
    } catch (err) { setError(errorText(err, "Could not save the contract.")); } finally { setSaving(false); }
  };

  const remove = async () => {
    if (!editing || !confirm(`Delete ${editing.contract_number}?`)) return;
    try { await api.del(`${API}/contracts/${editing.id}`); setOpen(false); setReload((n) => n + 1); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  const pickMachine = (i: number, id: string) => {
    const m = machines.rows.find((x) => x.id === id);
    setLine(i, { customer_machine_id: id, ...(m && !lines[i].description ? { description: m.label } : {}) });
  };

  return (
    <ListScreen<Contract>
      title="Contracts" subtitle="Maintenance and calibration agreements. Print gives the agreement; Invoice bills the next period."
      endpoint={`${API}/contracts`} storageKey="calibration.contracts" columns={COLUMNS}
      onCreate={() => show(null)} onEdit={show} reloadKey={reload}
      printPath={(r) => `${API}/contracts/${r.id}/print.pdf`}
      actionsLabel="Invoice"
      rowActions={(r) => r.contract_status === "ACTIVE" ? (
        <button onClick={() => router.push(`/calibration/invoices?contract=${r.id}`)} title="Invoice the next period of this contract"
          className="flex items-center gap-1 whitespace-nowrap rounded-md bg-violet/10 px-2 py-1 text-[10.5px] font-medium text-violet hover:bg-violet/20">
          <FilePlus2 size={11} /> Invoice
        </button>
      ) : null}
      empty="No contracts yet — Create New to draw one up.">
      <Modal title={editing ? `Contract ${editing.contract_number}` : "Contract"} open={open} saving={saving} error={error} width="xl"
        onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Apply Changes" : "Create"}
        onDelete={editing ? remove : undefined} deleteLabel="Delete">
        <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
          <div className="col-span-2 max-md:col-span-1">
            <Field label="Customer" required>
              <Combobox value={form.customer_id} options={customers} onChange={(v) => set("customer_id", v)} placeholder="Search customer…" />
            </Field>
          </div>
          <Field label="Agreement Reference">
            <TextInput value={form.reference} placeholder="JEZ-TGR.-0026 (number used when blank)" onChange={(e) => set("reference", e.target.value)} />
          </Field>
          <Field label="Contract Date" required>
            <TextInput type="date" value={form.contract_date} onChange={(e) => set("contract_date", e.target.value)} />
          </Field>
          <Field label="Start Date" required>
            <TextInput type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)} />
          </Field>
          <Field label="End Date">
            <TextInput type="date" value={form.end_date} onChange={(e) => set("end_date", e.target.value)} />
          </Field>
          <Field label="Contract Type" required>
            <Select value={form.contract_type} placeholder="- Select -" options={opts(lookups?.contract_types)} onChange={(e) => set("contract_type", e.target.value)} />
          </Field>
          <Field label="Billing Frequency" required>
            <Select value={form.billing_frequency} placeholder="- Select -" options={opts(lookups?.billing_frequencies)} onChange={(e) => set("billing_frequency", e.target.value)} />
          </Field>
          <Field label="Division / Site">
            <TextInput value={form.division} placeholder="Cutting Division" onChange={(e) => set("division", e.target.value)} />
          </Field>
          <Field label="Charges per Billing Period" required>
            <TextInput inputMode="decimal" value={form.charge_amount} placeholder="20000"
              onChange={(e) => set("charge_amount", e.target.value.replace(/[^\d.]/g, ""))} />
          </Field>
          <Field label="Currency">
            <Select value={form.currency} placeholder="PKR" options={opts(["PKR", "USD", "EUR"])} onChange={(e) => set("currency", e.target.value)} />
          </Field>
          <Field label="Without Tax Deductions">
            <Select value={form.without_tax_deduction} placeholder="- Select -" options={opts(["Yes", "No"])} onChange={(e) => set("without_tax_deduction", e.target.value)} />
          </Field>
          <Field label="Tax Applicable">
            <Select value={form.tax_applicable} placeholder="- Select -" options={opts(["Yes", "No"])} onChange={(e) => set("tax_applicable", e.target.value)} />
          </Field>
          <Field label="Sales Tax %">
            <TextInput inputMode="decimal" value={form.tax_percent} disabled={form.tax_applicable !== "Yes"}
              onChange={(e) => set("tax_percent", e.target.value.replace(/[^\d.]/g, ""))} />
          </Field>
          <Field label="Contract Status" required>
            <Select value={form.contract_status} placeholder="- Select -" options={opts(lookups?.contract_statuses)} onChange={(e) => set("contract_status", e.target.value)} />
          </Field>
          <Field label="Complaint Response (hours)">
            <TextInput inputMode="numeric" value={form.response_hours} onChange={(e) => set("response_hours", e.target.value.replace(/\D/g, ""))} />
          </Field>
          <Field label="Spare Parts & Lubrication by">
            <Select value={form.spare_parts_by} placeholder="Not stated" options={opts(["Customer", "Jezseem Traders"])} onChange={(e) => set("spare_parts_by", e.target.value)} />
          </Field>
          <Field label="Contract Owner">
            <TextInput value={form.contract_owner} onChange={(e) => set("contract_owner", e.target.value)} />
          </Field>
        </div>

        <div className="mt-5 overflow-hidden rounded-lg border border-line">
          <div className="flex items-center bg-sky/80 px-4 py-2.5 text-[13px] font-semibold text-white">
            Equipment Covered
            <button onClick={() => setLines((ls) => [...ls, emptyLine()])} className="ml-auto flex items-center gap-1 rounded-md bg-white/20 px-2 py-1 text-[11.5px] hover:bg-white/30">
              <Plus size={12} /> Add
            </button>
          </div>
          <table className="w-full border-collapse text-left text-[12.5px]">
            <thead><tr className="border-b border-line text-[11.5px] text-muted">
              <th className="w-10 px-2 py-2" /><th className="px-2 py-2">Customer Machine (optional)</th>
              <th className="px-2 py-2">Equipment as printed *</th><th className="w-20 px-2 py-2">Qty</th><th className="px-2 py-2">Remarks</th>
            </tr></thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i} className="border-b border-line last:border-0">
                  <td className="px-2 py-1.5"><button onClick={() => setLines((ls) => ls.length > 1 ? ls.filter((_, j) => j !== i) : [emptyLine()])}
                    aria-label="Remove" className="text-rose"><Trash2 size={14} /></button></td>
                  <td className="w-72 px-2 py-1.5">
                    <Combobox value={l.customer_machine_id} options={machines.options} onChange={(v) => pickMachine(i, v)}
                      placeholder={form.customer_id ? "Any machine" : "Choose the customer first"} disabled={!form.customer_id}
                      emptyMessage="This customer has no machines recorded." />
                  </td>
                  <td className="px-2 py-1.5"><TextInput value={l.description} placeholder="Spreaders" onChange={(e) => setLine(i, { description: e.target.value })} /></td>
                  <td className="px-2 py-1.5"><TextInput inputMode="decimal" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value.replace(/[^\d.]/g, "") })} /></td>
                  <td className="px-2 py-1.5"><TextInput value={l.remarks} onChange={(e) => setLine(i, { remarks: e.target.value })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4 max-md:grid-cols-1">
          <Field label="Service Coverage (one point per line)">
            <TextArea rows={4} value={form.service_coverage} onChange={(e) => set("service_coverage", e.target.value)} />
          </Field>
          <Field label="Other Terms (one point per line)">
            <TextArea rows={4} value={form.additional_terms} onChange={(e) => set("additional_terms", e.target.value)} />
          </Field>
          <div className="col-span-2 max-md:col-span-1">
            <Field label="Remarks (not printed)">
              <TextInput value={form.remarks} onChange={(e) => set("remarks", e.target.value)} />
            </Field>
          </div>
        </div>
        <p className="mb-0 mt-3 text-[11.5px] leading-relaxed text-faint">
          The agreement prints the response time and who provides spare parts as Service Coverage points of their own,
          the charges in words, and the company&apos;s Meezan Bank account.
        </p>

        {editing?.invoices && editing.invoices.length > 0 && (
          <div className="mt-4">
            <p className="m-0 mb-1.5 text-[12px] font-semibold">Invoices on this contract</p>
            <table className="w-full border-collapse text-[12px]">
              <tbody>
                {editing.invoices.map((inv) => (
                  <tr key={inv.id} className="border-b border-line last:border-0">
                    <td className="py-1 pr-4 font-medium">{inv.invoice_number}</td>
                    <td className="py-1 pr-4">{dmy(inv.invoice_date)}</td>
                    <td className="py-1 pr-4 text-muted">{inv.period_from ? `${dmy(inv.period_from)} – ${dmy(inv.period_to)}` : ""}</td>
                    <td className="py-1 pr-4 text-right tabular-nums">{money(inv.net_receivable)}</td>
                    <td className="py-1"><Pill value={inv.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>
    </ListScreen>
  );
}
