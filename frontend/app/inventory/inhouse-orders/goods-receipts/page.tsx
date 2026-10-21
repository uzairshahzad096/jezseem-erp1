"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Plus, Search, Loader2, Pencil, PackageCheck, Undo2, Route, AlertTriangle, Printer,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal, TextInput, TextArea, Combobox } from "@/components/ui/Modal";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate, gridAmount,
} from "@/components/ui/grid";
import { useProcurementList, useSuppliers } from "@/lib/useProcurement";
import { useLookups, toOptions } from "@/lib/useLookups";
import { money } from "@/lib/currency";
import { api } from "@/lib/api";
import { openPdf } from "@/lib/openPdf";

const STATUS_STYLE: Record<string, string> = {
  Draft: "bg-hover text-muted",
  Posted: "bg-success/15 text-success",
  Closed: "bg-violet/15 text-violet",
  Cancelled: "bg-rose/15 text-rose",
};

interface GrnRow {
  id: string;
  doc_number: string;
  doc_date: string;
  supplier: string | null;
  supplier_id: string;
  purchase_order: string | null;
  purchase_order_id: string | null;
  shipment_id: string | null;
  in_house_order_id: string | null;
  landed_cost_id: string | null;
  warehouse: string | null;
  warehouse_id: string | null;
  supplier_invoice_number: string | null;
  supplier_invoice_date: string | null;
  vehicle_number: string | null;
  received_by: string | null;
  status: string;
  is_posted: boolean;
  posted_at: string | null;
  currency: string;
  net_payable: number;
  total_items: number;
  remarks: string | null;
}

/** A line offered for receipt, from the `receivable` endpoint. */
interface ReceivableLine {
  purchase_order_line_id?: string | null;
  shipment_line_id?: string | null;
  item_id: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  ordered_quantity: number;
  already_received: number;
  outstanding_quantity: number;
  unit_price: number;
  discount_percent?: number;
  tax_percent?: number;
}

interface Receivable {
  source: "purchase_order" | "shipment";
  purchase_order_id: string;
  purchase_order: string | null;
  purchase_type?: string;
  shipment_id?: string;
  shipment?: string;
  supplier_id: string;
  warehouse_id: string | null;
  currency: string;
  exchange_rate: number;
  in_house_order_id?: string | null;
  transit_status?: string;
  landed_cost_id?: string | null;
  landed_cost?: string | null;
  landed_cost_ready?: boolean;
  pending_costing?: string | null;
  lines: ReceivableLine[];
}

const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: GrnRow) => React.ReactNode;
}[] = [
  { key: "doc_number", label: "GRN No", sort: "doc_number",
    render: (r) => <span className="font-medium">{r.doc_number}</span> },
  { key: "doc_date", label: "Date", sort: "doc_date",
    render: (r) => <span className="whitespace-nowrap">{gridDate(r.doc_date)}</span> },
  { key: "supplier", label: "Supplier", render: (r) => r.supplier ?? "—" },
  { key: "purchase_order", label: "PO No", render: (r) => r.purchase_order ?? "—" },
  { key: "warehouse", label: "Warehouse", render: (r) => r.warehouse ?? "—" },
  { key: "status", label: "Status", sort: "status",
    render: (r) => (
      <span className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                        ${STATUS_STYLE[r.status] ?? "bg-hover text-muted"}`}>
        {r.status}
      </span>
    ) },
  { key: "is_posted", label: "In Stock",
    render: (r) => (r.is_posted
      ? <span className="text-primary">Yes</span>
      : <span className="text-faint">Not yet</span>) },
  { key: "supplier_invoice_number", label: "Supplier Invoice",
    render: (r) => r.supplier_invoice_number ?? "—" },
  { key: "vehicle_number", label: "Vehicle", render: (r) => r.vehicle_number ?? "—" },
  { key: "received_by", label: "Received By", render: (r) => r.received_by ?? "—" },
  { key: "total_items", label: "Items", numeric: true, render: (r) => r.total_items },
  { key: "net_payable", label: "Value", numeric: true, sort: "net_payable",
    render: (r) => money(r.net_payable, r.currency) },
  { key: "remarks", label: "Remarks", render: (r) => r.remarks ?? "—" },
];

const DEFAULT_HIDDEN = ["vehicle_number", "received_by", "remarks"];

export default function GoodsReceiptsPage() {
  return (
    <Suspense fallback={
      <AppShell title="Goods Receipts">
        <div className="flex justify-center py-20">
          <Loader2 size={22} className="animate-spin text-primary" />
        </div>
      </AppShell>
    }>
      <GoodsReceipts />
    </Suspense>
  );
}

function GoodsReceipts() {
  const params = useSearchParams();
  const list = useProcurementList<GrnRow>("/procurement/goods-receipts");
  const { locations } = useLookups();
  const suppliers = useSuppliers();

  const [receiving, setReceiving] = useState<Receivable | null>(null);
  const [picking, setPicking] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [tracing, setTracing] = useState<string | null>(null);

  const columnState = useHiddenColumns("goods-receipts.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));

  const exportQuery = new URLSearchParams([
    ...(list.search ? [["search", list.search]] : []),
    ...list.statuses.map((s) => ["status", s] as [string, string]),
  ]).toString();

  /** Load what is still owed on an order or a shipment. */
  const startReceipt = useCallback(async (query: string) => {
    try {
      const data = await api.get<Receivable>(`/procurement/receivable?${query}`);
      setReceiving(data);
      setPicking(false);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not load what is outstanding.");
    }
  }, []);

  // Arriving from a purchase order or a shipment opens the receipt directly,
  // which is how this screen is normally reached.
  useEffect(() => {
    const po = params.get("po");
    const shipment = params.get("shipment");
    if (po) void startReceipt(`purchase_order_id=${po}`);
    else if (shipment) void startReceipt(`shipment_id=${shipment}`);
  }, [params, startReceipt]);

  const move = async (id: string, status: string) => {
    try {
      const result = await api.post<{ movements_written?: number; movements_reversed?: number }>(
        `/procurement/goods-receipts/${id}/status`, { status });
      await list.reload();
      if (result.movements_written) {
        alert(`Posted. ${result.movements_written} stock movement(s) written — the goods `
          + "are now in the warehouse.");
      } else if (result.movements_reversed) {
        alert(`Reversed. ${result.movements_reversed} movement(s) written back out; the `
          + "receipt stays on the record.");
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not change the status.");
    }
  };

  return (
    <AppShell title="Goods Receipts">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Goods Receipts (GRN)</h1>
        <p className="m-0 text-[12px] text-muted">
          What actually arrived. Posting one is the only thing that increases stock.
        </p>
        <button onClick={() => setPicking(true)}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br
                     from-primary to-primary-dark px-3.5 py-2 text-[12.8px]
                     font-medium text-on-primary">
          <Plus size={14} strokeWidth={2.4} /> Receive Goods
        </button>
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.total} onReset={list.reset} resettable={list.dirty} />

        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={list.search} onChange={(e) => list.setSearch(e.target.value)}
              placeholder="Search number, invoice, item…"
              className="w-56 border-none bg-transparent text-[12.8px] outline-none
                         placeholder:text-faint" />
          </div>
          <div className="ml-auto order-3 flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset="goods-receipts" query={exportQuery} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Draft", "Posted", "Cancelled"].map((s) => (
              <button key={s} onClick={() => list.toggleStatus(s)}
                className={`rounded-lg px-2.5 py-1.5 text-[11.5px] font-medium
                            transition-colors ${list.statuses.includes(s)
                              ? "bg-primary text-on-primary"
                              : "bg-hover text-muted hover:text-text"}`}>
                {s}
              </button>
            ))}
          </div>
        </div>

        {list.error && (
          <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">
            {list.error}
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left"
                 style={{ minWidth: `${250 + visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Actions</GridTh>
                <GridTh>Print</GridTh>
                {visible.map((c) => (
                  <GridTh key={c.key} numeric={c.numeric} sortKey={c.sort}
                          sort={list.sort} direction={list.direction}
                          onSort={list.toggleSort}>
                    {c.label}
                  </GridTh>
                ))}
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
                  No goods receipts yet. Use Receive Goods against an approved
                  purchase order or an arrived shipment.
                </td></tr>
              )}
              {!list.loading && list.rows.map((row, index) => (
                <tr key={row.id} className={`align-top ${gridRowClass(index)}`}>
                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1">
                      <button onClick={() => setViewing(row.id)} aria-label="Open"
                        title="Open"
                        className="rounded-md p-1.5 text-muted hover:bg-primary/10
                                   hover:text-primary">
                        <Pencil size={14} />
                      </button>
                      {!row.is_posted && row.status === "Draft" && (
                        <button onClick={() => move(row.id, "Posted")}
                          title="Post into stock"
                          className="whitespace-nowrap rounded-md bg-primary/10 px-2 py-1
                                     text-[10.5px] font-medium text-primary
                                     hover:bg-primary/20">
                          <PackageCheck size={11} className="mr-1 inline" />Post
                        </button>
                      )}
                      {row.is_posted && (
                        <>
                          <button onClick={() => setTracing(row.id)}
                            title="Trace back to the requirement"
                            className="rounded-md p-1.5 text-muted hover:bg-violet/10
                                       hover:text-violet">
                            <Route size={14} />
                          </button>
                          <button
                            onClick={() => {
                              if (confirm(
                                `Reverse ${row.doc_number}? The goods come back out of `
                                + "stock by an opposite movement; the receipt stays on "
                                + "the record.")) void move(row.id, "Cancelled");
                            }}
                            title="Reverse this receipt" aria-label="Reverse"
                            className="rounded-md p-1.5 text-muted hover:bg-rose/10
                                       hover:text-rose">
                            <Undo2 size={14} />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                  <td className={gridCellClass()}>
                    <button onClick={() => openPdf(`/documents/goods-receipts/${row.id}.pdf`)}
                      title="Print goods receipt note" aria-label="Print goods receipt note"
                      className="rounded-full bg-sky p-1.5 text-white shadow-sm hover:bg-sky/85">
                      <Printer size={13} />
                    </button>
                  </td>
                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "remarks" ? "max-w-[200px] truncate text-muted" : "")}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{list.total.toLocaleString()} goods receipts</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">
              Previous
            </button>
            <span className="px-2">Page {list.page} of {pages}</span>
            <button disabled={list.page >= pages} onClick={() => list.setPage(list.page + 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">
              Next
            </button>
          </div>
        </div>
      </section>

      {picking && (
        <SourcePicker onClose={() => setPicking(false)} onChoose={startReceipt} />
      )}

      {receiving && (
        <ReceiveForm
          source={receiving}
          locations={locations}
          onClose={() => setReceiving(null)}
          onDone={async () => { setReceiving(null); await list.reload(); }}
        />
      )}

      {viewing && (
        <ReceiptDetail id={viewing} onClose={() => setViewing(null)} />
      )}

      {tracing && (
        <TraceDialog id={tracing} onClose={() => setTracing(null)} />
      )}
    </AppShell>
  );
}

/** Choose what to receive against: an open order, or an arrived shipment. */
function SourcePicker({ onClose, onChoose }: {
  onClose: () => void; onChoose: (query: string) => void;
}) {
  const [tab, setTab] = useState<"orders" | "shipments">("orders");
  const orders = useProcurementList<{
    id: string; doc_number: string; doc_date: string; supplier: string | null;
    purchase_type: string; status: string; total_items: number; currency: string;
    net_payable: number;
  }>("/procurement/purchase-orders", {
    pageSize: 10,
    initialStatuses: ["Approved", "Open", "Partially Received"],
  });
  const shipments = useProcurementList<{
    id: string; doc_number: string; doc_date: string; supplier: string | null;
    purchase_order: string | null; transit_status: string; status: string;
    total_quantity: number;
  }>("/procurement/shipments", {
    pageSize: 10,
    extraParams: { in_transit_only: "true" },
  });

  const active = tab === "orders" ? orders : shipments;

  return (
    <Modal title="Receive against" open width="lg" onClose={onClose}>
      <div className="mb-3 flex gap-1.5">
        {([["orders", "Purchase Orders"], ["shipments", "Import Shipments"]] as const)
          .map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)}
              className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors
                          ${tab === key ? "bg-primary text-on-primary"
                                        : "bg-hover text-muted hover:text-text"}`}>
              {label}
            </button>
          ))}
      </div>

      <div className="mb-3 flex items-center gap-2 rounded-full border border-line bg-bg
                      px-3.5 py-2">
        <Search size={14} className="text-faint" />
        <input value={active.search} onChange={(e) => active.setSearch(e.target.value)}
          placeholder={tab === "orders"
            ? "Search order number or item…" : "Search shipment, container, BL…"}
          className="w-full border-none bg-transparent text-[12.8px] outline-none
                     placeholder:text-faint" />
      </div>

      {active.loading && (
        <div className="flex justify-center py-10">
          <Loader2 size={18} className="animate-spin text-primary" />
        </div>
      )}

      {!active.loading && tab === "orders" && orders.rows.length === 0 && (
        <p className="py-10 text-center text-[12.8px] text-faint">
          No open purchase orders. An order has to be approved before goods can be
          received against it.
        </p>
      )}
      {!active.loading && tab === "shipments" && shipments.rows.length === 0 && (
        <p className="py-10 text-center text-[12.8px] text-faint">
          Nothing in transit. A shipment appears here once it has left the supplier.
        </p>
      )}

      {!active.loading && (
        <div className="overflow-hidden rounded-[10px] border border-line">
          {tab === "orders" && orders.rows.map((row) => (
            <button key={row.id} type="button"
              onClick={() => onChoose(`purchase_order_id=${row.id}`)}
              className="flex w-full items-start gap-3 border-b border-line px-4 py-3
                         text-left transition-colors last:border-0 hover:bg-primary/5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold">{row.doc_number}</span>
                  <span className="text-[11.5px] text-faint">{gridDate(row.doc_date)}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold
                                    ${row.purchase_type === "Import"
                                      ? "bg-violet/15 text-violet"
                                      : "bg-hover text-muted"}`}>
                    {row.purchase_type}
                  </span>
                  <span className="text-[11px] text-muted">{row.status}</span>
                </div>
                <div className="truncate text-[12.5px]">{row.supplier ?? "—"}</div>
              </div>
              <div className="whitespace-nowrap text-right text-[12.5px] tabular-nums">
                {row.total_items} item{row.total_items === 1 ? "" : "s"}
              </div>
            </button>
          ))}

          {tab === "shipments" && shipments.rows.map((row) => (
            <button key={row.id} type="button"
              onClick={() => onChoose(`shipment_id=${row.id}`)}
              className="flex w-full items-start gap-3 border-b border-line px-4 py-3
                         text-left transition-colors last:border-0 hover:bg-primary/5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold">{row.doc_number}</span>
                  <span className="text-[11.5px] text-faint">{gridDate(row.doc_date)}</span>
                  <span className="rounded bg-sky/15 px-1.5 py-0.5 text-[10px] font-semibold
                                   text-sky">
                    {row.transit_status}
                  </span>
                </div>
                <div className="truncate text-[12.5px]">
                  {row.supplier ?? "—"}
                  {row.purchase_order ? ` · ${row.purchase_order}` : ""}
                </div>
              </div>
              <div className="whitespace-nowrap text-right text-[12.5px] tabular-nums">
                {gridAmount(row.total_quantity)}
              </div>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

/**
 * Record what arrived.
 *
 * Quantities default to everything outstanding, which is the common case; a
 * partial delivery is typed over the top. Saving records the receipt and
 * posting is a separate, deliberate step — that is the one that moves stock.
 */
function ReceiveForm({ source, locations, onClose, onDone }: {
  source: Receivable;
  locations: { id: string; label: string }[];
  onClose: () => void;
  onDone: () => void;
}) {
  const outstanding = source.lines.filter((l) => l.outstanding_quantity > 0);
  const key = (l: ReceivableLine) =>
    (l.shipment_line_id ?? l.purchase_order_line_id ?? l.item_id ?? l.description);

  const [docDate, setDocDate] = useState(new Date().toISOString().slice(0, 10));
  const [warehouseId, setWarehouseId] = useState(source.warehouse_id ?? "");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [vehicle, setVehicle] = useState("");
  const [receivedBy, setReceivedBy] = useState("");
  const [remarks, setRemarks] = useState("");
  const [quantities, setQuantities] = useState<Record<string, string>>(
    Object.fromEntries(outstanding.map((l) => [key(l), String(l.outstanding_quantity)])));
  // GRN template: what passed inspection (only this goes into stock), the
  // line's condition, and a remark. Accepted follows Received until typed over.
  const [accepted, setAccepted] = useState<Record<string, string>>({});
  const [conditions, setConditions] = useState<Record<string, string>>({});
  const [lineRemarks, setLineRemarks] = useState<Record<string, string>>({});
  const [deliveryNote, setDeliveryNote] = useState("");
  const [deliveryDate, setDeliveryDate] = useState("");
  const [transporter, setTransporter] = useState("");
  const [gdReference, setGdReference] = useState("");
  const [inspectionNotes, setInspectionNotes] = useState("");
  const [discrepancyNotes, setDiscrepancyNotes] = useState("");
  const [billToFinance, setBillToFinance] = useState("No");
  const [checkedBy, setCheckedBy] = useState("");
  const acceptedOf = (k: string) => accepted[k] ?? quantities[k] ?? "";
  const dueOf = (l: ReceivableLine) => l.outstanding_quantity;
  /** Received less what was due on this receipt: negative short, positive excess. */
  const shortExcess = (l: ReceivableLine) => Number(quantities[key(l)] || 0) - dueOf(l);
  const conditionOf = (l: ReceivableLine) => {
    const k = key(l);
    if (conditions[k]) return conditions[k];
    const d = shortExcess(l);
    return d < 0 ? "Short" : d > 0 ? "Excess" : "Good";
  };
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ id: string; doc_number: string } | null>(null);
  const [posting, setPosting] = useState(false);

  const isImport = source.source === "shipment";
  const costingMissing = isImport && !source.landed_cost_ready;

  const save = async () => {
    const lines = outstanding
      .filter((l) => Number(quantities[key(l)] || 0) > 0)
      .map((l) => ({
        purchase_order_line_id: l.purchase_order_line_id ?? null,
        shipment_line_id: l.shipment_line_id ?? null,
        item_id: l.item_id,
        item_code: l.item_code,
        description: l.description,
        uom: l.uom,
        ordered_quantity: String(l.ordered_quantity),
        received_quantity: quantities[key(l)],
        accepted_quantity: acceptedOf(key(l)) || "0",
        condition: conditionOf(l),
        remarks: lineRemarks[key(l)] || null,
        unit_price: String(l.unit_price),
        discount_percent: String(l.discount_percent ?? 0),
        tax_percent: String(l.tax_percent ?? 0),
        warehouse_id: warehouseId || null,
      }));
    if (lines.length === 0) { setError("Enter a quantity on at least one line."); return; }
    // Stock in this ERP is held per location, so a receipt with no warehouse
    // puts the goods nowhere: the total is right but "where is it?" has no
    // answer. Insisted on here rather than in the API, which stays permissive
    // for the legacy movements that predate locations.
    if (!warehouseId) {
      setError("Choose the warehouse the goods came into — stock is held per "
        + "location, and without one these goods would not be anywhere.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const grn = await api.post<{ id: string; doc_number: string }>(
        "/procurement/goods-receipts", {
          doc_date: docDate,
          supplier_id: source.supplier_id,
          purchase_order_id: source.purchase_order_id,
          shipment_id: source.shipment_id ?? null,
          landed_cost_id: source.landed_cost_id ?? null,
          warehouse_id: warehouseId || null,
          supplier_invoice_number: invoiceNumber || null,
          supplier_invoice_date: invoiceDate || null,
          vehicle_number: vehicle || null,
          received_by: receivedBy || null,
          remarks: remarks || null,
          delivery_note_number: deliveryNote || null,
          delivery_date: deliveryDate || null,
          transporter: transporter || null,
          gd_reference: gdReference || null,
          inspection_notes: inspectionNotes || null,
          discrepancy_notes: discrepancyNotes || null,
          bill_to_finance: billToFinance,
          checked_by: checkedBy || null,
          currency: source.currency,
          exchange_rate: String(source.exchange_rate),
          lines,
        });
      setCreated(grn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the receipt.");
    } finally {
      setSaving(false);
    }
  };

  const post = async () => {
    if (!created) return;
    setPosting(true);
    setError(null);
    try {
      const result = await api.post<{ movements_written: number }>(
        `/procurement/goods-receipts/${created.id}/status`, { status: "Posted" });
      alert(`${created.doc_number} posted. ${result.movements_written} stock movement(s) `
        + "written — the goods are now in the warehouse.");
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post the receipt.");
    } finally {
      setPosting(false);
    }
  };

  const total = outstanding.reduce(
    (sum, l) => sum + Number(acceptedOf(key(l)) || 0) * l.unit_price, 0);

  return (
    <Modal
      title={`Receive against ${source.shipment ?? source.purchase_order ?? "purchase order"}`}
      open width="xl" saving={saving || posting} error={error}
      onClose={created ? onDone : onClose}
      onSave={created ? undefined : save}
      saveLabel="Save Receipt"
    >
      {created ? (
        <div className="space-y-4">
          <div className="rounded-lg bg-primary/10 px-4 py-3.5 text-[12.8px] text-primary">
            Goods receipt <b>{created.doc_number}</b> saved as a draft. It has not
            moved any stock yet.
          </div>
          {costingMissing && (
            <div className="flex items-start gap-2 rounded-lg bg-amber/10 px-4 py-3
                            text-[12.5px] text-amber">
              <AlertTriangle size={15} className="mt-px flex-shrink-0" />
              <span>
                This shipment has no posted landed costing, so posting will be refused.
                Cost the shipment first, or the goods would come into stock at the
                supplier price and understate their value by everything the import cost.
              </span>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2.5">
            <button onClick={post} disabled={posting || costingMissing}
              className="flex items-center gap-2 rounded-lg bg-gradient-to-br from-primary
                         to-primary-dark px-4 py-2 text-[12.8px] font-medium text-on-primary
                         disabled:opacity-50">
              {posting && <Loader2 size={14} className="animate-spin" />}
              <PackageCheck size={14} /> Post into stock now
            </button>
            <button onClick={onDone}
              className="rounded-lg bg-hover px-4 py-2 text-[12.8px] font-medium text-muted">
              Leave as a draft
            </button>
          </div>
          <p className="m-0 text-[11px] text-faint">
            Posting writes the stock movements, rolls the received quantities up to the
            order and the requirement, and cannot be undone except by a reversal.
          </p>
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg
                          border border-line bg-bg px-3.5 py-2.5 text-[11.5px]">
            <span className="text-muted">
              Source <b className="text-text">
                {source.source === "shipment" ? "Import shipment" : "Purchase order"}
              </b>
            </span>
            {source.purchase_order && (
              <span className="text-muted">Order <b className="text-text">
                {source.purchase_order}</b></span>
            )}
            {source.shipment && (
              <span className="text-muted">Shipment <b className="text-text">
                {source.shipment}</b></span>
            )}
            {source.transit_status && (
              <span className="text-muted">Goods are <b className="text-text">
                {source.transit_status}</b></span>
            )}
            <span className="text-muted">Currency <b className="text-text">
              {source.currency}</b></span>
            {source.landed_cost && (
              <span className="text-muted">Costing <b className="text-primary">
                {source.landed_cost}</b></span>
            )}
          </div>

          {costingMissing && (
            <div className="mb-4 flex items-start gap-2 rounded-lg bg-amber/10 px-4 py-3
                            text-[12.5px] text-amber">
              <AlertTriangle size={15} className="mt-px flex-shrink-0" />
              {source.pending_costing ? (
                <span>
                  Costing <b>{source.pending_costing}</b> has not been posted yet. You can record the
                  receipt now, but it can only go into stock once that costing is posted — open it under
                  {" "}<Link href="/inventory/inhouse-orders/landed-costs" className="underline">Import Landed
                  Costing</Link> and press <b>Post the costing</b>.
                </span>
              ) : (
                <span>
                  No posted landed costing for this shipment. You can record the receipt,
                  but posting it into stock will be refused until the import has been
                  costed — otherwise the goods enter stock at the supplier price.
                  {" "}
                  <Link href="/inventory/inhouse-orders/landed-costs"
                        className="underline">Cost this import</Link>.
                </span>
              )}
            </div>
          )}

          <div className="grid grid-cols-4 gap-4 max-sm:grid-cols-1">
            <Labelled label="Receipt Date" required>
              <TextInput type="date" value={docDate}
                onChange={(e) => setDocDate(e.target.value)} />
            </Labelled>
            <Labelled label="Into Warehouse" required>
              <Combobox value={warehouseId} options={toOptions(locations)}
                placeholder="Pick a warehouse…"
                emptyMessage="No warehouse matches that name."
                onChange={setWarehouseId} />
            </Labelled>
            <Labelled label="Supplier Invoice No">
              <TextInput value={invoiceNumber}
                onChange={(e) => setInvoiceNumber(e.target.value)} />
            </Labelled>
            <Labelled label="Supplier Invoice Date">
              <TextInput type="date" value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)} />
            </Labelled>

            <Labelled label="Delivery Note / Challan No">
              <TextInput value={deliveryNote} onChange={(e) => setDeliveryNote(e.target.value)} />
            </Labelled>
            <Labelled label="Delivery Date">
              <TextInput type="date" value={deliveryDate} onChange={(e) => setDeliveryDate(e.target.value)} />
            </Labelled>
            <Labelled label="Vehicle No">
              <TextInput value={vehicle} onChange={(e) => setVehicle(e.target.value)} />
            </Labelled>
            <Labelled label="Transporter">
              <TextInput value={transporter} onChange={(e) => setTransporter(e.target.value)} />
            </Labelled>

            <Labelled label="Received By">
              <TextInput value={receivedBy}
                onChange={(e) => setReceivedBy(e.target.value)} />
            </Labelled>
            <Labelled label="Checked By">
              <TextInput value={checkedBy} onChange={(e) => setCheckedBy(e.target.value)} />
            </Labelled>
            <Labelled label="Import / GD Ref.">
              <TextInput value={gdReference} placeholder={isImport ? "GD number" : "If applicable"}
                onChange={(e) => setGdReference(e.target.value)} />
            </Labelled>
            <Labelled label="Supplier Bill Forwarded to Finance?">
              <select value={billToFinance} onChange={(e) => setBillToFinance(e.target.value)}
                className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-[12.8px] outline-none focus:border-primary">
                {["Yes", "No", "Hold"].map((v) => <option key={v}>{v}</option>)}
              </select>
            </Labelled>

            <div className="col-span-2 max-sm:col-span-1">
              <Labelled label="Inspection / Verification Notes">
                <TextInput value={inspectionNotes} onChange={(e) => setInspectionNotes(e.target.value)} />
              </Labelled>
            </div>
            <div className="col-span-2 max-sm:col-span-1">
              <Labelled label="Discrepancy / Damage Details">
                <TextInput value={discrepancyNotes} onChange={(e) => setDiscrepancyNotes(e.target.value)} />
              </Labelled>
            </div>
            <div className="col-span-4 max-sm:col-span-1">
              <Labelled label="Remarks">
                <TextInput value={remarks} onChange={(e) => setRemarks(e.target.value)} />
              </Labelled>
            </div>
          </div>

          {outstanding.length === 0 ? (
            <p className="mt-5 rounded-lg bg-hover px-4 py-3 text-[12.8px] text-muted">
              Nothing is outstanding here — everything has already been received.
            </p>
          ) : (
            <div className="mt-5 overflow-hidden rounded-[10px] border border-line">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-line">
                    {["Item Code / Description", "UOM", source.source === "shipment" ? "Shipped Qty" : "PO Qty",
                      "Already Received", "Due Now", "Received Qty", "Accepted Qty", "Short / Excess",
                      "Condition", "Remarks", `Value (${source.currency})`].map((h, i) => (
                      <GridTh key={h} numeric={(i >= 2 && i <= 7) || i === 10}>{h}</GridTh>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {outstanding.map((line, index) => {
                    const k = key(line);
                    const receiving = Number(quantities[k] || 0);
                    const taking = Number(acceptedOf(k) || 0);
                    const diff = shortExcess(line);
                    const tooMuch = taking > receiving;
                    const overAccepted = taking > line.outstanding_quantity;
                    const num = (v: string) => v.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1");
                    return (
                      <tr key={k} className={gridRowClass(index)}>
                        <td className={gridCellClass(false, "max-w-[260px]")}>
                          <div className="text-[11px] text-faint">{line.item_code ?? "—"}</div>
                          <div className="text-[12.5px]">{line.description}</div>
                        </td>
                        <td className={gridCellClass()}>{line.uom ?? "—"}</td>
                        <td className={gridCellClass(true)}>{gridAmount(line.ordered_quantity)}</td>
                        <td className={gridCellClass(true)}>{gridAmount(line.already_received)}</td>
                        <td className={gridCellClass(true)}><b>{gridAmount(line.outstanding_quantity)}</b></td>
                        <td className={gridCellClass(true, "w-[100px]")}>
                          <TextInput inputMode="decimal" value={quantities[k] ?? ""}
                            onChange={(e) => setQuantities((q) => ({ ...q, [k]: num(e.target.value) }))} />
                        </td>
                        <td className={gridCellClass(true, "w-[100px]")}>
                          <TextInput inputMode="decimal" value={acceptedOf(k)}
                            className={tooMuch || overAccepted ? "border-rose" : undefined}
                            onChange={(e) => setAccepted((a) => ({ ...a, [k]: num(e.target.value) }))} />
                          {(tooMuch || overAccepted) && (
                            <span className="mt-1 block text-[10px] leading-tight text-rose">
                              {tooMuch ? "More than received" : `Only ${gridAmount(line.outstanding_quantity)} is owed — record the rest as Excess`}
                            </span>
                          )}
                        </td>
                        <td className={gridCellClass(true, diff < 0 ? "font-semibold text-rose" : diff > 0 ? "font-semibold text-amber" : "text-muted")}>
                          {diff > 0 ? "+" : ""}{gridAmount(diff)}
                        </td>
                        <td className={gridCellClass(false, "w-[140px]")}>
                          <select value={conditionOf(line)}
                            onChange={(e) => setConditions((c) => ({ ...c, [k]: e.target.value }))}
                            className="w-full rounded-md border border-line bg-bg px-2 py-1.5 text-[12px] outline-none focus:border-primary">
                            {["Good", "Damaged", "Short", "Excess", "Under Inspection"].map((c) => <option key={c}>{c}</option>)}
                          </select>
                        </td>
                        <td className={gridCellClass(false, "w-[160px]")}>
                          <TextInput value={lineRemarks[k] ?? ""}
                            onChange={(e) => setLineRemarks((r) => ({ ...r, [k]: e.target.value }))} />
                        </td>
                        <td className={gridCellClass(true)}>
                          {money(taking * line.unit_price, source.currency)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {total > 0 && (
            <div className="mt-3 flex items-center gap-3 text-[13px]">
              <span className="ml-auto text-muted">Receipt value</span>
              <b className="tabular-nums">{money(total, source.currency)}</b>
            </div>
          )}

          <p className="mt-3 text-[11px] text-faint">
            Received defaults to everything still due and Accepted follows it; type over them for a partial
            delivery or for goods turned away. Short / Excess is Received less Due Now. Only the Accepted
            quantity goes into stock and counts against the order, and a line Under Inspection cannot be
            posted. Saving records the receipt — it does not move stock until it is posted.
          </p>
        </>
      )}
    </Modal>
  );
}

/** A saved receipt, read-only. */
function ReceiptDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const [data, setData] = useState<(GrnRow & { lines: {
    id: string; item_code: string | null; description: string; uom: string | null;
    ordered_quantity: number; received_quantity: number; remaining_quantity: number;
    rejected_quantity: number; unit_price: number; unit_cost_base: number;
    net_amount: number; accepted_quantity: number; short_excess_quantity: number; condition: string;
    remarks: string | null;
  }[] } & Record<string, unknown>) | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<typeof data>(`/procurement/goods-receipts/${id}`)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load."));
  }, [id]);

  return (
    <Modal title={data ? `Goods Receipt ${data.doc_number}` : "Goods Receipt"}
           open width="lg" onClose={onClose}>
      {error && (
        <p className="rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>
      )}
      {!data && !error && (
        <div className="flex justify-center py-10">
          <Loader2 size={18} className="animate-spin text-primary" />
        </div>
      )}
      {data && (
        <>
          <div className="mb-4 flex flex-wrap gap-x-5 gap-y-1 rounded-lg border border-line
                          bg-bg px-3.5 py-2.5 text-[11.5px]">
            <span className="text-muted">Date <b className="text-text">
              {gridDate(data.doc_date)}</b></span>
            <span className="text-muted">Supplier <b className="text-text">
              {data.supplier ?? "—"}</b></span>
            <span className="text-muted">Warehouse <b className="text-text">
              {data.warehouse ?? "—"}</b></span>
            <span className="text-muted">Status <b className="text-text">
              {data.status}</b></span>
            <span className="text-muted">In stock <b className={
              data.is_posted ? "text-primary" : "text-faint"}>
              {data.is_posted ? "Yes" : "Not yet"}</b></span>
            {([["Delivery Note", data.delivery_note_number], ["Delivery Date", data.delivery_date ? gridDate(String(data.delivery_date)) : null],
               ["Transporter", data.transporter], ["GD Ref.", data.gd_reference], ["Checked By", data.checked_by],
               ["Bill to Finance", data.bill_to_finance]] as [string, unknown][])
              .filter(([, v]) => v).map(([label, v]) => (
                <span key={label} className="text-muted">{label} <b className="text-text">{String(v)}</b></span>
              ))}
          </div>
          {(data.inspection_notes || data.discrepancy_notes) ? (
            <div className="mb-4 grid grid-cols-2 gap-3 text-[12px] max-sm:grid-cols-1">
              {data.inspection_notes ? <p className="m-0 rounded-lg bg-hover px-3 py-2"><b>Inspection:</b> {String(data.inspection_notes)}</p> : null}
              {data.discrepancy_notes ? <p className="m-0 rounded-lg bg-rose/10 px-3 py-2 text-rose"><b>Discrepancy:</b> {String(data.discrepancy_notes)}</p> : null}
            </div>
          ) : null}

          <div className="overflow-hidden rounded-[10px] border border-line">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-line">
                  {["Item", "Uom", "PO Qty", "Received", "Accepted", "Short / Excess", "Condition",
                    "Unit Price", "Unit Cost (PKR)", "Net"].map((h, i) => (
                    <GridTh key={h} numeric={i >= 2 && i !== 6}>{h}</GridTh>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.lines.map((line, index) => (
                  <tr key={line.id} className={gridRowClass(index)}>
                    <td className={gridCellClass(false, "max-w-[260px]")}>
                      <div className="text-[12.5px]">{line.description}</div>
                      <div className="text-[11px] text-faint">{line.item_code}</div>
                    </td>
                    <td className={gridCellClass()}>{line.uom ?? "—"}</td>
                    <td className={gridCellClass(true)}>
                      {gridAmount(line.ordered_quantity)}</td>
                    <td className={gridCellClass(true)}>
                      <b>{gridAmount(line.received_quantity)}</b></td>
                    <td className={gridCellClass(true)}>
                      <b className="text-primary">{gridAmount(line.accepted_quantity)}</b></td>
                    <td className={gridCellClass(true, line.short_excess_quantity < 0 ? "text-rose" : line.short_excess_quantity > 0 ? "text-amber" : "text-muted")}>
                      {line.short_excess_quantity > 0 ? "+" : ""}{gridAmount(line.short_excess_quantity)}</td>
                    <td className={gridCellClass()}>
                      {line.condition}{line.remarks && <div className="text-[11px] text-faint">{line.remarks}</div>}</td>
                    <td className={gridCellClass(true)}>{gridAmount(line.unit_price)}</td>
                    <td className={gridCellClass(true)}>
                      {/* What the unit actually entered stock at: the landed
                          cost on an import, the purchase price otherwise. */}
                      <b className="text-primary">{gridAmount(line.unit_cost_base)}</b>
                    </td>
                    <td className={gridCellClass(true)}>{gridAmount(line.net_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  );
}

/** The whole chain behind a posted receipt. */
function TraceDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const [trace, setTrace] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Record<string, unknown>>(`/procurement/trace/${id}`)
      .then(setTrace)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load."));
  }, [id]);

  const link = (obj: unknown, keys: string[]): string | null => {
    if (!obj || typeof obj !== "object") return null;
    const record = obj as Record<string, unknown>;
    return keys.map((k) => record[k]).filter(Boolean).join(" · ") || null;
  };

  const steps: { label: string; value: string | null; note?: string | null }[] = trace
    ? [
        { label: "Requirement",
          value: link(trace.requirement, ["doc_number"]),
          note: link(trace.requirement, ["source", "requested_by"]) },
        { label: "Purchase Order",
          value: link(trace.purchase_order, ["doc_number"]),
          note: link(trace.purchase_order, ["purchase_type", "currency"]) },
        { label: "Supplier",
          value: link(trace.supplier, ["name"]),
          note: link(trace.supplier, ["country"]) },
        { label: "Shipment",
          value: link(trace.shipment, ["doc_number"]),
          note: link(trace.shipment, ["container_number", "transit_status"]) },
        { label: "Landed Cost",
          value: link(trace.landed_cost, ["doc_number"]),
          note: link(trace.landed_cost, ["status"]) },
        { label: "Goods Receipt",
          value: link(trace.goods_receipt, ["doc_number"]),
          note: link(trace.goods_receipt, ["warehouse"]) },
      ]
    : [];

  const movements = (trace?.stock_movements as {
    entry_date: string; direction: string; quantity: number;
    unit_cost: number | null; warehouse: string | null;
  }[] | undefined) ?? [];

  return (
    <Modal title="Where this stock came from" open width="lg" onClose={onClose}>
      {error && (
        <p className="rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>
      )}
      {!trace && !error && (
        <div className="flex justify-center py-10">
          <Loader2 size={18} className="animate-spin text-primary" />
        </div>
      )}
      {trace && (
        <>
          <div className="overflow-hidden rounded-[10px] border border-line">
            {steps.map((step, i) => (
              <div key={step.label}
                   className={`flex items-center gap-3 border-b border-line px-4 py-2.5
                               last:border-0 ${step.value ? "" : "opacity-45"}`}>
                <div className={`flex h-6 w-6 flex-shrink-0 items-center justify-center
                                 rounded-full text-[10.5px] font-semibold
                                 ${step.value ? "bg-primary text-on-primary"
                                              : "bg-hover text-faint"}`}>
                  {i + 1}
                </div>
                <div className="w-[130px] flex-shrink-0 text-[11.5px] text-muted">
                  {step.label}
                </div>
                <div className="min-w-0 flex-1">
                  <span className="text-[12.5px] font-medium">
                    {step.value ?? "—"}
                  </span>
                  {step.note && (
                    <span className="ml-2 text-[11px] text-faint">{step.note}</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <h4 className="mb-2 mt-4 text-[12.5px] font-semibold">Stock movements</h4>
          {movements.length === 0 ? (
            <p className="text-[12px] text-faint">
              None — this receipt has not been posted.
            </p>
          ) : (
            <div className="overflow-hidden rounded-[10px] border border-line">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-line">
                    {["Date", "Direction", "Quantity", "Unit Cost", "Warehouse"]
                      .map((h, i) => <GridTh key={h} numeric={i === 2 || i === 3}>{h}</GridTh>)}
                  </tr>
                </thead>
                <tbody>
                  {movements.map((mv, index) => (
                    <tr key={index} className={gridRowClass(index)}>
                      <td className={gridCellClass()}>{gridDate(mv.entry_date)}</td>
                      <td className={gridCellClass()}>
                        <span className={mv.direction === "in" ? "text-success" : "text-rose"}>
                          {mv.direction === "in" ? "In" : "Out"}
                        </span>
                      </td>
                      <td className={gridCellClass(true)}>{gridAmount(mv.quantity)}</td>
                      <td className={gridCellClass(true)}>
                        {mv.unit_cost != null ? gridAmount(mv.unit_cost) : "—"}
                      </td>
                      <td className={gridCellClass()}>{mv.warehouse ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

function Labelled({ label, required, children }: {
  label: string; required?: boolean; children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium text-muted">
        {label} {required && <span className="text-rose">*</span>}
      </span>
      {children}
    </label>
  );
}
