"use client";

import { useCallback, useEffect, useState } from "react";
import {
  FileSpreadsheet, Hourglass, Loader2, PackagePlus, Repeat, Search, SlidersHorizontal, Skull, TrendingUp,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import { GridHeader, GridTh, gridRowClass, gridCellClass } from "@/components/ui/grid";
import { api } from "@/lib/api";
import { useLookups } from "@/lib/useLookups";
import { Modal, Field, TextInput, TextArea, Select } from "@/components/ui/Modal";

interface StockRow {
  item_id: string;
  item_code: string;
  description: string;
  uom: string | null;
  main_product: string | null;
  sub_category: string | null;
  quantity: number;
  min_level: number;
  re_order_qty: number;
  item_status: string;
  location: string | null;
  stock_location: string | null;
  assigned_location: string | null;
  below_reorder: boolean;
  movement: Movement;
  movement_label: string;
  orders_in_period: number;
  qty_sold_in_period: number;
  customers_in_period: number;
  last_sold: string | null;
  days_since_sale: number | null;
  lifetime_orders: number;
  avg_monthly_qty: number;
  /** Stock on hand right after the latest opening balance or goods receipt. */
  added_level: number | null;
  added_on: string | null;
  /** Stock now as a % of `added_level`. */
  remaining_pct: number | null;
  restock: boolean;
  restock_reason: string | null;
  restock_priority: "HIGH" | "MEDIUM" | "LOW" | null;
  suggested_restock_qty: number;
}

type Movement = "REPEAT" | "OCCASIONAL" | "SLOW" | "DEAD" | "INACTIVE";

interface Summary {
  counts: Record<Movement, number>;
  dead_quantity: number;
  dead_list_value: number;
  restock_total: number;
  restock_high: number;
  restock_medium: number;
  restock_low: number;
}

const MOVEMENT_STYLE: Record<Movement, string> = {
  REPEAT: "bg-success/15 text-success",
  OCCASIONAL: "bg-sky/15 text-sky",
  SLOW: "bg-amber/15 text-amber",
  DEAD: "bg-rose/15 text-rose",
  INACTIVE: "bg-hover text-faint",
};
const PRIORITY_STYLE = { HIGH: "bg-rose/15 text-rose", MEDIUM: "bg-amber/15 text-amber", LOW: "bg-hover text-muted" };
const MOVEMENT_HELP: Record<Movement, string> = {
  REPEAT: "Sold on several separate orders in the period",
  OCCASIONAL: "Sold on one or two orders in the period",
  SLOW: "Not sold in the period, but sold within the dead-stock window",
  DEAD: "In stock, but not sold for a long time (or never)",
  INACTIVE: "No stock and no recent sales",
};

const fmtDate = (iso: string | null) => {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}-${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m) - 1]}-${y}`;
};

/** The report's columns. Everything is available; the wider ones start off. */
const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: StockRow) => React.ReactNode;
}[] = [
  { key: "item_code", label: "Item Code", sort: "item_code", render: (r) => r.item_code },
  { key: "description", label: "Description", sort: "description", render: (r) => r.description },
  { key: "main_product", label: "Category",
    render: (r) => <span className="text-muted">{r.main_product ?? "—"}</span> },
  { key: "sub_category", label: "Sub Category",
    render: (r) => <span className="text-muted">{r.sub_category ?? "—"}</span> },
  { key: "uom", label: "UOM", render: (r) => r.uom ?? "—" },
  { key: "location", label: "Location",
    // Where the stock is. Falls back to the product's own location, shown
    // faintly, so a product filed somewhere but not yet stocked still reads.
    render: (r) => (r.stock_location
      ? r.stock_location
      : r.assigned_location
        ? <span className="text-faint" title="No stock here yet — this is the location on the product record">
            {r.assigned_location}
          </span>
        : <span className="text-faint">—</span>) },
  { key: "assigned_location", label: "Assigned Location",
    render: (r) => r.assigned_location ?? <span className="text-faint">—</span> },
  { key: "quantity", label: "Quantity", numeric: true, sort: "quantity",
    render: (r) => (
      <span className={`text-[13px] font-semibold ${r.quantity > 0 ? "text-success" : "text-rose"}`}>
        {r.quantity.toLocaleString()}
      </span>
    ) },
  { key: "added_level", label: "Stock Added", numeric: true, sort: "added_level",
    render: (r) => (r.added_level != null
      ? <span className="text-muted" title={`Stock on hand after the addition on ${fmtDate(r.added_on)}`}>
          {r.added_level.toLocaleString()}
        </span>
      : <span className="whitespace-nowrap text-[11.5px] text-faint"
          title="No opening balance or goods receipt on record for this product">none recorded</span>) },
  { key: "remaining_pct", label: "% Left", numeric: true, sort: "remaining_pct",
    render: (r) => (r.remaining_pct != null ? <PercentLeft row={r} /> : <span className="text-faint">—</span>) },
  { key: "min_level", label: "Min Level", numeric: true,
    render: (r) => <span className="text-muted">{r.min_level?.toLocaleString() ?? "—"}</span> },
  { key: "re_order_qty", label: "Re-order", numeric: true,
    render: (r) => <span className="text-muted">{r.re_order_qty?.toLocaleString() ?? "—"}</span> },
  { key: "movement", label: "Movement", sort: "movement",
    render: (r) => (
      <span title={MOVEMENT_HELP[r.movement]}
        className={`whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11px] font-semibold ${MOVEMENT_STYLE[r.movement]}`}>
        {r.movement_label}
      </span>
    ) },
  { key: "orders_in_period", label: "Orders", numeric: true, sort: "orders_in_period",
    render: (r) => (r.orders_in_period
      ? <span title={`${r.customers_in_period} customer(s)`}>{r.orders_in_period}</span>
      : <span className="text-faint">0</span>) },
  { key: "qty_sold_in_period", label: "Qty Sold", numeric: true, sort: "qty_sold_in_period",
    render: (r) => (r.qty_sold_in_period ? r.qty_sold_in_period.toLocaleString() : <span className="text-faint">0</span>) },
  { key: "last_sold", label: "Last Sold", sort: "last_sold",
    render: (r) => (r.last_sold
      ? <span title={`${r.days_since_sale} days ago · ${r.lifetime_orders} order(s) ever`}>{fmtDate(r.last_sold)}</span>
      : <span className="text-faint">Never</span>) },
  { key: "restock", label: "Restock", sort: "restock_priority",
    render: (r) => (r.restock && r.restock_priority ? (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <span className={`rounded-full px-2 py-[2px] text-[10.5px] font-bold ${PRIORITY_STYLE[r.restock_priority]}`}>
          {r.restock_priority}
        </span>
        <span title={`${r.restock_reason ?? ""} · avg ${r.avg_monthly_qty}/month over 12 months`} className="text-[12px]">
          order {r.suggested_restock_qty.toLocaleString()}
        </span>
      </span>
    ) : <span className="text-faint">—</span>) },
  { key: "item_status", label: "Status", render: (r) => r.item_status },
];

/** How much of the stock last added is left, as a small bar: red once it
 *  is at the restock level, amber within 20 points above it. */
function PercentLeft({ row }: { row: StockRow }) {
  const pct = row.remaining_pct ?? 0;
  const tone = row.restock ? "bg-rose" : pct <= 60 ? "bg-amber" : "bg-success";
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap"
      title={row.added_level != null
        ? `${row.quantity.toLocaleString()} of ${row.added_level.toLocaleString()} left`
        : "Out of stock; no stock added on record"}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-hover">
        <span className={`block h-full ${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </span>
      <span className={`text-[12px] font-semibold ${row.restock ? "text-rose" : "text-muted"}`}>{pct}%</span>
    </span>
  );
}

const DEFAULT_HIDDEN =["min_level", "assigned_location", "re_order_qty", "sub_category"];

const STOCK_STATUSES = [
  { value: "", label: "All" },
  { value: "in_stock", label: "In stock" },
  { value: "out_of_stock", label: "Out of stock" },
  { value: "below_reorder", label: "Below reorder" },
];

export default function ProductStockReport() {
  const { mainProducts, subCategories, locations } = useLookups();
  const [rows, setRows] = useState<StockRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [mainProduct, setMainProduct] = useState("");
  const [subCategory, setSubCategory] = useState("");
  const [stockStatus, setStockStatus] = useState("");
  const [locationId, setLocationId] = useState("");
  const [adjusting, setAdjusting] = useState<StockRow | null>(null);
  const [transferring, setTransferring] = useState<StockRow | null>(null);
  const [sort, setSort] = useState("item_code");
  const [direction, setDirection] = useState<"asc" | "desc">("asc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Movement analysis
  const [movement, setMovement] = useState<Movement | "">("");
  const [restockOnly, setRestockOnly] = useState(false);
  const [period, setPeriod] = useState("fy");
  const [repeatMin, setRepeatMin] = useState("3");
  const [restockPercent, setRestockPercent] = useState("40");
  const [deadDays, setDeadDays] = useState("365");
  const [showSettings, setShowSettings] = useState(false);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [periodLabel, setPeriodLabel] = useState("");
  const [downloading, setDownloading] = useState(false);

  const pageSize = 50;

  /** The analysis settings, shared by the grid and the workbook download. */
  const analysisQuery = () => {
    const qs = new URLSearchParams({ period });
    if (Number(repeatMin) >= 2) qs.set("repeat_min", repeatMin);
    if (restockPercent !== "" && Number(restockPercent) >= 0 && Number(restockPercent) <= 100) {
      qs.set("restock_percent", restockPercent);
    }
    if (Number(deadDays) >= 30) qs.set("dead_days", deadDays);
    if (search) qs.set("search", search);
    if (mainProduct) qs.set("main_product_id", mainProduct);
    if (subCategory) qs.set("sub_category_id", subCategory);
    if (locationId) qs.set("location_id", locationId);
    return qs;
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = analysisQuery();
      qs.set("page", String(page));
      qs.set("page_size", String(pageSize));
      qs.set("sort", sort);
      qs.set("direction", direction);
      if (stockStatus) qs.set("stock_status", stockStatus);
      if (movement) qs.set("movement", movement);
      if (restockOnly) qs.set("restock", "true");
      const data = await api.get<{ items: StockRow[]; total: number; summary: Summary; period: { label: string } }>(
        `/reports/product-stock?${qs}`);
      setRows(data.items);
      setTotal(data.total);
      setSummary(data.summary);
      setPeriodLabel(data.period.label);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the report.");
      setRows([]); setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, search, mainProduct, subCategory, stockStatus, locationId, sort, direction, // eslint-disable-line react-hooks/exhaustive-deps
      movement, restockOnly, period, repeatMin, restockPercent, deadDays]);

  const downloadWorkbook = async () => {
    setDownloading(true);
    try {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
      const token = sessionStorage.getItem("jezseem-access-token");
      const res = await fetch(`${base}/reports/product-stock/workbook?${analysisQuery()}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) {
        let detail = `Could not build the workbook (${res.status}).`;
        try { detail = (await res.json()).detail ?? detail; } catch { /* no body */ }
        alert(detail);
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `stock-movement-${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  /** A tile is a quick filter; clicking the active one clears it. */
  const pickMovement = (m: Movement) => { setMovement((cur) => (cur === m ? "" : m)); setRestockOnly(false); setPage(1); };
  const pickRestock = () => { setRestockOnly((v) => !v); setMovement(""); setPage(1);
    if (!restockOnly) { setSort("restock_priority"); setDirection("asc"); } };

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  const toggleSort = (column: string) => {
    if (sort === column) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(column); setDirection("asc"); }
    setPage(1);
  };

  const dirty = Boolean(search || mainProduct || subCategory || stockStatus || locationId || movement || restockOnly)
    || sort !== "item_code" || direction !== "asc";

  const reset = () => {
    setSearch(""); setMainProduct(""); setSubCategory("");
    setStockStatus(""); setLocationId(""); setMovement(""); setRestockOnly(false);
    setSort("item_code"); setDirection("asc");
    setPage(1);
  };

  const pages = Math.max(1, Math.ceil(total / pageSize));

  const exportQuery = new URLSearchParams([
    ...(search ? [["search", search]] : []),
    ...(locationId ? [["location_id", locationId]] : []),
  ]).toString();

  const columnState = useHiddenColumns("product-stock.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  const select = "rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] outline-none focus:border-primary";

  return (
    <AppShell title="Product Stock">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="m-0 text-[19px] font-semibold">Product Stock</h1>
          <p className="m-0 mt-0.5 text-[12px] text-muted">
            Movement measured on posted sales orders · {periodLabel || "…"} · repeat seller = {repeatMin}+ orders ·
            restock at {restockPercent || 0}% or less of stock added
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => setShowSettings((v) => !v)}
            className="flex items-center gap-1.5 rounded-lg bg-hover px-3.5 py-2 text-[12.5px] font-medium text-muted hover:text-text">
            <SlidersHorizontal size={14} /> Analysis settings
          </button>
          <button onClick={downloadWorkbook} disabled={downloading}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary to-primary-dark px-3.5 py-2
                       text-[12.5px] font-medium text-on-primary hover:opacity-90 disabled:opacity-50">
            {downloading ? <Loader2 size={14} className="animate-spin" /> : <FileSpreadsheet size={14} />}
            Download analysis (Excel)
          </button>
        </div>
      </div>

      {showSettings && (
        <div className="mb-4 grid grid-cols-4 gap-4 rounded-[14px] border border-line bg-surface px-5 py-4 shadow-panel max-lg:grid-cols-2 max-sm:grid-cols-1">
          <label className="text-[11.5px] text-muted">Period for "sold this year"
            <select className={`${select} mt-1 w-full`} value={period} onChange={(e) => { setPeriod(e.target.value); setPage(1); }}>
              <option value="fy">This financial year (from 1 July)</option>
              <option value="calendar">This calendar year (from 1 January)</option>
              <option value="last12">Last 12 months</option>
            </select>
          </label>
          <label className="text-[11.5px] text-muted">Repeat seller = sold on at least … orders
            <input type="number" min={2} className={`${select} mt-1 w-full`} value={repeatMin}
              onChange={(e) => { setRepeatMin(e.target.value); setPage(1); }} />
          </label>
          <label className="text-[11.5px] text-muted">Restock when this % of stock added (or less) is left
            <div className="relative mt-1">
              <input type="number" min={0} max={100} className={`${select} w-full pr-8`} value={restockPercent}
                onChange={(e) => { setRestockPercent(e.target.value); setPage(1); }} />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[12px] text-faint">%</span>
            </div>
          </label>
          <label className="text-[11.5px] text-muted">Dead stock = not sold for … days
            <input type="number" min={30} className={`${select} mt-1 w-full`} value={deadDays}
              onChange={(e) => { setDeadDays(e.target.value); setPage(1); }} />
          </label>
        </div>
      )}

      {summary && (
        <div className="mb-4 grid grid-cols-5 gap-3 max-xl:grid-cols-3 max-sm:grid-cols-2">
          <Tile active={restockOnly} onClick={pickRestock} tone="rose" icon={<PackagePlus size={18} />}
            label="Needs restock" value={summary.restock_total}
            note={`${summary.restock_high} high · ${summary.restock_medium} medium · ${summary.restock_low} low`} />
          <Tile active={movement === "REPEAT"} onClick={() => pickMovement("REPEAT")} tone="primary" icon={<Repeat size={18} />}
            label="Repeat sellers" value={summary.counts.REPEAT} note={`${repeatMin}+ orders in the period`} />
          <Tile active={movement === "OCCASIONAL"} onClick={() => pickMovement("OCCASIONAL")} tone="sky" icon={<TrendingUp size={18} />}
            label="Occasional" value={summary.counts.OCCASIONAL} note="1–2 orders in the period" />
          <Tile active={movement === "SLOW"} onClick={() => pickMovement("SLOW")} tone="amber" icon={<Hourglass size={18} />}
            label="Slow movers" value={summary.counts.SLOW} note="not sold this period" />
          <Tile active={movement === "DEAD"} onClick={() => pickMovement("DEAD")} tone="rose" icon={<Skull size={18} />}
            label="Dead stock" value={summary.counts.DEAD}
            note={`${summary.dead_quantity.toLocaleString()} units · not sold ${deadDays}+ days`} />
        </div>
      )}

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={total} onReset={reset} resettable={dirty} />

        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder="Search product or code…"
              className="w-52 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint" />
          </div>
          <select className={select} value={mainProduct}
            onChange={(e) => { setMainProduct(e.target.value); setSubCategory(""); setPage(1); }}>
            <option value="">All categories</option>
            {mainProducts.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <select className={select} value={subCategory}
            onChange={(e) => { setSubCategory(e.target.value); setPage(1); }}>
            <option value="">All sub categories</option>
            {subCategories
              .filter((s) => !mainProduct || s.parentId === mainProduct)
              .map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <select className={select} value={stockStatus}
            onChange={(e) => { setStockStatus(e.target.value); setPage(1); }}>
            {STOCK_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <select className={select} value={locationId}
            onChange={(e) => { setLocationId(e.target.value); setPage(1); }}>
            <option value="">All locations</option>
            {locations.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
          <div className="ml-auto flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset="product-stock" query={exportQuery} />
          </div>
        </div>

        {error && <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left"
                 style={{ minWidth: `${visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Actions</GridTh>
                {visible.map((c) => (
                  <GridTh key={c.key} numeric={c.numeric} sortKey={c.sort}
                          sort={sort} direction={direction} onSort={toggleSort}>
                    {c.label}
                  </GridTh>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={visible.length + 1} className="px-5 py-12 text-center">
                <Loader2 size={18} className="mx-auto animate-spin text-primary" /></td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={visible.length + 1} className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No stock matches these filters.
                </td></tr>
              )}
              {!loading && rows.map((r, index) => (
                <tr key={r.item_id} className={gridRowClass(index)}>
                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => setTransferring(r)}
                        className="whitespace-nowrap rounded-md bg-hover px-2.5 py-1 text-[11.5px]
                                   font-medium text-muted transition-colors
                                   hover:bg-primary/10 hover:text-primary"
                      >
                        Transfer
                      </button>
                      <button
                        onClick={() => setAdjusting(r)}
                        className="whitespace-nowrap rounded-md bg-hover px-2.5 py-1 text-[11.5px]
                                   font-medium text-muted transition-colors
                                   hover:bg-primary/10 hover:text-primary"
                      >
                        Adjust
                      </button>
                    </div>
                  </td>
                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "description" ? "max-w-[300px] truncate" : "")}
                        title={c.key === "description" ? r.description : undefined}>
                      {c.render(r)}
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
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
            <span className="px-2">Page {page} of {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>

      <p className="mt-4 text-[11.5px] leading-relaxed text-faint">
        Quantities are the stock ledger balance. Movement counts separate posted sales orders
        (quotations and un-posted orders do not count). Stock Added is the quantity on hand right
        after the latest opening balance or goods receipt (had 5, received 95 = 100); a product is
        flagged for restock once {restockPercent || 0}% of that or less is left. A product with no
        stock added on record is flagged only when it is out of stock and still selling. The
        suggested quantity refills to the stock-added level, or two months of average sales if
        more. Services and software are never flagged. Click a tile to filter;
        the Excel analysis has Summary, Restock list, Repeat sellers, Dead stock and All products tabs.
      </p>
      {transferring && (
        <StockTransfer
          row={transferring}
          locations={locations}
          onClose={() => setTransferring(null)}
          onSaved={() => { setTransferring(null); load(); }}
        />
      )}

      {adjusting && (
        <StockAdjustment
          row={adjusting}
          locations={locations}
          onClose={() => setAdjusting(null)}
          onSaved={() => { setAdjusting(null); load(); }}
        />
      )}
    </AppShell>
  );
}

/**
 * Move stock from one location to another.
 *
 * All stock normally sits at the main office; when parts go out to someone at
 * another location they are transferred rather than adjusted, because the
 * company still owns them. The company total is unchanged — only where the
 * goods sit changes — so this is written as a matched pair of movements.
 */
function StockTransfer({
  row, locations, onClose, onSaved,
}: {
  row: StockRow;
  locations: { id: string; label: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!fromId || !toId) { setError("Choose both locations."); return; }
    if (fromId === toId) { setError("Choose two different locations."); return; }
    if (Number(quantity) <= 0) { setError("Quantity must be greater than zero."); return; }

    setSaving(true);
    setError(null);
    try {
      const res = await api.post<{
        from: { location: string; balance_after: number };
        to: { location: string; balance_after: number };
      }>("/inventory/stock/transfers", {
        item_id: row.item_id,
        from_location_id: fromId,
        to_location_id: toId,
        quantity,
        remarks: remarks.trim() || null,
      });
      alert(
        `${row.item_code} moved.

` +
        `${res.from.location}: ${res.from.balance_after.toLocaleString()}
` +
        `${res.to.location}: ${res.to.balance_after.toLocaleString()}`,
      );
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not transfer the stock.");
    } finally {
      setSaving(false);
    }
  };

  const options = locations.map((l) => ({ value: l.id, label: l.label }));

  return (
    <Modal title="Transfer stock" open width="md" saving={saving} error={error}
           onClose={onClose} onSave={save} saveLabel="Post transfer">
      <div className="space-y-4">
        <div className="rounded-lg border border-line bg-bg px-3.5 py-2.5 text-[12.5px]">
          <div className="font-medium">{row.item_code}</div>
          <div className="text-muted">{row.description}</div>
          <div className="mt-1 text-faint">
            {row.quantity.toLocaleString()} in total
            {row.location ? ` across ${row.location}` : " — no location recorded"}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="From" required>
            <Select value={fromId} placeholder="Select…" options={options}
              onChange={(e) => setFromId(e.target.value)} />
          </Field>
          <Field label="To" required>
            <Select value={toId} placeholder="Select…" options={options}
              onChange={(e) => setToId(e.target.value)} />
          </Field>
        </div>

        <Field label="Quantity" required>
          <TextInput type="number" step="0.01" min="0" value={quantity}
            onChange={(e) => setQuantity(e.target.value)} />
        </Field>

        <Field label="Reason">
          <TextArea rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)}
            placeholder="Parts issued to the technician, stock moved to the branch, …" />
        </Field>

        <p className="m-0 text-[11px] leading-snug text-faint">
          The total stock of this product does not change — a transfer only
          moves it between locations.
        </p>
      </div>
    </Modal>
  );
}

/**
 * Add or remove stock at a location by hand.
 *
 * The change is written as a ledger movement with a reason, never as an edit
 * to a balance — stock is the sum of its movements, so a correction has to be
 * one too, and a figure can always be traced to what caused it.
 */
function StockAdjustment({
  row, locations, onClose, onSaved,
}: {
  row: StockRow;
  locations: { id: string; label: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [direction, setDirection] = useState<"in" | "out">("out");
  const [locationId, setLocationId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (Number(quantity) <= 0) { setError("Quantity must be greater than zero."); return; }
    if (remarks.trim().length < 3) { setError("Give a reason for the adjustment."); return; }

    setSaving(true);
    setError(null);
    try {
      const res = await api.post<{ balance_after: number; location: string | null }>(
        "/inventory/stock/adjustments",
        {
          item_id: row.item_id,
          location_id: locationId || null,
          direction,
          quantity,
          remarks: remarks.trim(),
        },
      );
      alert(
        `${row.item_code} is now ${res.balance_after.toLocaleString()} ` +
        `${res.location ? `at ${res.location}` : "with no location"}.`,
      );
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not adjust the stock.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Adjust stock" open width="md" saving={saving} error={error}
           onClose={onClose} onSave={save} saveLabel="Post adjustment">
      <div className="space-y-4">
        <div className="rounded-lg border border-line bg-bg px-3.5 py-2.5 text-[12.5px]">
          <div className="font-medium">{row.item_code}</div>
          <div className="text-muted">{row.description}</div>
          <div className="mt-1 text-faint">
            Currently {row.quantity.toLocaleString()}
            {row.location ? ` across ${row.location}` : " — no location recorded"}
          </div>
        </div>

        <Field label="Adjustment">
          <div className="flex gap-2">
            {(["out", "in"] as const).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDirection(d)}
                className={`flex-1 rounded-lg px-3 py-2 text-[12.5px] font-medium transition-colors
                            ${direction === d
                              ? d === "out" ? "bg-rose/15 text-rose" : "bg-success/15 text-success"
                              : "bg-hover text-muted"}`}
              >
                {d === "out" ? "Remove from stock" : "Add to stock"}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Location">
          <Select
            value={locationId}
            placeholder="No location"
            options={locations.map((l) => ({ value: l.id, label: l.label }))}
            onChange={(e) => setLocationId(e.target.value)}
          />
        </Field>

        <Field label="Quantity" required>
          <TextInput type="number" step="0.01" min="0" value={quantity}
            onChange={(e) => setQuantity(e.target.value)} />
        </Field>

        <Field label="Reason" required>
          <TextArea rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)}
            placeholder="Damaged in transit, stock count correction, …" />
        </Field>
      </div>
    </Modal>
  );
}



/** A headline figure that doubles as a quick filter. */
function Tile({ label, value, note, tone, icon, active, onClick }: {
  label: string; value: number; note: string; tone: "primary" | "sky" | "amber" | "rose";
  icon: React.ReactNode; active: boolean; onClick: () => void;
}) {
  const tones = {
    primary: "text-primary bg-primary/10", sky: "text-sky bg-sky/10",
    amber: "text-amber bg-amber/10", rose: "text-rose bg-rose/10",
  };
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
      className={`flex items-center gap-3 rounded-[14px] border bg-surface px-4 py-3.5 text-left shadow-panel
                  transition-colors hover:border-primary/40 ${active ? "border-primary ring-2 ring-primary/20" : "border-line"}`}>
      <span className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full ${tones[tone]}`}>{icon}</span>
      <span className="min-w-0">
        <span className="block text-[11.5px] text-muted">{label}</span>
        <span className="block text-[20px] font-bold leading-tight tabular-nums">{value.toLocaleString()}</span>
        <span className="block truncate text-[10.5px] text-faint" title={note}>{note}</span>
      </span>
    </button>
  );
}
