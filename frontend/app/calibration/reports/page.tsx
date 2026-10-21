"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { ListScreen, Pill, dmy, dmyTime, type ListColumn } from "@/components/calibration/ListScreen";
import { Combobox, Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { API, errorText, opts, orNull, todayIso, useCustomers, useLookups, useOptions } from "@/lib/calibration";

interface Report {
  id: string;
  certificate_number: string;
  customer_id: string;
  customer_name: string | null;
  customer_machine_id: string;
  calibration_definition_id: string;
  contract_id: string | null;
  contract_line_id: string | null;
  calibration_date: string;
  issue_date: string;
  expiry_date: string;
  next_calibration_date: string | null;
  technician_name: string | null;
  overall_result: string;
  report_status: string;
  temperature: string | null;
  relative_humidity: string | null;
  main_voltage: string | null;
  main_frequency: string | null;
  noise_level: string | null;
  comments: string | null;
  note: string | null;
  remarks: string | null;
  machine_code: string | null;
  vendor_name: string | null;
  model_number: string | null;
  serial_number: string | null;
  updated_at: string;
  results?: { seq: number; test_title: string; expected_result: string | null; unit: string | null; initial_reading: string | null;
              observed: string | null; uncertainty: string | null; passed: boolean | null; remarks: string | null }[];
}

interface Machine { id: string; label: string; machine_definition_id: string }
interface Definition {
  id: string; definition_name: string; version_number: number; validity_days: number; machine_definition_id: string;
  default_temperature: string | null; default_relative_humidity: string | null; default_main_voltage: string | null;
  default_main_frequency: string | null; default_noise_level: string | null; standard_comments: string | null;
  standard_note: string | null; tests?: { seq: number; test_title: string; expected_result: string | null; unit: string | null; active: boolean }[];
}
interface ContractLine { id: string; description: string; customer_machine_id: string | null }
interface Result { seq: string; test_title: string; expected_result: string; unit: string; initial_reading: string; observed: string; uncertainty: string; passed: string; remarks: string }

const EMPTY = {
  certificate_number: "", customer_id: "", customer_machine_id: "", calibration_definition_id: "", contract_id: "",
  contract_line_id: "", calibration_date: todayIso(), issue_date: todayIso(), expiry_date: "", next_calibration_date: "",
  technician_name: "", overall_result: "PENDING", report_status: "DRAFT", temperature: "", relative_humidity: "",
  main_voltage: "", main_frequency: "", noise_level: "", comments: "", note: "", remarks: "",
};
const emptyResult = (seq: number): Result => ({ seq: String(seq), test_title: "", expected_result: "", unit: "",
  initial_reading: "✓", observed: "✓", uncertainty: "0", passed: "Yes", remarks: "" });

const addDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

const COLUMNS: ListColumn<Report>[] = [
  { key: "certificate_number", label: "Certificate Number", render: (r) => <span className="whitespace-nowrap font-medium">{r.certificate_number}</span> },
  { key: "customer_name", label: "Customer" },
  { key: "machine_code", label: "Machine Code" },
  { key: "vendor_name", label: "Vendor" },
  { key: "model_number", label: "Model" },
  { key: "serial_number", label: "Serial Number" },
  { key: "calibration_date", label: "Calibration Date", render: (r) => dmy(r.calibration_date) },
  { key: "issue_date", label: "Issue Date", render: (r) => dmy(r.issue_date) },
  { key: "expiry_date", label: "Expiry Date", render: (r) => dmy(r.expiry_date) },
  { key: "next_calibration_date", label: "Next Calibration Date", render: (r) => dmy(r.next_calibration_date) },
  { key: "technician_name", label: "Technician" },
  { key: "overall_result", label: "Overall Result", render: (r) => <Pill value={r.overall_result} /> },
  { key: "report_status", label: "Report Status", render: (r) => <Pill value={r.report_status} /> },
  { key: "updated_at", label: "Last Updated", render: (r) => dmyTime(r.updated_at) },
];

export default function CalibrationReportsPage() {
  const lookups = useLookups();
  const customers = useCustomers();
  const [editing, setEditing] = useState<Report | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [results, setResults] = useState<Result[]>([emptyResult(1)]);
  const [contractLines, setContractLines] = useState<ContractLine[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [dueOnly, setDueOnly] = useState(false);
  const machines = useOptions<Machine>(form.customer_id ? `${API}/customer-machines?customer_id=${form.customer_id}` : null, (m) => m.label);
  const machine = machines.rows.find((m) => m.id === form.customer_machine_id);
  const definitions = useOptions<Definition>(
    machine ? `${API}/definitions?active_only=true&machine_definition_id=${machine.machine_definition_id}` : null,
    (d) => `${d.definition_name} (v${d.version_number}, ${d.validity_days} days)`);
  const contracts = useOptions<{ id: string; contract_number: string; reference: string | null }>(
    form.customer_id ? `${API}/contracts?customer_id=${form.customer_id}` : null,
    (c) => `${c.contract_number}${c.reference ? ` (${c.reference})` : ""}`);
  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const setResult = (i: number, patch: Partial<Result>) => setResults((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const loadContractLines = async (id: string) => {
    if (!id) { setContractLines([]); return; }
    try { setContractLines((await api.get<{ lines: ContractLine[] }>(`${API}/contracts/${id}`)).lines); }
    catch { setContractLines([]); }
  };

  /** Choosing the definition brings in its conditions, comments, note and tests. */
  const pickDefinition = async (id: string) => {
    set("calibration_definition_id", id);
    if (!id) return;
    try {
      const d = await api.get<Definition>(`${API}/definitions/${id}`);
      setForm((f) => ({
        ...f, calibration_definition_id: id,
        temperature: d.default_temperature ?? "", relative_humidity: d.default_relative_humidity ?? "",
        main_voltage: d.default_main_voltage ?? "", main_frequency: d.default_main_frequency ?? "",
        noise_level: d.default_noise_level ?? "", comments: d.standard_comments ?? "", note: d.standard_note ?? "",
        expiry_date: f.issue_date ? addDays(f.issue_date, d.validity_days) : f.expiry_date,
        next_calibration_date: f.issue_date ? addDays(f.issue_date, d.validity_days - 1) : f.next_calibration_date,
      }));
      const tests = (d.tests ?? []).filter((t) => t.active);
      if (tests.length) setResults(tests.map((t) => ({ ...emptyResult(t.seq), test_title: t.test_title,
        expected_result: t.expected_result ?? "", unit: t.unit ?? "" })));
    } catch (err) { setError(errorText(err, "Could not load the definition.")); }
  };

  const show = async (row: Report | null) => {
    setError(null);
    if (!row) { setEditing(null); setForm({ ...EMPTY }); setResults([emptyResult(1)]); setContractLines([]); setOpen(true); return; }
    try {
      const r = await api.get<Report>(`${API}/reports/${row.id}`);
      setEditing(r);
      const s = (v: string | null) => v ?? "";
      setForm({
        certificate_number: r.certificate_number, customer_id: r.customer_id, customer_machine_id: r.customer_machine_id,
        calibration_definition_id: r.calibration_definition_id, contract_id: s(r.contract_id), contract_line_id: s(r.contract_line_id),
        calibration_date: r.calibration_date, issue_date: r.issue_date, expiry_date: r.expiry_date,
        next_calibration_date: s(r.next_calibration_date), technician_name: s(r.technician_name),
        overall_result: r.overall_result, report_status: r.report_status, temperature: s(r.temperature),
        relative_humidity: s(r.relative_humidity), main_voltage: s(r.main_voltage), main_frequency: s(r.main_frequency),
        noise_level: s(r.noise_level), comments: s(r.comments), note: s(r.note), remarks: s(r.remarks),
      });
      setResults(r.results?.length ? r.results.map((x) => ({ seq: String(x.seq), test_title: x.test_title,
        expected_result: s(x.expected_result), unit: s(x.unit), initial_reading: s(x.initial_reading), observed: s(x.observed),
        uncertainty: s(x.uncertainty), passed: x.passed == null ? "" : x.passed ? "Yes" : "No", remarks: s(x.remarks) }))
        : [emptyResult(1)]);
      loadContractLines(r.contract_id ?? "");
      setOpen(true);
    } catch (err) { alert(errorText(err, "Could not open the report.")); }
  };

  const save = async () => {
    if (!form.customer_id) { setError("Choose the customer."); return; }
    if (!form.customer_machine_id) { setError("Choose the installed machine."); return; }
    if (!form.calibration_definition_id) { setError("Choose the calibration definition."); return; }
    if (!form.calibration_date || !form.issue_date) { setError("Enter the calibration and issue dates."); return; }
    setSaving(true); setError(null);
    const body = {
      certificate_number: orNull(form.certificate_number), customer_id: form.customer_id,
      customer_machine_id: form.customer_machine_id, calibration_definition_id: form.calibration_definition_id,
      contract_id: form.contract_id || null, contract_line_id: form.contract_line_id || null,
      calibration_date: form.calibration_date, issue_date: form.issue_date, expiry_date: form.expiry_date || null,
      next_calibration_date: form.next_calibration_date || null, technician_name: orNull(form.technician_name),
      overall_result: form.overall_result, report_status: form.report_status, temperature: orNull(form.temperature),
      relative_humidity: orNull(form.relative_humidity), main_voltage: orNull(form.main_voltage),
      main_frequency: orNull(form.main_frequency), noise_level: orNull(form.noise_level), comments: orNull(form.comments),
      note: orNull(form.note), remarks: orNull(form.remarks),
      results: results.filter((r) => r.test_title.trim()).map((r) => ({
        seq: r.seq ? Number(r.seq) : null, test_title: r.test_title.trim(), expected_result: orNull(r.expected_result),
        unit: orNull(r.unit), initial_reading: orNull(r.initial_reading), observed: orNull(r.observed),
        uncertainty: orNull(r.uncertainty), passed: r.passed === "" ? null : r.passed === "Yes", remarks: orNull(r.remarks) })),
    };
    try {
      if (editing) await api.put(`${API}/reports/${editing.id}`, body);
      else await api.post(`${API}/reports`, body);
      setOpen(false); setReload((n) => n + 1);
    } catch (err) { setError(errorText(err, "Could not save the report.")); } finally { setSaving(false); }
  };

  const remove = async () => {
    if (!editing || !confirm(`Delete ${editing.certificate_number}?`)) return;
    try { await api.del(`${API}/reports/${editing.id}`); setOpen(false); setReload((n) => n + 1); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  const text = (k: keyof typeof EMPTY, label: string, placeholder = "") => (
    <Field label={label}><TextInput value={form[k]} placeholder={placeholder} onChange={(e) => set(k, e.target.value)} /></Field>
  );
  const date = (k: keyof typeof EMPTY, label: string, required = false) => (
    <Field label={label} required={required}><TextInput type="date" value={form[k]} onChange={(e) => set(k, e.target.value)} /></Field>
  );

  return (
    <ListScreen<Report>
      title="Calibration Reports" subtitle="One calibration of one machine. Print gives the Certificate of Calibration."
      endpoint={`${API}/reports`} storageKey="calibration.reports" columns={COLUMNS}
      onCreate={() => show(null)} onEdit={show} reloadKey={reload}
      query={dueOnly ? "&due_within_days=30" : ""}
      toolbar={(
        <label className="flex items-center gap-2 text-[12.5px] text-muted">
          <input type="checkbox" checked={dueOnly} onChange={(e) => setDueOnly(e.target.checked)} />
          Due for calibration within 30 days
        </label>
      )}
      printPath={(r) => (r.report_status === "CANCELLED" ? null : `${API}/reports/${r.id}/print.pdf`)}
      empty="No calibration reports yet.">
      <Modal title={editing ? `Calibration Report ${editing.certificate_number}` : "Calibration Report"} open={open}
        saving={saving} error={error} width="xl" onClose={() => setOpen(false)} onSave={save}
        saveLabel={editing ? "Apply Changes" : "Create"}
        onDelete={editing && editing.report_status !== "ISSUED" ? remove : undefined} deleteLabel="Delete">
        <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
          <div className="col-span-2 max-md:col-span-1">
            <Field label="Customer" required>
              <Combobox value={form.customer_id} options={customers} placeholder="Search customer…"
                onChange={(v) => { setForm((f) => ({ ...f, customer_id: v, customer_machine_id: "", calibration_definition_id: "", contract_id: "", contract_line_id: "" })); setContractLines([]); }} />
            </Field>
          </div>
          {text("certificate_number", "Certificate Number (auto when blank)", "JT-26031-C01-OAP")}
          <div className="col-span-2 max-md:col-span-1">
            <Field label="Installed Machine" required>
              <Combobox value={form.customer_machine_id} options={machines.options} disabled={!form.customer_id}
                onChange={(v) => setForm((f) => ({ ...f, customer_machine_id: v, calibration_definition_id: "" }))}
                placeholder={form.customer_id ? "- Select -" : "Choose the customer first"}
                emptyMessage="Record this customer's machine under Customer Machines first." />
            </Field>
          </div>
          <Field label="Calibration Definition" required>
            <Combobox value={form.calibration_definition_id} options={definitions.options} disabled={!form.customer_machine_id}
              onChange={pickDefinition} placeholder={form.customer_machine_id ? "- Select -" : "Choose the machine first"}
              emptyMessage="No active calibration definition for this model." />
          </Field>
          <Field label="Contract">
            <Combobox value={form.contract_id} options={[{ value: "", label: "No contract" }, ...contracts.options]}
              disabled={!form.customer_id} placeholder="No contract"
              onChange={(v) => { setForm((f) => ({ ...f, contract_id: v, contract_line_id: "" })); loadContractLines(v); }} />
          </Field>
          <Field label="Contract Line">
            <Select value={form.contract_line_id} placeholder="- Select -" disabled={!form.contract_id}
              options={contractLines.map((l) => ({ value: l.id, label: l.description }))}
              onChange={(e) => set("contract_line_id", e.target.value)} />
          </Field>
          {text("technician_name", "Technician Name")}
          {date("calibration_date", "Calibration Date", true)}
          {date("issue_date", "Issue Date", true)}
          {date("expiry_date", "Expiry Date (from validity when blank)")}
          {date("next_calibration_date", "Next Calibration Date")}
          <Field label="Overall Result" required>
            <Select value={form.overall_result} placeholder="- Select -" options={opts(lookups?.overall_results)} onChange={(e) => set("overall_result", e.target.value)} />
          </Field>
          <Field label="Report Status" required>
            <Select value={form.report_status} placeholder="- Select -" options={opts(lookups?.report_statuses)} onChange={(e) => set("report_status", e.target.value)} />
          </Field>
          {text("temperature", "Temperature")}
          {text("relative_humidity", "Relative Humidity")}
          {text("main_voltage", "Main Voltage")}
          {text("main_frequency", "Main Frequency")}
          {text("noise_level", "Noise Level")}
          <div className="col-span-2 max-md:col-span-1">{text("note", "Note (printed under the tests)")}</div>
          <div className="col-span-3 grid grid-cols-2 gap-4 max-md:col-span-1 max-md:grid-cols-1">
            <Field label="Comments"><TextArea rows={3} value={form.comments} onChange={(e) => set("comments", e.target.value)} /></Field>
            <Field label="Remarks (not printed)"><TextArea rows={3} value={form.remarks} onChange={(e) => set("remarks", e.target.value)} /></Field>
          </div>
        </div>

        <div className="mt-5 overflow-hidden rounded-lg border border-line">
          <div className="flex items-center bg-sky/80 px-4 py-2.5 text-[13px] font-semibold text-white">
            Test Results
            <button onClick={() => setResults((rs) => [...rs, emptyResult(rs.length + 1)])}
              className="ml-auto flex items-center gap-1 rounded-md bg-white/20 px-2 py-1 text-[11.5px] hover:bg-white/30">
              <Plus size={12} /> Add
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left text-[12.5px]">
              <thead><tr className="border-b border-line text-[11.5px] text-muted">
                <th className="w-10 px-2 py-2" /><th className="w-14 px-2 py-2">Seq</th><th className="px-2 py-2">Test Title</th>
                <th className="w-28 px-2 py-2">Initial Reading</th><th className="w-28 px-2 py-2">Observed</th>
                <th className="w-28 px-2 py-2">Uncertainty</th><th className="w-24 px-2 py-2">Passed</th><th className="px-2 py-2">Remarks</th>
              </tr></thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} className="border-b border-line last:border-0">
                    <td className="px-2 py-1.5"><button onClick={() => setResults((rs) => rs.length > 1 ? rs.filter((_, j) => j !== i) : [emptyResult(1)])}
                      aria-label="Remove" className="text-rose"><Trash2 size={14} /></button></td>
                    <td className="px-2 py-1.5"><TextInput inputMode="numeric" value={r.seq} onChange={(e) => setResult(i, { seq: e.target.value.replace(/\D/g, "") })} /></td>
                    <td className="px-2 py-1.5"><TextInput value={r.test_title} onChange={(e) => setResult(i, { test_title: e.target.value })} /></td>
                    <td className="px-2 py-1.5"><TextInput value={r.initial_reading} onChange={(e) => setResult(i, { initial_reading: e.target.value })} /></td>
                    <td className="px-2 py-1.5"><TextInput value={r.observed} onChange={(e) => setResult(i, { observed: e.target.value })} /></td>
                    <td className="px-2 py-1.5"><TextInput value={r.uncertainty} onChange={(e) => setResult(i, { uncertainty: e.target.value })} /></td>
                    <td className="px-2 py-1.5"><Select value={r.passed} placeholder="—" options={opts(["Yes", "No"])} onChange={(e) => setResult(i, { passed: e.target.value })} /></td>
                    <td className="px-2 py-1.5"><TextInput value={r.remarks} onChange={(e) => setResult(i, { remarks: e.target.value })} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="m-0 border-t border-line px-4 py-2 text-[11px] text-faint">
            A reading of ✓ (or OK) prints as a tick on the certificate; anything else prints as typed.
          </p>
        </div>
      </Modal>
    </ListScreen>
  );
}
