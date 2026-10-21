"use client";

import { useState } from "react";
import { ListScreen, dmyTime, yesNo, type ListColumn } from "@/components/calibration/ListScreen";
import { Field, Modal, Select, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { API, errorText, orNull } from "@/lib/calibration";

interface MachineDefinition {
  id: string;
  machine_category: string;
  vendor_name: string;
  model_number: string;
  origin: string | null;
  description: string | null;
  remarks: string | null;
  active: boolean;
  updated_at: string;
}

const EMPTY = { machine_category: "", vendor_name: "", model_number: "", origin: "", description: "", remarks: "", active: "Yes" };

const COLUMNS: ListColumn<MachineDefinition>[] = [
  { key: "machine_category", label: "Machine Category" },
  { key: "vendor_name", label: "Vendor Name" },
  { key: "model_number", label: "Model Number" },
  { key: "description", label: "Machine Description" },
  { key: "origin", label: "Origin" },
  { key: "active", label: "Active", value: (r) => yesNo(r.active), render: (r) => yesNo(r.active) },
  { key: "updated_at", label: "Last Updated", render: (r) => dmyTime(r.updated_at) },
];

export default function MachineDefinitionsPage() {
  const [editing, setEditing] = useState<MachineDefinition | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const show = (row: MachineDefinition | null) => {
    setEditing(row);
    setForm(row ? {
      machine_category: row.machine_category, vendor_name: row.vendor_name, model_number: row.model_number,
      origin: row.origin ?? "", description: row.description ?? "", remarks: row.remarks ?? "",
      active: row.active ? "Yes" : "No",
    } : { ...EMPTY });
    setError(null);
    setOpen(true);
  };

  const save = async () => {
    if (!form.machine_category.trim() || !form.vendor_name.trim() || !form.model_number.trim()) {
      setError("Machine Category, Vendor Name and Model Number are required."); return;
    }
    if (!form.active) { setError("Choose whether the machine is active."); return; }
    setSaving(true); setError(null);
    const body = {
      machine_category: form.machine_category.trim(), vendor_name: form.vendor_name.trim(),
      model_number: form.model_number.trim(), origin: orNull(form.origin), description: orNull(form.description),
      remarks: orNull(form.remarks), active: form.active === "Yes",
    };
    try {
      if (editing) await api.put(`${API}/machine-definitions/${editing.id}`, body);
      else await api.post(`${API}/machine-definitions`, body);
      setOpen(false); setReload((n) => n + 1);
    } catch (err) { setError(errorText(err, "Could not save the machine.")); } finally { setSaving(false); }
  };

  const remove = async () => {
    if (!editing || !confirm(`Delete ${editing.vendor_name} ${editing.model_number}?`)) return;
    try { await api.del(`${API}/machine-definitions/${editing.id}`); setOpen(false); setReload((n) => n + 1); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  return (
    <ListScreen<MachineDefinition>
      title="Machine Definitions" subtitle="The makes and models the company sells, services and calibrates."
      endpoint={`${API}/machine-definitions`} storageKey="calibration.machine-definitions"
      columns={COLUMNS} onCreate={() => show(null)} onEdit={show} reloadKey={reload}
      empty="No machines defined yet — Create New to add the first model.">
      <Modal title="Machine Definition" open={open} saving={saving} error={error} width="lg"
        onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Apply Changes" : "Create"}
        onDelete={editing ? remove : undefined} deleteLabel="Delete">
        <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
          <Field label="Machine Category" required>
            <TextInput value={form.machine_category} placeholder="AUTO CUTTER" onChange={(e) => set("machine_category", e.target.value)} />
          </Field>
          <Field label="Vendor Name" required>
            <TextInput value={form.vendor_name} placeholder="MORGAN TECNICA" onChange={(e) => set("vendor_name", e.target.value)} />
          </Field>
          <Field label="Model Number" required>
            <TextInput value={form.model_number} placeholder="NEXT2" onChange={(e) => set("model_number", e.target.value)} />
          </Field>
          <Field label="Origin">
            <TextInput value={form.origin} placeholder="Italy" onChange={(e) => set("origin", e.target.value)} />
          </Field>
          <Field label="Active" required>
            <Select value={form.active} placeholder="- Select -" options={[{ value: "Yes", label: "Yes" }, { value: "No", label: "No" }]}
              onChange={(e) => set("active", e.target.value)} />
          </Field>
          <div />
          <div className="col-span-3 grid grid-cols-2 gap-4 max-md:col-span-1 max-md:grid-cols-1">
            <Field label="Machine Description">
              <TextInput value={form.description} placeholder="AUTOMATIC CUTTER MACHINE" onChange={(e) => set("description", e.target.value)} />
            </Field>
            <Field label="Remarks">
              <TextInput value={form.remarks} onChange={(e) => set("remarks", e.target.value)} />
            </Field>
          </div>
        </div>
      </Modal>
    </ListScreen>
  );
}
