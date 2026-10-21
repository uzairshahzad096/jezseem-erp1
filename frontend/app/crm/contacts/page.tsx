"use client";

import { useState } from "react";
import Link from "next/link";
import { MessageCircle, Star } from "lucide-react";
import { ListScreen, type ListColumn } from "@/components/calibration/ListScreen";
import { ContactForm } from "@/components/crm/ContactForm";
import { useCustomers } from "@/lib/calibration";
import type { Contact } from "@/lib/crm";

const wa = (n: string) => `https://wa.me/${n.replace(/\D/g, "").replace(/^0/, "92")}`;

const COLUMNS: ListColumn<Contact>[] = [
  { key: "contact_name", label: "Name", render: (r) => (
    <span className="font-medium">{r.contact_name}{r.is_primary && <Star size={11} className="ml-1 inline text-amber" />}
      {!r.is_active && <span className="ml-1.5 text-[11px] text-faint">inactive</span>}</span>) },
  { key: "customer_name", label: "Customer", render: (r) => (
    <Link href={`/crm/customers/${r.partner_id}`} onClick={(e) => e.stopPropagation()} className="hover:text-primary hover:underline">{r.customer_name}</Link>) },
  { key: "title", label: "Designation" },
  { key: "department", label: "Department" },
  { key: "cell", label: "Mobile", render: (r) => (r.cell ? <a href={`tel:${r.cell}`} className="hover:text-primary">{r.cell}</a> : "") },
  { key: "whatsapp", label: "WhatsApp", value: (r) => r.whatsapp || r.cell || "", render: (r) => {
    const n = r.whatsapp || r.cell;
    return n ? <a href={wa(n)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary"><MessageCircle size={12} />Message</a> : "";
  } },
  { key: "phone", label: "Office Phone" },
  { key: "email", label: "Email", render: (r) => (r.email ? <a href={`mailto:${r.email}`} className="hover:text-primary">{r.email}</a> : "") },
];

export default function ContactsPage() {
  const customers = useCustomers();
  const [editing, setEditing] = useState<Contact | "new" | null>(null);
  const [reload, setReload] = useState(0);
  return (
    <ListScreen<Contact> title="Contacts" subtitle="The people at our customers — who buys, who runs the cutting floor, who pays."
      endpoint="/crm/contacts" storageKey="crm.contacts" columns={COLUMNS} onCreate={() => setEditing("new")}
      onEdit={(r) => setEditing(r)} reloadKey={reload} noun="Contact"
      empty="No contacts yet. Add them here or from a customer's page.">
      {editing && (
        <ContactForm contact={editing === "new" ? null : editing} customers={customers} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); setReload((n) => n + 1); }} />
      )}
    </ListScreen>
  );
}
