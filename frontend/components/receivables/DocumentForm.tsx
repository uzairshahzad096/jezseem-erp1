"use client";

import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Field, Modal, Select, TextArea, TextInput, Toggle } from "@/components/ui/Modal";
import { PartnerPicker } from "@/components/finance/ui";
import { ProductPicker } from "@/components/procurement/ProductPicker";
import { errorText, money, useFinance, useFinanceContext } from "@/lib/finance";
import {
  CREDIT_REASONS, DOC_META, previewLine,
  type ARSettings, type DocDetail, type DocLine, type DocType, type PaymentTerm, type TaxCode,
} from "@/lib/receivables";

interface Prefill {
  customer_id?: string;
  customer_label?: string;
  source_document_id?: string | null;
  quotation_id?: string | null;
  gate_pass_id?: string | null;
  currency?: string;
  exchange_rate?: number;
  tax_inclusive?: boolean;
  location?: string | null;
  customer_po_number?: string | null;
  remarks?: string | null;
  source_label?: string;
  lines?: DocLine[];
}

const blankLine = (): DocLine => ({
  item_id: null, item_code: null, description: "", uom: null, quantity: "1", unit_price: "0",
  discount_percent: "0", tax_code_id: null,
});

/**
 * Create or edit a draft invoice, credit note or debit note. The totals shown
 * are a preview; the server recalculates on save, takes the tax rate from the
 * tax code, and checks every quantity against what the source order, gate
 * pass or invoice still allows.
 */
export function DocumentForm({
  docType, doc, prefill, onClose, onSaved,
}: {
  docType: DocType;
  doc: DocDetail | null;
  prefill?: Prefill | null;
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const meta = DOC_META[docType];
  const { data: ctx } = useFinanceContext();
  const { data: taxCodes } = useFinance<TaxCode[]>("/ar/tax-codes");
  const { data: terms } = useFinance<PaymentTerm[]>("/ar/payment-terms");
  const { data: settings } = useFinance<ARSettings>("/ar/settings");

  const source = doc ?? prefill ?? {};
  const [customerId, setCustomerId] = useState<string | null>(doc?.customer_id ?? prefill?.customer_id ?? null);
  const [customerLabel, setCustomerLabel] = useState<string | null>(
    doc ? `${doc.customer.code} ${doc.customer.name}` : prefill?.customer_label ?? null);
  const [docDate, setDocDate] = useState(doc?.doc_date ?? new Date().toISOString().slice(0, 10));
  const [termId, setTermId] = useState(doc?.payment_term_id ?? "");
  const [dueDate, setDueDate] = useState(doc?.due_date_overridden ? doc.due_date ?? "" : "");
  const [currency, setCurrency] = useState((source as Prefill).currency ?? doc?.currency ?? "PKR");
  const [rate, setRate] = useState(String(doc?.exchange_rate ?? prefill?.exchange_rate ?? 1));
  const [inclusive, setInclusive] = useState(doc?.tax_inclusive ?? prefill?.tax_inclusive ?? false);
  const [cashSale, setCashSale] = useState(doc?.is_cash_sale ?? false);
  const [cashAccount, setCashAccount] = useState(doc?.cash_account_id ?? "");
  const [branch, setBranch] = useState(doc?.branch_id ?? "");
  const [po, setPo] = useState(doc?.customer_po_number ?? prefill?.customer_po_number ?? "");
  const [location, setLocation] = useState(doc?.location ?? prefill?.location ?? "");
  const [billing, setBilling] = useState(doc?.billing_address ?? "");
  const [shipping, setShipping] = useState(doc?.shipping_address ?? "");
  const [remarks, setRemarks] = useState(doc?.remarks ?? prefill?.remarks ?? "");
  const [reasonCode, setReasonCode] = useState(doc?.reason_code ?? "");
  const [reason, setReason] = useState(doc?.reason ?? "");
  const [freight, setFreight] = useState(String(doc?.freight_amount ?? 0));
  const [docDiscount, setDocDiscount] = useState(() => {
    if (!doc) return "0";
    const lineDiscount = doc.lines.reduce((s, l) => s + (Number((l as unknown as { discount_amount: number }).discount_amount) || 0), 0);
    return String(Math.round((doc.discount_amount - lineDiscount) * 100) / 100);
  });
  const [lines, setLines] = useState<DocLine[]>(() => (doc?.lines ?? prefill?.lines ?? [blankLine()]).map((l) => ({
    ...l, quantity: String(l.quantity), unit_price: String(l.unit_price), discount_percent: String(l.discount_percent ?? 0),
  })));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const codes = useMemo(() => new Map((taxCodes ?? []).map((c) => [c.id, c])), [taxCodes]);
  const defaultTax = (taxCodes ?? []).find((c) => c.code === "GST18" && c.is_active)?.id ?? null;

  // Lines copied from a source carry a percentage but no code yet: match a
  // taxed rate to its code. A 0% line is left without one: exempt and
  // zero-rated are different treatments, and guessing between them is wrong.
  const codeFor = (l: DocLine) => l.tax_code_id
    ?? (Number(l.tax_percent ?? 0) > 0
      ? (taxCodes ?? []).find((c) => c.is_active && Number(c.rate) === Number(l.tax_percent))?.id ?? null
      : null);

  const computed = lines.map((l) => {
    const code = codes.get(codeFor(l) ?? "");
    return previewLine(Number(l.quantity) || 0, Number(l.unit_price) || 0, Number(l.discount_percent) || 0,
      code ? Number(code.rate) : 0, inclusive);
  });
  const taxable = computed.reduce((s, c) => s + c.taxable, 0);
  const tax = computed.reduce((s, c) => s + c.tax, 0);
  const total = taxable + tax + (Number(freight) || 0) - (Number(docDiscount) || 0);
  const isInvoice = docType === "sales_invoice";
  const fromSource = Boolean(prefill?.source_document_id || prefill?.gate_pass_id || doc?.source_document_id || doc?.gate_pass_id);

  const update = (i: number, patch: Partial<DocLine>) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, ...patch } : l)));

  const save = async () => {
    if (!customerId) { setError("Choose the customer."); return; }
    setSaving(true);
    setError(null);
    try {
      const body = {
        customer_id: customerId, doc_date: docDate, branch_id: branch || null,
        payment_term_id: termId || null, due_date: dueDate || null,
        currency, exchange_rate: rate || "1", tax_inclusive: inclusive,
        is_cash_sale: isInvoice && cashSale, cash_account_id: isInvoice && cashSale ? cashAccount || null : null,
        freight_amount: docType === "debit_note" ? "0" : freight || "0",
        document_discount: isInvoice ? docDiscount || "0" : "0",
        customer_po_number: po || null, location: location || null,
        billing_address: billing || null, shipping_address: shipping || null, remarks: remarks || null,
        source_document_id: doc?.source_document_id ?? prefill?.source_document_id ?? null,
        quotation_id: doc?.quotation_id ?? prefill?.quotation_id ?? null,
        gate_pass_id: doc?.gate_pass_id ?? prefill?.gate_pass_id ?? null,
        reason_code: reasonCode || null, reason: reason || null,
        lines: lines.map((l) => ({
          item_id: l.item_id, item_code: l.item_code, description: l.description, uom: l.uom,
          lot_number: l.lot_number ?? null, quantity: String(l.quantity), unit_price: String(l.unit_price),
          discount_percent: String(l.discount_percent || 0), tax_code_id: codeFor(l),
          source_line_id: l.source_line_id ?? null, gate_pass_line_id: l.gate_pass_line_id ?? null,
        })),
      };
      const saved = doc
        ? await api.put<DocDetail>(`/sales/${meta.path}/${doc.id}`, body)
        : await api.post<DocDetail>(`/sales/${meta.path}`, body);
      onSaved(saved.id);
    } catch (err) {
      setError(errorText(err, `Could not save the ${meta.label.toLowerCase()}.`));
    } finally {
      setSaving(false);
    }
  };

  const cell = "rounded-md border border-line bg-bg px-2 py-1.5 text-[12px] outline-none focus:border-primary";

  return (
    <Modal title={doc ? `Edit ${meta.label} ${doc.doc_number}` : `New ${meta.label}`} open width="xl"
           saving={saving} error={error} onClose={onClose} onSave={save} saveLabel="Save draft">
      {prefill?.source_label && (
        <p className="mb-4 rounded-lg bg-primary/10 px-3.5 py-2.5 text-[12.5px] text-primary">{prefill.source_label}</p>
      )}
      <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1">
        <Field label="Customer" required>
          {fromSource ? <TextInput value={customerLabel ?? ""} disabled /> : (
            <PartnerPicker role="customer" value={customerId} label={customerLabel}
              onChange={(id, label) => { setCustomerId(id); setCustomerLabel(label); }} />
          )}
        </Field>
        <Field label="Date" required>
          <TextInput type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} />
        </Field>
        {docType !== "credit_note" ? (
          <Field label="Payment terms">
            <Select value={termId} placeholder="Customer / company default" onChange={(e) => setTermId(e.target.value)}
              options={(terms ?? []).filter((t) => t.is_active).map((t) => ({ value: t.id, label: t.name }))} />
          </Field>
        ) : (
          <Field label="Reason">
            <Select value={reasonCode} placeholder="Choose…" onChange={(e) => setReasonCode(e.target.value)}
              options={CREDIT_REASONS.map(([v, l]) => ({ value: v, label: l }))} />
          </Field>
        )}
        <Field label={docType === "credit_note" ? "Branch" : "Due date (leave blank to calculate)"}>
          {docType === "credit_note" ? (
            <Select value={branch} placeholder="Company level" onChange={(e) => setBranch(e.target.value)}
              options={(ctx?.branches ?? []).map((b) => ({ value: b.id, label: b.name }))} />
          ) : <TextInput type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />}
        </Field>
        <Field label="Currency">
          <Select value={currency} placeholder="PKR" onChange={(e) => { setCurrency(e.target.value || "PKR"); if ((e.target.value || "PKR") === "PKR") setRate("1"); }}
            options={["PKR", "USD", "EUR", "GBP", "AED", "CNY"].map((c) => ({ value: c, label: c }))} />
        </Field>
        <Field label="Exchange rate to PKR">
          <TextInput value={rate} disabled={currency === "PKR"} inputMode="decimal" onChange={(e) => setRate(e.target.value)} />
        </Field>
        <Field label="Customer PO / reference">
          <TextInput value={po} onChange={(e) => setPo(e.target.value)} />
        </Field>
        {docType !== "credit_note" && (
          <Field label="Branch">
            <Select value={branch} placeholder="Company level" onChange={(e) => setBranch(e.target.value)}
              options={(ctx?.branches ?? []).map((b) => ({ value: b.id, label: b.name }))} />
          </Field>
        )}
        {docType === "credit_note" && (
          <Field label="Explanation">
            <TextInput value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why the credit is given" />
          </Field>
        )}
        <Toggle label="Prices include sales tax" checked={inclusive} onChange={setInclusive} />
        {isInvoice && <Toggle label="Cash sale (paid now)" checked={cashSale} onChange={setCashSale} />}
        {isInvoice && cashSale && (
          <Field label="Received into" required>
            <Select value={cashAccount} placeholder="Choose cash / bank account" onChange={(e) => setCashAccount(e.target.value)}
              options={(settings?.cash_accounts ?? []).map((a) => ({ value: a.id, label: a.label }))} />
          </Field>
        )}
        <Field label="Warehouse / location">
          <TextInput value={location} onChange={(e) => setLocation(e.target.value)} />
        </Field>
      </div>

      <div className="mt-5 overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[1100px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line text-[11.5px] font-semibold text-primary">
              <th className="w-8 px-2 py-2.5">#</th>
              <th className="w-[240px] px-2 py-2.5">Product</th>
              <th className="px-2 py-2.5">Description</th>
              <th className="w-[90px] px-2 py-2.5 text-right">Qty</th>
              <th className="w-[70px] px-2 py-2.5">Unit</th>
              <th className="w-[110px] px-2 py-2.5 text-right">Unit price</th>
              <th className="w-[70px] px-2 py-2.5 text-right">Disc %</th>
              <th className="w-[140px] px-2 py-2.5">Tax code</th>
              <th className="w-[110px] px-2 py-2.5 text-right">Taxable</th>
              <th className="w-[90px] px-2 py-2.5 text-right">Tax</th>
              <th className="w-[110px] px-2 py-2.5 text-right">Total</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i} className="border-b border-line last:border-0 align-top">
                <td className="px-2 py-1.5 text-[12px] text-faint">{i + 1}</td>
                <td className="px-2 py-1.5">
                  {l.source_line_id || l.gate_pass_line_id ? (
                    <span className="text-[12px] text-muted">{l.item_code ?? "—"}</span>
                  ) : (
                    <ProductPicker value={l.item_id} onPick={(p) => update(i, {
                      item_id: p.id, item_code: p.item_code, description: l.description || p.description,
                      uom: p.uom, unit_price: String(p.price ?? l.unit_price), tax_code_id: l.tax_code_id ?? defaultTax,
                    })} />
                  )}
                </td>
                <td className="px-2 py-1.5">
                  <input className={`${cell} w-full`} value={l.description} onChange={(e) => update(i, { description: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <input className={`${cell} w-full text-right tabular-nums`} inputMode="decimal" value={String(l.quantity)}
                    onChange={(e) => update(i, { quantity: e.target.value })} />
                  {l.max_quantity != null && (
                    <div className={`mt-0.5 text-right text-[10.5px] ${Number(l.quantity) > l.max_quantity ? "text-rose" : "text-faint"}`}>
                      max {l.max_quantity}
                    </div>
                  )}
                </td>
                <td className="px-2 py-1.5"><input className={`${cell} w-full`} value={l.uom ?? ""} onChange={(e) => update(i, { uom: e.target.value })} /></td>
                <td className="px-2 py-1.5">
                  <input className={`${cell} w-full text-right tabular-nums`} inputMode="decimal" value={String(l.unit_price)}
                    onChange={(e) => update(i, { unit_price: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <input className={`${cell} w-full text-right tabular-nums`} inputMode="decimal" value={String(l.discount_percent)}
                    onChange={(e) => update(i, { discount_percent: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <select className={`${cell} w-full`} value={codeFor(l) ?? ""} onChange={(e) => update(i, { tax_code_id: e.target.value || null })}>
                    <option value="">No tax</option>
                    {(taxCodes ?? []).filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </td>
                <td className="px-2 py-1.5 text-right text-[12px] tabular-nums">{money(computed[i].taxable)}</td>
                <td className="px-2 py-1.5 text-right text-[12px] tabular-nums">{money(computed[i].tax)}</td>
                <td className="px-2 py-1.5 text-right text-[12px] font-medium tabular-nums">{money(computed[i].total)}</td>
                <td className="px-1 py-1.5">
                  <button type="button" aria-label="Remove line" disabled={lines.length <= 1}
                    onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))}
                    className="rounded p-1 text-faint hover:bg-rose/10 hover:text-rose disabled:opacity-30">
                    <Trash2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!fromSource && (
        <button type="button" onClick={() => setLines((ls) => [...ls, { ...blankLine(), tax_code_id: defaultTax }])}
          className="mt-2 flex items-center gap-1 text-[12px] font-medium text-primary hover:underline">
          <Plus size={13} /> Add line
        </button>
      )}

      <div className="mt-4 grid grid-cols-[1fr_320px] gap-5 max-lg:grid-cols-1">
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="Billing address (blank = customer's address)">
            <TextArea rows={2} value={billing} onChange={(e) => setBilling(e.target.value)} />
          </Field>
          <Field label="Shipping address">
            <TextArea rows={2} value={shipping} onChange={(e) => setShipping(e.target.value)} />
          </Field>
          <div className="col-span-2 max-sm:col-span-1">
            <Field label="Notes"><TextArea rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></Field>
          </div>
        </div>
        <div className="space-y-2 rounded-lg border border-line bg-bg px-4 py-3 text-[12.5px]">
          <Row label="Taxable value">{money(taxable)}</Row>
          <Row label="Sales tax">{money(tax)}</Row>
          {docType !== "debit_note" && (
            <Row label="Freight">
              <input className={`${cell} w-28 text-right`} inputMode="decimal" value={freight} onChange={(e) => setFreight(e.target.value)} />
            </Row>
          )}
          {isInvoice && (
            <Row label="Document discount">
              <input className={`${cell} w-28 text-right`} inputMode="decimal" value={docDiscount} onChange={(e) => setDocDiscount(e.target.value)} />
            </Row>
          )}
          <div className="border-t border-line pt-2">
            <Row label={<b>Total ({currency})</b>}><b>{money(total)}</b></Row>
          </div>
          <p className="m-0 text-[10.5px] text-faint">Preview only; the server recalculates on save.</p>
        </div>
      </div>
    </Modal>
  );
}

function Row({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-3"><span className="text-muted">{label}</span><span className="tabular-nums">{children}</span></div>;
}
