"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Globe, Info } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal } from "@/components/ui/Modal";
import { ColumnPicker, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate, gridAmount, gridMoney,
} from "@/components/ui/grid";
import { useLookups, toOptions } from "@/lib/useLookups";
import { api } from "@/lib/api";

interface Row {
  item_id: string;
  item_code: string;
  description: string;
  sku: string | null;
  uom: string | null;
  main_product: string | null;
  sub_category: string | null;
  quantity: number;
  average_cost: number | null;
  stock_value: number | null;
  costed_quantity: number;
  uncosted_quantity: number;
  is_estimate: boolean;
  lowest_cost: number | null;
  highest_cost: number | null;
  receipts: number;
  last_cost: number | null;
  last_receipt: string | null;
  last_receipt_date: string | null;
  cost_source: string;
  selling_price: number | null;
  margin_percent: number | null;
}

interface Summary {
  products: number;
  total_quantity: number;
  products_valued: number;
  products_without_a_cost: number;
  quantity_without_a_cost: number;
  total_stock_value: number;
  average_unit_cost: number;
  imported_products: number;
  imported_stock_value: number;
  estimated_rows: number;
}

interface LandedSplit {
  landed_cost_number: string;
  unit_purchase_cost: number;
  unit_import_cost: number;
  unit_landed_cost: number;
  freight: number; insurance: number; customs: number; taxes: number;
  port: number; clearing: number; bank: number; other: number;
}

interface Receipt {
  entry_date: string;
  quantity: number;
  unit_cost: number;
  total_cost: number;
  goods_receipt: string | null;
  warehouse: string | null;
  supplier: string | null;
  purchase_order: string | null;
  purchase_type: string | null;
  currency: string | null;
  exchange_rate: number | null;
  landed: LandedSplit | null;
}

interface History {
  item_code: string;
  description: string;
  uom: string | null;
  quantity_on_hand: number;
  costed_quantity: number;
  uncosted_quantity: number;
  average_cost: number | null;
  stock_value: number | null;
  selling_price: number | null;
  receipts: Receipt[];
}

const SOURCE_STYLE: Record<string, string> = {
  Import: "bg-violet/15 text-violet",
  "Local purchase": "bg-success/15 text-success",
  Purchase: "bg-success/15 text-success",
  "Opening balance": "bg-hover text-muted",
};

const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: Row) => React.ReactNode;
}[] = [
  { key: "item_code", label: "Item Code",
    render: (r) => <span className="font-medium text-primary">{r.item_code}</span> },
  { key: "description", label: "Product", render: (r) => r.description },
  { key: "uom", label: "Uom", render: (r) => r.uom ?? "—" },
  { key: "quantity", label: "In Stock", numeric: true, sort: "quantity",
    render: (r) => gridAmount(r.quantity) },
  { key: "average_cost", label: "Cost Per Unit", numeric: true, sort: "average_cost",
    render: (r) => (r.average_cost != null
      ? <b>{gridMoney(r.average_cost)}</b>
      : <span className="text-faint">not known</span>) },
  { key: "stock_value", label: "Stock Value", numeric: true, sort: "stock_value",
    render: (r) => (r.stock_value != null
      ? (
        <span className="font-semibold">
          {gridMoney(r.stock_value)}
          {r.is_estimate && (
            // Part of the balance predates any costed receipt, so the average
            // has been applied to stock whose real cost nobody recorded.
            <span className="block text-[10px] font-normal text-amber"
                  title={`${r.uncosted_quantity} unit(s) came in as an opening `
                    + "balance with no cost, so this much is an estimate."}>
              part estimated
            </span>
          )}
        </span>
      )
      : <span className="text-faint">—</span>) },
  { key: "cost_source", label: "Cost From",
    render: (r) => (
      <span className={`whitespace-nowrap rounded-md px-2 py-0.5 text-[10.5px] font-semibold
                        ${SOURCE_STYLE[r.cost_source] ?? "bg-hover text-muted"}`}>
        {r.cost_source === "Import" && <Globe size={9} className="mr-1 inline" />}
        {r.cost_source}
      </span>
    ) },
  { key: "last_cost", label: "Latest Cost", numeric: true,
    render: (r) => (r.last_cost != null ? gridMoney(r.last_cost) : "—") },
  { key: "last_receipt", label: "From Receipt",
    render: (r) => r.last_receipt ?? "—" },
  { key: "last_receipt_date", label: "Received",
    render: (r) => (r.last_receipt_date
      ? <span className="whitespace-nowrap">{gridDate(r.last_receipt_date)}</span> : "—") },
  { key: "receipts", label: "Receipts", numeric: true,
    render: (r) => (r.receipts || "—") },
  { key: "selling_price", label: "Sells At", numeric: true,
    render: (r) => (r.selling_price != null ? gridMoney(r.selling_price) : "—") },
  { key: "margin_percent", label: "Margin", numeric: true,
    render: (r) => (r.margin_percent != null
      ? <span className={r.margin_percent < 0 ? "text-rose" : "text-success"}>
          {r.margin_percent}%
        </span>
      : "—") },
  { key: "main_product", label: "Category", render: (r) => r.main_product ?? "—" },
];

const DEFAULT_HIDDEN = ["last_receipt_date", "receipts", "main_product", "uom"];

const EMPTY = {
  search: "", mainProductId: "", locationId: "", source: "",
  costedOnly: "false", inStockOnly: "true",
};

export default function InventoryValuationPage() {
  const { mainProducts, locations } = useLookups();
  const [rows, setRows] = useState<Row[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("stock_value");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [filters, setFilters] = useState({ ...EMPTY });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tracing, setTracing] = useState<string | null>(null);

  const pageSize = 50;

  const query = useMemo(() => {
    const qs = new URLSearchParams();
    if (filters.search) qs.set("search", filters.search);
    if (filters.mainProductId) qs.set("main_product_id", filters.mainProductId);
    if (filters.locationId) qs.set("location_id", filters.locationId);
    if (filters.source) qs.set("source", filters.source);
    qs.set("costed_only", filters.costedOnly);
    qs.set("in_stock_only", filters.inStockOnly);
    return qs;
  }, [filters]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams(query);
      qs.set("page", String(page));
      qs.set("page_size", String(pageSize));
      qs.set("sort", sort);
      qs.set("direction", direction);
      const data = await api.get<{
        items: Row[]; total: number; summary: Summary;
      }>(`/reports/inventory-valuation?${qs}`);
      setRows(data.items);
      setTotal(data.total);
      setSummary(data.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the valuation.");
      setRows([]); setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [query, page, sort, direction]);

  useEffect(() => { void load(); }, [load]);

  const setFilter = (patch: Partial<typeof EMPTY>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };

  const toggleSort = (key: string) => {
    if (sort === key) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(key); setDirection("desc"); }
    setPage(1);
  };

  const dirty = JSON.stringify(filters) !== JSON.stringify(EMPTY)
    || sort !== "stock_value" || direction !== "desc";

  const columnState = useHiddenColumns("inventory-valuation.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const field = "rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] "
    + "outline-none focus:border-primary";

  return (
    <AppShell title="Inventory Valuation">
      <div className="mb-5 flex flex-wrap items-baseline gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Inventory Valuation</h1>
        <p className="m-0 text-[12px] text-muted">
          What each product actually cost to get into stock, and what that stock is
          worth. Click a row to see where the cost came from.
        </p>
      </div>

      {summary && (
        <>
          <div className="mb-[18px] grid grid-cols-4 gap-[18px] max-[1100px]:grid-cols-2
                          max-[600px]:grid-cols-1">
            <Tile label="Stock value (PKR)" value={gridMoney(summary.total_stock_value)}
                  note={`${summary.products_valued} product${summary.products_valued === 1 ? "" : "s"} with a known cost`}
                  highlight />
            <Tile label="Average cost per unit" value={gridMoney(summary.average_unit_cost)}
                  note={`over ${gridMoney(summary.total_quantity)} units in stock`} />
            <Tile label="Held from imports" value={gridMoney(summary.imported_stock_value)}
                  note={`${summary.imported_products} product${summary.imported_products === 1 ? "" : "s"}, at landed cost`} />
            <Tile label="No cost on record"
                  value={gridMoney(summary.quantity_without_a_cost)}
                  note={`${summary.products_without_a_cost} products — opening balances`} />
          </div>

          {summary.products_without_a_cost > 0 && (
            <div className="mb-[18px] flex items-start gap-2 rounded-[14px] border
                            border-amber/30 bg-amber/10 px-4 py-3 text-[12.5px] text-amber">
              <Info size={15} className="mt-px flex-shrink-0" />
              <span>
                {summary.quantity_without_a_cost.toLocaleString()} units across{" "}
                {summary.products_without_a_cost.toLocaleString()} products came over
                from the old ERP as opening balances with no cost recorded, so they
                are shown as <b>not known</b> rather than zero — a zero would
                understate the stock. They pick up a cost the first time they are
                received on a purchase order.
              </span>
            </div>
          )}
        </>
      )}

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={total} noun="Product" onReset={() => {
          setFilters({ ...EMPTY }); setSort("stock_value");
          setDirection("desc"); setPage(1); columnState.reset();
        }} resettable={dirty} />

        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 pb-4 pt-2">
          <input value={filters.search} className={`${field} w-56`}
            placeholder="Search item code, product, SKU…"
            onChange={(e) => setFilter({ search: e.target.value })} />
          <select className={field} value={filters.mainProductId}
            onChange={(e) => setFilter({ mainProductId: e.target.value })}>
            <option value="">All categories</option>
            {toOptions(mainProducts).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select className={field} value={filters.locationId}
            onChange={(e) => setFilter({ locationId: e.target.value })}>
            <option value="">All warehouses</option>
            {toOptions(locations).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select className={field} value={filters.source}
            onChange={(e) => setFilter({ source: e.target.value })}>
            <option value="">Any cost source</option>
            <option value="Import">Imported</option>
            <option value="Local purchase">Bought locally</option>
            <option value="Opening balance">Opening balance</option>
          </select>
          <select className={field} value={filters.costedOnly}
            onChange={(e) => setFilter({ costedOnly: e.target.value })}>
            <option value="false">Every product in stock</option>
            <option value="true">Only products with a known cost</option>
          </select>
          <div className="ml-auto">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
          </div>
        </div>

        {error && (
          <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left"
                 style={{ minWidth: `${visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                {visible.map((c) => (
                  <GridTh key={c.key} numeric={c.numeric} sortKey={c.sort}
                          sort={sort} direction={direction} onSort={toggleSort}>
                    {c.label}
                  </GridTh>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={visible.length} className="px-5 py-12 text-center">
                  <Loader2 size={18} className="mx-auto animate-spin text-primary" />
                </td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={visible.length}
                        className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No products match these filters.
                </td></tr>
              )}
              {!loading && rows.map((row, index) => (
                <tr key={row.item_id}
                    onClick={() => setTracing(row.item_id)}
                    className={`cursor-pointer ${gridRowClass(index)}`}
                    title="See where this cost came from">
                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "description" ? "max-w-[300px]" : "")}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{total.toLocaleString()} products</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">
              Previous
            </button>
            <span className="px-2">Page {page} of {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">
              Next
            </button>
          </div>
        </div>
      </section>

      {tracing && <CostHistory itemId={tracing} onClose={() => setTracing(null)} />}
    </AppShell>
  );
}

function Tile({ label, value, note, highlight }: {
  label: string; value: string; note?: string; highlight?: boolean;
}) {
  return (
    <div className="rounded-[14px] border border-line bg-surface p-5 shadow-panel">
      <div className="mb-1.5 text-[12px] text-muted">{label}</div>
      <div className={`text-[22px] font-bold tabular-nums ${highlight ? "text-primary" : ""}`}>
        {value}
      </div>
      {note && <div className="mt-1 text-[11px] text-faint">{note}</div>}
    </div>
  );
}

/**
 * Where one product's cost came from.
 *
 * Every costed receipt, newest first. An import receipt splits into what the
 * supplier charged and what the import added on top — which is the difference
 * between what was paid and what the thing is actually worth on the shelf.
 */
function CostHistory({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const [data, setData] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<History>(`/reports/inventory-valuation/${itemId}`)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load."));
  }, [itemId]);

  return (
    <Modal title={data ? `What ${data.item_code} cost` : "Cost history"}
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
          <div className="mb-4 rounded-lg border border-line bg-bg px-3.5 py-3">
            <div className="mb-2 text-[13px] font-medium">{data.description}</div>
            <div className="flex flex-wrap gap-x-6 gap-y-1.5 text-[11.5px] text-muted">
              <span>In stock{" "}
                <b className="text-text">
                  {gridAmount(data.quantity_on_hand)} {data.uom ?? ""}
                </b></span>
              <span>Cost per unit{" "}
                <b className="text-primary">
                  {data.average_cost != null ? gridMoney(data.average_cost) : "not known"}
                </b></span>
              <span>Stock worth{" "}
                <b className="text-text">
                  {data.stock_value != null ? gridMoney(data.stock_value) : "—"}
                </b></span>
              {data.selling_price != null && (
                <span>Sells at{" "}
                  <b className="text-text">{gridMoney(data.selling_price)}</b></span>
              )}
            </div>
            {data.uncosted_quantity > 0 && (
              <p className="m-0 mt-2 text-[11px] text-amber">
                {gridAmount(data.uncosted_quantity)} of these units came in as an
                opening balance with no cost recorded, so the cost above is the
                average of the {gridAmount(data.costed_quantity)} that were actually
                received on a purchase order.
              </p>
            )}
          </div>

          {data.receipts.length === 0 ? (
            <p className="rounded-lg bg-hover px-4 py-3 text-[12.8px] text-muted">
              This product has never been received on a purchase order, so nothing
              records what it cost. It will pick one up the first time it is.
            </p>
          ) : (
            <div className="space-y-3">
              {data.receipts.map((r, i) => (
                <div key={i} className="overflow-hidden rounded-[10px] border border-line">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1
                                  border-b border-line bg-hover px-4 py-2.5 text-[11.5px]">
                    <span className="text-[12.5px] font-semibold">
                      {r.goods_receipt}
                    </span>
                    <span className="text-faint">{gridDate(r.entry_date)}</span>
                    {r.purchase_type && (
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold
                                        ${r.purchase_type === "Import"
                                          ? "bg-violet/15 text-violet"
                                          : "bg-success/15 text-success"}`}>
                        {r.purchase_type}
                      </span>
                    )}
                    <span className="text-muted">{r.supplier ?? "—"}</span>
                    {r.purchase_order && (
                      <span className="text-muted">via {r.purchase_order}</span>
                    )}
                    <span className="ml-auto tabular-nums">
                      {gridAmount(r.quantity)} @{" "}
                      <b className="text-primary">{gridMoney(r.unit_cost)}</b>
                      {" "}= {gridMoney(r.total_cost)}
                    </span>
                  </div>

                  {r.landed ? (
                    // The whole point of landed costing: the supplier's price is
                    // not what the goods cost.
                    <div className="px-4 py-3">
                      <div className="mb-2 flex flex-wrap items-baseline gap-2
                                      text-[12.5px]">
                        <span className="text-muted">Supplier charged</span>
                        <b>{gridMoney(r.landed.unit_purchase_cost)}</b>
                        <span className="text-muted">+ import cost</span>
                        <b className="text-amber">
                          {gridMoney(r.landed.unit_import_cost)}
                        </b>
                        <span className="text-muted">=</span>
                        <b className="text-primary">
                          {gridMoney(r.landed.unit_landed_cost)} per {data.uom ?? "unit"}
                        </b>
                        <span className="text-[11px] text-faint">
                          ({r.landed.landed_cost_number})
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
                        {([["Freight", r.landed.freight],
                           ["Insurance", r.landed.insurance],
                           ["Customs", r.landed.customs],
                           ["Taxes", r.landed.taxes],
                           ["Port", r.landed.port],
                           ["Clearing", r.landed.clearing],
                           ["Bank", r.landed.bank],
                           ["Other", r.landed.other]] as const)
                          .filter(([, amount]) => amount > 0)
                          .map(([name, amount]) => (
                            <span key={name}>
                              {name}{" "}
                              <b className="tabular-nums text-text">{gridMoney(amount)}</b>
                            </span>
                          ))}
                      </div>
                      {r.currency && r.currency !== "PKR" && (
                        <p className="m-0 mt-1.5 text-[11px] text-faint">
                          Bought in {r.currency} at {r.exchange_rate}.
                        </p>
                      )}
                    </div>
                  ) : (
                    <div className="px-4 py-2.5 text-[11.5px] text-muted">
                      Bought locally — the unit cost is the purchase price, with no
                      import costs to add.
                      {r.warehouse ? ` Received into ${r.warehouse}.` : ""}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <p className="mt-4 text-[11px] leading-snug text-faint">
            The cost per unit is the weighted average of these receipts. It is what
            the stock ledger recorded at the moment each delivery was posted, so it
            cannot drift from the documents behind it.
          </p>
        </>
      )}
    </Modal>
  );
}
