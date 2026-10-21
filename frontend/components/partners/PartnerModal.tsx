"use client";

import { useEffect, useState } from "react";
import { Modal, Field, TextInput, TextArea, Toggle, Combobox } from "@/components/ui/Modal";
import { COUNTRIES, INCOTERMS } from "@/lib/useProcurement";
import { currencyOptions } from "@/lib/currency";
import { api } from "@/lib/api";

export interface Partner {
  id: string; code: string; name: string;
  is_customer: boolean; is_supplier: boolean;
  is_international?: boolean;
  country?: string | null; country_of_origin?: string | null;
  currency?: string | null; incoterm?: string | null;
  bank_name?: string | null; bank_account_number?: string | null;
  bank_iban?: string | null; bank_swift?: string | null;
  address: string | null; city: string | null; territory: string | null;
  ntn: string | null; stn: string | null;
  phone: string | null; email: string | null;
  payment_terms: string | null; is_active: boolean;
}

const EMPTY = {
  code: "", name: "", address: "", city: "", territory: "",
  ntn: "", stn: "", phone: "", email: "", payment_terms: "",
  // What a supplier abroad needs beyond a local one. Without these an import
  // order cannot default its currency and the landed-costing report has no
  // country to group by.
  country: "", country_of_origin: "", currency: "", incoterm: "",
  bank_name: "", bank_account_number: "", bank_iban: "", bank_swift: "",
};

/**
 * Add or edit a customer / supplier. One record serves the whole system: once
 * saved, a customer can be picked on quotations, sales orders, invoices,
 * receipts and the General Ledger, and is listed under Accounts Receivable in
 * the Chart of Accounts. A new customer is offered the next code in the old
 * ERP's numbering.
 */
export function PartnerModal({ open, partner, prefill, onClose, onSaved }: {
  open: boolean;
  partner: Partner | null;
  /** Details to start a new customer from, e.g. a lead being converted. */
  prefill?: Partial<Record<keyof typeof EMPTY, string>>;
  onClose: () => void;
  onSaved: (saved: Partner) => void;
}) {
  const [form, setForm] = useState({ ...EMPTY });
  const [isCustomer, setIsCustomer] = useState(true);
  const [isSupplier, setIsSupplier] = useState(false);
  const [isInternational, setIsInternational] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const set = (key: keyof typeof EMPTY, value: string) => setForm((f) => ({ ...f, [key]: value }));

  useEffect(() => {
    if (!open) return;
    setFormError(null);
    if (partner) {
      const p = partner;
      setForm({
        code: p.code, name: p.name, address: p.address ?? "", city: p.city ?? "",
        territory: p.territory ?? "", ntn: p.ntn ?? "", stn: p.stn ?? "",
        phone: p.phone ?? "", email: p.email ?? "", payment_terms: p.payment_terms ?? "",
        country: p.country ?? "", country_of_origin: p.country_of_origin ?? "",
        currency: p.currency ?? "", incoterm: p.incoterm ?? "",
        bank_name: p.bank_name ?? "", bank_account_number: p.bank_account_number ?? "",
        bank_iban: p.bank_iban ?? "", bank_swift: p.bank_swift ?? "",
      });
      setIsCustomer(p.is_customer); setIsSupplier(p.is_supplier);
      setIsInternational(Boolean(p.is_international));
      return;
    }
    setForm({ ...EMPTY, ...(prefill ?? {}) });
    setIsCustomer(true); setIsSupplier(false); setIsInternational(false);
    let current = true;
    api.get<{ code: string | null }>("/partners/next-code?role=customer")
      .then((r) => { if (current && r.code) setForm((f) => (f.code ? f : { ...f, code: r.code as string })); })
      .catch(() => { /* the code is typed by hand instead */ });
    return () => { current = false; };
  }, [open, partner]);   // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!form.code.trim()) { setFormError("Code is required."); return; }
    if (!form.name.trim()) { setFormError("Name is required."); return; }
    if (!isCustomer && !isSupplier) {
      setFormError("A partner must be a customer, a supplier, or both."); return;
    }
    setSaving(true); setFormError(null);
    try {
      const body = {
        ...Object.fromEntries(
          Object.entries(form).map(([k, v]) => [k, (v as string).trim() || null]),
        ),
        code: form.code.trim(),
        name: form.name.trim(),
        is_customer: isCustomer,
        is_supplier: isSupplier,
        is_international: isInternational,
        is_active: partner ? partner.is_active : true,
      };
      const saved = partner
        ? await api.put<Partner>(`/partners/${partner.id}`, body)
        : await api.post<Partner>("/partners", body);
      onSaved(saved);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the partner.");
    } finally { setSaving(false); }
  };

  return (
    <Modal title={partner ? "Edit Partner" : "New customer / supplier"} open={open}
      saving={saving} error={formError} width="md"
      onClose={onClose} onSave={save} saveLabel={partner ? "Save" : "Create"}>
      <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
        <Field label="Code" required>
          <TextInput value={form.code} onChange={(e) => set("code", e.target.value)} />
        </Field>
        <Field label="Name" required>
          <TextInput value={form.name} onChange={(e) => set("name", e.target.value)} />
        </Field>
        <Field label="NTN #">
          <TextInput value={form.ntn} onChange={(e) => set("ntn", e.target.value)} />
        </Field>
        <Field label="STN #">
          <TextInput value={form.stn} onChange={(e) => set("stn", e.target.value)} />
        </Field>
        <Field label="Phone">
          <TextInput value={form.phone} onChange={(e) => set("phone", e.target.value)} />
        </Field>
        <Field label="Email">
          <TextInput value={form.email} onChange={(e) => set("email", e.target.value)} />
        </Field>
        <Field label="City">
          <TextInput value={form.city} onChange={(e) => set("city", e.target.value)} />
        </Field>
        <Field label="Territory">
          <TextInput value={form.territory} onChange={(e) => set("territory", e.target.value)} />
        </Field>
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Address (printed on invoices)">
            <TextArea value={form.address} onChange={(e) => set("address", e.target.value)} />
          </Field>
        </div>
        <div className="col-span-2 max-sm:col-span-1">
          <Field label="Payment Terms">
            <TextInput value={form.payment_terms} onChange={(e) => set("payment_terms", e.target.value)} />
          </Field>
        </div>
        <Toggle label="Is a customer" checked={isCustomer} onChange={setIsCustomer} />
        <Toggle label="Is a supplier" checked={isSupplier} onChange={setIsSupplier} />

        {/* Purchase orders can only be raised on an account marked as a
            supplier, so the rest of this only appears once it is. */}
        {isSupplier && (
          <div className="col-span-2 max-sm:col-span-1 rounded-[10px] border
                          border-line bg-bg p-4">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h4 className="m-0 text-[12.5px] font-semibold">Purchasing</h4>
              <Toggle label="Buys from abroad (import)" checked={isInternational}
                      onChange={setIsInternational} />
            </div>
            <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
              <Field label="Country">
                <Combobox value={form.country} allowCustom
                  options={COUNTRIES.map((c) => ({ value: c, label: c }))}
                  placeholder="Where the supplier is"
                  onChange={(v) => set("country", v)} />
              </Field>
              <Field label="Invoices in">
                <Combobox value={form.currency} allowCustom options={currencyOptions}
                  placeholder="PKR"
                  emptyMessage="Not a listed currency — saved as typed."
                  onChange={(v) => set("currency", v.toUpperCase())} />
              </Field>
              {isInternational && (
                <>
                  <Field label="Country of Origin">
                    <Combobox value={form.country_of_origin} allowCustom
                      options={COUNTRIES.map((c) => ({ value: c, label: c }))}
                      placeholder="Where the goods are made"
                      onChange={(v) => set("country_of_origin", v)} />
                  </Field>
                  <Field label="Incoterm">
                    <Combobox value={form.incoterm} allowCustom
                      options={INCOTERMS.map((c) => ({ value: c, label: c }))}
                      placeholder="FOB, CIF, …"
                      onChange={(v) => set("incoterm", v)} />
                  </Field>
                  <Field label="Bank">
                    <TextInput value={form.bank_name}
                      onChange={(e) => set("bank_name", e.target.value)} />
                  </Field>
                  <Field label="Bank Account">
                    <TextInput value={form.bank_account_number}
                      onChange={(e) => set("bank_account_number", e.target.value)} />
                  </Field>
                  <Field label="IBAN">
                    <TextInput value={form.bank_iban}
                      onChange={(e) => set("bank_iban", e.target.value)} />
                  </Field>
                  <Field label="SWIFT">
                    <TextInput value={form.bank_swift}
                      onChange={(e) => set("bank_swift", e.target.value)} />
                  </Field>
                </>
              )}
            </div>
            {isInternational && !form.currency && (
              <p className="mt-2 text-[11px] text-amber">
                Set a currency, or import orders on this account will default to
                PKR and be refused.
              </p>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
