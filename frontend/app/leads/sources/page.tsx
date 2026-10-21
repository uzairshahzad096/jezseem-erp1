"use client";

import { useState } from "react";
import { ListScreen, type ListColumn } from "@/components/calibration/ListScreen";
import { Field, Modal, Select, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { API, errorText, money } from "@/lib/leads";

interface Source {
  id: string; name: string; description: string | null; is_active: boolean; sort_order: number;
  leads: number; open: number; won: number; lost: number; won_value: number; win_rate: number | null;
}

const COLUMNS: ListColumn<Source>[] = [
  { key: "name", label: "Source", render: (r) => <span className="font-medium">{r.name}</span> },
  { key: "description", label: "Description", render: (r) => <span className="text-muted">{r.description ?? ""}</span> },
  { key: "leads", label: "Leads", numeric: true },
  { key: "open", label: "Open", numeric: true },
  { key: "won", label: "Won", numeric: true },
  { key: "lost", label: "Lost", numeric: true },
  { key: "win_rate", label: "Win Rate", numeric: true, value: (r) => r.win_rate ?? "",
    render: (r) => (r.win_rate == null ? "—" : (
      <span className="inline-flex items-center gap-2">
        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-hover"><span className="block h-full bg-primary" style={{ width: `${r.win_rate}%` }} /></span>
        {r.win_rate}%
      </span>)) },
  { key: "won_value", label: "Won Value (PKR)", numeric: true, render: (r) => money(r.won_value) },
  { key: "is_active", label: "Active", value: (r) => (r.is_active ? "Yes" : "No"),
    render: (r) => (r.is_active ? <span className="text-primary">Yes</span> : <span className="text-faint">No</span>) },
];

export default function SourcesPage() {
  const [editing, setEditing] = useState<Source | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", is_active: "Yes", sort_order: "100" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const show = (row: Source | null) => {
    setEditing(row);
    setForm(row ? { name: row.name, description: row.description ?? "", is_active: row.is_active ? "Yes" : "No",
                    sort_order: String(row.sort_order) } : { name: "", description: "", is_active: "Yes", sort_order: "100" });
    setError(null); setOpen(true);
  };
  const save = async () => {
    if (!form.name.trim()) { setError("Name the source."); return; }
    setSaving(true); setError(null);
    const body = { ...form, is_active: form.is_active === "Yes", sort_order: Number(form.sort_order || 100) };
    try {
      if (editing) await api.put(`${API}/sources/${editing.id}`, body); else await api.post(`${API}/sources`, body);
      setOpen(false); setReload((n) => n + 1);
    } catch (err) { setError(errorText(err, "Could not save.")); } finally { setSaving(false); }
  };
  const remove = async () => {
    if (!editing || !confirm(`Delete ${editing.name}?`)) return;
    try { await api.del(`${API}/sources/${editing.id}`); setOpen(false); setReload((n) => n + 1); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  return (
    <ListScreen<Source> title="Lead Sources" subtitle="Where leads come from, and which sources turn into orders."
      endpoint={`${API}/sources/all`} storageKey="leads.sources" columns={COLUMNS} onCreate={() => show(null)}
      onEdit={show} reloadKey={reload} noun="Source">
      <Modal title={editing ? `Source — ${editing.name}` : "New source"} open={open} saving={saving} error={error}
        width="md" onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Apply Changes" : "Create"}
        onDelete={editing ? remove : undefined} deleteLabel="Delete">
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="Name" required><TextInput value={form.name} placeholder="IGATEX Exhibition"
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} /></Field>
          <Field label="Active"><Select value={form.is_active} placeholder="Yes" options={[{ value: "Yes", label: "Yes" }, { value: "No", label: "No" }]}
            onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.value }))} /></Field>
          <div className="col-span-2 max-sm:col-span-1">
            <Field label="Description"><TextInput value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} /></Field>
          </div>
          <Field label="Order in lists"><TextInput inputMode="numeric" value={form.sort_order}
            onChange={(e) => setForm((f) => ({ ...f, sort_order: e.target.value.replace(/\D/g, "") }))} /></Field>
        </div>
      </Modal>
    </ListScreen>
  );
}
