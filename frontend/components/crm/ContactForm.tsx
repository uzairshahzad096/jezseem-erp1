"use client";

import { useEffect, useState } from "react";
import { Combobox, Field, Modal, TextArea, TextInput, Toggle } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import type { Contact } from "@/lib/crm";
import { errorText } from "@/lib/leads";

const EMPTY = { partner_id: "", contact_name: "", title: "", department: "", phone: "", cell: "", whatsapp: "", email: "", description: "" };

/** Add or edit a person at a customer. */
export function ContactForm({ contact, customerId, customers, onClose, onSaved }: {
  contact: Contact | null;
  /** Fixed customer (from Customer 360); otherwise the form asks. */
  customerId?: string;
  customers?: { value: string; label: string }[];
  onClose: () => void;
  onSaved: (c: Contact) => void;
}) {
  const [form, setForm] = useState({ ...EMPTY });
  const [primary, setPrimary] = useState(false);
  const [active, setActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (!contact) { setForm({ ...EMPTY, partner_id: customerId ?? "" }); setPrimary(false); setActive(true); return; }
    const s = (v: string | null) => v ?? "";
    setForm({ partner_id: contact.partner_id, contact_name: contact.contact_name, title: s(contact.title),
              department: s(contact.department), phone: s(contact.phone), cell: s(contact.cell),
              whatsapp: s(contact.whatsapp), email: s(contact.email), description: s(contact.description) });
    setPrimary(contact.is_primary); setActive(contact.is_active);
  }, [contact, customerId]);

  const save = async () => {
    if (!form.partner_id) { setError("Choose the customer."); return; }
    if (!form.contact_name.trim()) { setError("Enter the name."); return; }
    setSaving(true); setError(null);
    try {
      const body = { ...form, is_primary: primary, is_active: active };
      const saved = contact ? await api.put<Contact>(`/crm/contacts/${contact.id}`, body)
        : await api.post<Contact>("/crm/contacts", body);
      onSaved(saved);
    } catch (err) { setError(errorText(err, "Could not save the contact.")); } finally { setSaving(false); }
  };

  return (
    <Modal title={contact ? `Contact — ${contact.contact_name}` : "New contact"} open width="lg" saving={saving}
      error={error} onClose={onClose} onSave={save} saveLabel={contact ? "Apply Changes" : "Add contact"}>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        {!customerId && (
          <div className="col-span-2 max-sm:col-span-1">
            <Field label="Customer" required>
              <Combobox value={form.partner_id} options={customers ?? []} onChange={(v) => set("partner_id", v)}
                placeholder="Search customer…" />
            </Field>
          </div>
        )}
        <Field label="Name" required><TextInput value={form.contact_name} placeholder="Mr. Kashif"
          onChange={(e) => set("contact_name", e.target.value)} /></Field>
        <Field label="Designation"><TextInput value={form.title} placeholder="Cutting Manager"
          onChange={(e) => set("title", e.target.value)} /></Field>
        <Field label="Department"><TextInput value={form.department} placeholder="Cutting / Purchase / Accounts"
          onChange={(e) => set("department", e.target.value)} /></Field>
        <Field label="Email"><TextInput value={form.email} onChange={(e) => set("email", e.target.value)} /></Field>
        <Field label="Mobile"><TextInput value={form.cell} placeholder="0300-0000000" onChange={(e) => set("cell", e.target.value)} /></Field>
        <Field label="WhatsApp (if different)"><TextInput value={form.whatsapp} onChange={(e) => set("whatsapp", e.target.value)} /></Field>
        <Field label="Office Phone"><TextInput value={form.phone} onChange={(e) => set("phone", e.target.value)} /></Field>
        <div className="flex items-end gap-6 pb-2">
          <Toggle label="Main contact" checked={primary} onChange={setPrimary} />
          <Toggle label="Active" checked={active} onChange={setActive} />
        </div>
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Notes"><TextArea rows={2} value={form.description} onChange={(e) => set("description", e.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  );
}
