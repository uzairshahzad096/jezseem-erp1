"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Plus, Search, Loader2, Pencil, Ship, Calculator, PackageCheck, ChevronRight,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal, TextInput, Select, Combobox } from "@/components/ui/Modal";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate, gridAmount,
} from "@/components/ui/grid";
import {
  useProcurementList, SHIPPING_MODES, PAKISTAN_PORTS,
} from "@/lib/useProcurement";
import { useLookups, toOptions } from "@/lib/useLookups";
import { money } from "@/lib/currency";
import { api } from "@/lib/api";

/** Spec section 41 — how far the paperwork has got. */
const SHIPMENT_FLOW = [
  "Draft", "Booked", "Shipped", "In Transit", "Arrived",
  "Customs Pending", "Customs Cleared", "Warehouse Pending",
  "Partially Received", "Fully Received", "Closed",
];

/** Spec section 20 — where the goods physically are. */
const TRANSIT_STYLE: Record<string, string> = {
  Purchased: "bg-hover text-muted",
  Shipped: "bg-sky/15 text-sky",
  "In Transit": "bg-sky/15 text-sky",
  "Arrived Pakistan": "bg-amber/15 text-amber",
  Customs: "bg-amber/15 text-amber",
  Cleared: "bg-violet/15 text-violet",
  "Warehouse Received": "bg-success/15 text-success",
};

interface ShipRow {
  id: string;
  doc_number: string;
  doc_date: string;
  purchase_order_id: string;
  purchase_order: string | null;
  supplier_id: string;
  supplier: string | null;
  warehouse: string | null;
  warehouse_id: string | null;
  status: string;
  transit_status: string;
  customs_status: string | null;
  clearance_status: string | null;
  currency: string;
  exchange_rate: number;
  container_number: string | null;
  bill_of_lading_number: string | null;
  airway_bill_number: string | null;
  vessel_or_flight: string | null;
  port_of_loading: string | null;
  port_of_discharge: string | null;
  shipping_mode: string | null;
  clearing_agent: string | null;
  customs_reference: string | null;
  etd: string | null;
  eta: string | null;
  actual_arrival_date: string | null;
  cleared_date: string | null;
  freight_amount: number;
  insurance_amount: number;
  shipment_value: number;
  shipment_value_base: number;
  total_quantity: number;
  total_items: number;
  remarks: string | null;
}

interface ShipLine {
  id: string;
  purchase_order_line_id: string | null;
  item_id: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  hs_code: string | null;
  shipped_quantity: number;
  received_quantity: number;
  outstanding_quantity: number;
  unit_price: number;
  line_value: number;
  total_weight: number | null;
  total_volume: number | null;
}

interface ShipDetail extends ShipRow { lines: ShipLine[] }

const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: ShipRow) => React.ReactNode;
}[] = [
  { key: "doc_number", label: "Shipment No", sort: "doc_number",
    render: (r) => <span className="font-medium">{r.doc_number}</span> },
  { key: "doc_date", label: "Date", sort: "doc_date",
    render: (r) => <span className="whitespace-nowrap">{gridDate(r.doc_date)}</span> },
  { key: "purchase_order", label: "PO No", render: (r) => r.purchase_order ?? "—" },
  { key: "supplier", label: "Supplier", render: (r) => r.supplier ?? "—" },
  { key: "transit_status", label: "Where the goods are", sort: "transit_status",
    render: (r) => (
      <span className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                        ${TRANSIT_STYLE[r.transit_status] ?? "bg-hover text-muted"}`}>
        {r.transit_status}
      </span>
    ) },
  { key: "status", label: "Status", sort: "status", render: (r) => r.status },
  { key: "container_number", label: "Container", render: (r) => r.container_number ?? "—" },
  { key: "bill_of_lading_number", label: "BL No",
    render: (r) => r.bill_of_lading_number ?? "—" },
  { key: "vessel_or_flight", label: "Vessel / Flight",
    render: (r) => r.vessel_or_flight ?? "—" },
  { key: "port_of_loading", label: "Loading", render: (r) => r.port_of_loading ?? "—" },
  { key: "port_of_discharge", label: "Discharge",
    render: (r) => r.port_of_discharge ?? "—" },
  { key: "etd", label: "ETD",
    render: (r) => (r.etd ? <span className="whitespace-nowrap">{gridDate(r.etd)}</span> : "—") },
  { key: "eta", label: "ETA", sort: "eta",
    render: (r) => (r.eta ? <span className="whitespace-nowrap">{gridDate(r.eta)}</span> : "—") },
  { key: "actual_arrival_date", label: "Arrived",
    render: (r) => (r.actual_arrival_date
      ? <span className="whitespace-nowrap">{gridDate(r.actual_arrival_date)}</span> : "—") },
  { key: "clearing_agent", label: "Clearing Agent",
    render: (r) => r.clearing_agent ?? "—" },
  { key: "warehouse", label: "Warehouse", render: (r) => r.warehouse ?? "—" },
  { key: "total_quantity", label: "Qty", numeric: true,
    render: (r) => gridAmount(r.total_quantity) },
  { key: "shipment_value", label: "Value", numeric: true,
    render: (r) => money(r.shipment_value, r.currency) },
  { key: "shipment_value_base", label: "Value (PKR)", numeric: true,
    render: (r) => gridAmount(r.shipment_value_base) },
  { key: "freight_amount", label: "Freight (PKR)", numeric: true,
    render: (r) => gridAmount(r.freight_amount) },
  { key: "insurance_amount", label: "Insurance (PKR)", numeric: true,
    render: (r) => gridAmount(r.insurance_amount) },
];

const DEFAULT_HIDDEN = [
  "vessel_or_flight", "port_of_loading", "clearing_agent", "warehouse",
  "shipment_value_base", "freight_amount", "insurance_amount", "status",
];

export default function ShipmentsPage() {
  return (
    <Suspense fallback={
      <AppShell title="Import Shipments">
        <div className="flex justify-center py-20">
          <Loader2 size={22} className="animate-spin text-primary" />
        </div>
      </AppShell>
    }>
      <Shipments />
    </Suspense>
  );
}

function Shipments() {
  const params = useSearchParams();
  const [inTransitOnly, setInTransitOnly] = useState(false);
  const list = useProcurementList<ShipRow>("/procurement/shipments",
    inTransitOnly ? { extraParams: { in_transit_only: "true" } } : {});
  const { locations } = useLookups();

  const [creatingFor, setCreatingFor] = useState<string | null>(null);
  const [editing, setEditing] = useState<ShipDetail | null>(null);
  const [pickingOrder, setPickingOrder] = useState(false);

  const columnState = useHiddenColumns("import-shipments.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));

  const exportQuery = new URLSearchParams([
    ...(list.search ? [["search", list.search]] : []),
    ...list.statuses.map((s) => ["status", s] as [string, string]),
  ]).toString();

  // Arriving from a purchase order opens the shipment form on that order.
  useEffect(() => {
    const po = params.get("po");
    if (po) setCreatingFor(po);
  }, [params]);

  const open = async (id: string) => {
    try {
      setEditing(await api.get<ShipDetail>(`/procurement/shipments/${id}`));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not open the shipment.");
    }
  };

  const move = async (id: string, status: string) => {
    try {
      await api.post(`/procurement/shipments/${id}/status`, { status });
      await list.reload();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not change the status.");
    }
  };

  return (
    <AppShell title="Import Shipments">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Import Shipments</h1>
        <p className="m-0 text-[12px] text-muted">
          What left the supplier, and where it is. None of it is warehouse stock
          until a goods receipt is posted.
        </p>
        <button
          onClick={() => setInTransitOnly((v) => !v)}
          className={`rounded-lg px-3 py-1.5 text-[11.5px] font-medium transition-colors
                      ${inTransitOnly ? "bg-sky text-white"
                                      : "bg-hover text-muted hover:text-text"}`}>
          Goods in Transit only
        </button>
        <button onClick={() => setPickingOrder(true)}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br
                     from-primary to-primary-dark px-3.5 py-2 text-[12.8px]
                     font-medium text-on-primary">
          <Plus size={14} strokeWidth={2.4} /> Record Shipment
        </button>
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.total} noun={inTransitOnly ? "Shipment" : "Row"}
                    onReset={list.reset} resettable={list.dirty} />

        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={list.search} onChange={(e) => list.setSearch(e.target.value)}
              placeholder="Search shipment, container, BL, AWB…"
              className="w-60 border-none bg-transparent text-[12.8px] outline-none
                         placeholder:text-faint" />
          </div>
          <div className="ml-auto order-3 flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset={inTransitOnly ? "goods-in-transit" : "import-shipments"}
                          query={exportQuery} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Shipped", "In Transit", "Arrived", "Customs Cleared"].map((s) => (
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
                 style={{ minWidth: `${300 + visible.length * 125}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Edit</GridTh>
                <GridTh>Actions</GridTh>
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
                  {inTransitOnly
                    ? "Nothing in transit — every shipment has been received."
                    : "No shipments yet. Record one against an approved import order."}
                </td></tr>
              )}
              {!list.loading && list.rows.map((row, index) => (
                <tr key={row.id} className={`align-top ${gridRowClass(index)}`}>
                  <td className={gridCellClass()}>
                    <button onClick={() => void open(row.id)} aria-label="Edit" title="Edit"
                      className="rounded-md p-1.5 text-muted hover:bg-primary/10
                                 hover:text-primary">
                      <Pencil size={14} />
                    </button>
                  </td>
                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1">
                      {nextStep(row.status) && (
                        <button onClick={() => move(row.id, nextStep(row.status)!)}
                          title={`Mark as ${nextStep(row.status)}`}
                          className="whitespace-nowrap rounded-md bg-sky/10 px-2 py-1
                                     text-[10.5px] font-medium text-sky hover:bg-sky/20">
                          {nextStep(row.status)}
                          <ChevronRight size={10} className="ml-0.5 inline" />
                        </button>
                      )}
                      {["Cleared", "Arrived Pakistan", "Customs"]
                        .includes(row.transit_status) && (
                        <Link href={`/inventory/inhouse-orders/landed-costs?shipment=${row.id}`}
                          title="Work out the landed cost"
                          className="whitespace-nowrap rounded-md bg-violet/10 px-2 py-1
                                     text-[10.5px] font-medium text-violet hover:bg-violet/20">
                          <Calculator size={11} className="mr-1 inline" />Cost
                        </Link>
                      )}
                      {row.transit_status === "Cleared" && (
                        <Link href={`/inventory/inhouse-orders/goods-receipts?shipment=${row.id}`}
                          title="Receive into the warehouse"
                          className="whitespace-nowrap rounded-md bg-primary/10 px-2 py-1
                                     text-[10.5px] font-medium text-primary
                                     hover:bg-primary/20">
                          <PackageCheck size={11} className="mr-1 inline" />Receive
                        </Link>
                      )}
                    </div>
                  </td>
                  {visible.map((c) => (
                    <td key={c.key} className={gridCellClass(c.numeric)}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{list.total.toLocaleString()} shipments</span>
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

      {pickingOrder && (
        <ImportOrderPicker
          onClose={() => setPickingOrder(false)}
          onChoose={(id) => { setPickingOrder(false); setCreatingFor(id); }} />
      )}

      {creatingFor && (
        <ShipmentForm
          purchaseOrderId={creatingFor}
          locations={locations}
          onClose={() => setCreatingFor(null)}
          onDone={async () => { setCreatingFor(null); await list.reload(); }} />
      )}

      {editing && (
        <ShipmentDetail
          shipment={editing}
          onClose={() => setEditing(null)}
          onMove={async (status) => {
            await move(editing.id, status);
            setEditing(await api.get<ShipDetail>(`/procurement/shipments/${editing.id}`));
          }} />
      )}
    </AppShell>
  );
}

/** The next step in the shipment's journey, or nothing if it is finished. */
function nextStep(status: string): string | null {
  const i = SHIPMENT_FLOW.indexOf(status);
  if (i < 0 || i >= SHIPMENT_FLOW.length - 1) return null;
  // Skip the two "Pending" holding states: they are for a shipment stuck
  // somewhere, not the normal path forward.
  const next = SHIPMENT_FLOW[i + 1];
  if (next === "Warehouse Pending") return null;
  if (next === "Partially Received" || next === "Fully Received") return null;
  return next;
}

/** Approved import orders that can still be shipped. */
function ImportOrderPicker({ onClose, onChoose }: {
  onClose: () => void; onChoose: (id: string) => void;
}) {
  const list = useProcurementList<{
    id: string; doc_number: string; doc_date: string; supplier: string | null;
    supplier_country: string | null; currency: string; net_payable: number;
    total_items: number; status: string;
  }>("/procurement/purchase-orders", {
    pageSize: 10,
    initialStatuses: ["Approved", "Open", "Partially Received"],
    extraParams: { purchase_type: "Import" },
  });

  return (
    <Modal title="Record a shipment against" open width="lg" onClose={onClose}>
      <div className="mb-3 flex items-center gap-2 rounded-full border border-line bg-bg
                      px-3.5 py-2">
        <Search size={14} className="text-faint" />
        <input value={list.search} onChange={(e) => list.setSearch(e.target.value)}
          placeholder="Search import order, LC, invoice…"
          className="w-full border-none bg-transparent text-[12.8px] outline-none
                     placeholder:text-faint" />
      </div>

      {list.loading && (
        <div className="flex justify-center py-10">
          <Loader2 size={18} className="animate-spin text-primary" />
        </div>
      )}
      {!list.loading && list.rows.length === 0 && (
        <p className="py-10 text-center text-[12.8px] text-faint">
          No open import orders. An import order has to be approved before goods
          can ship against it.
        </p>
      )}
      {!list.loading && list.rows.length > 0 && (
        <div className="overflow-hidden rounded-[10px] border border-line">
          {list.rows.map((row) => (
            <button key={row.id} type="button" onClick={() => onChoose(row.id)}
              className="flex w-full items-start gap-3 border-b border-line px-4 py-3
                         text-left transition-colors last:border-0 hover:bg-primary/5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold">{row.doc_number}</span>
                  <span className="text-[11.5px] text-faint">{gridDate(row.doc_date)}</span>
                  <span className="text-[11px] text-muted">{row.status}</span>
                </div>
                <div className="truncate text-[12.5px]">
                  {row.supplier ?? "—"}
                  {row.supplier_country ? ` · ${row.supplier_country}` : ""}
                </div>
              </div>
              <div className="whitespace-nowrap text-right text-[12.5px] tabular-nums">
                {money(row.net_payable, row.currency)}
              </div>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

/** Record a shipment: the documents, the dates, and what is on board. */
function ShipmentForm({ purchaseOrderId, locations, onClose, onDone }: {
  purchaseOrderId: string;
  locations: { id: string; label: string }[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [order, setOrder] = useState<{
    doc_number: string; supplier: string | null; currency: string;
    exchange_rate: number; warehouse_id: string | null;
    port_of_loading: string | null; port_of_discharge: string | null;
    shipping_mode: string | null; clearing_agent: string | null;
    container_number: string | null;
    lines: { id: string; item_code: string | null; description: string;
             uom: string | null; hs_code: string | null; quantity: number;
             shipped_quantity: number; unit_price: number;
             unit_weight: number | null; unit_volume: number | null }[];
  } | null>(null);

  const [form, setForm] = useState({
    doc_date: new Date().toISOString().slice(0, 10),
    warehouse_id: "",
    container_number: "",
    bill_of_lading_number: "",
    airway_bill_number: "",
    vessel_or_flight: "",
    port_of_loading: "",
    port_of_discharge: "",
    shipping_mode: "",
    clearing_agent: "",
    customs_reference: "",
    etd: "",
    eta: "",
    freight_amount: "0",
    insurance_amount: "0",
    exchange_rate: "1",
    remarks: "",
  });
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [weights, setWeights] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const po = await api.get<typeof order>(
          `/procurement/purchase-orders/${purchaseOrderId}`);
        setOrder(po);
        if (!po) return;
        setForm((f) => ({
          ...f,
          warehouse_id: po.warehouse_id ?? "",
          container_number: po.container_number ?? "",
          port_of_loading: po.port_of_loading ?? "",
          port_of_discharge: po.port_of_discharge ?? "",
          shipping_mode: po.shipping_mode ?? "",
          clearing_agent: po.clearing_agent ?? "",
          exchange_rate: String(po.exchange_rate ?? 1),
        }));
        // Default to shipping everything not yet shipped.
        setQuantities(Object.fromEntries(po.lines.map((l) => [
          l.id, String(Math.max(0, l.quantity - l.shipped_quantity))])));
        setWeights(Object.fromEntries(po.lines
          .filter((l) => l.unit_weight)
          .map((l) => [l.id, String((l.unit_weight ?? 0)
            * Math.max(0, l.quantity - l.shipped_quantity))])));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load the order.");
      }
    })();
  }, [purchaseOrderId]);

  const save = async () => {
    if (!order) return;
    const lines = order.lines
      .filter((l) => Number(quantities[l.id] || 0) > 0)
      .map((l) => ({
        purchase_order_line_id: l.id,
        item_id: null,
        item_code: l.item_code,
        description: l.description,
        uom: l.uom,
        hs_code: l.hs_code,
        shipped_quantity: quantities[l.id],
        unit_price: String(l.unit_price),
        total_weight: weights[l.id] || null,
      }));
    if (lines.length === 0) { setError("Put at least one line on the shipment."); return; }

    setSaving(true);
    setError(null);
    try {
      await api.post("/procurement/shipments", {
        ...form,
        purchase_order_id: purchaseOrderId,
        warehouse_id: form.warehouse_id || null,
        etd: form.etd || null,
        eta: form.eta || null,
        currency: order.currency,
        exchange_rate: form.exchange_rate || "1",
        transit_status: "Purchased",
        lines,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the shipment.");
    } finally {
      setSaving(false);
    }
  };

  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));

  return (
    <Modal title={order ? `Shipment against ${order.doc_number}` : "Record Shipment"}
           open width="xl" saving={saving} error={error}
           onClose={onClose} onSave={order ? save : undefined} saveLabel="Save Shipment">
      {!order && !error && (
        <div className="flex justify-center py-10">
          <Loader2 size={18} className="animate-spin text-primary" />
        </div>
      )}

      {order && (
        <>
          <div className="mb-4 flex flex-wrap gap-x-5 gap-y-1 rounded-lg border border-line
                          bg-bg px-3.5 py-2.5 text-[11.5px]">
            <span className="text-muted">Supplier <b className="text-text">
              {order.supplier ?? "—"}</b></span>
            <span className="text-muted">Currency <b className="text-text">
              {order.currency}</b></span>
          </div>

          <div className="grid grid-cols-4 gap-4 max-sm:grid-cols-1">
            <Labelled label="Shipment Date" required>
              <TextInput type="date" value={form.doc_date}
                onChange={(e) => set({ doc_date: e.target.value })} />
            </Labelled>
            <Labelled label="Shipping Mode">
              <Select value={form.shipping_mode}
                options={SHIPPING_MODES.map((m) => ({ value: m, label: m }))}
                placeholder="Sea, Air, …"
                onChange={(e) => set({ shipping_mode: e.target.value })} />
            </Labelled>
            <Labelled label="Container No">
              <TextInput value={form.container_number}
                onChange={(e) => set({ container_number: e.target.value })} />
            </Labelled>
            <Labelled label="Vessel / Flight">
              <TextInput value={form.vessel_or_flight}
                onChange={(e) => set({ vessel_or_flight: e.target.value })} />
            </Labelled>

            <Labelled label="Bill of Lading No">
              <TextInput value={form.bill_of_lading_number}
                onChange={(e) => set({ bill_of_lading_number: e.target.value })} />
            </Labelled>
            <Labelled label="Airway Bill No">
              <TextInput value={form.airway_bill_number}
                onChange={(e) => set({ airway_bill_number: e.target.value })} />
            </Labelled>
            <Labelled label="Port of Loading">
              <TextInput value={form.port_of_loading}
                onChange={(e) => set({ port_of_loading: e.target.value })} />
            </Labelled>
            <Labelled label="Port of Discharge">
              <Combobox value={form.port_of_discharge} allowCustom
                options={PAKISTAN_PORTS.map((p) => ({ value: p, label: p }))}
                placeholder="Karachi Port, …"
                onChange={(v) => set({ port_of_discharge: v })} />
            </Labelled>

            <Labelled label="ETD">
              <TextInput type="date" value={form.etd}
                onChange={(e) => set({ etd: e.target.value })} />
            </Labelled>
            <Labelled label="ETA">
              <TextInput type="date" value={form.eta}
                onChange={(e) => set({ eta: e.target.value })} />
            </Labelled>
            <Labelled label="Clearing Agent">
              <TextInput value={form.clearing_agent}
                onChange={(e) => set({ clearing_agent: e.target.value })} />
            </Labelled>
            <Labelled label="Into Warehouse">
              <Combobox value={form.warehouse_id} options={toOptions(locations)}
                placeholder="Pick a warehouse…"
                onChange={(v) => set({ warehouse_id: v })} />
            </Labelled>

            <Labelled label="Freight (PKR)">
              <TextInput type="number" step="0.01" value={form.freight_amount}
                onChange={(e) => set({ freight_amount: e.target.value })} />
            </Labelled>
            <Labelled label="Insurance (PKR)">
              <TextInput type="number" step="0.01" value={form.insurance_amount}
                onChange={(e) => set({ insurance_amount: e.target.value })} />
            </Labelled>
            <Labelled label={`Exchange Rate (1 ${order.currency} = ? PKR)`}>
              <TextInput type="number" step="0.000001" value={form.exchange_rate}
                onChange={(e) => set({ exchange_rate: e.target.value })} />
            </Labelled>
            <Labelled label="Customs / GD Reference">
              <TextInput value={form.customs_reference}
                onChange={(e) => set({ customs_reference: e.target.value })} />
            </Labelled>
          </div>

          <p className="mt-2 text-[11px] text-faint">
            Freight and insurance are entered in PKR — they are normally settled
            locally. Both carry through to the landed costing, where they are spread
            across the goods. Anything billed in another currency is added there
            instead, with its own rate.
          </p>

          <div className="mt-5 overflow-hidden rounded-[10px] border border-line">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-line">
                  {["Item", "Uom", "Ordered", "Already Shipped", "Unshipped",
                    "Shipping Now", "Total Weight", `Unit Price (${order.currency})`,
                    "Line Value"].map((h, i) => (
                    <GridTh key={h} numeric={i >= 2}>{h}</GridTh>
                  ))}
                </tr>
              </thead>
              <tbody>
                {order.lines.map((line, index) => {
                  const unshipped = Math.max(0, line.quantity - line.shipped_quantity);
                  const now = Number(quantities[line.id] || 0);
                  const over = now > unshipped;
                  return (
                    <tr key={line.id} className={gridRowClass(index)}>
                      <td className={gridCellClass(false, "max-w-[260px]")}>
                        <div className="text-[12.5px]">{line.description}</div>
                        <div className="text-[11px] text-faint">{line.item_code}</div>
                      </td>
                      <td className={gridCellClass()}>{line.uom ?? "—"}</td>
                      <td className={gridCellClass(true)}>{gridAmount(line.quantity)}</td>
                      <td className={gridCellClass(true)}>
                        {gridAmount(line.shipped_quantity)}</td>
                      <td className={gridCellClass(true)}><b>{gridAmount(unshipped)}</b></td>
                      <td className={gridCellClass(true, "w-[120px]")}>
                        <TextInput type="number" step="0.0001" min="0"
                          value={quantities[line.id] ?? ""}
                          className={over ? "border-rose" : ""}
                          onChange={(e) => setQuantities((q) => ({
                            ...q, [line.id]: e.target.value }))} />
                        {over && (
                          <span className="mt-1 block text-[10px] text-rose">
                            More than the order has left.
                          </span>
                        )}
                      </td>
                      <td className={gridCellClass(true, "w-[110px]")}>
                        <TextInput type="number" step="0.0001" min="0"
                          value={weights[line.id] ?? ""}
                          placeholder="for freight"
                          onChange={(e) => setWeights((w) => ({
                            ...w, [line.id]: e.target.value }))} />
                      </td>
                      <td className={gridCellClass(true)}>{gridAmount(line.unit_price)}</td>
                      <td className={gridCellClass(true)}>
                        {money(now * line.unit_price, order.currency)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-[11px] text-faint">
            Total weight is what freight is usually spread by when the import is
            costed. A shipment does not move warehouse stock — it records goods that
            are on their way.
          </p>
        </>
      )}
    </Modal>
  );
}

/** A saved shipment, with its journey and its cargo. */
function ShipmentDetail({ shipment, onClose, onMove }: {
  shipment: ShipDetail;
  onClose: () => void;
  onMove: (status: string) => Promise<void>;
}) {
  const reached = SHIPMENT_FLOW.indexOf(shipment.status);
  const next = nextStep(shipment.status);

  return (
    <Modal title={`Shipment ${shipment.doc_number}`} open width="lg" onClose={onClose}>
      {/* The journey, so where it has got to is readable at a glance. */}
      <div className="mb-4 flex flex-wrap items-center gap-1">
        {SHIPMENT_FLOW.slice(0, 7).map((step, i) => (
          <span key={step}
            className={`rounded-md px-2 py-1 text-[10.5px] font-medium
                        ${i <= reached
                          ? "bg-success/15 text-success"
                          : "bg-hover text-faint"}`}>
            {step}
          </span>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap gap-x-5 gap-y-1 rounded-lg border border-line
                      bg-bg px-3.5 py-2.5 text-[11.5px]">
        <span className="text-muted">Goods are{" "}
          <b className="text-text">{shipment.transit_status}</b></span>
        <span className="text-muted">Order{" "}
          <b className="text-text">{shipment.purchase_order ?? "—"}</b></span>
        <span className="text-muted">Supplier{" "}
          <b className="text-text">{shipment.supplier ?? "—"}</b></span>
        {shipment.container_number && (
          <span className="text-muted">Container{" "}
            <b className="text-text">{shipment.container_number}</b></span>
        )}
        {shipment.eta && (
          <span className="text-muted">ETA{" "}
            <b className="text-text">{gridDate(shipment.eta)}</b></span>
        )}
        <span className="text-muted">Value{" "}
          <b className="text-text">
            {money(shipment.shipment_value, shipment.currency)}
          </b></span>
      </div>

      {next && (
        <button onClick={() => void onMove(next)}
          className="mb-4 flex items-center gap-2 rounded-lg bg-sky/10 px-3.5 py-2
                     text-[12.5px] font-medium text-sky hover:bg-sky/20">
          <Ship size={14} /> Mark as {next}
        </button>
      )}

      <div className="overflow-hidden rounded-[10px] border border-line">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-line">
              {["Item", "Uom", "HS Code", "Shipped", "Received", "Outstanding",
                "Weight", "Line Value"].map((h, i) => (
                <GridTh key={h} numeric={i >= 3}>{h}</GridTh>
              ))}
            </tr>
          </thead>
          <tbody>
            {shipment.lines.map((line, index) => (
              <tr key={line.id} className={gridRowClass(index)}>
                <td className={gridCellClass(false, "max-w-[240px]")}>
                  <div className="text-[12.5px]">{line.description}</div>
                  <div className="text-[11px] text-faint">{line.item_code}</div>
                </td>
                <td className={gridCellClass()}>{line.uom ?? "—"}</td>
                <td className={gridCellClass()}>{line.hs_code ?? "—"}</td>
                <td className={gridCellClass(true)}>
                  {gridAmount(line.shipped_quantity)}</td>
                <td className={gridCellClass(true)}>
                  {gridAmount(line.received_quantity)}</td>
                <td className={gridCellClass(true)}>
                  <b>{gridAmount(line.outstanding_quantity)}</b></td>
                <td className={gridCellClass(true)}>
                  {line.total_weight != null ? gridAmount(line.total_weight) : "—"}</td>
                <td className={gridCellClass(true)}>
                  {money(line.line_value, shipment.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
