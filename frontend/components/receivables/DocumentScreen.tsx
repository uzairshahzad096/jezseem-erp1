"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Plus, Printer, Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal } from "@/components/ui/Modal";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { JournalView } from "@/components/finance/JournalView";
import { Button, EmptyState, PageHeader, ReasonDialog, Spinner, StatusBadge, filterClass } from "@/components/finance/ui";
import { DocumentForm } from "@/components/receivables/DocumentForm";
import { api } from "@/lib/api";
import { openDocumentPdf } from "@/lib/useSalesDocs";
import { errorText, fmtDate, fmtDateTime, money } from "@/lib/finance";
import {
  DOC_META, paymentLabel, paymentTone, type DocDetail, type DocLine, type DocSummary, type DocType,
} from "@/lib/receivables";

type Prefill = React.ComponentProps<typeof DocumentForm>["prefill"];

export function PaymentBadge({ status, overdue }: { status: string | null; overdue?: boolean }) {
  if (!status) return null;
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11px] font-semibold ${paymentTone(status)}`}>
        {paymentLabel(status)}
      </span>
      {overdue && <span className="rounded-full bg-rose/10 px-2 py-[3px] text-[11px] font-semibold text-rose">OVERDUE</span>}
    </span>
  );
}

/** List, detail and form for one of the three receivable document types. */
export function DocumentScreen({ docType }: { docType: DocType }) {
  const meta = DOC_META[docType];
  const params = useSearchParams();
  const [rows, setRows] = useState<DocSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [payment, setPayment] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(params.get("open"));
  const [editing, setEditing] = useState<DocDetail | "new" | null>(null);
  const [prefill, setPrefill] = useState<Prefill>(null);
  const [picker, setPicker] = useState(false);
  const pageSize = 25;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search) qs.set("search", search);
      if (status) qs.set("status", status);
      if (payment) qs.set("payment_status", payment);
      if (from) qs.set("date_from", from);
      if (to) qs.set("date_to", to);
      const data = await api.get<{ items: DocSummary[]; total: number }>(`/sales/${meta.path}?${qs}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(errorText(err, "Could not load."));
    } finally {
      setLoading(false);
    }
  }, [meta.path, page, search, status, payment, from, to]);

  useEffect(() => { const t = setTimeout(load, search ? 300 : 0); return () => clearTimeout(t); }, [load, search]);

  // Arriving from a sales order, gate pass or invoice: open a pre-filled form.
  useEffect(() => {
    const order = params.get("from_order");
    const pass = params.get("from_pass");
    const invoice = params.get("from_invoice");
    const run = async () => {
      try {
        if (order && docType === "sales_invoice") {
          const d = await api.get<Prefill & { order_number: string; lines: DocLine[] }>(`/sales/invoicing/from-order/${order}`);
          setPrefill({ ...d, source_label: `From sales order ${d!.order_number}: only what is still to invoice is offered.` });
          setEditing("new");
        } else if (pass && docType === "sales_invoice") {
          const d = await api.get<Prefill & { pass_number: string }>(`/sales/invoicing/from-gate-pass/${pass}`);
          setPrefill({ ...d, source_label: `From outward gate pass ${d!.pass_number}.` });
          setEditing("new");
        } else if (invoice && docType !== "sales_invoice") {
          await startFromInvoice(invoice);
        }
      } catch (err) {
        setError(errorText(err, "Could not start from that document."));
      }
    };
    run();
  }, [params, docType]); // eslint-disable-line react-hooks/exhaustive-deps

  const startFromInvoice = async (invoiceId: string) => {
    const d = await api.get<Prefill & { invoice_number: string }>(
      `/sales/invoicing/from-invoice/${invoiceId}?kind=${docType}`);
    setPrefill({ ...d, source_label: `Against invoice ${d!.invoice_number}.` });
    setPicker(false);
    setEditing("new");
  };

  const dirty = Boolean(search || status || payment || from || to);
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <AppShell title={meta.plural}>
      <PageHeader title={meta.plural}
        subtitle={docType === "sales_invoice"
          ? "Draft → Confirmed → Posted. Posting creates the ledger entry; payments are tracked from receipts."
          : "Posted notes adjust the customer's receivable through the ledger; the original invoice is never altered."}>
        {docType !== "sales_invoice" && <Button onClick={() => setPicker(true)}>Against an invoice</Button>}
        <Button tone="primary" onClick={() => { setPrefill(null); setEditing("new"); }}><Plus size={14} /> New</Button>
      </PageHeader>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={total} noun="Document" resettable={dirty}
          onReset={() => { setSearch(""); setStatus(""); setPayment(""); setFrom(""); setTo(""); setPage(1); }} />
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Number, customer, PO…"
              className="w-52 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint" />
          </div>
          <select className={filterClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {["DRAFT", "CONFIRMED", "POSTED", "CANCELLED"].map((s) => <option key={s}>{s}</option>)}
          </select>
          {docType !== "credit_note" && (
            <select className={filterClass} value={payment} onChange={(e) => { setPayment(e.target.value); setPage(1); }}>
              <option value="">Any payment state</option>
              {["OPEN", "PARTIALLY_PAID", "PAID", "OVERDUE"].map((s) => <option key={s} value={s}>{paymentLabel(s)}</option>)}
            </select>
          )}
          <input type="date" className={filterClass} value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} />
          <input type="date" className={filterClass} value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} />
        </div>
        {error && <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1000px] border-collapse text-left">
            <thead><tr className="border-b border-line">
              <GridTh>Number</GridTh><GridTh>Date</GridTh><GridTh>Due</GridTh><GridTh>Customer</GridTh>
              <GridTh numeric>Total</GridTh><GridTh numeric>{docType === "credit_note" ? "Applied" : "Paid"}</GridTh>
              <GridTh numeric>{docType === "credit_note" ? "Unapplied" : "Outstanding"}</GridTh>
              <GridTh>Status</GridTh><GridTh>Payment</GridTh>
            </tr></thead>
            <tbody>
              {loading && <tr><td colSpan={9}><Spinner /></td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={9}><EmptyState>{dirty ? "Nothing matches these filters." : `No ${meta.plural.toLowerCase()} yet.`}</EmptyState></td></tr>
              )}
              {!loading && rows.map((d, i) => (
                <tr key={d.id} className={`${gridRowClass(i)} cursor-pointer`} onClick={() => setViewing(d.id)}>
                  <td className={gridCellClass(false, "font-medium text-primary")}>{d.doc_number}</td>
                  <td className={gridCellClass()}>{fmtDate(d.doc_date)}</td>
                  <td className={gridCellClass(false, d.overdue ? "text-rose" : "text-muted")}>{fmtDate(d.due_date)}</td>
                  <td className={gridCellClass()}>{d.customer_name}{d.is_cash_sale && <span className="ml-1.5 text-[11px] text-faint">cash</span>}</td>
                  <td className={gridCellClass(true)}>{d.currency !== "PKR" && `${d.currency} `}{money(d.net_total)}</td>
                  <td className={gridCellClass(true)}>{money(d.paid)}</td>
                  <td className={gridCellClass(true, d.outstanding ? "font-medium" : "text-faint")}>{money(d.outstanding)}</td>
                  <td className={gridCellClass()}><StatusBadge status={d.status} /></td>
                  <td className={gridCellClass()}><PaymentBadge status={d.payment_status} overdue={d.overdue} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{total.toLocaleString()} documents</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
            <span className="px-2">Page {page} of {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>

      {viewing && (
        <DocumentView docType={docType} id={viewing} onClose={() => setViewing(null)} onChanged={load}
          onEdit={(d) => { setViewing(null); setPrefill(null); setEditing(d); }} />
      )}
      {editing && (
        <DocumentForm docType={docType} doc={editing === "new" ? null : editing} prefill={editing === "new" ? prefill : null}
          onClose={() => setEditing(null)}
          onSaved={(id) => { setEditing(null); setPrefill(null); load(); setViewing(id); }} />
      )}
      {picker && <InvoicePicker onClose={() => setPicker(false)} onPick={(id) => startFromInvoice(id).catch((e) => setError(errorText(e, "Could not load the invoice.")))} />}
    </AppShell>
  );
}

function InvoicePicker({ onClose, onPick }: { onClose: () => void; onPick: (id: string) => void }) {
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<DocSummary[]>([]);
  useEffect(() => {
    const t = setTimeout(async () => {
      const qs = new URLSearchParams({ status: "POSTED", page_size: "20" });
      if (search) qs.set("search", search);
      try { setRows((await api.get<{ items: DocSummary[] }>(`/sales/invoices?${qs}`)).items); } catch { setRows([]); }
    }, 250);
    return () => clearTimeout(t);
  }, [search]);
  return (
    <Modal title="Choose the original invoice" open width="md" onClose={onClose}>
      <input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Invoice number or customer…"
        className="mb-3 w-full rounded-lg border border-line bg-bg px-3.5 py-2.5 text-[13px] outline-none focus:border-primary" />
      <ul className="m-0 max-h-80 list-none overflow-y-auto p-0">
        {rows.length === 0 && <li className="py-6 text-center text-[12.5px] text-faint">No posted invoices found.</li>}
        {rows.map((r) => (
          <li key={r.id}>
            <button onClick={() => onPick(r.id)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[12.8px] hover:bg-primary/10">
              <b>{r.doc_number}</b><span className="flex-1 truncate text-muted">{r.customer_name}</span>
              <span className="tabular-nums">{money(r.net_total)}</span>
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

export function DocumentView({ docType, id, onClose, onChanged, onEdit }: {
  docType: DocType; id: string; onClose: () => void; onChanged?: () => void; onEdit?: (d: DocDetail) => void;
}) {
  const meta = DOC_META[docType];
  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"cancel" | "credit" | "unallocate" | null>(null);
  const [allocationId, setAllocationId] = useState<string | null>(null);
  const [journal, setJournal] = useState<string | null>(null);

  const load = async () => {
    try { setDoc(await api.get<DocDetail>(`/sales/${meta.path}/${id}`)); } catch (err) { setError(errorText(err, "Could not load.")); }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (step: string, body: unknown = {}) => {
    setBusy(step);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.post<DocDetail>(`/sales/${meta.path}/${id}/${step}`, body);
      setDoc(updated);
      if (updated.credit_check?.message) setNotice(`Credit warning: ${updated.credit_check.message}`);
      onChanged?.();
    } catch (err) {
      setError(errorText(err, `Could not ${step}.`));
      throw err;
    } finally {
      setBusy(null);
    }
  };
  const quiet = (step: string) => () => { act(step).catch(() => undefined); };
  const d = doc;

  return (
    <>
      <Modal title={d ? `${meta.label} ${d.doc_number}` : meta.label} open width="lg" error={error} onClose={onClose}>
        {!d ? <p className="text-[12.5px] text-faint">Loading…</p> : (
          <div className="space-y-5">
            {notice && <p className="m-0 rounded-lg bg-amber/10 px-3.5 py-2.5 text-[12.5px] text-amber">{notice}</p>}
            <div className="flex flex-wrap items-center gap-2.5">
              <StatusBadge status={d.status} />
              <PaymentBadge status={d.payment_status} overdue={d.overdue} />
              {d.credit_check_status && d.credit_check_status !== "OK" && (
                <span className="rounded-full bg-amber/15 px-2.5 py-[3px] text-[11px] font-semibold text-amber">
                  CREDIT {d.credit_check_status.replace("_", " ")}
                </span>
              )}
              <div className="ml-auto flex flex-wrap gap-2">
                {d.status === "DRAFT" && onEdit && <Button onClick={() => onEdit(d)}>Edit</Button>}
                {d.status === "DRAFT" && <Button tone="soft" busy={busy === "confirm"} onClick={quiet("confirm")}>Confirm</Button>}
                {d.status === "CONFIRMED" && <Button onClick={quiet("reopen")}>Back to draft</Button>}
                {d.status === "CONFIRMED" && d.credit_check_status === "APPROVAL_REQUIRED" && (
                  <Button tone="soft" onClick={() => setDialog("credit")}>Approve credit</Button>
                )}
                {d.status === "CONFIRMED" && d.credit_check_status !== "APPROVAL_REQUIRED" && (
                  <Button tone="primary" busy={busy === "post"} onClick={quiet("post")}>Post to ledger</Button>
                )}
                {d.status !== "CANCELLED" && <Button tone="danger" onClick={() => setDialog("cancel")}>{d.status === "POSTED" ? "Cancel / reverse" : "Cancel"}</Button>}
              </div>
            </div>

            <dl className="grid grid-cols-4 gap-x-5 gap-y-3 text-[12.5px] max-md:grid-cols-2">
              <Fact label="Customer">{d.customer.code} {d.customer.name}</Fact>
              <Fact label="Date">{fmtDate(d.doc_date)}</Fact>
              <Fact label="Due">{fmtDate(d.due_date)}{d.due_date_overridden && <span className="text-faint"> (set by hand)</span>}</Fact>
              <Fact label="Terms">{d.payment_terms ?? "—"}</Fact>
              <Fact label="Currency">{d.currency}{d.currency !== "PKR" && ` @ ${d.exchange_rate}`}</Fact>
              <Fact label="Customer PO">{d.customer_po_number ?? "—"}</Fact>
              <Fact label="Source">
                {d.references.source ? (
                  d.references.source.doc_type === "sales_order"
                    ? <Link className="text-primary hover:underline" href={`/inventory/transactions/sales-orders?open=${d.references.source.id}`}>SO {d.references.source.doc_number}</Link>
                    : <Link className="text-primary hover:underline" href={`/finance/invoices?open=${d.references.source.id}`}>Invoice {d.references.source.doc_number}</Link>
                ) : d.references.gate_pass ? `Gate pass ${d.references.gate_pass.doc_number}` : "—"}
              </Fact>
              <Fact label="Journal">
                {d.journal ? <button className="text-primary hover:underline" onClick={() => setJournal(d.journal!.id)}>{d.journal.journal_number}</button> : "—"}
                {d.cancel_journal && <> · reversed by <button className="text-primary hover:underline" onClick={() => setJournal(d.cancel_journal!.id)}>{d.cancel_journal.journal_number}</button></>}
              </Fact>
              {d.references.quotation && <Fact label="Quotation">{d.references.quotation.doc_number}</Fact>}
              {d.reason && <Fact label="Reason">{d.reason_code ? `${d.reason_code}: ` : ""}{d.reason}</Fact>}
              {d.is_cash_sale && <Fact label="Payment">Cash sale</Fact>}
            </dl>
            {d.cancel_reason && <p className="m-0 rounded-lg bg-rose/10 px-3.5 py-2.5 text-[12.5px] text-rose">Cancelled: {d.cancel_reason}</p>}

            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full min-w-[760px] border-collapse text-left">
                <thead><tr className="border-b border-line">
                  <GridTh>#</GridTh><GridTh>Description</GridTh><GridTh numeric>Qty</GridTh><GridTh numeric>Price</GridTh>
                  <GridTh numeric>Disc %</GridTh><GridTh numeric>Taxable</GridTh><GridTh numeric>Tax %</GridTh>
                  <GridTh numeric>Tax</GridTh><GridTh numeric>Total</GridTh>
                </tr></thead>
                <tbody>
                  {d.lines.map((l, i) => (
                    <tr key={l.id} className={gridRowClass(i)}>
                      <td className={gridCellClass()}>{i + 1}</td>
                      <td className={gridCellClass()}>{l.item_code && <span className="text-muted">{l.item_code} · </span>}{l.description}</td>
                      <td className={gridCellClass(true)}>{Number(l.quantity)} {l.uom}</td>
                      <td className={gridCellClass(true)}>{money(Number(l.unit_price))}</td>
                      <td className={gridCellClass(true)}>{Number(l.discount_percent)}</td>
                      <td className={gridCellClass(true)}>{money(l.taxable_amount)}</td>
                      <td className={gridCellClass(true)}>{l.tax_percent}</td>
                      <td className={gridCellClass(true)}>{money(l.tax_amount)}</td>
                      <td className={gridCellClass(true)}>{money(l.net_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="grid grid-cols-[1fr_300px] gap-5 max-md:grid-cols-1">
              <div className="space-y-3">
                {d.allocations.length > 0 && (
                  <div>
                    <div className="mb-1.5 text-[12px] font-semibold">{docType === "credit_note" ? "Applied to" : "Payments and credits"}</div>
                    <ul className="m-0 list-none space-y-1 p-0 text-[12.5px]">
                      {d.allocations.map((a) => (
                        <li key={a.id} className={`flex items-center gap-3 ${a.status !== "ACTIVE" ? "text-faint line-through" : ""}`}>
                          <span className="w-24">{fmtDate(a.date)}</span>
                          <span className="flex-1">{a.document_number} <span className="text-faint">{a.item_type.replace("_", " ").toLowerCase()}</span></span>
                          <span className="tabular-nums">{money(a.amount)}</span>
                          {a.status === "ACTIVE" && (
                            <button className="text-[11.5px] text-rose hover:underline" onClick={() => { setAllocationId(a.id); setDialog("unallocate"); }}>undo</button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {d.order_progress && (
                  <div>
                    <div className="mb-1.5 text-[12px] font-semibold">Sales order progress</div>
                    <table className="w-full text-[12px]">
                      <thead><tr className="text-faint"><th className="text-left font-normal">Line</th><th className="text-right font-normal">Ordered</th>
                        <th className="text-right font-normal">Delivered</th><th className="text-right font-normal">Invoiced</th><th className="text-right font-normal">Remaining</th></tr></thead>
                      <tbody>
                        {d.order_progress.map((p) => (
                          <tr key={p.line_id}><td className="max-w-[240px] truncate">{p.description}</td>
                            <td className="text-right">{p.ordered}</td><td className="text-right">{p.delivered}</td>
                            <td className="text-right">{p.invoiced}</td><td className="text-right font-medium">{p.remaining}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="text-[11.5px] text-faint">
                  Created {d.created_by} {fmtDateTime(d.created_at)}
                  {d.confirmed_by && <> · confirmed {d.confirmed_by} {fmtDateTime(d.confirmed_at)}</>}
                  {d.posted_by && <> · posted {d.posted_by} {fmtDateTime(d.posted_at)}</>}
                  {d.credit_approved_by && <> · credit approved by {d.credit_approved_by}</>}
                  {d.cancelled_by && <> · cancelled {d.cancelled_by} {fmtDateTime(d.cancelled_at)}</>}
                </div>
              </div>
              <div className="space-y-1.5 rounded-lg border border-line bg-bg px-4 py-3 text-[12.5px]">
                <Total label="Taxable">{money(d.excluding_tax_value)}</Total>
                <Total label="Sales tax">{money(d.sales_tax_value)}</Total>
                {d.freight_amount > 0 && <Total label="Freight">{money(d.freight_amount)}</Total>}
                <Total label={<b>Total {d.currency}</b>}><b>{money(d.net_total)}</b></Total>
                {d.status === "POSTED" && <>
                  <Total label={docType === "credit_note" ? "Applied" : "Paid / credited"}>{money(d.paid)}</Total>
                  <Total label={<b>{docType === "credit_note" ? "Unapplied" : "Outstanding"}</b>}><b>{money(d.outstanding)}</b></Total>
                </>}
              </div>
            </div>

            <div className="flex flex-wrap gap-2 border-t border-line pt-4">
              {docType === "sales_invoice" && d.status === "DRAFT" && (
                <Button onClick={() => openDocumentPdf(d.id, "proforma_invoice")}><Printer size={13} /> Proforma</Button>
              )}
              {docType === "sales_invoice" && ["CONFIRMED", "POSTED"].includes(d.status) && <>
                <Button onClick={() => openDocumentPdf(d.id, d.sales_tax_value > 0 ? "sales_tax_invoice" : "sales_invoice")}><Printer size={13} /> Print invoice</Button>
                <Button onClick={() => openDocumentPdf(d.id, "delivery_note")}><Printer size={13} /> Delivery note</Button>
              </>}
              {docType !== "sales_invoice" && ["CONFIRMED", "POSTED"].includes(d.status) && (
                <Button onClick={() => openDocumentPdf(d.id, docType)}><Printer size={13} /> Print</Button>
              )}
              {docType === "sales_invoice" && d.status === "POSTED" && !d.is_cash_sale && <>
                {d.outstanding > 0 && <Link href={`/finance/receipts?new=1&customer=${d.customer_id}&invoice=${d.id}`}><Button tone="soft">Receive payment</Button></Link>}
                <Link href={`/finance/credit-notes?from_invoice=${d.id}`}><Button>Credit note</Button></Link>
                <Link href={`/finance/debit-notes?from_invoice=${d.id}`}><Button>Debit note</Button></Link>
              </>}
              <Link href={`/finance/statement?customer=${d.customer_id}`}><Button>Customer statement</Button></Link>
            </div>
          </div>
        )}
      </Modal>

      <ReasonDialog open={dialog === "cancel"} title={`Cancel ${meta.label} ${d?.doc_number ?? ""}`}
        confirmLabel={d?.status === "POSTED" ? "Reverse and cancel" : "Cancel document"}
        onClose={() => setDialog(null)} onConfirm={(reason) => act("cancel", { reason })}>
        {d?.status === "POSTED" && (
          <p className="m-0 text-[12.5px] text-muted">
            A reversing journal is posted today and the document stays on file as CANCELLED.
            {docType !== "credit_note" && " Payments allocated to it must be unallocated first. For a partial correction, raise a credit note instead."}
          </p>
        )}
      </ReasonDialog>
      <ReasonDialog open={dialog === "credit"} title="Approve credit limit override" label="Approval note"
        confirmLabel="Approve" onClose={() => setDialog(null)} onConfirm={(reason) => act("approve-credit", { reason })} />
      <ReasonDialog open={dialog === "unallocate"} title="Undo allocation" confirmLabel="Undo allocation"
        onClose={() => setDialog(null)}
        onConfirm={async (reason) => { await api.post(`/ar/allocations/${allocationId}/unallocate`, { reason }); await load(); onChanged?.(); }}>
        <p className="m-0 text-[12.5px] text-muted">The payment goes back to the customer&apos;s unallocated credit; the ledger is adjusted accordingly.</p>
      </ReasonDialog>
      {journal && <JournalView journalId={journal} onClose={() => setJournal(null)} onOpen={setJournal} />}
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="min-w-0"><dt className="text-[11px] text-faint">{label}</dt><dd className="m-0 truncate">{children}</dd></div>;
}

function Total({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return <div className="flex justify-between gap-3"><span className="text-muted">{label}</span><span className="tabular-nums">{children}</span></div>;
}
