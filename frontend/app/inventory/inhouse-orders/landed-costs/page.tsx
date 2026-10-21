"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Plus, Search, Loader2, Pencil, Calculator, CheckCircle2, Trash2,
  PackageCheck, Lock,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal, TextInput, Select, Combobox } from "@/components/ui/Modal";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate, gridAmount, gridMoney,
} from "@/components/ui/grid";
import { useProcurementList, useSuppliers } from "@/lib/useProcurement";
import { money } from "@/lib/currency";
import { api } from "@/lib/api";

const ALLOCATION_METHODS = ["Value", "Quantity", "Weight", "Volume", "Percentage", "Manual"];

const STATUS_STYLE: Record<string, string> = {
  Draft: "bg-hover text-muted",
  "Cost Entry": "bg-sky/15 text-sky",
  "Pending Approval": "bg-amber/15 text-amber",
  Approved: "bg-violet/15 text-violet",
  Posted: "bg-success/15 text-success",
  Cancelled: "bg-rose/15 text-rose",
};

/** The eight cost groups the report has columns for. */
const GROUP_COLUMN: { key: string; label: string }[] = [
  { key: "freight_cost", label: "Freight" },
  { key: "insurance_cost", label: "Insurance" },
  { key: "customs_cost", label: "Customs" },
  { key: "tax_cost", label: "Taxes" },
  { key: "port_cost", label: "Port" },
  { key: "clearing_cost", label: "Clearing" },
  { key: "bank_cost", label: "Bank" },
  { key: "other_cost", label: "Other" },
];

interface ChargeType {
  id: string;
  name: string;
  cost_group: string;
  default_allocation: string;
  default_rate_percent: number | null;
  is_inventoriable: boolean;
  is_active: boolean;
}

interface LcRow {
  id: string;
  doc_number: string;
  doc_date: string;
  purchase_order: string | null;
  purchase_order_id: string | null;
  shipment: string | null;
  shipment_id: string | null;
  supplier: string | null;
  supplier_id: string | null;
  status: string;
  is_posted: boolean;
  currency: string;
  exchange_rate: number;
  allocation_method: string;
  supplier_invoice_number: string | null;
  customs_reference: string | null;
  purchase_cost_base: number;
  additional_cost_base: number;
  total_landed_cost: number;
  additional_cost_percent: number | null;
  total_quantity: number;
  total_items: number;
  remarks: string | null;
}

interface LcCharge {
  id: string;
  charge_type_id: string | null;
  name: string;
  cost_group: string;
  vendor_id: string | null;
  vendor: string | null;
  reference: string | null;
  currency: string;
  exchange_rate: number;
  amount: number;
  amount_base: number;
  allocation_method: string;
  is_inventoriable: boolean;
  remarks: string | null;
}

interface LcItem {
  id: string;
  line_number: number;
  purchase_order_line_id: string | null;
  shipment_line_id: string | null;
  item_id: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  hs_code: string | null;
  quantity: number;
  total_weight: number | null;
  total_volume: number | null;
  manual_share_percent: number | null;
  unit_price: number;
  purchase_cost: number;
  purchase_cost_base: number;
  freight_cost: number;
  insurance_cost: number;
  customs_cost: number;
  tax_cost: number;
  port_cost: number;
  clearing_cost: number;
  bank_cost: number;
  other_cost: number;
  additional_cost: number;
  total_landed_cost: number;
  unit_landed_cost: number;
  unit_purchase_cost: number;
}

interface LcDetail extends LcRow { charges: LcCharge[]; items: LcItem[] }

const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: LcRow) => React.ReactNode;
}[] = [
  { key: "doc_number", label: "Costing No", sort: "doc_number",
    render: (r) => <span className="font-medium">{r.doc_number}</span> },
  { key: "doc_date", label: "Date", sort: "doc_date",
    render: (r) => <span className="whitespace-nowrap">{gridDate(r.doc_date)}</span> },
  { key: "shipment", label: "Shipment", render: (r) => r.shipment ?? "—" },
  { key: "purchase_order", label: "PO No", render: (r) => r.purchase_order ?? "—" },
  { key: "supplier", label: "Supplier", render: (r) => r.supplier ?? "—" },
  { key: "status", label: "Status", sort: "status",
    render: (r) => (
      <span className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                        ${STATUS_STYLE[r.status] ?? "bg-hover text-muted"}`}>
        {r.status}
      </span>
    ) },
  { key: "allocation_method", label: "Allocated By", render: (r) => r.allocation_method },
  { key: "currency", label: "Currency", render: (r) => r.currency },
  { key: "exchange_rate", label: "Rate", numeric: true,
    render: (r) => gridAmount(r.exchange_rate) },
  { key: "purchase_cost_base", label: "Purchase Cost", numeric: true,
    render: (r) => gridAmount(r.purchase_cost_base) },
  { key: "additional_cost_base", label: "Import Cost", numeric: true,
    render: (r) => gridAmount(r.additional_cost_base) },
  { key: "total_landed_cost", label: "Total Landed Cost", numeric: true,
    sort: "total_landed_cost",
    render: (r) => <span className="font-semibold">{gridAmount(r.total_landed_cost)}</span> },
  { key: "additional_cost_percent", label: "Import Cost %", numeric: true,
    render: (r) => (r.additional_cost_percent != null
      ? <span className={r.additional_cost_percent > 25 ? "text-rose" : ""}>
          {r.additional_cost_percent}%
        </span>
      : "—") },
  { key: "total_quantity", label: "Qty", numeric: true,
    render: (r) => gridAmount(r.total_quantity) },
  { key: "supplier_invoice_number", label: "Supplier Invoice",
    render: (r) => r.supplier_invoice_number ?? "—" },
];

const DEFAULT_HIDDEN = ["purchase_order", "exchange_rate", "supplier_invoice_number"];

export default function LandedCostsPage() {
  return (
    <Suspense fallback={
      <AppShell title="Import Landed Costing">
        <div className="flex justify-center py-20">
          <Loader2 size={22} className="animate-spin text-primary" />
        </div>
      </AppShell>
    }>
      <LandedCosts />
    </Suspense>
  );
}

function LandedCosts() {
  const params = useSearchParams();
  const list = useProcurementList<LcRow>("/procurement/landed-costs");
  const suppliers = useSuppliers();

  const [chargeTypes, setChargeTypes] = useState<ChargeType[]>([]);
  const [editing, setEditing] = useState<LcDetail | null>(null);
  const [pickingShipment, setPickingShipment] = useState(false);

  const columnState = useHiddenColumns("landed-costs.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));

  useEffect(() => {
    api.get<{ items: ChargeType[] }>("/procurement/charge-types")
      .then((d) => setChargeTypes(d.items))
      .catch(() => setChargeTypes([]));
  }, []);

  const open = useCallback(async (id: string) => {
    try {
      setEditing(await api.get<LcDetail>(`/procurement/landed-costs/${id}`));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not open the costing.");
    }
  }, []);

  /** Start a costing from a shipment, pre-filled with its goods and charges. */
  const starting = useRef(false);
  const startFromShipment = useCallback(async (shipmentId: string) => {
    // One at a time: a double click, or the page's start-up running twice, must not
    // make two costings for one shipment (LC-2600006 / 07, 19-Oct-2026).
    if (starting.current) return;
    starting.current = true;
    try {
      // A shipment with a costing already opens that one.
      const found = await api.get<{ items: { id: string; status: string }[] }>(
        `/procurement/landed-costs?shipment_id=${shipmentId}&page_size=50`);
      const live = found.items.find((c) => c.status !== "Cancelled");
      if (live) {
        setPickingShipment(false);
        setEditing(await api.get<LcDetail>(`/procurement/landed-costs/${live.id}`));
        return;
      }
      const voucher = await api.post<LcDetail>(
        `/procurement/shipments/${shipmentId}/landed-cost`,
        { allocation_method: "Value", include_shipment_charges: true });
      setPickingShipment(false);
      setEditing(voucher);
      await list.reload();
    } catch (err) {
      // Most often: this shipment already has a costing. Say which one.
      alert(err instanceof Error ? err.message : "Could not start a costing.");
      setPickingShipment(false);
    } finally {
      starting.current = false;
    }
  }, [list]);

  // Arriving from a shipment starts (or opens) its costing straight away.
  useEffect(() => {
    const shipment = params.get("shipment");
    if (shipment) void startFromShipment(shipment);
    // startFromShipment is stable enough here; re-running on every list
    // reload would create a second voucher.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const exportQuery = new URLSearchParams([
    ...(list.search ? [["search", list.search]] : []),
  ]).toString();

  return (
    <AppShell title="Import Landed Costing">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Import Landed Costing</h1>
        <p className="m-0 text-[12px] text-muted">
          What an import really cost. Only a posted costing sets the value goods
          enter stock at.
        </p>
        <Link href="/inventory/reports/import-landed-costing"
          className="rounded-lg bg-hover px-3 py-1.5 text-[11.5px] font-medium text-muted
                     hover:text-text">
          Open the report
        </Link>
        <button onClick={() => setPickingShipment(true)}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br
                     from-primary to-primary-dark px-3.5 py-2 text-[12.8px]
                     font-medium text-on-primary">
          <Plus size={14} strokeWidth={2.4} /> Cost an Import
        </button>
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.total} onReset={list.reset} resettable={list.dirty} />

        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={list.search} onChange={(e) => list.setSearch(e.target.value)}
              placeholder="Search costing, invoice, GD reference…"
              className="w-60 border-none bg-transparent text-[12.8px] outline-none
                         placeholder:text-faint" />
          </div>
          <div className="ml-auto order-3 flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset="import-landed-costing" query={exportQuery} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Cost Entry", "Pending Approval", "Approved", "Posted"].map((s) => (
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
                 style={{ minWidth: `${200 + visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Edit</GridTh>
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
                <tr><td colSpan={visible.length + 1} className="px-5 py-12 text-center">
                  <Loader2 size={18} className="mx-auto animate-spin text-primary" />
                </td></tr>
              )}
              {!list.loading && list.rows.length === 0 && (
                <tr><td colSpan={visible.length + 1}
                        className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No costings yet. Cost an import once its shipment has arrived and
                  the duty, freight and clearing charges are known.
                </td></tr>
              )}
              {!list.loading && list.rows.map((row, index) => (
                <tr key={row.id} className={`align-top ${gridRowClass(index)}`}>
                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1">
                      <button onClick={() => void open(row.id)}
                        aria-label="Open" title="Open"
                        className="rounded-md p-1.5 text-muted hover:bg-primary/10
                                   hover:text-primary">
                        {row.is_posted ? <Lock size={13} /> : <Pencil size={14} />}
                      </button>
                      {row.is_posted && row.shipment_id && (
                        <Link
                          href={`/inventory/inhouse-orders/goods-receipts?shipment=${row.shipment_id}`}
                          title="Receive the goods into the warehouse"
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
          <span>{list.total.toLocaleString()} costings</span>
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

      {pickingShipment && (
        <ShipmentPicker onClose={() => setPickingShipment(false)}
                        onChoose={startFromShipment} />
      )}

      {editing && (
        <CostingForm
          voucher={editing}
          chargeTypes={chargeTypes}
          suppliers={suppliers}
          onClose={() => setEditing(null)}
          onSaved={async (fresh) => { setEditing(fresh); await list.reload(); }}
          onDone={async () => { setEditing(null); await list.reload(); }} />
      )}
    </AppShell>
  );
}

/** Shipments that have arrived and can be costed. */
function ShipmentPicker({ onClose, onChoose }: {
  onClose: () => void; onChoose: (id: string) => void;
}) {
  const list = useProcurementList<{
    id: string; doc_number: string; doc_date: string; supplier: string | null;
    purchase_order: string | null; transit_status: string; currency: string;
    shipment_value: number; total_quantity: number; container_number: string | null;
  }>("/procurement/shipments", { pageSize: 10 });

  // Costing before the goods land is possible but unusual; the ones worth
  // offering are those that have arrived or cleared.
  const ready = list.rows.filter((r) =>
    ["Arrived Pakistan", "Customs", "Cleared"].includes(r.transit_status));

  return (
    <Modal title="Cost which import?" open width="lg" onClose={onClose}>
      <div className="mb-3 flex items-center gap-2 rounded-full border border-line bg-bg
                      px-3.5 py-2">
        <Search size={14} className="text-faint" />
        <input value={list.search} onChange={(e) => list.setSearch(e.target.value)}
          placeholder="Search shipment, container, BL…"
          className="w-full border-none bg-transparent text-[12.8px] outline-none
                     placeholder:text-faint" />
      </div>

      {list.loading && (
        <div className="flex justify-center py-10">
          <Loader2 size={18} className="animate-spin text-primary" />
        </div>
      )}
      {!list.loading && ready.length === 0 && (
        <p className="py-10 text-center text-[12.8px] text-faint">
          No arrived shipments to cost. A shipment becomes costable once it reaches
          Pakistan — that is when duty, port and clearing charges are known.
        </p>
      )}
      {!list.loading && ready.length > 0 && (
        <div className="overflow-hidden rounded-[10px] border border-line">
          {ready.map((row) => (
            <button key={row.id} type="button" onClick={() => onChoose(row.id)}
              className="flex w-full items-start gap-3 border-b border-line px-4 py-3
                         text-left transition-colors last:border-0 hover:bg-primary/5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-semibold">{row.doc_number}</span>
                  <span className="text-[11.5px] text-faint">{gridDate(row.doc_date)}</span>
                  <span className="rounded bg-amber/15 px-1.5 py-0.5 text-[10px]
                                   font-semibold text-amber">
                    {row.transit_status}
                  </span>
                </div>
                <div className="truncate text-[12.5px]">
                  {row.supplier ?? "—"}
                  {row.purchase_order ? ` · ${row.purchase_order}` : ""}
                  {row.container_number ? ` · ${row.container_number}` : ""}
                </div>
              </div>
              <div className="whitespace-nowrap text-right text-[12.5px] tabular-nums">
                {money(row.shipment_value, row.currency)}
              </div>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

/**
 * Enter the import's costs and see what each unit really cost.
 *
 * The arithmetic is done on the server on every save, so the unit landed cost
 * shown here is the figure that will be used — not a browser estimate of it.
 */
function CostingForm({ voucher, chargeTypes, suppliers, onClose, onSaved, onDone }: {
  voucher: LcDetail;
  chargeTypes: ChargeType[];
  suppliers: ReturnType<typeof useSuppliers>;
  onClose: () => void;
  onSaved: (fresh: LcDetail) => Promise<void>;
  onDone: () => void;
}) {
  const posted = voucher.is_posted;
  const [rate, setRate] = useState(String(voucher.exchange_rate));
  const [method, setMethod] = useState(voucher.allocation_method);
  const [invoiceNumber, setInvoiceNumber] = useState(voucher.supplier_invoice_number ?? "");
  const [customsRef, setCustomsRef] = useState(voucher.customs_reference ?? "");
  const [charges, setCharges] = useState<LcCharge[]>(voucher.charges);
  const [items, setItems] = useState<LcItem[]>(voucher.items);
  const [saving, setSaving] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showBreakdown, setShowBreakdown] = useState(false);

  useEffect(() => {
    setCharges(voucher.charges);
    setItems(voucher.items);
    setRate(String(voucher.exchange_rate));
    setMethod(voucher.allocation_method);
  }, [voucher]);

  const addCharge = (typeId: string) => {
    const type = chargeTypes.find((t) => t.id === typeId);
    if (!type) return;
    setCharges((c) => [...c, {
      id: `new-${Date.now()}`,
      charge_type_id: type.id,
      name: type.name,
      cost_group: type.cost_group,
      vendor_id: null, vendor: null, reference: null,
      currency: "PKR", exchange_rate: 1,
      amount: 0, amount_base: 0,
      allocation_method: type.default_allocation,
      is_inventoriable: type.is_inventoriable,
      remarks: null,
    }]);
  };

  const setCharge = (id: string, patch: Partial<LcCharge>) =>
    setCharges((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));

  /** Save and re-cost. The server returns the allocated figures. */
  const recost = async () => {
    setWorking(true);
    setError(null);
    try {
      const fresh = await api.put<LcDetail>(`/procurement/landed-costs/${voucher.id}`, {
        doc_date: voucher.doc_date,
        purchase_order_id: voucher.purchase_order_id,
        shipment_id: voucher.shipment_id,
        supplier_id: voucher.supplier_id,
        currency: voucher.currency,
        exchange_rate: rate || "1",
        allocation_method: method,
        supplier_invoice_number: invoiceNumber || null,
        customs_reference: customsRef || null,
        charges: charges.map((c) => ({
          id: c.id.startsWith("new-") ? null : c.id,
          charge_type_id: c.charge_type_id,
          name: c.name,
          cost_group: c.cost_group,
          vendor_id: c.vendor_id,
          reference: c.reference,
          currency: c.currency,
          exchange_rate: String(c.exchange_rate || 1),
          amount: String(c.amount || 0),
          allocation_method: c.allocation_method,
          is_inventoriable: c.is_inventoriable,
        })),
        items: items.map((i) => ({
          id: i.id,
          purchase_order_line_id: i.purchase_order_line_id,
          shipment_line_id: i.shipment_line_id,
          item_id: i.item_id,
          item_code: i.item_code,
          description: i.description,
          uom: i.uom,
          hs_code: i.hs_code,
          quantity: String(i.quantity),
          unit_price: String(i.unit_price),
          total_weight: i.total_weight != null ? String(i.total_weight) : null,
          total_volume: i.total_volume != null ? String(i.total_volume) : null,
          manual_share_percent: i.manual_share_percent != null
            ? String(i.manual_share_percent) : null,
        })),
      });
      await onSaved(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not work out the costing.");
    } finally {
      setWorking(false);
    }
  };

  const move = async (status: string) => {
    setSaving(true);
    setError(null);
    try {
      await api.post(`/procurement/landed-costs/${voucher.id}/status`, { status });
      if (status === "Posted") {
        alert(`${voucher.doc_number} posted. The goods will come into stock at the `
          + "unit landed costs shown.");
        onDone();
      } else {
        const fresh = await api.get<LcDetail>(`/procurement/landed-costs/${voucher.id}`);
        await onSaved(fresh);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the status.");
    } finally {
      setSaving(false);
    }
  };

  const chargeTotal = useMemo(
    () => charges.reduce((sum, c) =>
      sum + Number(c.amount || 0) * Number(c.exchange_rate || 1), 0),
    [charges]);

  /** What the form holds, in the shape that matters for the figures, so a change
   *  not yet worked out on the server can be told apart from the saved costing. */
  const shape = (r: string, m: string, inv: string, ref: string, cs: LcCharge[], its: LcItem[]) => JSON.stringify({
    r: Number(r || 0), m, inv: inv || "", ref: ref || "",
    cs: cs.map((c) => [c.charge_type_id, c.vendor_id, c.reference ?? "", c.currency, Number(c.exchange_rate || 1),
                       Number(c.amount || 0), c.allocation_method, c.is_inventoriable]),
    its: its.map((i) => [i.id, i.manual_share_percent ?? null]),
  });
  const stale = !posted && shape(rate, method, invoiceNumber, customsRef, charges, items)
    !== shape(String(voucher.exchange_rate), voucher.allocation_method, voucher.supplier_invoice_number ?? "",
              voucher.customs_reference ?? "", voucher.charges, voucher.items);

  const nextStatus = {
    Draft: "Cost Entry",
    "Cost Entry": "Pending Approval",
    "Pending Approval": "Approved",
    Approved: "Posted",
  }[voucher.status];

  /** Weight and volume only mean something if they were captured. */
  const missingBasis =
    (method === "Weight" && items.every((i) => !i.total_weight)) ||
    (method === "Volume" && items.every((i) => !i.total_volume));

  return (
    <Modal
      title={`${posted ? "" : "Costing "}${voucher.doc_number}`}
      open width="xl" saving={saving || working} error={error}
      onClose={onClose}
      onSave={posted ? undefined : recost}
      saveLabel="Work out the costs"
    >
      <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg
                      border border-line bg-bg px-3.5 py-2.5 text-[11.5px]">
        <span className="text-muted">Shipment{" "}
          <b className="text-text">{voucher.shipment ?? "—"}</b></span>
        <span className="text-muted">Order{" "}
          <b className="text-text">{voucher.purchase_order ?? "—"}</b></span>
        <span className="text-muted">Supplier{" "}
          <b className="text-text">{voucher.supplier ?? "—"}</b></span>
        <span className={`rounded-md px-2 py-0.5 text-[10.5px] font-semibold
                          ${STATUS_STYLE[voucher.status] ?? "bg-hover text-muted"}`}>
          {voucher.status}
        </span>
        {posted && (
          <span className="flex items-center gap-1 text-primary">
            <Lock size={11} /> Posted — these figures are now history
          </span>
        )}
      </div>

      <div className="grid grid-cols-4 gap-4 max-sm:grid-cols-1">
        <Labelled label={`Exchange Rate (1 ${voucher.currency} = ? PKR)`}>
          <TextInput inputMode="decimal" value={rate} disabled={posted} onFocus={(e) => e.target.select()}
            onChange={(e) => setRate(e.target.value.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1"))} />
        </Labelled>
        <Labelled label="Spread costs by">
          <Select value={method} disabled={posted}
            options={ALLOCATION_METHODS.map((m) => ({ value: m, label: m }))}
            onChange={(e) => setMethod(e.target.value)} />
        </Labelled>
        <Labelled label="Supplier Invoice No">
          <TextInput value={invoiceNumber} disabled={posted}
            onChange={(e) => setInvoiceNumber(e.target.value)} />
        </Labelled>
        <Labelled label="Customs / GD Reference">
          <TextInput value={customsRef} disabled={posted}
            onChange={(e) => setCustomsRef(e.target.value)} />
        </Labelled>
      </div>

      {missingBasis && (
        <p className="mt-3 rounded-lg bg-amber/10 px-3.5 py-2.5 text-[12px] text-amber">
          Spreading by {method.toLowerCase()} needs a {method.toLowerCase()} on the
          goods, and none is recorded. Every charge would be split evenly instead —
          either enter the figures on the shipment, or spread by value.
        </p>
      )}

      {/* ------------------------------------------------------- the charges */}
      <div className="mt-5 overflow-hidden rounded-[10px] border border-line">
        <div className="flex flex-wrap items-center gap-3 bg-primary px-4 py-2.5 text-on-primary">
          <h4 className="m-0 text-[13px] font-semibold">Import Costs</h4>
          <span className="text-[11px] text-on-primary/80">
            Freight, duty, taxes, port, clearing, bank — each spread across the goods
          </span>
          {!posted && (
            <div className="ml-auto w-[240px]">
              {/* The options are drawn by the browser on its own white popup,
                  so the control cannot inherit white text — that is what made
                  this list look empty. Only the closed box is tinted. */}
              <Select value="" placeholder="Add a cost…"
                className="border-white/40 bg-white text-text"
                options={chargeTypes.map((t) => ({
                  value: t.id, label: `${t.name}  (${t.cost_group})` }))}
                onChange={(e) => { if (e.target.value) addCharge(e.target.value); }} />
            </div>
          )}
        </div>

        {charges.length === 0 ? (
          <p className="px-4 py-6 text-center text-[12.5px] text-faint">
            No costs entered. Add the freight, duty, taxes, port and clearing charges —
            without them, posting would treat the supplier price as the landed cost.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] border-collapse text-left">
              <thead>
                <tr className="border-b border-line bg-hover">
                  {["Cost", "Group", "Paid To", "Reference", "Currency", "Rate",
                    "Amount", "Amount (PKR)", "Spread By", "In Stock Value", ""]
                    .map((h, i) => (
                      <GridTh key={h} numeric={[5, 6, 7].includes(i)}>{h}</GridTh>
                    ))}
                </tr>
              </thead>
              <tbody>
                {charges.map((charge, index) => (
                  <tr key={charge.id} className={gridRowClass(index)}>
                    <td className={gridCellClass(false, "min-w-[170px]")}>
                      {charge.name}
                    </td>
                    <td className={gridCellClass()}>
                      <span className="rounded bg-hover px-1.5 py-0.5 text-[10.5px]">
                        {charge.cost_group}
                      </span>
                    </td>
                    <td className={gridCellClass(false, "w-[180px]")}>
                      <Combobox value={charge.vendor_id ?? ""} disabled={posted}
                        options={suppliers.map((s) => ({
                          value: s.id, label: s.name, short: s.name }))}
                        placeholder="Forwarder, agent, bank…"
                        onChange={(v) => setCharge(charge.id, { vendor_id: v || null })} />
                    </td>
                    <td className={gridCellClass(false, "w-[130px]")}>
                      <TextInput value={charge.reference ?? ""} disabled={posted}
                        onChange={(e) => setCharge(charge.id, {
                          reference: e.target.value })} />
                    </td>
                    <td className={gridCellClass(false, "w-[90px]")}>
                      <TextInput value={charge.currency} disabled={posted}
                        onChange={(e) => setCharge(charge.id, {
                          currency: e.target.value.toUpperCase(),
                          exchange_rate: e.target.value.toUpperCase() === "PKR"
                            ? 1 : charge.exchange_rate })} />
                    </td>
                    <td className={gridCellClass(true, "w-[100px]")}>
                      <TextInput type="number" step="0.000001"
                        value={String(charge.exchange_rate)}
                        disabled={posted || charge.currency === "PKR"}
                        onChange={(e) => setCharge(charge.id, {
                          exchange_rate: Number(e.target.value) })} />
                    </td>
                    <td className={gridCellClass(true, "w-[130px]")}>
                      <TextInput type="number" step="0.01" value={String(charge.amount)}
                        disabled={posted}
                        onChange={(e) => setCharge(charge.id, {
                          amount: Number(e.target.value) })} />
                    </td>
                    <td className={gridCellClass(true)}>
                      {gridAmount(Number(charge.amount || 0)
                        * Number(charge.exchange_rate || 1))}
                    </td>
                    <td className={gridCellClass(false, "w-[120px]")}>
                      <Select value={charge.allocation_method} disabled={posted}
                        options={ALLOCATION_METHODS.map((m) => ({ value: m, label: m }))}
                        onChange={(e) => setCharge(charge.id, {
                          allocation_method: e.target.value })} />
                    </td>
                    <td className={gridCellClass()}>
                      {/* A charge the company chooses to expense rather than
                          capitalise is recorded but not added to stock value. */}
                      <button type="button" disabled={posted}
                        onClick={() => setCharge(charge.id, {
                          is_inventoriable: !charge.is_inventoriable })}
                        className={`rounded px-2 py-0.5 text-[10.5px] font-medium
                                    ${charge.is_inventoriable
                                      ? "bg-success/15 text-success"
                                      : "bg-hover text-muted"}`}>
                        {charge.is_inventoriable ? "Included" : "Expensed"}
                      </button>
                    </td>
                    <td className={gridCellClass()}>
                      {!posted && (
                        <button type="button" aria-label="Remove cost"
                          onClick={() => setCharges((cs) =>
                            cs.filter((c) => c.id !== charge.id))}
                          className="rounded-md p-1.5 text-muted hover:bg-rose/10
                                     hover:text-rose">
                          <Trash2 size={13} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-line bg-hover/50">
                  <td className={gridCellClass(false)} colSpan={7}>
                    <b className="text-[12px]">Total import costs</b>
                  </td>
                  <td className={gridCellClass(true)}>
                    <b>{gridAmount(chargeTotal)}</b>
                  </td>
                  <td className={gridCellClass()} colSpan={3} />
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* --------------------------------------------------------- the goods */}
      {stale && (
        <div className="mt-5 flex flex-wrap items-center gap-3 rounded-[10px] border border-amber/40 bg-amber/10
                        px-4 py-3 text-[12.5px] text-amber">
          <span className="flex-1">
            <b>These figures are out of date.</b> The costs or the exchange rate have changed since they were
            last worked out — press <b>Work out the costs</b> to spread the new costs over the goods.
          </span>
          <button type="button" onClick={() => void recost()} disabled={working}
            className="rounded-lg bg-amber px-3.5 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50">
            Work out the costs
          </button>
        </div>
      )}
      <div className={`mt-5 overflow-hidden rounded-[10px] border border-line ${stale ? "opacity-60" : ""}`}>
        <div className="flex flex-wrap items-center gap-3 bg-hover px-4 py-2.5">
          <h4 className="m-0 text-[13px] font-semibold">
            What each unit actually cost
          </h4>
          <span className="text-[11px] text-muted">
            Purchase cost plus its share of every import cost
          </span>
          {/* The eight component columns push the figures people actually
              want off the side of the table, so they are off by default and
              the totals sit where they can be read. */}
          <button type="button" onClick={() => setShowBreakdown((v) => !v)}
            className="ml-auto rounded-lg bg-bg px-3 py-1.5 text-[11.5px] font-medium
                       text-muted transition-colors hover:text-text">
            {showBreakdown ? "Hide cost breakdown" : "Show cost breakdown"}
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className={`w-full border-collapse text-left
                             ${showBreakdown ? "min-w-[1400px]" : ""}`}>
            <thead>
              <tr className="border-b border-line">
                {["Item", "Uom", "Qty", "Purchase Cost", "Import Cost",
                  "Total Landed", "Unit Purchase", "Unit Landed", "+%",
                  ...(showBreakdown ? GROUP_COLUMN.map((g) => g.label) : [])]
                  .map((h, i) => <GridTh key={h} numeric={i >= 2}>{h}</GridTh>)}
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <tr key={item.id} className={gridRowClass(index)}>
                  <td className={gridCellClass(false, "max-w-[240px]")}>
                    <div className="text-[12.5px]">{item.description}</div>
                    <div className="text-[11px] text-faint">
                      {item.item_code}
                      {item.hs_code ? ` · HS ${item.hs_code}` : ""}
                    </div>
                  </td>
                  <td className={gridCellClass()}>{item.uom ?? "—"}</td>
                  <td className={gridCellClass(true)}>
                    {gridAmount(item.quantity)}
                    {/* What the supplier charged for this line, in their
                        money — the figure on the commercial invoice. */}
                    <span className="block text-[10px] font-normal text-faint">
                      @ {gridAmount(item.unit_price)} {voucher.currency}
                    </span>
                  </td>
                  <td className={gridCellClass(true)}>
                    <b>{gridMoney(item.purchase_cost_base)}</b>
                    <span className="block text-[10px] font-normal text-faint">
                      {voucher.currency} {gridAmount(item.purchase_cost)}
                    </span>
                  </td>
                  <td className={gridCellClass(true)}>
                    {gridMoney(item.additional_cost)}</td>
                  <td className={gridCellClass(true)}>
                    <b>{gridMoney(item.total_landed_cost)}</b></td>
                  <td className={gridCellClass(true)}>
                    {gridMoney(item.unit_purchase_cost)}</td>
                  <td className={gridCellClass(true)}>
                    <b className="text-primary">{gridMoney(item.unit_landed_cost)}</b>
                  </td>
                  <td className={gridCellClass(true)}>
                    {item.purchase_cost_base > 0
                      ? `${Math.round(item.additional_cost
                          / item.purchase_cost_base * 1000) / 10}%`
                      : "—"}
                  </td>
                  {showBreakdown && GROUP_COLUMN.map((g) => (
                    <td key={g.key} className={gridCellClass(true)}>
                      {gridAmount(item[g.key as keyof LcItem] as number)}
                    </td>
                  ))}
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={showBreakdown ? 17 : 9}
                        className="px-4 py-8 text-center text-[12.5px] text-faint">
                  No goods on this costing.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* --------------------------------------------------------- the total */}
      <div className="ml-auto mt-5 w-full max-w-sm space-y-2 rounded-[10px] border
                      border-line bg-surface p-4">
        <Row label="Purchase cost (PKR)" value={gridMoney(voucher.purchase_cost_base)} />
        <Row label="Import costs (PKR)" value={gridMoney(voucher.additional_cost_base)} />
        {stale && (
          <p className="m-0 rounded-md bg-amber/10 px-2.5 py-1.5 text-[11.5px] text-amber">
            Last worked out. The costs entered now total <b>{gridMoney(chargeTotal)}</b> — work out the costs to
            update these figures.
          </p>
        )}
        <div className="flex items-center gap-3 border-t border-line pt-2.5">
          <span className="flex-1 text-[13px] font-semibold">Total landed cost</span>
          <span className="text-[15px] font-bold text-primary">
            {gridMoney(voucher.total_landed_cost)}
          </span>
        </div>
        {voucher.additional_cost_percent != null && (
          <p className="m-0 text-[11.5px] text-muted">
            The import added <b>{voucher.additional_cost_percent}%</b> on top of what
            the supplier charged.
          </p>
        )}
      </div>

      {!posted && nextStatus && (
        <div className="mt-5 flex flex-wrap items-center gap-2.5 border-t border-line pt-4">
          <button onClick={() => void move(nextStatus)} disabled={saving || working || stale}
            title={stale ? "Work out the costs first — the figures are out of date." : undefined}
            className="flex items-center gap-2 rounded-lg bg-gradient-to-br from-primary
                       to-primary-dark px-4 py-2 text-[12.8px] font-medium text-on-primary
                       disabled:opacity-50">
            {nextStatus === "Posted" ? <CheckCircle2 size={14} /> : <Calculator size={14} />}
            {nextStatus === "Posted" ? "Post the costing" : `Move to ${nextStatus}`}
          </button>
          <p className="m-0 text-[11px] text-faint">
            {nextStatus === "Posted"
              ? "Posting fixes these unit costs. The goods come into stock at them, "
                + "and the costing can no longer be edited."
              : "Work out the costs first, then move it along for approval."}
          </p>
        </div>
      )}
    </Modal>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex-1 text-[12px] text-muted">{label}</span>
      <span className="text-[12.5px] tabular-nums">{value}</span>
    </div>
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
