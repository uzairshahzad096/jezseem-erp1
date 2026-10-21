"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
import { api } from "@/lib/api";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import { GridActionChips, GridActionView, GridActions, useGridActions } from "@/components/ui/GridActions";
import { Fragment } from "react";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate,
} from "@/components/ui/grid";
import { money } from "@/lib/currency";

const STATUSES = ["Draft", "Sent", "Approved", "Rejected", "Closed"];

/** Every column the grid can show, in order. */
const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (q: SalesDocSummary) => React.ReactNode;
}[] = [
  { key: "doc_number", label: "Quotation No.", sort: "doc_number",
    render: (q) => <span className="font-medium">{q.doc_number}</span> },
  { key: "doc_date", label: "Quotation Date", sort: "doc_date",
    render: (q) => <span className="whitespace-nowrap">{gridDate(q.doc_date)}</span> },
  { key: "customer_name", label: "Customer", render: (q) => q.customer_name ?? "—" },
  { key: "demand_number", label: "Demand #", render: (q) => q.demand_number ?? "—" },
  { key: "payment_terms", label: "Payment Terms", render: (q) => q.payment_terms ?? "—" },
  { key: "gst", label: "Gst or Non Gst",
    render: (q) => (q.is_service ? "Service" : q.with_sales_tax ? "With Sale Tax" : "Without Sale Tax") },
  { key: "status", label: "Status", sort: "status",
    render: (q) => (
      <span className={`rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                        ${STATUS_STYLE[q.status] ?? "bg-hover text-muted"}`}>
        {q.status}
      </span>
    ) },
  { key: "remarks", label: "Remarks", render: (q) => q.remarks ?? "—" },
  { key: "detail_items", label: "Detail Items",
    render: (q) => (q.detail_items
      ? <span className="line-clamp-2">{q.detail_items}</span>
      : <span className="text-faint">—</span>) },
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
  { key: "net_receivable", label: "Net", numeric: true, sort: "net_receivable",
    render: (q) => <span className="font-semibold">{money(q.net_receivable, q.currency)}</span> },
  { key: "customer_stn", label: "GST #", render: (q) => q.customer_stn ?? "—" },
  { key: "customer_ntn", label: "NTN #", render: (q) => q.customer_ntn ?? "—" },
  { key: "total_items", label: "Total Items", numeric: true, render: (q) => q.total_items },
];

// Hidden until asked for, so the default grid matches what was there before.
const DEFAULT_HIDDEN = [
  "payment_terms", "gst", "excluding_tax_value", "sales_tax_value", "gross_amount",
  "discount_amount", "freight_amount", "customer_stn", "customer_ntn", "total_items",
];

const STATUS_STYLE: Record<string, string> = {
  Draft: "bg-hover text-muted",
  Sent: "bg-sky/15 text-sky",
  Approved: "bg-success/15 text-success",
  Rejected: "bg-rose/15 text-rose",
  Closed: "bg-violet/15 text-violet",
};

export default function QuotationsPage() {
  const router = useRouter();
  const list = useSalesDocs("/sales/quotations", 25);
  const [customers, setCustomers] = useState<Customer[]>([]);

  const [isOpen, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [header, setHeader] = useState<DocHeader>(emptyHeader());
  const [lines, setLines] = useState<DocLine[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

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
    setHeader(emptyHeader());
    setLines([emptyLine()]);
    setFormError(null);
    setOpen(true);
  };

  const openEdit = async (id: string) => {
    setFormError(null);
    try {
      const doc = await api.get<SalesDocDetail>(`/sales/quotations/${id}`);
      setEditingId(id);
      setHeader({
        ...emptyHeader(),
        doc_date: doc.doc_date,
        customer_id: doc.customer_id,
        status: doc.status,
        remarks: doc.remarks ?? "",
        demand_number: doc.demand_number ?? "",
        payment_terms: doc.payment_terms ?? "",
        with_sales_tax: doc.with_sales_tax,
        is_service: Boolean(doc.is_service),
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
      alert(err instanceof Error ? err.message : "Could not open this quotation.");
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
        with_sales_tax: header.with_sales_tax,
        is_service: header.is_service,
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
      if (editingId) await api.put(`/sales/quotations/${editingId}`, body);
      else await api.post("/sales/quotations", body);
      setOpen(false);
      await list.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the quotation.");
    } finally {
      setSaving(false);
    }
  };

  /** Delete from inside the form. A saved quotation is removed on the server;
   *  an unsaved one has nothing to remove, so it is simply discarded. */
  const removeFromForm = async () => {
    if (!editingId) {
      if (!confirm("Discard this quotation? Nothing has been saved yet.")) return;
      setOpen(false);
      return;
    }
    if (!confirm("Delete this quotation permanently? This cannot be undone.")) return;

    setSaving(true);
    setFormError(null);
    try {
      await api.del(`/sales/quotations/${editingId}`);
      setOpen(false);
      await list.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not delete this quotation.");
    } finally {
      setSaving(false);
    }
  };

  const convert = async (id: string, number: string) => {
    if (!confirm(
      `Convert quotation ${number} into a Product Sale Order?\n\n` +
      `The customer, products, quantities and prices will be carried across, ` +
      `and this quotation will be marked Closed.`
    )) return;
    try {
      const order = await api.post<{ doc_number: string }>(`/sales/quotations/${id}/convert`, {});
      alert(`Sales order ${order.doc_number} created.`);
      router.push("/inventory/transactions/sales-orders");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not convert this quotation.");
    }
  };

  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));

  const exportQuery = new URLSearchParams([
    ...(list.search ? [["search", list.search]] : []),
    ...list.statuses.map((s) => ["status", s] as [string, string]),
  ]).toString();

  const columnState = useHiddenColumns("quotations.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  // The Actions menu: filters, highlights, control breaks and summaries over the loaded rows.
  const actions = useGridActions<(typeof list.rows)[number]>(`quotations`, COLUMNS);
  const shown = actions.apply(list.rows);

  return (
    <AppShell title="Quotations">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Quotations</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2.5">
          <DownloadMenu dataset="quotations" query={exportQuery} />
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
              placeholder="Search number, item, remarks, demand…"
              className="w-64 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint"
            />
          </div>
          <div className="ml-auto order-3 flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <GridActions state={actions} pageSize={list.pageSize} onPageSize={list.setPageSize}
              hidden={columnState.hidden} onToggleColumn={columnState.toggle} onShowAllColumns={columnState.reset} />
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

        <GridActionChips state={actions} />
        <GridActionView state={actions} rows={shown} total={list.total} />

        {list.error && (
          <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{list.error}</p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left"
                 style={{ minWidth: `${340 + visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Edit</GridTh>
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
                <tr><td colSpan={visible.length + 3} className="px-5 py-12 text-center">
                  <Loader2 size={18} className="mx-auto animate-spin text-primary" />
                </td></tr>
              )}
              {!list.loading && shown.length === 0 && (
                <tr><td colSpan={visible.length + 3}
                        className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No quotations match these filters.
                </td></tr>
              )}
              {!list.loading && shown.map((q, index) => (
                <Fragment key={q.id}>
                {actions.breakBefore(shown, index) && (
                  <tr className="border-b border-line bg-primary/5">
                    <td colSpan={visible.length + 3} className="px-4 py-2 text-[12px] font-semibold text-primary">
                      {actions.breakBefore(shown, index)}</td>
                  </tr>
                )}
                <tr className={`align-top ${gridRowClass(index)}`} style={actions.rowStyle(q)}>
                  <td className={gridCellClass()}>
                    <button onClick={() => openEdit(q.id)} aria-label="Edit" title="Edit"
                      className="rounded-md p-1.5 text-muted hover:bg-primary/10 hover:text-primary">
                      <Pencil size={14} />
                    </button>
                  </td>
                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1.5">
                      <PrintIcon color="sky" title="Service Invoice"
                        onClick={() => openDocumentPdf(q.id, "service_invoice")} />
                      <PrintIcon color="green" title="Quotation"
                        onClick={() => openDocumentPdf(q.id, "quotation")} />
                      <PrintIcon color="rose" title="Proforma Invoice" pdf
                        onClick={() => openDocumentPdf(q.id, "proforma_invoice")} />
                    </div>
                  </td>

                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "detail_items" ? "max-w-[320px]"
                            : c.key === "remarks" ? "max-w-[200px] truncate text-muted" : "")}
                        title={c.key === "remarks" ? q.remarks ?? "" : undefined}>
                      {c.render(q)}
                    </td>
                  ))}

                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1.5">

                      {q.status === "Approved" && (
                        <button onClick={() => convert(q.id, q.doc_number)}
                          title="Convert to Sale Order"
                          className="flex items-center gap-1 whitespace-nowrap rounded-md bg-primary/10 px-2 py-1.5
                                     text-[11px] font-medium text-primary hover:bg-primary/20">
                          <ArrowRightLeft size={12} /> To Order
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{list.total.toLocaleString()} quotations</span>
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
        title={editingId ? "Edit Quotation" : "Quotations"}
        open={isOpen} saving={saving} error={formError} width="xl"
        onClose={() => setOpen(false)} onSave={save}
        saveLabel={editingId ? "Apply Changes" : "Create"}
        onDelete={removeFromForm}
        deleteLabel={editingId ? "Delete" : "Discard"}
      >
        <SalesDocumentForm
          kind="quotation"
          header={header} lines={lines} customers={customers}
          onHeader={setHeader} onLines={setLines}
        />
      </Modal>
    </AppShell>
  );
}

function PrintIcon({ color, title, onClick, pdf }: {
  color: "sky" | "green" | "rose"; title: string; onClick: () => void; pdf?: boolean;
}) {
  const styles = {
    sky: "bg-sky text-white shadow-sm hover:bg-sky/85",
    green: "bg-success text-white shadow-sm hover:bg-success/85",
    rose: "bg-rose text-white shadow-sm hover:bg-rose/85",
  }[color];
  const Icon = pdf ? FileText : Printer;
  return (
    <button onClick={onClick} title={title} aria-label={title}
      className={`rounded-full p-1.5 transition-colors ${styles}`}>
      <Icon size={13} />
    </button>
  );
}
