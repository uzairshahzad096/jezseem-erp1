"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { ListScreen, dmy, dmyTime, yesNo, type ListColumn } from "@/components/calibration/ListScreen";
import { Combobox, Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { API, errorText, orNull, useOptions } from "@/lib/calibration";

interface Test { seq: number | string; test_title: string; expected_result: string | null; unit: string | null; active: boolean; remarks: string | null }
interface Definition {
  id: string;
  machine_definition_id: string;
  definition_name: string;
  version_number: number;
  validity_days: number;
  effective_from: string | null;
  effective_to: string | null;
  default_temperature: string | null;
  default_relative_humidity: string | null;
  default_main_voltage: string | null;
  default_main_frequency: string | null;
  default_noise_level: string | null;
  active: boolean;
  standard_comments: string | null;
  standard_note: string | null;
  vendor_name: string | null;
  model_number: string | null;
  machine_category: string | null;
  test_count: number;
  updated_at: string;
  tests?: Test[];
}

interface Row { seq: string; test_title: string; expected_result: string; unit: string; active: string; remarks: string }

const EMPTY = {
  machine_definition_id: "", definition_name: "", version_number: "1", validity_days: "", effective_from: "", effective_to: "",
  default_temperature: "", default_relative_humidity: "", default_main_voltage: "", default_main_frequency: "",
  default_noise_level: "", active: "Yes", standard_comments: "", standard_note: "",
};
const emptyRow = (seq: number): Row => ({ seq: String(seq), test_title: "", expected_result: "", unit: "", active: "Yes", remarks: "" });

const COLUMNS: ListColumn<Definition>[] = [
  { key: "definition_name", label: "Definition Name", render: (r) => <span className="font-medium">{r.definition_name}</span> },
  { key: "vendor_name", label: "Vendor" },
  { key: "model_number", label: "Model" },
  { key: "machine_category", label: "Machine Category" },
  { key: "version_number", label: "Version", numeric: true },
  { key: "validity_days", label: "Validity Days", numeric: true },
  { key: "test_count", label: "Tests", numeric: true },
  { key: "effective_from", label: "Effective From", render: (r) => dmy(r.effective_from) },
  { key: "effective_to", label: "Effective To", render: (r) => dmy(r.effective_to) },
  { key: "active", label: "Active", value: (r) => yesNo(r.active), render: (r) => yesNo(r.active) },
  { key: "updated_at", label: "Last Updated", render: (r) => dmyTime(r.updated_at) },
];

export default function CalibrationDefinitionsPage() {
  const machines = useOptions<{ id: string; machine_category: string; vendor_name: string; model_number: string }>(
    `${API}/machine-definitions`, (m) => `${m.machine_category} — ${m.vendor_name} ${m.model_number}`);
  const [editing, setEditing] = useState<Definition | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [rows, setRows] = useState<Row[]>([emptyRow(1)]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const setRow = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const show = async (row: Definition | null) => {
    setError(null);
    if (!row) { setEditing(null); setForm({ ...EMPTY }); setRows([emptyRow(1)]); setOpen(true); return; }
    try {
      const d = await api.get<Definition>(`${API}/definitions/${row.id}`);
      setEditing(d);
      const s = (v: string | number | null) => (v == null ? "" : String(v));
      setForm({
        machine_definition_id: d.machine_definition_id, definition_name: d.definition_name,
        version_number: s(d.version_number), validity_days: s(d.validity_days), effective_from: s(d.effective_from),
        effective_to: s(d.effective_to), default_temperature: s(d.default_temperature),
        default_relative_humidity: s(d.default_relative_humidity), default_main_voltage: s(d.default_main_voltage),
        default_main_frequency: s(d.default_main_frequency), default_noise_level: s(d.default_noise_level),
        active: d.active ? "Yes" : "No", standard_comments: s(d.standard_comments), standard_note: s(d.standard_note),
      });
      setRows(d.tests?.length ? d.tests.map((t) => ({ seq: String(t.seq), test_title: t.test_title,
        expected_result: t.expected_result ?? "", unit: t.unit ?? "", active: t.active ? "Yes" : "No", remarks: t.remarks ?? "" }))
        : [emptyRow(1)]);
      setOpen(true);
    } catch (err) { alert(errorText(err, "Could not open the definition.")); }
  };

  const save = async () => {
    if (!form.machine_definition_id) { setError("Choose the machine definition."); return; }
    if (!form.definition_name.trim()) { setError("Enter the definition name."); return; }
    if (!(Number(form.version_number) > 0)) { setError("Enter the version number."); return; }
    if (!(Number(form.validity_days) > 0)) { setError("Enter the validity in days."); return; }
    setSaving(true); setError(null);
    const body = {
      machine_definition_id: form.machine_definition_id, definition_name: form.definition_name.trim(),
      version_number: Number(form.version_number), validity_days: Number(form.validity_days),
      effective_from: form.effective_from || null, effective_to: form.effective_to || null,
      default_temperature: orNull(form.default_temperature), default_relative_humidity: orNull(form.default_relative_humidity),
      default_main_voltage: orNull(form.default_main_voltage), default_main_frequency: orNull(form.default_main_frequency),
      default_noise_level: orNull(form.default_noise_level), active: form.active === "Yes",
      standard_comments: orNull(form.standard_comments), standard_note: orNull(form.standard_note),
      tests: rows.filter((r) => r.test_title.trim()).map((r) => ({
        seq: r.seq ? Number(r.seq) : null, test_title: r.test_title.trim(), expected_result: orNull(r.expected_result),
        unit: orNull(r.unit), active: r.active !== "No", remarks: orNull(r.remarks) })),
    };
    try {
      if (editing) await api.put(`${API}/definitions/${editing.id}`, body);
      else await api.post(`${API}/definitions`, body);
      setOpen(false); setReload((n) => n + 1);
    } catch (err) { setError(errorText(err, "Could not save the definition.")); } finally { setSaving(false); }
  };

  const remove = async () => {
    if (!editing || !confirm(`Delete ${editing.definition_name}?`)) return;
    try { await api.del(`${API}/definitions/${editing.id}`); setOpen(false); setReload((n) => n + 1); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  const text = (k: keyof typeof EMPTY, label: string, placeholder = "") => (
    <Field label={label}><TextInput value={form[k]} placeholder={placeholder} onChange={(e) => set(k, e.target.value)} /></Field>
  );

  return (
    <ListScreen<Definition>
      title="Calibration Definitions" subtitle="The tests a machine model is calibrated against, with its validity and standard conditions."
      endpoint={`${API}/definitions`} storageKey="calibration.definitions" columns={COLUMNS}
      onCreate={() => show(null)} onEdit={show} reloadKey={reload}
      empty="No calibration definitions yet.">
      <Modal title="Calibration Definition" open={open} saving={saving} error={error} width="xl"
        onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Apply Changes" : "Create"}
        onDelete={editing ? remove : undefined} deleteLabel="Delete">
        <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
          <div className="col-span-2 max-md:col-span-1">
            <Field label="Machine Definition" required>
              <Combobox value={form.machine_definition_id} options={machines.options}
                onChange={(v) => set("machine_definition_id", v)} placeholder="Search machine…" />
            </Field>
          </div>
          {text("definition_name", "Definition Name *", "Auto Cutter 01")}
          <Field label="Version Number" required>
            <TextInput inputMode="numeric" value={form.version_number} onChange={(e) => set("version_number", e.target.value.replace(/\D/g, ""))} />
          </Field>
          <Field label="Validity Days" required>
            <TextInput inputMode="numeric" value={form.validity_days} placeholder="90" onChange={(e) => set("validity_days", e.target.value.replace(/\D/g, ""))} />
          </Field>
          <Field label="Effective From"><TextInput type="date" value={form.effective_from} onChange={(e) => set("effective_from", e.target.value)} /></Field>
          <Field label="Effective To"><TextInput type="date" value={form.effective_to} onChange={(e) => set("effective_to", e.target.value)} /></Field>
          {text("default_temperature", "Default Temperature", "35°C +/- 10°C")}
          {text("default_relative_humidity", "Default Relative Humidity", "50% +/- 10%")}
          {text("default_main_voltage", "Default Main Voltage", "3Φ, 400VAC")}
          {text("default_main_frequency", "Default Main Frequency", "50Hz +/- 1Hz")}
          {text("default_noise_level", "Default Noise Level", "<75 dBA")}
          <Field label="Active" required>
            <Select value={form.active} placeholder="- Select -" options={[{ value: "Yes", label: "Yes" }, { value: "No", label: "No" }]}
              onChange={(e) => set("active", e.target.value)} />
          </Field>
          <div className="col-span-2 max-md:col-span-1">{text("standard_note", "Standard Note", "CALIBRATION PASSED, INSTRUMENT IS CERTIFIED FOR OPERATION.")}</div>
          <div className="col-span-3 max-md:col-span-1">
            <Field label="Standard Comments (printed under Comments; one line each)">
              <TextArea rows={3} value={form.standard_comments} onChange={(e) => set("standard_comments", e.target.value)} />
            </Field>
          </div>
        </div>

        <div className="mt-5 overflow-hidden rounded-lg border border-line">
          <div className="flex items-center bg-sky/80 px-4 py-2.5 text-[13px] font-semibold text-white">
            Calibration Tests
            <button onClick={() => setRows((rs) => [...rs, emptyRow(rs.length + 1)])}
              className="ml-auto flex items-center gap-1 rounded-md bg-white/20 px-2 py-1 text-[11.5px] hover:bg-white/30">
              <Plus size={12} /> Add
            </button>
          </div>
          <table className="w-full border-collapse text-left text-[12.5px]">
            <thead><tr className="border-b border-line text-[11.5px] text-muted">
              <th className="w-10 px-2 py-2" /><th className="w-16 px-2 py-2">Seq</th><th className="px-2 py-2">Test Title *</th>
              <th className="px-2 py-2">Expected Result</th><th className="w-24 px-2 py-2">Unit</th><th className="w-24 px-2 py-2">Active</th>
              <th className="px-2 py-2">Remarks</th>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-line last:border-0">
                  <td className="px-2 py-1.5"><button onClick={() => setRows((rs) => rs.length > 1 ? rs.filter((_, j) => j !== i) : [emptyRow(1)])}
                    aria-label="Remove" className="text-rose"><Trash2 size={14} /></button></td>
                  <td className="px-2 py-1.5"><TextInput inputMode="numeric" value={r.seq} onChange={(e) => setRow(i, { seq: e.target.value.replace(/\D/g, "") })} /></td>
                  <td className="px-2 py-1.5"><TextInput value={r.test_title} placeholder="Knife perpendicular test" onChange={(e) => setRow(i, { test_title: e.target.value })} /></td>
                  <td className="px-2 py-1.5"><TextInput value={r.expected_result} onChange={(e) => setRow(i, { expected_result: e.target.value })} /></td>
                  <td className="px-2 py-1.5"><TextInput value={r.unit} onChange={(e) => setRow(i, { unit: e.target.value })} /></td>
                  <td className="px-2 py-1.5"><Select value={r.active} placeholder="- Select -" options={[{ value: "Yes", label: "Yes" }, { value: "No", label: "No" }]}
                    onChange={(e) => setRow(i, { active: e.target.value })} /></td>
                  <td className="px-2 py-1.5"><TextInput value={r.remarks} onChange={(e) => setRow(i, { remarks: e.target.value })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Modal>
    </ListScreen>
  );
}
