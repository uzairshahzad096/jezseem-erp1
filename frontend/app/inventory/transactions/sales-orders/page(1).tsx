"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Printer, FileText, Pencil, Plus, Search, Loader2, ArrowRightLeft,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal } from "@/components/ui/Modal";
import {
  SalesDocumentForm, emptyHeader, emptyLine,
  type DocHeader, type DocLine, type Customer,
} from "@/components/sales/SalesDocumentForm";
import { useSalesDocs, openDocumentPdf,
  type SalesDocDetail, type SalesDocSummary } from "@/lib/useSalesDocs";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate,
} from "@/components/ui/grid";
import { api } from "@/lib/api";
import { money } from "@/lib/currency";

const STATUSES = ["Draft", "Posted", "Delivered", "Cancelled"];

/**
 * Every column the old ERP's grid shows, in its order. `render` produces the
 * cell; anything not listed in DEFAULT_HIDDEN starts visible.
 */
const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (q: SalesDocSummary) => React.ReactNode;
}[] = [
  { key: "doc_number", label: "Sale NO.", sort: "doc_number",
    render: (q) => <span className="font-medium">{q.doc_number}</span> },
  { key: "doc_date", label: "Sale Date", sort: "doc_date",
    render: (q) => <span className="whitespace-nowrap">{gridDate(q.doc_date)}</span> },
  { key: "customer_po_number", label: "PO NO#", render: (q) => q.customer_po_number ?? "—" },
  { key: "source_doc_number", label: "Quotation No#",
    render: (q) => q.source_doc_number ?? "—" },
  { key: "customer_name", label: "Customer", render: (q) => q.customer_name ?? "—" },
  { key: "remarks", label: "Remarks", render: (q) => q.remarks ?? "—" },
  { key: "dc_number", label: "Dc No", render: (q) => q.dc_number ?? "—" },
  { key: "delivery_person", label: "Delivery Person", render: (q) => q.delivery_person ?? "—" },
  { key: "vehicle_number", label: "Vehicle No", render: (q) => q.vehicle_number ?? "—" },
  { key: "gst", label: "Gst or Non Gst",
    render: (q) => (q.with_sales_tax ? "With Sale Tax" : "Without Sale Tax") },
  { key: "status", label: "Status", sort: "status",
    render: (q) => (
      <span className={`rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                        ${STATUS_STYLE[q.status] ?? "bg-hover text-muted"}`}>
        {q.status}
      </span>
    ) },
  { key: "payment_status", label: "Payment Status",
    render: (q) => (
      <span className={`rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                        ${q.payment_status === "PAID" ? "bg-success/15 text-success"
                          : q.payment_status === "PARTIAL" ? "bg-amber/15 text-amber"
                          : "bg-rose/15 text-rose"}`}>
        {q.payment_status ?? "—"}
      </span>
    ) },
  { key: "excluding_tax_value", label: "Excluding Stax Value", numeric: true,
    render: (q) => money(q.excluding_tax_value, q.currency) },
  { key: "sales_tax_value", label: "Sale Tax Value", numeric: true,
    render: (q) => money(q.sales_tax_value, q.currency) },
  { key: "gross_amount", label: "Gross Amount", numeric: true,
    render: (q) => money(q.gross_amount, q.currency) },
  { key: "discount_amount", label: "Discount", numeric: true,
    render: (q) => money(q.discount_amount, q.currency) },
  { key: "freight_amount", label: "Freight", numeric: true,
    render: (q) => money(q.freight_amount, q.currency) },
  { key: "net_receivable", label: "Net Receivable", numeric: true, sort: "net_receivable",
    render: (q) => <span className="font-semibold">{money(q.net_receivable, q.currency)}</span> },
  { key: "customer_stn", label: "GST #", render: (q) => q.customer_stn ?? "—" },
  { key: "customer_ntn", label: "NTN #", render: (q) => q.customer_ntn ?? "—" },
  { key: "total_items", label: "Total Items", numeric: true, render: (q) => q.total_items },
  { key: "detail_items", label: "Detail Items",
    render: (q) => (q.detail_items
      ? <span className="line-clamp-2">{q.detail_items}</span>
      : <span className="text-faint">—</span>) },
];

// Started hidden because the grid is already wide; all of them are one click
// away in the Columns menu.
const DEFAULT_HIDDEN = [
  "dc_number", "vehicle_number", "excluding_tax_value", "sales_tax_value",
  "gross_amount", "discount_amount", "freight_amount", "customer_stn", "customer_ntn",
];

const STATUS_STYLE: Record<string, string> = {
  Draft: "bg-hover text-muted",
  Posted: "bg-success/15 text-success",
  Delivered: "bg-sky/15 text-sky",
  Cancelled: "bg-rose/15 text-rose",
};

/** Reading the query string opts the route out of static rendering unless it
 *  sits behind a Suspense boundary, which the build enforces. */
export default function SalesOrdersPage() {
  return (
    <Suspense fallback={
      <AppShell title="Product Sale Order">
        <div className="flex justify-center py-20">
          <Loader2 size={22} className="animate-spin text-primary" />
        </div>
      </AppShell>
    }>
      <SalesOrders />
    </Suspense>
  );
}

function SalesOrders() {
  // ?search=202609231 — how the Product Sales Report's Doc Id links through
  // to the order a line came from.
  const params = useSearchParams();
  const list = useSalesDocs("/sales/orders", 25, [], params.get("search") ?? "");
  const [customers, setCustomers] = useState<Customer[]>([]);

  const [isOpen, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [header, setHeader] = useState<DocHeader>(emptyHeader());
  const [lines, setLines] = useState<DocLine[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  /** The approved quotation this order is being raised from, if any. Kept so
   *  the order records where it came from and that quotation gets closed. */
  const [source, setSource] = useState<{ id: string; doc_number: string } | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Every customer, not the first page: the picker filters client-side, and a
  // capped request would silently hide the account being looked for.
  useEffect(() => {
    (async () => {
      const all: Customer[] = [];
      try {
        for (let page = 1; ; page += 1) {
          const d = await api.get<{ items: typeof all; total: number }>(
            `/partners?role=customer&page=${page}&page_size=500`,
          );
          all.push(...d.items);
          if (d.items.length === 0 || all.length >= d.total) break;
        }
        setCustomers(all);
      } catch {
        setCustomers([]);
      }
    })();
  }, []);

  const openNew = () => {
    setEditingId(null);
    setSource(null);
    setHeader(emptyHeader());
    setLines([emptyLine()]);
    setFormError(null);
    setOpen(true);
  };

  /** Load an approved quotation into a blank sales order form. Nothing is
   *  written yet — the user reviews the lines and prices, and the order is
   *  created on Save with the quotation recorded as its source. */
  const openFromQuotation = async (id: string, docNumber: string) => {
    setFormError(null);
    try {
      const q = await api.get<SalesDocDetail>(`/sales/quotations/${id}`);
      setEditingId(null);
      setSource({ id: q.id, doc_number: docNumber });
      setHeader({
        ...emptyHeader(),
        customer_id: q.customer_id,
        remarks: q.remarks ?? "",
        demand_number: q.demand_number ?? "",
        with_sales_tax: q.with_sales_tax,
        currency: q.currency,
      });
      setLines(q.lines.map((l) => ({
        item_id: l.item_id,
        item_code: l.item_code,
        description: l.description,
        uom: l.uom,
        hs_code: l.hs_code,
        quantity: String(l.quantity),
        unit_price: String(l.unit_price),
        discount_percent: String(l.discount_percent),
        tax_percent: String(l.tax_percent),
        currency: l.currency,
        rack_name: l.rack_name,
        stock: l.stock,
        last_rate: null,
        sale_rate: l.sale_rate,
      })));
      setPickerOpen(false);
      setOpen(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not open that quotation.");
    }
  };

  const openEdit = async (id: string) => {
    setFormError(null);
    try {
      const doc = await api.get<SalesDocDetail>(`/sales/orders/${id}`);
      setEditingId(id);
      setSource(null);
      setHeader({
        ...emptyHeader(),
        doc_date: doc.doc_date,
        customer_id: doc.customer_id,
        status: doc.status,
        remarks: doc.remarks ?? "",
        demand_number: doc.demand_number ?? "",
        customer_po_number: doc.customer_po_number ?? "",
        dc_number: doc.dc_number ?? "",
        delivery_person: doc.delivery_person ?? "",
        vehicle_number: doc.vehicle_number ?? "",
        location: doc.location ?? "",
        payment_terms: doc.payment_terms ?? "",
        with_sales_tax: doc.with_sales_tax,
        currency: doc.currency,
        payment_status: doc.payment_status ?? "PENDING",
      });
      setLines(
        doc.lines.map((l) => ({
          item_id: l.item_id,
          item_code: l.item_code,
          description: l.description,
          uom: l.uom,
          hs_code: l.hs_code,
          quantity: String(l.quantity),
          unit_price: String(l.unit_price),
          discount_percent: String(l.discount_percent),
          tax_percent: String(l.tax_percent),
          currency: l.currency,
          rack_name: l.rack_name,
          stock: l.stock,
          last_rate: null,
          sale_rate: l.sale_rate,
        })),
      );
      setOpen(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not open this sales order.");
    }
  };

  const save = async () => {
    if (!header.customer_id) { setFormError("Select a customer."); return; }
    if (lines.length === 0) { setFormError("Add at least one product line."); return; }
    if (lines.some((l) => !l.description.trim())) {
      setFormError("Every line needs a description."); return;
    }
    if (lines.some((l) => Number(l.quantity) <= 0)) {
      setFormError("Every line needs a quantity greater than zero."); return;
    }

    setSaving(true);
    setFormError(null);
    try {
      const body = {
        doc_date: header.doc_date,
        customer_id: header.customer_id,
        status: header.status,
        remarks: header.remarks || null,
        demand_number: header.demand_number || null,
        // These were on the form but never sent, so a PO number typed into
        // the order was silently dropped on save.
        customer_po_number: header.customer_po_number || null,
        dc_number: header.dc_number || null,
        delivery_person: header.delivery_person || null,
        vehicle_number: header.vehicle_number || null,
        location: header.location || null,
        with_sales_tax: header.with_sales_tax,
        currency: header.currency,
        payment_terms: header.payment_terms || null,
        payment_status: header.payment_status || null,
        freight_amount: header.freight_amount || "0",
        document_discount: header.document_discount || "0",
        lines: lines.map((l) => ({
          item_id: l.item_id,
          item_code: l.item_code,
          description: l.description,
          uom: l.uom,
          hs_code: l.hs_code,
          quantity: l.quantity,
          unit_price: l.unit_price,
          discount_percent: l.discount_percent || "0",
          tax_percent: l.tax_percent || "0",
          currency: l.currency || null,
        })),
      };
      if (editingId) await api.put(`/sales/orders/${editingId}`, body);
      else await api.post("/sales/orders", { ...body, source_document_id: source?.id ?? null });
      setOpen(false);
      await list.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the sales order.");
    } finally {
      setSaving(false);
    }
  };

  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));

  const columnState = useHiddenColumns("sales-orders.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));

  // The download follows what is on screen, so "all data" means all data
  // matching these filters rather than the whole table.
  const exportQuery = new URLSearchParams([
    ...(list.search ? [["search", list.search]] : []),
    ...list.statuses.map((s) => ["status", s] as [string, string]),
  ]).toString();

  return (
    <AppShell title="Product Sale Order">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Product Sale Order</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2.5">
          <button
            onClick={() => setPickerOpen(true)}
            className="flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10
                       px-3.5 py-2 text-[12.8px] font-medium text-primary transition-colors
                       hover:bg-primary/20"
          >
            <ArrowRightLeft size={14} /> Convert Sale Order
          </button>
          <button
            onClick={openNew}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary
                       to-primary-dark px-3.5 py-2 text-[12.8px] font-medium text-on-primary"
          >
            <Plus size={14} strokeWidth={2.4} /> Create
          </button>
        </div>
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.total} onReset={list.reset} resettable={list.dirty} />

        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input
              value={list.search}
              onChange={(e) => list.setSearch(e.target.value)}
              placeholder="Search number, remarks, demand…"
              className="w-56 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint"
            />
          </div>
          <div className="ml-auto order-3 flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset="sales-orders" query={exportQuery} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => list.toggleStatus(s)}
                className={`rounded-lg px-2.5 py-1.5 text-[11.5px] font-medium transition-colors
                            ${list.statuses.includes(s)
                              ? "bg-primary text-on-primary"
                              : "bg-hover text-muted hover:text-text"}`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {list.error && (
          <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{list.error}</p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left"
                 style={{ minWidth: `${420 + visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Print</GridTh>
                {visible.map((c) => (
                  <GridTh key={c.key} numeric={c.numeric} sortKey={c.sort}
                          sort={list.sort} direction={list.direction}
                          onSort={list.toggleSort}>
                    {c.label}
                  </GridTh>
                ))}
                <GridTh> </GridTh>
              </tr>
            </thead>
            <tbody>
              {list.loading && (
                <tr><td colSpan={visible.length + 2} className="px-5 py-12 text-center">
                  <Loader2 size={18} className="mx-auto animate-spin text-primary" />
                </td></tr>
              )}
              {!list.loading && list.rows.length === 0 && (
                <tr><td colSpan={visible.length + 2}
                        className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No sales orders match these filters.
                </td></tr>
              )}
              {!list.loading && list.rows.map((q, index) => (
                <tr key={q.id} className={`align-top ${gridRowClass(index)}`}>
                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1.5">
                      {q.with_sales_tax ? (
                        <PrintIcon color="sky" title="Sales Tax Invoice"
                          onClick={() => openDocumentPdf(q.id, "sales_tax_invoice")} />
                      ) : (
                        <PrintIcon color="amber" title="Sales Invoice"
                          onClick={() => openDocumentPdf(q.id, "sales_invoice")} />
                      )}
                      <PrintIcon color="green" title="Delivery Note"
                        onClick={() => openDocumentPdf(q.id, "delivery_note")} />
                      <PrintIcon color="rose" title="Proforma Invoice" pdf
                        onClick={() => openDocumentPdf(q.id, "proforma_invoice")} />
                      <PrintIcon color="violet" title="Service Invoice"
                        onClick={() => openDocumentPdf(q.id, "service_invoice")} />
                    </div>
                  </td>

                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "detail_items" ? "max-w-[280px]"
                            : c.key === "remarks" ? "max-w-[200px] truncate text-muted" : "")}
                        title={c.key === "remarks" ? q.remarks ?? "" : undefined}>
                      {c.render(q)}
                    </td>
                  ))}

                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => openEdit(q.id)} aria-label="Edit"
                        className="rounded-md p-1.5 text-muted hover:bg-primary/10 hover:text-primary">
                        <Pencil size={14} />
                      </button>
                      {q.source_document_id && (
                        <span title="Created from a quotation"
                          className="whitespace-nowrap rounded-md bg-violet/10 px-2 py-1 text-[10.5px] font-medium text-violet">
                          From quotation
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{list.total.toLocaleString()} sales orders</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
            <span className="px-2">Page {list.page} of {pages}</span>
            <button disabled={list.page >= pages} onClick={() => list.setPage(list.page + 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>

      <Modal
        title={editingId ? "Edit Sale Order" : "Product Sale Order"}
        open={isOpen} saving={saving} error={formError} width="xl"
        onClose={() => setOpen(false)} onSave={save}
        saveLabel={editingId ? "Save" : source ? "Create Sale Order" : "Create"}
      >
        {source && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-primary/30
                          bg-primary/10 px-3.5 py-2.5 text-[12.5px] text-primary">
            <ArrowRightLeft size={14} />
            <span>
              Raising this order from quotation <b>{source.doc_number}</b>. Saving closes
              that quotation so it cannot be converted twice.
            </span>
          </div>
        )}
        <SalesDocumentForm
          kind="sales_order"
          header={header} lines={lines} customers={customers}
          onHeader={setHeader} onLines={setLines}
        />
      </Modal>

      {pickerOpen && (
        <Modal
          title="Convert an approved quotation"
          open width="lg"
          onClose={() => setPickerOpen(false)}
        >
          <ApprovedQuotations onPick={openFromQuotation} />
        </Modal>
      )}
    </AppShell>
  );
}

/**
 * The approved quotations waiting to become orders.
 *
 * Only Approved ones are listed: a draft has not been agreed and a closed one
 * has already been converted, so offering either would only produce an error
 * on save. Mounted with its modal, so the list is fetched on demand.
 */
function ApprovedQuotations({
  onPick,
}: {
  onPick: (id: string, docNumber: string) => void;
}) {
  const list = useSalesDocs("/sales/quotations", 10, ["Approved"]);
  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
        <Search size={14} className="text-faint" />
        <input
          value={list.search}
          onChange={(e) => list.setSearch(e.target.value)}
          placeholder="Search number, item, customer reference…"
          className="w-full border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint"
        />
      </div>

      {list.error && (
        <p className="mb-3 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{list.error}</p>
      )}

      {list.loading && (
        <div className="flex justify-center py-10">
          <Loader2 size={18} className="animate-spin text-primary" />
        </div>
      )}

      {!list.loading && list.rows.length === 0 && (
        <p className="py-10 text-center text-[12.8px] text-faint">
          No approved quotations are waiting to be converted.
        </p>
      )}

      {!list.loading && list.rows.length > 0 && (
        <div className="overflow-hidden rounded-[10px] border border-line">
          {list.rows.map((q) => (
            <button
              key={q.id}
              type="button"
              onClick={() => onPick(q.id, q.doc_number)}
              className="flex w-full items-start gap-3 border-b border-line px-4 py-3 text-left
                         transition-colors last:border-0 hover:bg-primary/5"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold">{q.doc_number}</span>
                  <span className="text-[11.5px] text-faint">{q.doc_date}</span>
                </div>
                <div className="truncate text-[12.5px]">{q.customer_name ?? "—"}</div>
                {q.detail_items && (
                  <div className="truncate text-[11.5px] text-muted">{q.detail_items}</div>
                )}
              </div>
              <div className="whitespace-nowrap text-right text-[12.5px] tabular-nums">
                {q.currency}{" "}
                {q.net_receivable.toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </div>
            </button>
          ))}
        </div>
      )}

      <div className="mt-3 flex items-center gap-3 text-[12.3px] text-muted">
        <span>{list.total.toLocaleString()} approved</span>
        <div className="ml-auto flex items-center gap-1.5">
          <button disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}
            className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
          <span className="px-2">Page {list.page} of {pages}</span>
          <button disabled={list.page >= pages} onClick={() => list.setPage(list.page + 1)}
            className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
        </div>
      </div>
    </div>
  );
}

function PrintIcon({ color, title, onClick, pdf }: {
  color: "sky" | "green" | "rose" | "amber" | "violet";
  title: string; onClick: () => void; pdf?: boolean;
}) {
  const styles = {
    sky: "bg-sky/15 text-sky hover:bg-sky/25",
    green: "bg-success/15 text-success hover:bg-success/25",
    rose: "bg-rose/15 text-rose hover:bg-rose/25",
    amber: "bg-amber/15 text-amber hover:bg-amber/25",
    violet: "bg-violet/15 text-violet hover:bg-violet/25",
  }[color];
  const Icon = pdf ? FileText : Printer;
  return (
    <button onClick={onClick} title={title} aria-label={title}
      className={`rounded-full p-1.5 transition-colors ${styles}`}>
      <Icon size={13} />
    </button>
  );
}
