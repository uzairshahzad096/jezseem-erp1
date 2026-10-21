"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, BarChart3 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate, gridAmount, gridMoney,
} from "@/components/ui/grid";
import { useSuppliers, COUNTRIES } from "@/lib/useProcurement";
import { api } from "@/lib/api";

interface Row {
  landed_cost_id: string;
  landed_cost_number: string;
  doc_date: string;
  status: string;
  is_posted: boolean;
  po_number: string | null;
  shipment_number: string | null;
  container_number: string | null;
  supplier: string | null;
  supplier_country: string | null;
  country_of_origin: string | null;
  country: string | null;
  invoice_number: string | null;
  currency: string;
  exchange_rate: number;
  port_of_discharge: string | null;
  clearing_agent: string | null;
  transit_status: string | null;
  customs_status: string | null;
  item_code: string | null;
  item: string;
  uom: string | null;
  hs_code: string | null;
  quantity: number;
  unit_price: number;
  purchase_cost_foreign: number;
  purchase_cost: number;
  unit_purchase_cost: number;
  freight: number;
  insurance: number;
  customs: number;
  taxes: number;
  clearing: number;
  port: number;
  bank: number;
  other: number;
  additional_cost: number;
  total_landed_cost: number;
  unit_landed_cost: number;
  additional_cost_percent: number | null;
}

interface Summary {
  total_import_pos: number;
  total_shipments: number;
  total_landed_costs: number;
  total_products: number;
  total_quantity: number;
  total_foreign_value: number;
  total_purchase_value: number;
  total_freight: number;
  total_insurance: number;
  total_customs: number;
  total_taxes: number;
  total_clearing: number;
  total_port: number;
  total_bank: number;
  total_other: number;
  total_additional_cost: number;
  total_landed_cost: number;
  average_unit_landed_cost: number;
  additional_cost_percent: number;
  currencies: string[];
}

interface GroupRow {
  lines: number;
  quantity: number;
  purchase_cost: number;
  freight: number;
  insurance: number;
  customs: number;
  taxes: number;
  clearing: number;
  port: number;
  bank: number;
  other: number;
  additional_cost: number;
  total_landed_cost: number;
  unit_landed_cost: number;
  landed_cost_percent: number | null;
  [key: string]: unknown;
}

interface Analysis {
  by_supplier: GroupRow[];
  by_country: GroupRow[];
  by_product: GroupRow[];
  by_shipment: GroupRow[];
  by_component: { component: string; amount: number; share_percent: number }[];
  summary: Summary;
}

/** Spec section 31's columns, in its order. */
const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: Row) => React.ReactNode;
}[] = [
  { key: "po_number", label: "PO No.",
    render: (r) => <span className="font-medium text-primary">{r.po_number ?? "—"}</span> },
  { key: "shipment_number", label: "Shipment No.",
    render: (r) => r.shipment_number ?? "—" },
  { key: "landed_cost_number", label: "Landed Cost No.", sort: "landed_cost_number",
    render: (r) => (
      <span className="whitespace-nowrap">
        {r.landed_cost_number}
        {!r.is_posted && (
          <span className="ml-1.5 rounded bg-amber/15 px-1.5 py-0.5 text-[9.5px]
                           font-semibold text-amber">draft</span>
        )}
      </span>
    ) },
  { key: "doc_date", label: "Date", sort: "doc_date",
    render: (r) => <span className="whitespace-nowrap">{gridDate(r.doc_date)}</span> },
  { key: "supplier", label: "Supplier", render: (r) => r.supplier ?? "—" },
  { key: "country", label: "Country", render: (r) => r.country ?? "—" },
  { key: "invoice_number", label: "Invoice No.", render: (r) => r.invoice_number ?? "—" },
  { key: "currency", label: "Currency", render: (r) => r.currency },
  { key: "exchange_rate", label: "Exchange Rate", numeric: true,
    render: (r) => gridAmount(r.exchange_rate) },
  { key: "item_code", label: "Item Code", render: (r) => r.item_code ?? "—" },
  { key: "item", label: "Item", sort: "item", render: (r) => r.item },
  { key: "hs_code", label: "HS Code", render: (r) => r.hs_code ?? "—" },
  { key: "uom", label: "Uom", render: (r) => r.uom ?? "—" },
  { key: "quantity", label: "Quantity", numeric: true, sort: "quantity",
    render: (r) => gridAmount(r.quantity) },
  { key: "purchase_cost", label: "Purchase Cost", numeric: true, sort: "purchase_cost",
    render: (r) => gridAmount(r.purchase_cost) },
  { key: "freight", label: "Freight", numeric: true, render: (r) => gridAmount(r.freight) },
  { key: "insurance", label: "Insurance", numeric: true,
    render: (r) => gridAmount(r.insurance) },
  { key: "customs", label: "Customs", numeric: true, render: (r) => gridAmount(r.customs) },
  { key: "taxes", label: "Taxes", numeric: true, render: (r) => gridAmount(r.taxes) },
  { key: "clearing", label: "Clearing", numeric: true,
    render: (r) => gridAmount(r.clearing) },
  { key: "port", label: "Port", numeric: true, render: (r) => gridAmount(r.port) },
  { key: "bank", label: "Bank", numeric: true, render: (r) => gridAmount(r.bank) },
  { key: "other", label: "Other", numeric: true, render: (r) => gridAmount(r.other) },
  { key: "additional_cost", label: "Additional Cost", numeric: true,
    sort: "additional_cost", render: (r) => gridAmount(r.additional_cost) },
  { key: "total_landed_cost", label: "Total Landed Cost", numeric: true,
    sort: "total_landed_cost",
    render: (r) => <span className="font-semibold">{gridAmount(r.total_landed_cost)}</span> },
  { key: "unit_landed_cost", label: "Unit Landed Cost", numeric: true,
    sort: "unit_landed_cost",
    render: (r) => (
      <span className="font-semibold text-primary">{gridAmount(r.unit_landed_cost)}</span>
    ) },
  { key: "additional_cost_percent", label: "Import Cost %", numeric: true,
    render: (r) => (r.additional_cost_percent != null
      ? <span className={r.additional_cost_percent > 25 ? "text-rose" : ""}>
          {r.additional_cost_percent}%
        </span>
      : "—") },
];

const DEFAULT_HIDDEN = ["exchange_rate", "invoice_number", "uom", "doc_date"];

const EMPTY_FILTERS = {
  search: "", dateFrom: "", dateTo: "", supplierId: "", country: "",
  hsCode: "", currency: "", postedOnly: "true",
};

export default function ImportLandedCostingReport() {
  const [rows, setRows] = useState<Row[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("doc_date");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [showAnalysis, setShowAnalysis] = useState(false);

  const suppliers = useSuppliers();
  const pageSize = 50;

  const query = useMemo(() => {
    const qs = new URLSearchParams();
    if (filters.search) qs.set("search", filters.search);
    if (filters.dateFrom) qs.set("date_from", filters.dateFrom);
    if (filters.dateTo) qs.set("date_to", filters.dateTo);
    if (filters.supplierId) qs.set("supplier_id", filters.supplierId);
    if (filters.country) qs.set("country_of_origin", filters.country);
    if (filters.hsCode) qs.set("hs_code", filters.hsCode);
    if (filters.currency) qs.set("currency", filters.currency);
    qs.set("posted_only", filters.postedOnly);
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
      }>(`/reports/import-landed-costing?${qs}`);
      setRows(data.items);
      setTotal(data.total);
      setSummary(data.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the report.");
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [query, page, sort, direction]);

  useEffect(() => { void load(); }, [load]);

  const loadAnalysis = async () => {
    setShowAnalysis(true);
    if (analysis) return;
    try {
      setAnalysis(await api.get<Analysis>(
        `/reports/import-landed-costing/analysis?${query}`));
    } catch {
      setAnalysis(null);
    }
  };

  const setFilter = (patch: Partial<typeof EMPTY_FILTERS>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
    setAnalysis(null);
  };

  const toggleSort = (key: string) => {
    if (sort === key) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(key); setDirection("desc"); }
    setPage(1);
  };

  const dirty = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS)
    || sort !== "doc_date" || direction !== "desc";

  const columnState = useHiddenColumns("import-landed-costing.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const field = "rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] "
    + "outline-none focus:border-primary";

  return (
    <AppShell title="Import Landed Costing">
      {summary && (
        <>
          <div className="mb-[18px] grid grid-cols-4 gap-[18px] max-[1100px]:grid-cols-2
                          max-[600px]:grid-cols-1">
            <Tile label="Purchase value (PKR)"
                  value={gridMoney(summary.total_purchase_value)}
                  note={summary.currencies.length
                    ? `${summary.currencies.join(", ")} ${gridMoney(summary.total_foreign_value)}`
                    : undefined} />
            <Tile label="Import costs (PKR)"
                  value={gridMoney(summary.total_additional_cost)}
                  note={`${summary.additional_cost_percent}% on top of the goods`} />
            <Tile label="Total landed cost (PKR)"
                  value={gridMoney(summary.total_landed_cost)} highlight />
            <Tile label="Average unit landed cost"
                  value={gridMoney(summary.average_unit_landed_cost)}
                  note={`${gridMoney(summary.total_quantity)} units`} />
          </div>

          {/* Where the import money actually went (section 32). */}
          <div className="mb-[18px] rounded-[14px] border border-line bg-surface p-4
                          shadow-panel">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h2 className="m-0 text-[13px] font-semibold">Cost components</h2>
              <span className="text-[11.5px] text-muted">
                {summary.total_landed_costs} costing{summary.total_landed_costs === 1 ? "" : "s"}
                {" · "}{summary.total_shipments} shipment
                {summary.total_shipments === 1 ? "" : "s"}
                {" · "}{summary.total_products} product
                {summary.total_products === 1 ? "" : "s"}
              </span>
              <button onClick={loadAnalysis}
                className="ml-auto flex items-center gap-1.5 rounded-lg bg-hover px-3 py-1.5
                           text-[11.5px] font-medium text-muted hover:text-text">
                <BarChart3 size={13} /> Break it down
              </button>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              {([["Freight", summary.total_freight],
                 ["Insurance", summary.total_insurance],
                 ["Customs", summary.total_customs],
                 ["Taxes", summary.total_taxes],
                 ["Clearing", summary.total_clearing],
                 ["Port", summary.total_port],
                 ["Bank", summary.total_bank],
                 ["Other", summary.total_other]] as const).map(([label, amount]) => (
                <span key={label} className="text-[11.5px] text-muted">
                  {label}{" "}
                  <b className="tabular-nums text-text">{gridMoney(amount)}</b>
                  {summary.total_additional_cost > 0 && (
                    <span className="ml-1 text-faint">
                      ({Math.round(amount / summary.total_additional_cost * 1000) / 10}%)
                    </span>
                  )}
                </span>
              ))}
            </div>
          </div>
        </>
      )}

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={total} onReset={() => {
          setFilters({ ...EMPTY_FILTERS });
          setSort("doc_date");
          setDirection("desc");
          setPage(1);
          columnState.reset();
        }} resettable={dirty} />

        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 pb-4 pt-2">
          <input value={filters.search} className={`${field} w-52`}
            placeholder="Search costing, PO, item, container…"
            onChange={(e) => setFilter({ search: e.target.value })} />
          <label className="flex items-center gap-2 text-[12px] text-muted">
            From
            <input type="date" className={field} value={filters.dateFrom}
              onChange={(e) => setFilter({ dateFrom: e.target.value })} />
          </label>
          <label className="flex items-center gap-2 text-[12px] text-muted">
            To
            <input type="date" className={field} value={filters.dateTo}
              onChange={(e) => setFilter({ dateTo: e.target.value })} />
          </label>
          <select className={field} value={filters.supplierId}
            onChange={(e) => setFilter({ supplierId: e.target.value })}>
            <option value="">All suppliers</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <select className={field} value={filters.country}
            onChange={(e) => setFilter({ country: e.target.value })}>
            <option value="">All countries of origin</option>
            {COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <input value={filters.hsCode} className={`${field} w-28`} placeholder="HS code"
            onChange={(e) => setFilter({ hsCode: e.target.value })} />
          <select className={field} value={filters.postedOnly}
            onChange={(e) => setFilter({ postedOnly: e.target.value })}>
            <option value="true">Posted costings only</option>
            <option value="false">Include drafts</option>
          </select>
          <div className="ml-auto flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset="import-landed-costing" query={query.toString()} />
          </div>
        </div>

        {filters.postedOnly === "false" && (
          <p className="m-5 mb-0 rounded-lg bg-amber/10 px-4 py-2.5 text-[12px] text-amber">
            Drafts are included. An unposted costing has not affected inventory
            valuation, so these totals are above what the stock is actually carried at.
          </p>
        )}

        {error && (
          <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">
            {error}
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left"
                 style={{ minWidth: `${visible.length * 125}px` }}>
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
                  No landed costings match these filters. Rows appear here once an
                  import has been costed and posted.
                </td></tr>
              )}
              {!loading && rows.map((row, index) => (
                <tr key={`${row.landed_cost_id}-${index}`} className={gridRowClass(index)}>
                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "item" ? "max-w-[300px]" : "")}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{total.toLocaleString()} rows</span>
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

      {showAnalysis && (
        <AnalysisPanel analysis={analysis} onClose={() => setShowAnalysis(false)} />
      )}
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

/** The four analyses from spec section 33, plus the component split. */
function AnalysisPanel({ analysis, onClose }: {
  analysis: Analysis | null; onClose: () => void;
}) {
  const [tab, setTab] = useState<"by_supplier" | "by_country" | "by_product" | "by_shipment">(
    "by_supplier");

  const LABEL: Record<string, string> = {
    by_supplier: "supplier", by_country: "country",
    by_product: "product", by_shipment: "shipment",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto
                    bg-black/50 p-4 py-10">
      <div className="w-full max-w-5xl rounded-[14px] border border-line bg-surface shadow-xl">
        <div className="flex items-center gap-3 border-b border-line px-5 py-4">
          <h3 className="m-0 text-[15px] font-semibold">Where the import cost went</h3>
          <button onClick={onClose} aria-label="Close"
            className="ml-auto rounded-md px-2 py-1 text-[12px] text-muted hover:bg-hover">
            Close
          </button>
        </div>

        <div className="p-5">
          {!analysis ? (
            <div className="flex justify-center py-10">
              <Loader2 size={18} className="animate-spin text-primary" />
            </div>
          ) : (
            <>
              <h4 className="mb-2 text-[12.5px] font-semibold">By cost component</h4>
              <div className="mb-5 overflow-hidden rounded-[10px] border border-line">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-line">
                      {["Component", "Amount (PKR)", "Share"].map((h, i) => (
                        <GridTh key={h} numeric={i > 0}>{h}</GridTh>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.by_component.map((c, index) => (
                      <tr key={c.component} className={gridRowClass(index)}>
                        <td className={gridCellClass()}>{c.component}</td>
                        <td className={gridCellClass(true)}>{gridAmount(c.amount)}</td>
                        <td className={gridCellClass(true)}>
                          <div className="flex items-center justify-end gap-2">
                            <span>{c.share_percent}%</span>
                            <span className="h-1.5 w-20 overflow-hidden rounded-full bg-hover">
                              <span className="block h-full rounded-full bg-primary"
                                    style={{ width: `${Math.min(100, c.share_percent)}%` }} />
                            </span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mb-3 flex flex-wrap gap-1.5">
                {(["by_supplier", "by_country", "by_product", "by_shipment"] as const)
                  .map((key) => (
                    <button key={key} onClick={() => setTab(key)}
                      className={`rounded-lg px-3 py-1.5 text-[11.5px] font-medium
                                  capitalize transition-colors
                                  ${tab === key ? "bg-primary text-on-primary"
                                                : "bg-hover text-muted hover:text-text"}`}>
                      By {LABEL[key]}
                    </button>
                  ))}
              </div>

              <div className="overflow-x-auto rounded-[10px] border border-line">
                <table className="w-full min-w-[900px] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-line">
                      {[LABEL[tab], "Lines", "Qty", "Purchase Cost", "Freight",
                        "Customs", "Taxes", "Clearing", "Import Cost",
                        "Total Landed", "Unit Landed", "+%"].map((h, i) => (
                        <GridTh key={h} numeric={i > 0} className="capitalize">{h}</GridTh>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {analysis[tab].map((group, index) => (
                      <tr key={index} className={gridRowClass(index)}>
                        <td className={gridCellClass(false, "max-w-[240px]")}>
                          {String(group[LABEL[tab]] ?? "—")}
                        </td>
                        <td className={gridCellClass(true)}>{group.lines}</td>
                        <td className={gridCellClass(true)}>
                          {gridAmount(group.quantity)}</td>
                        <td className={gridCellClass(true)}>
                          {gridAmount(group.purchase_cost)}</td>
                        <td className={gridCellClass(true)}>{gridAmount(group.freight)}</td>
                        <td className={gridCellClass(true)}>{gridAmount(group.customs)}</td>
                        <td className={gridCellClass(true)}>{gridAmount(group.taxes)}</td>
                        <td className={gridCellClass(true)}>{gridAmount(group.clearing)}</td>
                        <td className={gridCellClass(true)}>
                          {gridAmount(group.additional_cost)}</td>
                        <td className={gridCellClass(true)}>
                          <b>{gridAmount(group.total_landed_cost)}</b></td>
                        <td className={gridCellClass(true)}>
                          <b className="text-primary">
                            {gridAmount(group.unit_landed_cost)}
                          </b></td>
                        <td className={gridCellClass(true)}>
                          {group.landed_cost_percent != null
                            ? `${group.landed_cost_percent}%` : "—"}</td>
                      </tr>
                    ))}
                    {analysis[tab].length === 0 && (
                      <tr><td colSpan={12}
                              className="px-4 py-8 text-center text-[12.5px] text-faint">
                        Nothing to group.
                      </td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
