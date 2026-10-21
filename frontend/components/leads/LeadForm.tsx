"use client";

import { useEffect, useState } from "react";
import { Building2, UserRound } from "lucide-react";
import { Combobox, Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { API, addDays, errorText, type Lead, type LeadLookups } from "@/lib/leads";

const EMPTY = {
  title: "", customer_id: "", company_name: "", contact_person: "", designation: "", phone: "", email: "",
  city: "", address: "", source_id: "", interest: "", estimated_value: "", currency: "PKR",
  expected_close_date: "", stage: "New", rating: "Warm", owner_id: "", remarks: "",
  follow_up_date: addDays(1), follow_up_type: "Call", follow_up_note: "",
};

/**
 * New lead or edit one. A lead is for one of our customers (pick them and their
 * details come with them) or for a new prospect (type the company in).
 */
export function LeadForm({ lead, lookups, customers, preset, onClose, onSaved }: {
  lead: Lead | null;
  lookups: LeadLookups | null;
  customers: { value: string; label: string }[];
  /** Start a new lead with these, e.g. from a customer gone quiet. */
  preset?: Partial<typeof EMPTY>;
  onClose: () => void;
  onSaved: (lead: Lead) => void;
}) {
  const [kind, setKind] = useState<"customer" | "prospect">(lead?.customer_id || preset?.customer_id ? "customer" : "prospect");
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (!lead) { setForm({ ...EMPTY, ...(preset ?? {}) }); return; }
    const s = (v: string | number | null | undefined) => (v == null ? "" : String(v));
    setForm({
      ...EMPTY, title: lead.title, customer_id: s(lead.customer_id), company_name: lead.company_name,
      contact_person: s(lead.contact_person), designation: s(lead.designation), phone: s(lead.phone),
      email: s(lead.email), city: s(lead.city), address: s(lead.address), source_id: s(lead.source_id),
      interest: s(lead.interest), estimated_value: lead.estimated_value ? String(lead.estimated_value) : "",
      currency: lead.currency, expected_close_date: s(lead.expected_close_date), stage: lead.stage,
      rating: lead.rating, owner_id: s(lead.owner_id), remarks: s(lead.remarks),
    });
  }, [lead]);   // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!form.title.trim()) { setError("Say in a line what they want."); return; }
    if (kind === "customer" && !form.customer_id) { setError("Choose the customer."); return; }
    if (kind === "prospect" && !form.company_name.trim()) { setError("Enter the company name."); return; }
    setSaving(true); setError(null);
    const body: Record<string, unknown> = { ...form, customer_id: kind === "customer" ? form.customer_id : "" };
    if (lead) { delete body.follow_up_date; delete body.follow_up_type; delete body.follow_up_note; }
    try {
      const saved = lead ? await api.put<Lead>(`${API}/${lead.id}`, body) : await api.post<Lead>(API, body);
      onSaved(saved);
    } catch (err) { setError(errorText(err, "Could not save the lead.")); } finally { setSaving(false); }
  };

  const tab = (value: typeof kind, icon: React.ReactNode, label: string, hint: string) => (
    <button type="button" onClick={() => setKind(value)}
      className={`flex flex-1 items-start gap-3 rounded-xl border px-4 py-3 text-left transition-colors ${
        kind === value ? "border-primary bg-primary/5" : "border-line hover:bg-hover"}`}>
      <span className={`mt-0.5 rounded-lg p-1.5 ${kind === value ? "bg-primary text-on-primary" : "bg-hover text-muted"}`}>{icon}</span>
      <span><b className="block text-[13px]">{label}</b><span className="text-[11.5px] text-muted">{hint}</span></span>
    </button>
  );

  return (
    <Modal title={lead ? `Lead ${lead.lead_number}` : "New lead"} open width="xl" saving={saving} error={error}
      onClose={onClose} onSave={save} saveLabel={lead ? "Apply Changes" : "Create lead"}>
      <div className="mb-4 flex gap-3 max-sm:flex-col">
        {tab("customer", <Building2 size={15} />, "One of our customers", "New business with someone who already buys from us")}
        {tab("prospect", <UserRound size={15} />, "New prospect", "A company we have not sold to yet")}
      </div>

      <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
        <div className="col-span-3 max-md:col-span-1">
          <Field label="What do they want?" required>
            <TextInput value={form.title} placeholder="2 x TKT plotters for the new cutting hall"
              onChange={(e) => set("title", e.target.value)} />
          </Field>
        </div>
        {kind === "customer" ? (
          <div className="col-span-2 max-md:col-span-1">
            <Field label="Customer" required>
              <Combobox value={form.customer_id} options={customers} placeholder="Search our customers…"
                onChange={(v) => set("customer_id", v)} emptyMessage="No customer by that name." />
            </Field>
          </div>
        ) : (
          <div className="col-span-2 max-md:col-span-1">
            <Field label="Company" required>
              <TextInput value={form.company_name} placeholder="Company name" onChange={(e) => set("company_name", e.target.value)} />
            </Field>
          </div>
        )}
        <Field label="City">
          <TextInput value={form.city} placeholder={kind === "customer" ? "From the customer when blank" : "Lahore"}
            onChange={(e) => set("city", e.target.value)} />
        </Field>
        <Field label="Contact Person">
          <TextInput value={form.contact_person} onChange={(e) => set("contact_person", e.target.value)} />
        </Field>
        <Field label="Designation">
          <TextInput value={form.designation} placeholder="Cutting Manager" onChange={(e) => set("designation", e.target.value)} />
        </Field>
        <Field label="Phone / WhatsApp">
          <TextInput value={form.phone} onChange={(e) => set("phone", e.target.value)} />
        </Field>
        <Field label="Email">
          <TextInput value={form.email} onChange={(e) => set("email", e.target.value)} />
        </Field>
        <Field label="Interested In">
          <TextInput value={form.interest} placeholder="Auto cutter, spare parts, inks…" onChange={(e) => set("interest", e.target.value)} />
        </Field>
        <Field label="Source">
          <Select value={form.source_id} placeholder="Not known" onChange={(e) => set("source_id", e.target.value)}
            options={(lookups?.sources ?? []).map((s) => ({ value: s.id, label: s.name }))} />
        </Field>
        <Field label="Estimated Value">
          <div className="flex gap-2">
            <select value={form.currency} onChange={(e) => set("currency", e.target.value)}
              className="w-24 rounded-lg border border-line bg-bg px-2 text-[13px] outline-none focus:border-primary">
              {["PKR", "USD", "EUR"].map((c) => <option key={c}>{c}</option>)}
            </select>
            <TextInput inputMode="decimal" value={form.estimated_value} placeholder="0"
              onChange={(e) => set("estimated_value", e.target.value.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1"))} />
          </div>
        </Field>
        <Field label="Expected to Close">
          <TextInput type="date" value={form.expected_close_date} onChange={(e) => set("expected_close_date", e.target.value)} />
        </Field>
        <Field label="Rating">
          <div className="flex gap-2">
            {(lookups?.ratings ?? ["Hot", "Warm", "Cold"]).map((r) => (
              <button key={r} type="button" onClick={() => set("rating", r)}
                className={`flex-1 rounded-lg border px-2 py-2.5 text-[12.5px] font-medium transition-colors ${
                  form.rating === r ? (r === "Hot" ? "border-rose bg-rose/10 text-rose" : r === "Warm"
                    ? "border-amber bg-amber/10 text-amber" : "border-sky bg-sky/10 text-sky") : "border-line text-muted hover:bg-hover"}`}>
                {r}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Owner (salesperson)">
          <Select value={form.owner_id} placeholder={lead ? "Unassigned" : "Me"} onChange={(e) => set("owner_id", e.target.value)}
            options={(lookups?.users ?? []).map((u) => ({ value: u.id, label: u.name }))} />
        </Field>
        {lead && (
          <Field label="Stage">
            <Select value={form.stage} placeholder="New" onChange={(e) => set("stage", e.target.value)}
              options={(lookups?.stages ?? []).filter((s) => s.name !== "Lost").map((s) => ({ value: s.name, label: `${s.name} (${s.probability}%)` }))} />
          </Field>
        )}
        <div className={lead ? "col-span-2 max-md:col-span-1" : "col-span-3 max-md:col-span-1"}>
          <Field label="Notes">
            <TextArea rows={2} value={form.remarks} onChange={(e) => set("remarks", e.target.value)} />
          </Field>
        </div>
      </div>

      {!lead && (
        <div className="mt-4 rounded-xl border border-dashed border-primary/40 bg-primary/5 p-4">
          <p className="m-0 mb-3 text-[12.5px] font-semibold text-primary">First follow-up — every lead starts with a next step</p>
          <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
            <Field label="When">
              <TextInput type="date" value={form.follow_up_date} onChange={(e) => set("follow_up_date", e.target.value)} />
            </Field>
            <Field label="How">
              <Select value={form.follow_up_type} placeholder="Call" onChange={(e) => set("follow_up_type", e.target.value)}
                options={(lookups?.activity_types ?? []).filter((t) => t !== "Note").map((t) => ({ value: t, label: t }))} />
            </Field>
            <Field label="To do">
              <TextInput value={form.follow_up_note} placeholder="Introduce our range" onChange={(e) => set("follow_up_note", e.target.value)} />
            </Field>
          </div>
        </div>
      )}
    </Modal>
  );
}
