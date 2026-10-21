"use client";

import { useEffect, useState } from "react";
import { FileText, Flame, Mail, MapPin, MessageCircle, Pencil, Phone, UserRound } from "lucide-react";
import { Combobox, Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import type { Contact } from "@/lib/crm";
import { addDays, errorText } from "@/lib/leads";

export const ACTIVITY_ICON: Record<string, React.ReactNode> = {
  Call: <Phone size={13} />, Visit: <MapPin size={13} />, WhatsApp: <MessageCircle size={13} />,
  Email: <Mail size={13} />, Meeting: <UserRound size={13} />, Demo: <Flame size={13} />,
  "Quotation Sent": <FileText size={13} />, Note: <Pencil size={13} />,
};
const TYPES = ["Call", "Visit", "WhatsApp", "Email", "Meeting", "Demo", "Quotation Sent", "Note"];

/** Log (or plan) something with a customer — a visit, a complaint call, a courtesy call. */
export function LogActivity({ customerId, customers, onClose, onSaved }: {
  customerId?: string;
  customers?: { value: string; label: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [customer, setCustomer] = useState(customerId ?? "");
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contact, setContact] = useState("");
  const [type, setType] = useState("Call");
  const [summary, setSummary] = useState("");
  const [outcome, setOutcome] = useState("");
  const [plan, setPlan] = useState(false);
  const [due, setDue] = useState(addDays(1));
  const [next, setNext] = useState("");
  const [nextNote, setNextNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setContact("");
    if (!customer) { setContacts([]); return; }
    api.get<{ items: Contact[] }>(`/crm/contacts?customer_id=${customer}&page_size=200`)
      .then((d) => setContacts(d.items)).catch(() => setContacts([]));
  }, [customer]);

  const save = async () => {
    if (!customer) { setError("Choose the customer."); return; }
    if (!summary.trim()) { setError(plan ? "Say what is to be done." : "Say what happened."); return; }
    setSaving(true); setError(null);
    try {
      await api.post("/crm/activities", {
        customer_id: customer, contact_id: contact, activity_type: type, summary, outcome: plan ? "" : outcome,
        due_date: plan ? due : "", next_follow_up_date: plan ? "" : next, next_follow_up_note: nextNote,
      });
      onSaved();
    } catch (err) { setError(errorText(err, "Could not save.")); } finally { setSaving(false); }
  };

  return (
    <Modal title={plan ? "Plan an activity" : "Log an activity"} open width="lg" saving={saving} error={error}
      onClose={onClose} onSave={save} saveLabel={plan ? "Add to-do" : "Log it"}>
      <div className="mb-4 flex flex-wrap gap-1.5">
        {TYPES.map((t) => (
          <button key={t} type="button" onClick={() => setType(t)}
            className={`flex items-center gap-1 rounded-full px-3 py-1.5 text-[12px] font-medium ${
              type === t ? "bg-primary text-on-primary" : "bg-hover text-muted hover:text-text"}`}>
            {ACTIVITY_ICON[t]} {t}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        {!customerId && (
          <Field label="Customer" required>
            <Combobox value={customer} options={customers ?? []} onChange={setCustomer} placeholder="Search customer…" />
          </Field>
        )}
        <Field label="With">
          <Select value={contact} placeholder={customer ? (contacts.length ? "Anyone there" : "No contacts recorded") : "Choose the customer first"}
            onChange={(e) => setContact(e.target.value)}
            options={contacts.map((c) => ({ value: c.id, label: `${c.contact_name}${c.title ? ` — ${c.title}` : ""}` }))} />
        </Field>
        <div className="col-span-2 max-sm:col-span-1">
          <Field label={plan ? "What is to be done" : "What happened"} required>
            <TextArea rows={3} value={summary} onChange={(e) => setSummary(e.target.value)}
              placeholder={plan ? "Visit to check the spreader's knife" : "Complaint about plotter ink — sent a technician"} />
          </Field>
        </div>
        <label className="col-span-2 flex items-center gap-2 text-[12.5px] text-muted max-sm:col-span-1">
          <input type="checkbox" checked={plan} onChange={(e) => setPlan(e.target.checked)} /> Plan it for later instead
        </label>
        {plan ? (
          <Field label="When"><TextInput type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
        ) : (
          <>
            <Field label="Outcome"><TextInput value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder="Resolved / to be quoted…" /></Field>
            <Field label="Next follow-up"><TextInput type="date" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
            {next && <Field label="Follow-up to do"><TextInput value={nextNote} onChange={(e) => setNextNote(e.target.value)} placeholder="Call to confirm" /></Field>}
          </>
        )}
      </div>
    </Modal>
  );
}
