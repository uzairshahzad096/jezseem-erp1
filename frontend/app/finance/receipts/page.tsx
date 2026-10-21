"use client";

import { Fragment, Suspense, useCallback, useEffect, useState } from "react";
import { GridActionChips, GridActionView, GridActions, useGridActions } from "@/components/ui/GridActions";
import { usePageSize } from "@/lib/usePageSize";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Plus, Printer, Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Field, Modal, Select, TextArea, TextInput } from "@/components/ui/Modal";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { JournalView } from "@/components/finance/JournalView";
import {
  Button, EmptyState, ErrorNote, PageHeader, PartnerPicker, ReasonDialog, Spinner, StatusBadge, filterClass,
} from "@/components/finance/ui";
import { PaymentBadge } from "@/components/receivables/DocumentScreen";
import { api } from "@/lib/api";
import { download, errorText, fmtDate, fmtDateTime, money, useFinance } from "@/lib/finance";
import type { ARSettings, OpenItem, PaymentMethod, Receipt } from "@/lib/receivables";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

function ReceiptsScreen() {
  const params = useSearchParams();
  const [rows, setRows] = useState<Receipt[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(params.get("open"));
  const [editing, setEditing] = useState<Receipt | "new" | null>(params.get("new") ? "new" : null);
  const [pageSize, setPageSize] = usePageSize("/ar/receipts", 25);
  // The Actions menu over the loaded receipts.
  const actions = useGridActions<Receipt>("payment-receipts", RECEIPT_COLUMNS);
  const shown = actions.apply(rows);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search) qs.set("search", search);
      if (status) qs.set("status", status);
      const data = await api.get<{ items: Receipt[]; total: number }>(`/ar/receipts?${qs}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(errorText(err, "Could not load receipts."));
    } finally {
      setLoading(false);
    }
  }, [page, search, status, pageSize]);
  useEffect(() => { const t = setTimeout(load, search ? 300 : 0); return () => clearTimeout(t); }, [load, search]);
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <AppShell title="Payment Receipts">
      <PageHeader title="Payment Receipts"
        subtitle="Money received from customers. Choose invoices to settle them, or choose none for an on-account receipt: it comes off the customer's balance at once and can be matched to invoices later.">
        <Button tone="primary" onClick={() => setEditing("new")}><Plus size={14} /> New payment receipt</Button>
      </PageHeader>
      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={total} noun="Receipt" resettable={Boolean(search || status)}
          onReset={() => { setSearch(""); setStatus(""); setPage(1); }} />
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Number, customer, cheque…"
              className="w-52 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint" />
          </div>
          <span className="ml-auto order-3"><GridActions state={actions} pageSize={pageSize}
            onPageSize={(n) => { setPageSize(n); setPage(1); }} /></span>
          <select className={filterClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {["DRAFT", "POSTED", "REVERSED", "CANCELLED"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <GridActionChips state={actions} />
        <GridActionView state={actions} rows={shown} total={total} />
        <ErrorNote message={error} />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse text-left">
            <thead><tr className="border-b border-line">
              <GridTh>Receipt</GridTh><GridTh>Date</GridTh><GridTh>Customer</GridTh><GridTh>Method</GridTh>
              <GridTh>Reference</GridTh><GridTh numeric>Amount</GridTh><GridTh numeric>Unallocated</GridTh>
              <GridTh>Status</GridTh><GridTh>Allocation</GridTh>
            </tr></thead>
            <tbody>
              {loading && <tr><td colSpan={9}><Spinner /></td></tr>}
              {!loading && shown.length === 0 && <tr><td colSpan={9}><EmptyState>No receipts yet.</EmptyState></td></tr>}
              {!loading && shown.map((r, i) => (
                <Fragment key={r.id}>
                {actions.breakBefore(shown, i) && (
                  <tr className="border-b border-line bg-primary/5"><td colSpan={9} className="px-4 py-2 text-[12px] font-semibold text-primary">
                    {actions.breakBefore(shown, i)}</td></tr>
                )}
                <tr className={`${gridRowClass(i)} cursor-pointer`} style={actions.rowStyle(r)} onClick={() => setViewing(r.id)}>
                  <td className={gridCellClass(false, "font-medium text-primary")}>{r.receipt_number}</td>
                  <td className={gridCellClass()}>{fmtDate(r.receipt_date)}</td>
                  <td className={gridCellClass()}>{r.customer_name}</td>
                  <td className={gridCellClass(false, "text-muted")}>{r.payment_method}</td>
                  <td className={gridCellClass(false, "text-muted")}>{r.cheque_number ?? r.reference}</td>
                  <td className={gridCellClass(true)}>{money(r.amount)}</td>
                  <td className={gridCellClass(true, r.unallocated ? "font-medium" : "text-faint")}>{money(r.unallocated)}</td>
                  <td className={gridCellClass()}><StatusBadge status={r.status} /></td>
                  <td className={gridCellClass()}><PaymentBadge status={r.allocation_status} /></td>
                </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{total.toLocaleString()} receipts</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
            <span className="px-2">Page {page} of {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>
      {viewing && <ReceiptView id={viewing} onClose={() => setViewing(null)} onChanged={load}
        onEdit={(r) => { setViewing(null); setEditing(r); }} />}
      {editing && (
        <ReceiptForm receipt={editing === "new" ? null : editing}
          presetCustomer={editing === "new" ? params.get("customer") : null}
          presetInvoice={editing === "new" ? params.get("invoice") : null}
          onClose={() => setEditing(null)} onSaved={(id) => { setEditing(null); load(); setViewing(id); }} />
      )}
    </AppShell>
  );
}

/** The receipt columns the Actions menu can filter, sort, group and chart. */
const RECEIPT_COLUMNS = [
  { key: "receipt_number", label: "Receipt" },
  { key: "receipt_date", label: "Date" },
  { key: "customer_name", label: "Customer" },
  { key: "payment_method", label: "Method" },
  { key: "reference", label: "Reference", value: (r: Receipt) => r.cheque_number ?? r.reference },
  { key: "amount", label: "Amount", numeric: true },
  { key: "unallocated", label: "Unallocated", numeric: true },
  { key: "status", label: "Status" },
  { key: "allocation_status", label: "Allocation" },
];

function AllocationGrid({ items, values, onChange, total }: {
  items: OpenItem[]; values: Record<string, string>; onChange: (v: Record<string, string>) => void; total: number;
}) {
  const allocated = Object.values(values).reduce((s, v) => s + (Number(v) || 0), 0);
  const autofill = () => {
    let left = total;
    const next: Record<string, string> = {};
    for (const item of [...items].sort((a, b) => (a.due_date ?? a.document_date).localeCompare(b.due_date ?? b.document_date))) {
      const take = Math.min(left, item.outstanding);
      if (take > 0) next[item.item_id] = String(Math.round(take * 100) / 100);
      left -= take;
    }
    onChange(next);
  };
  // Ticking an invoice pays it in full, or with what is left of the receipt
  // when that is less; with no amount typed yet, in full.
  const tick = (item: OpenItem, on: boolean) => {
    const next = { ...values };
    if (!on) { delete next[item.item_id]; onChange(next); return; }
    const used = Object.entries(next).reduce((s, [, v]) => s + (Number(v) || 0), 0);
    const left = total > 0 ? Math.max(0, total - used) : item.outstanding;
    const take = Math.min(item.outstanding, left > 0 ? left : item.outstanding);
    next[item.item_id] = String(Math.round(take * 100) / 100);
    onChange(next);
  };
  const ticked = (item: OpenItem) => Number(values[item.item_id]) > 0;
  const allTicked = items.length > 0 && items.every(ticked);
  return (
    <div className="rounded-lg border border-line">
      <div className="flex items-center gap-3 border-b border-line px-4 py-2.5 text-[12.5px]">
        <b>Allocate to open documents</b>
        <button type="button" onClick={autofill} className="text-primary hover:underline">Oldest first</button>
        <button type="button" onClick={() => onChange({})} className="text-muted hover:underline">Clear</button>
        <span className="ml-auto tabular-nums">
          Allocated {money(allocated)} · On account (not matched to an invoice) <b className={total - allocated < 0 ? "text-rose" : ""}>{money(total - allocated)}</b>
        </span>
      </div>
      {items.length === 0 ? <p className="m-0 px-4 py-4 text-[12.5px] text-faint">No open invoices; the whole amount is received on account.</p> : (
        <table className="w-full text-left text-[12.5px]">
          <thead><tr className="text-[11.5px] text-primary">
            <th className="w-10 py-2 pl-4">
              <input type="checkbox" aria-label="Select every invoice" checked={allTicked}
                onChange={(e) => (e.target.checked ? onChange(Object.fromEntries(items.map((i) => [i.item_id, String(i.outstanding)]))) : onChange({}))} />
            </th>
            <th className="px-2 py-2">Document</th><th className="px-2 py-2">Date</th>
            <th className="px-2 py-2">Due</th><th className="px-2 py-2 text-right">Outstanding</th><th className="w-40 px-4 py-2 text-right">Allocate</th></tr></thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.item_id} className={`cursor-pointer border-t border-line ${ticked(item) ? "bg-primary/5" : "hover:bg-hover/60"}`}
                onClick={(e) => { if ((e.target as HTMLElement).tagName !== "INPUT") tick(item, !ticked(item)); }}>
                <td className="py-1.5 pl-4">
                  <input type="checkbox" aria-label={`Select ${item.document_number}`} checked={ticked(item)}
                    onChange={(e) => tick(item, e.target.checked)} />
                </td>
                <td className="px-2 py-1.5">{item.document_number} <span className="text-[11px] text-faint">{item.item_type.toLowerCase()}</span></td>
                <td className="px-2 py-1.5">{fmtDate(item.document_date)}</td>
                <td className={`px-2 py-1.5 ${item.overdue ? "text-rose" : ""}`}>{fmtDate(item.due_date)}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">{money(item.outstanding)}</td>
                <td className="px-4 py-1.5 text-right">
                  <input inputMode="decimal" value={values[item.item_id] ?? ""}
                    onChange={(e) => onChange({ ...values, [item.item_id]: e.target.value })}
                    className={`w-32 rounded-md border bg-bg px-2 py-1 text-right text-[12px] outline-none focus:border-primary
                                ${Number(values[item.item_id]) > item.outstanding ? "border-rose" : "border-line"}`} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ReceiptForm({ receipt, presetCustomer, presetInvoice, onClose, onSaved }: {
  receipt: Receipt | null; presetCustomer: string | null; presetInvoice: string | null;
  onClose: () => void; onSaved: (id: string) => void;
}) {
  const { data: methods } = useFinance<PaymentMethod[]>("/ar/payment-methods");
  const { data: settings } = useFinance<ARSettings>("/ar/settings");
  const [customerId, setCustomerId] = useState<string | null>(receipt?.customer_id ?? presetCustomer);
  const [customerLabel, setCustomerLabel] = useState<string | null>(receipt ? `${receipt.customer_code} ${receipt.customer_name}` : null);
  const [date, setDate] = useState(receipt?.receipt_date ?? new Date().toISOString().slice(0, 10));
  const [methodId, setMethodId] = useState(receipt?.payment_method_id ?? "");
  const [accountId, setAccountId] = useState(receipt?.deposit_account_id ?? "");
  const [currency, setCurrency] = useState(receipt?.currency ?? "PKR");
  const [rate, setRate] = useState(receipt?.exchange_rate ? String(receipt.exchange_rate) : "1");
  // As on the old ERP's form: what reached the bank, and the tax the customer
  // kept back. The customer is credited with the two together.
  const [received, setReceived] = useState(receipt ? String(receipt.amount - (receipt.wht_amount ?? 0)) : "");
  const [withheld, setWithheld] = useState(receipt?.wht_amount ? String(receipt.wht_amount) : "");
  const amount = String(Math.round(((Number(received) || 0) + (Number(withheld) || 0)) * 100) / 100);
  // One "Cheque/Ref Number" box, as on the old form: a cheque number for a cheque, a reference otherwise.
  const [ref, setRef] = useState(receipt?.cheque_number ?? receipt?.reference ?? "");
  const [chequeDate, setChequeDate] = useState(receipt?.cheque_date ?? "");
  const [notes, setNotes] = useState(receipt?.notes ?? "");
  const [arrear, setArrear] = useState<number | null>(null);
  const [items, setItems] = useState<OpenItem[]>([]);
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries((receipt?.planned_allocations ?? []).map((p) => [p.item_id, p.amount])));
  const [picking, setPicking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!customerId) { setItems([]); setArrear(null); return; }
    api.get<OpenItem[]>(`/ar/customers/${customerId}/open-items`).then((list) => {
      setItems(list);
      if (presetInvoice && !receipt) {
        const target = list.find((i) => i.sales_document_id === presetInvoice);
        if (target) { setValues({ [target.item_id]: String(target.outstanding) }); setReceived(String(target.outstanding)); }
      }
    }).catch(() => setItems([]));
    // Arrear: what the customer owes before this receipt, from their ledger.
    api.get<{ customer_code: string; customer_name: string; net_balance: number }>(`/ar/customers/${customerId}/profile`)
      .then((p) => { setArrear(p.net_balance); if (!customerLabel) setCustomerLabel(`${p.customer_code} ${p.customer_name}`); })
      .catch(() => setArrear(null));
  }, [customerId]); // eslint-disable-line react-hooks/exhaustive-deps

  const method = (methods ?? []).find((m) => m.id === methodId);
  // The receiving accounts that fit the payment mode: cash into a cash
  // account, everything else (cheque, transfer, online) into a bank account.
  const accounts = !method ? [] : (settings?.cash_accounts ?? []).filter((a) =>
    method.kind === "CASH" ? a.control_type === "CASH" : a.control_type === "BANK");
  const selected = items.filter((i) => Number(values[i.item_id]) > 0);
  const selectedAmount = selected.reduce((sum, i) => sum + (Number(values[i.item_id]) || 0), 0);
  const foreign = currency !== "PKR";

  const save = async (postToo: boolean) => {
    if (!customerId) { setError("Choose the customer."); return; }
    setSaving(true);
    setError(null);
    try {
      const cheque = method?.kind === "CHEQUE";
      const body = {
        customer_id: customerId, receipt_date: date, payment_method_id: methodId,
        deposit_account_id: accountId || null, amount, wht_amount: withheld || "0",
        currency, exchange_rate: foreign ? rate || "1" : "1",
        reference: cheque ? receipt?.reference ?? null : ref || null,
        cheque_number: cheque ? ref || null : null, cheque_date: chequeDate || null,
        bank_name: receipt?.bank_name ?? null, notes: notes || null,
        allocations: Object.entries(values).filter(([, v]) => Number(v) > 0).map(([item_id, v]) => ({ item_id, amount: v })),
      };
      const saved = receipt ? await api.put<Receipt>(`/ar/receipts/${receipt.id}`, body)
        : await api.post<Receipt>("/ar/receipts", body);
      if (postToo) {
        try { await api.post(`/ar/receipts/${saved.id}/post`, {}); }
        catch (err) {
          // Saved as a draft; say why it was not posted and leave the form open on it.
          setError(`Saved as draft ${saved.receipt_number}, but not posted: ${errorText(err, "could not post.")}`);
          return;
        }
      }
      onSaved(saved.id);
    } catch (err) {
      setError(errorText(err, "Could not save the receipt."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={receipt ? `Edit payment receipt ${receipt.receipt_number}` : "Payment Receipt"} open width="lg"
           saving={saving} error={error} onClose={onClose}
           onAlt={() => save(false)} altLabel="Create" onSave={() => save(true)} saveLabel="Post Payment">
      <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
        <Field label="Payment Mode" required>
          <Select value={methodId} placeholder="Choose…"
            onChange={(e) => {
              setMethodId(e.target.value);
              const m = (methods ?? []).find((x) => x.id === e.target.value);
              const fits = (settings?.cash_accounts ?? []).filter((a) =>
                m?.kind === "CASH" ? a.control_type === "CASH" : a.control_type === "BANK");
              // The mode's own default if it fits, else the only account there is, else let them choose.
              setAccountId(fits.some((a) => a.id === m?.default_account_id) ? m!.default_account_id!
                : fits.length === 1 ? fits[0].id : "");
            }}
            options={(methods ?? []).filter((m) => m.is_active).map((m) => ({ value: m.id, label: m.name }))} />
        </Field>
        <Field label="Payment Date" required><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Currency">
          <Select value={currency} onChange={(e) => { setCurrency(e.target.value); if (e.target.value === "PKR") setRate("1"); }}
            options={["PKR", "USD", "EUR", "GBP", "AED"].map((c) => ({ value: c, label: c }))} />
        </Field>
        <Field label="Customer Code" required>
          <PartnerPicker role="customer" value={customerId} label={customerLabel}
            onChange={(id, label) => { setCustomerId(id); setCustomerLabel(label); setValues({}); }} />
        </Field>
        <Field label="Receiving Account" required>
          <Select value={accountId} disabled={!method}
            placeholder={!method ? "Choose the payment mode first" : method.kind === "CASH" ? "Cash account" : "Bank account"}
            onChange={(e) => setAccountId(e.target.value)}
            options={accounts.map((a) => ({ value: a.id, label: a.label }))} />
        </Field>
        <Field label="Conversion Rate">
          <TextInput inputMode="decimal" value={foreign ? rate : "1"} disabled={!foreign}
            onChange={(e) => setRate(e.target.value)} />
        </Field>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 max-md:grid-cols-1">
        <Field label="Received Amount" required>
          <TextInput inputMode="decimal" value={received} onChange={(e) => setReceived(e.target.value)} />
        </Field>
        <Field label="Wh Tax Deduction">
          <TextInput inputMode="decimal" value={withheld} placeholder="0.00" onChange={(e) => setWithheld(e.target.value)} />
        </Field>
        <Field label="Cheque/Ref Number" required={Boolean(method?.requires_reference)}>
          <TextInput value={ref} onChange={(e) => setRef(e.target.value)} />
        </Field>
        <Field label="Cheque/Ref Date"><TextInput type="date" value={chequeDate} onChange={(e) => setChequeDate(e.target.value)} /></Field>
        <Field label="Arrear">
          <TextInput value={arrear === null ? "" : money(arrear)} disabled placeholder="Choose the customer" />
        </Field>
        <Field label="Selected Invoice Amount">
          <TextInput value={money(selectedAmount)} disabled />
        </Field>
        <div className="col-span-2 max-md:col-span-1">
          <Field label="Remarks"><TextArea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        </div>
      </div>
      <p className="mb-0 mt-3 rounded-lg bg-hover/60 px-3.5 py-2.5 text-[12.3px] text-muted">
        The customer is credited with <b className="tabular-nums text-text">{currency} {money(Number(amount) || 0)}</b>
        {Number(withheld) > 0 && <> ({money(Number(received) || 0)} received + {money(Number(withheld))} tax withheld)</>}.
        Select no invoice for an <b>on-account receipt</b>.
      </p>

      <div className="mt-5 overflow-hidden rounded-lg border border-line">
        <div className="flex items-center gap-3 border-b border-line bg-primary/10 px-4 py-2.5">
          <b className="text-[13.5px]">Payment Receipt Details</b>
          <span className="text-[12px] text-muted">{selected.length} invoice{selected.length === 1 ? "" : "s"} · {money(selectedAmount)}</span>
          <button type="button" disabled={!customerId} onClick={() => setPicking((p) => !p)}
            title={customerId ? undefined : "Choose the customer first"}
            className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary to-primary-dark px-4 py-2
                       text-[13px] font-semibold text-on-primary shadow-md transition-opacity hover:opacity-90
                       disabled:cursor-not-allowed disabled:opacity-50">
            {picking ? "Done" : "Select Invoice"}
          </button>
        </div>
        {picking ? (
          <div className="p-3"><AllocationGrid items={items} values={values} onChange={setValues} total={Number(amount) || 0} /></div>
        ) : selected.length === 0 ? (
          <p className="m-0 px-4 py-6 text-center text-[12.5px] text-faint">
            {customerId ? "No invoice selected — the whole amount is received on account." : "Choose the customer, then Select Invoice."}
          </p>
        ) : (
          <table className="w-full text-left text-[12.5px]">
            <thead><tr className="text-[11.5px] text-primary"><th className="px-4 py-2">Invoice</th><th className="px-2 py-2">Date</th>
              <th className="px-2 py-2 text-right">Outstanding</th><th className="px-4 py-2 text-right">Paid now</th></tr></thead>
            <tbody>
              {selected.map((i) => (
                <tr key={i.item_id} className="border-t border-line">
                  <td className="px-4 py-1.5">{i.document_number}</td>
                  <td className="px-2 py-1.5">{fmtDate(i.document_date)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{money(i.outstanding)}</td>
                  <td className="px-4 py-1.5 text-right font-medium tabular-nums">{money(Number(values[i.item_id]))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Modal>
  );
}
function ReceiptView({ id, onClose, onChanged, onEdit }: {
  id: string; onClose: () => void; onChanged: () => void; onEdit: (r: Receipt) => void;
}) {
  const [r, setR] = useState<Receipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<"reverse" | "cancel" | "unallocate" | null>(null);
  const [allocationId, setAllocationId] = useState<string | null>(null);
  const [allocating, setAllocating] = useState(false);
  const [items, setItems] = useState<OpenItem[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [journal, setJournal] = useState<string | null>(null);

  const load = async () => {
    try { setR(await api.get<Receipt>(`/ar/receipts/${id}`)); } catch (err) { setError(errorText(err, "Could not load.")); }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const post = async () => {
    setBusy(true); setError(null);
    try { setR(await api.post<Receipt>(`/ar/receipts/${id}/post`, {})); onChanged(); }
    catch (err) { setError(errorText(err, "Could not post.")); } finally { setBusy(false); }
  };
  const startAllocate = async () => {
    setItems(await api.get<OpenItem[]>(`/ar/customers/${r!.customer_id}/open-items`));
    setValues({});
    setAllocating(true);
  };
  const allocate = async () => {
    setBusy(true); setError(null);
    try {
      setR(await api.post<Receipt>(`/ar/receipts/${id}/allocate`, {
        allocations: Object.entries(values).filter(([, v]) => Number(v) > 0).map(([item_id, amount]) => ({ item_id, amount })),
      }));
      setAllocating(false);
      onChanged();
    } catch (err) { setError(errorText(err, "Could not allocate.")); } finally { setBusy(false); }
  };

  return (
    <>
      <Modal title={r ? `Receipt ${r.receipt_number}` : "Receipt"} open width="lg" error={error} onClose={onClose}>
        {!r ? <p className="text-[12.5px] text-faint">Loading…</p> : (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2.5">
              <StatusBadge status={r.status} /><PaymentBadge status={r.allocation_status} />
              <div className="ml-auto flex flex-wrap gap-2">
                {r.status === "DRAFT" && <>
                  <Button onClick={() => onEdit(r)}>Edit</Button>
                  <Button tone="primary" busy={busy} onClick={post}>Post Payment</Button>
                  <Button tone="danger" onClick={() => setDialog("cancel")}>Cancel</Button>
                </>}
                {r.status === "POSTED" && <>
                  {r.unallocated > 0 && <Button tone="soft" onClick={startAllocate}>Allocate</Button>}
                  <Button onClick={() => download(`/ar/receipts/${r.id}/voucher.pdf`, `${r.receipt_number}.pdf`)
                    .catch(() => window.open(`${BASE}/ar/receipts/${r.id}/voucher.pdf`, "_blank"))}><Printer size={13} /> Voucher</Button>
                  <Button tone="danger" onClick={() => setDialog("reverse")}>Reverse</Button>
                </>}
              </div>
            </div>
            <dl className="grid grid-cols-4 gap-x-5 gap-y-3 text-[12.5px] max-md:grid-cols-2">
              <Fact label="Customer">{r.customer_code} {r.customer_name}</Fact>
              <Fact label="Date">{fmtDate(r.receipt_date)}</Fact>
              <Fact label="Amount">{r.currency} {money(r.amount)}</Fact>
              <Fact label="Method">{r.payment_method}</Fact>
              <Fact label="Received into">{r.deposit_account}</Fact>
              <Fact label="Reference">{r.cheque_number ? `Cheque ${r.cheque_number}${r.cheque_date ? ` · ${fmtDate(r.cheque_date)}` : ""}` : r.reference ?? "—"}</Fact>
              <Fact label="Journal">
                {r.journal ? <button className="text-primary hover:underline" onClick={() => setJournal(r.journal!.id)}>{r.journal.journal_number}</button> : "—"}
                {r.reversal_journal && <> · reversed <button className="text-primary hover:underline" onClick={() => setJournal(r.reversal_journal!.id)}>{r.reversal_journal.journal_number}</button></>}
              </Fact>
              <Fact label="Matched to invoices / on account">{money(r.allocated)} / {money(r.unallocated)}</Fact>
              {r.wht_amount > 0 && <Fact label="Received / tax withheld">{money(r.amount - r.wht_amount)} / {money(r.wht_amount)}</Fact>}
            </dl>
            {r.reverse_reason && <p className="m-0 rounded-lg bg-rose/10 px-3.5 py-2.5 text-[12.5px] text-rose">Reversed: {r.reverse_reason}</p>}

            {r.status === "DRAFT" && r.planned_allocations.length > 0 && (
              <div className="text-[12.5px]"><b>Planned allocations</b> (applied on posting):{" "}
                {r.planned_allocations.map((p) => `${p.document_number} ${money(Number(p.amount))}`).join(", ")}</div>
            )}
            {r.allocations.length > 0 && (
              <div>
                <div className="mb-1.5 text-[12px] font-semibold">Allocations</div>
                <ul className="m-0 list-none space-y-1 p-0 text-[12.5px]">
                  {r.allocations.map((a) => (
                    <li key={a.id} className={`flex items-center gap-3 ${a.status !== "ACTIVE" ? "text-faint line-through" : ""}`}>
                      <span className="w-24">{fmtDate(a.date)}</span>
                      <span className="flex-1">
                        {a.sales_document_id ? <Link className="text-primary hover:underline" href={`/finance/invoices?open=${a.sales_document_id}`}>{a.document_number}</Link> : a.document_number}
                      </span>
                      <span className="tabular-nums">{money(a.amount)}</span>
                      {a.status === "ACTIVE" && r.status === "POSTED" && (
                        <button className="text-[11.5px] text-rose hover:underline" onClick={() => { setAllocationId(a.id); setDialog("unallocate"); }}>undo</button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {allocating && (
              <div className="space-y-3">
                <AllocationGrid items={items} values={values} onChange={setValues} total={r.unallocated} />
                <div className="flex gap-2"><Button tone="primary" busy={busy} onClick={allocate}>Save allocation</Button>
                  <Button onClick={() => setAllocating(false)}>Close</Button></div>
              </div>
            )}
            <p className="m-0 text-[11.5px] text-faint">
              Created {r.created_by} {fmtDateTime(r.created_at)}{r.posted_by && ` · posted ${r.posted_by} ${fmtDateTime(r.posted_at)}`}
              {r.reversed_by && ` · reversed ${r.reversed_by} ${fmtDateTime(r.reversed_at)}`}
            </p>
          </div>
        )}
      </Modal>
      <ReasonDialog open={dialog === "reverse"} title={`Reverse ${r?.receipt_number ?? ""}`} confirmLabel="Reverse receipt"
        onClose={() => setDialog(null)}
        onConfirm={async (reason) => { setR(await api.post<Receipt>(`/ar/receipts/${id}/reverse`, { reason })); onChanged(); }}>
        <p className="m-0 text-[12.5px] text-muted">Every allocation is undone and a reversing entry takes the money out of the bank account. Use for bounced cheques and receipts entered in error.</p>
      </ReasonDialog>
      <ReasonDialog open={dialog === "cancel"} title="Cancel draft receipt" confirmLabel="Cancel receipt" required={false}
        onClose={() => setDialog(null)}
        onConfirm={async (reason) => { setR(await api.post<Receipt>(`/ar/receipts/${id}/cancel`, { reason })); onChanged(); }} />
      <ReasonDialog open={dialog === "unallocate"} title="Undo allocation" confirmLabel="Undo"
        onClose={() => setDialog(null)}
        onConfirm={async (reason) => { await api.post(`/ar/allocations/${allocationId}/unallocate`, { reason }); await load(); onChanged(); }} />
      {journal && <JournalView journalId={journal} onClose={() => setJournal(null)} onOpen={setJournal} />}
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="min-w-0"><dt className="text-[11px] text-faint">{label}</dt><dd className="m-0 truncate">{children}</dd></div>;
}

export default function ReceiptsPage() {
  return <Suspense><ReceiptsScreen /></Suspense>;
}
