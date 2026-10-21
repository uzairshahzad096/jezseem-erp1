"use client";

import { useState } from "react";
import { ListScreen, Pill, dmy, dmyTime, type ListColumn } from "@/components/calibration/ListScreen";
import { Combobox, Field, Modal, Select, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { API, errorText, opts, orNull, useCustomers, useLookups, useOptions } from "@/lib/calibration";

interface CustomerMachine {
  id: string;
  customer_id: string;
  customer_name: string | null;
  machine_definition_id: string;
  machine_code: string | null;
  serial_number: string | null;
  installation_date: string | null;
  machine_status: string;
  machine_location: string | null;
  remarks: string | null;
  machine_category: string | null;
  vendor_name: string | null;
  model_number: string | null;
  label: string;
  updated_at: string;
}

interface Definition { id: string; machine_category: string; vendor_name: string; model_number: string; active: boolean }

const EMPTY = {
  customer_id: "", machine_definition_id: "", machine_code: "", serial_number: "", installation_date: "",
  machine_status: "ACTIVE", machine_location: "", remarks: "",
};

const COLUMNS: ListColumn<CustomerMachine>[] = [
  { key: "customer_name", label: "Customer" },
  { key: "machine_code", label: "Machine Code" },
  { key: "machine_category", label: "Machine Category" },
  { key: "vendor_name", label: "Vendor" },
  { key: "model_number", label: "Model" },
  { key: "serial_number", label: "Serial Number" },
  { key: "installation_date", label: "Installation Date", render: (r) => dmy(r.installation_date) },
  { key: "machine_location", label: "Machine Location" },
  { key: "machine_status", label: "Machine Status", render: (r) => <Pill value={r.machine_status} /> },
  { key: "updated_at", label: "Last Updated", render: (r) => dmyTime(r.updated_at) },
];

export default function CustomerMachinesPage() {
  const lookups = useLookups();
  const customers = useCustomers();
  const defs = useOptions<Definition>(`${API}/machine-definitions?active_only=true`,
    (d) => `${d.machine_category} — ${d.vendor_name} ${d.model_number}`);
  const [customer, setCustomer] = useState("");
  const [editing, setEditing] = useState<CustomerMachine | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const show = (row: CustomerMachine | null) => {
    setEditing(row);
    setForm(row ? {
      customer_id: row.customer_id, machine_definition_id: row.machine_definition_id,
      machine_code: row.machine_code ?? "", serial_number: row.serial_number ?? "",
      installation_date: row.installation_date ?? "", machine_status: row.machine_status,
      machine_location: row.machine_location ?? "", remarks: row.remarks ?? "",
    } : { ...EMPTY, customer_id: customer });
    setError(null);
    setOpen(true);
  };

  const save = async () => {
    if (!form.customer_id) { setError("Choose the customer."); return; }
    if (!form.machine_definition_id) { setError("Choose the machine definition."); return; }
    if (!form.machine_status) { setError("Choose the machine status."); return; }
    setSaving(true); setError(null);
    const body = {
      customer_id: form.customer_id, machine_definition_id: form.machine_definition_id,
      machine_code: orNull(form.machine_code), serial_number: orNull(form.serial_number),
      installation_date: form.installation_date || null, machine_status: form.machine_status,
      machine_location: orNull(form.machine_location), remarks: orNull(form.remarks),
    };
    try {
      if (editing) await api.put(`${API}/customer-machines/${editing.id}`, body);
      else await api.post(`${API}/customer-machines`, body);
      setOpen(false); setReload((n) => n + 1);
    } catch (err) { setError(errorText(err, "Could not save the machine.")); } finally { setSaving(false); }
  };

  const remove = async () => {
    if (!editing || !confirm("Delete this customer machine?")) return;
    try { await api.del(`${API}/customer-machines/${editing.id}`); setOpen(false); setReload((n) => n + 1); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  return (
    <ListScreen<CustomerMachine>
      title="Customer Machines" subtitle="Which machine is installed at which customer — pick a customer to see all of theirs."
      endpoint={`${API}/customer-machines`} storageKey="calibration.customer-machines" columns={COLUMNS}
      onCreate={() => show(null)} onEdit={show} reloadKey={reload}
      query={customer ? `&customer_id=${customer}` : ""}
      toolbar={(
        <div className="w-72">
          <Combobox value={customer} options={[{ value: "", label: "All customers" }, ...customers]}
            onChange={setCustomer} placeholder="All customers" />
        </div>
      )}
      empty="No machines recorded at customers yet.">
      <Modal title="Customer Machine" open={open} saving={saving} error={error} width="lg"
        onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Apply Changes" : "Create"}
        onDelete={editing ? remove : undefined} deleteLabel="Delete">
        <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
          <Field label="Customer" required>
            <Combobox value={form.customer_id} options={customers} onChange={(v) => set("customer_id", v)}
              placeholder="Search customer…" emptyMessage="No customer by that name." />
          </Field>
          <Field label="General Machine Definition" required>
            <Combobox value={form.machine_definition_id} options={defs.options}
              onChange={(v) => set("machine_definition_id", v)} placeholder="Search machine…"
              emptyMessage="Add the model under Machine Definitions first." />
          </Field>
          <Field label="Machine Code">
            <TextInput value={form.machine_code} placeholder="Auto Cutter 01" onChange={(e) => set("machine_code", e.target.value)} />
          </Field>
          <Field label="Serial Number">
            <TextInput value={form.serial_number} onChange={(e) => set("serial_number", e.target.value)} />
          </Field>
          <Field label="Installation Date">
            <TextInput type="date" value={form.installation_date} onChange={(e) => set("installation_date", e.target.value)} />
          </Field>
          <Field label="Machine Status" required>
            <Select value={form.machine_status} placeholder="- Select -" options={opts(lookups?.machine_statuses)}
              onChange={(e) => set("machine_status", e.target.value)} />
          </Field>
          <Field label="Machine Location">
            <TextInput value={form.machine_location} placeholder="Lahore" onChange={(e) => set("machine_location", e.target.value)} />
          </Field>
          <Field label="Remarks">
            <TextInput value={form.remarks} onChange={(e) => set("remarks", e.target.value)} />
          </Field>
        </div>
      </Modal>
    </ListScreen>
  );
}
