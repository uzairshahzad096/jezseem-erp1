"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass,
  gridAmount as amount, gridDate as docDate,
} from "@/components/ui/grid";
import { api } from "@/lib/api";
import { Combobox } from "@/components/ui/Modal";

interface SalesRow {
  doc_id: string;
  doc_number: string;
  doc_date: string;
  customer: string | null;
  customer_ntn: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  quantity: number;
  unit_price: number;
  gross_amount: number;
  discount_amount: number;
  taxable_amount: number;
  tax_amount: number;
  net_amount: number;
  status: string;
  with_sales_tax: boolean;
  currency: string;
}

/**
 * The report's columns, in the order the printed one carries them. `sort` is
 * the key the server orders by; a column without one cannot be sorted on.
 */
const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: SalesRow) => React.ReactNode;
}[] = [
  { key: "doc_number", label: "Doc Id", sort: "doc_number",
    // Drills through to the sale order this line came from, as the reference
    // report's Doc Id does.
    render: (r) => (
      <Link href={`/inventory/transactions/sales-orders?search=${encodeURIComponent(r.doc_number)}`}
            className="font-medium text-primary hover:underline">
        {r.doc_number}
      </Link>
    ) },
  { key: "doc_date", label: "Doc Date", sort: "doc_date",
    render: (r) => <span className="whitespace-nowrap">{docDate(r.doc_date)}</span> },
  { key: "description", label: "Item Name", sort: "description", render: (r) => r.description },
  { key: "quantity", label: "Sale Quantity", numeric: true, sort: "quantity",
    render: (r) => amount(r.quantity) },
  { key: "taxable_amount", label: "Excluding Tax Amount", numeric: true, sort: "taxable_amount",
    render: (r) => amount(r.taxable_amount) },
  { key: "tax_amount", label: "Sales Tax Amount", numeric: true, sort: "tax_amount",
    render: (r) => amount(r.tax_amount) },
  { key: "net_amount", label: "Net Amount", numeric: true, sort: "net_amount",
    render: (r) => amount(r.net_amount) },
  { key: "customer", label: "Customer", render: (r) => r.customer ?? "—" },
  { key: "customer_ntn", label: "Ntn",
    render: (r) => r.customer_ntn ?? <span className="text-faint" /> },
  // Beyond the printed report, one click away in the Columns menu.
  { key: "item_code", label: "Item Code", render: (r) => r.item_code ?? "—" },
  { key: "uom", label: "Uom", render: (r) => r.uom ?? "—" },
  { key: "unit_price", label: "Unit Price", numeric: true, render: (r) => amount(r.unit_price) },
  { key: "discount_amount", label: "Discount", numeric: true,
    render: (r) => amount(r.discount_amount) },
  { key: "status", label: "Status", render: (r) => r.status },
];

const DEFAULT_HIDDEN = ["item_code", "uom", "unit_price", "discount_amount", "status"];

const EMPTY_FILTERS = { customerId: "", dateFrom: "", dateTo: "", taxStatus: "" };

export default function ProductSalesReport() {
  const [rows, setRows] = useState<SalesRow[]>([]);
  const [totals, setTotals] = useState({ quantity: 0, net_amount: 0, tax_amount: 0 });
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [customers, setCustomers] = useState<{ id: string; name: string }[]>([]);
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS });
  const [sort, setSort] = useState("doc_date");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const pageSize = 50;

  useEffect(() => {
    // Only customers with sales on the report, not every account in the ledger.
    api.get<{ items: { id: string; name: string }[] }>("/reports/product-sales/customers")
      .then((d) => setCustomers(d.items))
      .catch(() => setCustomers([]));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        page: String(page), page_size: String(pageSize), sort, direction,
      });
      if (filters.customerId) qs.set("customer_id", filters.customerId);
      if (filters.dateFrom) qs.set("date_from", filters.dateFrom);
      if (filters.dateTo) qs.set("date_to", filters.dateTo);
      if (filters.taxStatus) qs.set("tax_status", filters.taxStatus);
      const data = await api.get<{
        items: SalesRow[]; total: number;
        totals: { quantity: number; net_amount: number; tax_amount: number };
      }>(`/reports/product-sales?${qs}`);
      setRows(data.items);
      setTotal(data.total);
      setTotals(data.totals);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the report.");
      setRows([]); setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, filters, sort, direction]);

  useEffect(() => { load(); }, [load]);

  const setFilter = (patch: Partial<typeof EMPTY_FILTERS>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };

  const toggleSort = (key: string) => {
    if (sort === key) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(key); setDirection("desc"); }
    setPage(1);
  };

  const columnState = useHiddenColumns("product-sales.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));

  const dirty = useMemo(
    () => JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS)
       || sort !== "doc_date" || direction !== "desc",
    [filters, sort, direction],
  );

  const reset = () => {
    setFilters({ ...EMPTY_FILTERS });
    setSort("doc_date");
    setDirection("desc");
    setPage(1);
    columnState.reset();
  };

  const pages = Math.max(1, Math.ceil(total / pageSize));

  // Mirror the report's own filters so the file matches the screen.
  const exportQuery = new URLSearchParams([
    ...(filters.customerId ? [["customer_id", filters.customerId]] : []),
    ...(filters.dateFrom ? [["date_from", filters.dateFrom]] : []),
    ...(filters.dateTo ? [["date_to", filters.dateTo]] : []),
  ]).toString();

  const field =
    "rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] outline-none focus:border-primary";

  return (
    <AppShell title="Product Sales Report">
      <div className="mb-[18px] grid grid-cols-3 gap-[18px] max-[900px]:grid-cols-1">
        <Summary label="Quantity sold" value={totals.quantity.toLocaleString()} />
        <Summary label="Sales tax" value={amount(totals.tax_amount)} />
        <Summary label="Net sales" value={amount(totals.net_amount)} highlight />
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={total} onReset={reset} resettable={dirty} />

        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3">
          {/* Type a name to narrow the list, or open it with the arrow. */}
          <div className="w-72">
            <Combobox value={filters.customerId}
              options={[{ value: "", label: "All customers" },
                        ...customers.map((c) => ({ value: c.id, label: c.name }))]}
              onChange={(v) => setFilter({ customerId: v })}
              placeholder="All customers — type to search" emptyMessage="No customer by that name." />
          </div>
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
          <select className={field} value={filters.taxStatus}
            onChange={(e) => setFilter({ taxStatus: e.target.value })}>
            <option value="">All tax statuses</option>
            <option value="with_tax">With sale tax</option>
            <option value="without_tax">Without sale tax</option>
          </select>
          <div className="ml-auto flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset="product-sales" query={exportQuery} />
          </div>
        </div>

        {error && <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>}

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
              {loading && <tr><td colSpan={visible.length} className="px-5 py-12 text-center">
                <Loader2 size={18} className="mx-auto animate-spin text-primary" /></td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={visible.length} className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No sales match these filters. Sales appear here once sales orders exist.
                </td></tr>
              )}
              {!loading && rows.map((r, i) => (
                <tr key={`${r.doc_id}-${i}`} className={gridRowClass(i)}>
                  {visible.map((c) => (
                    <td key={c.key} className={gridCellClass(c.numeric,
                          c.key === "description" ? "max-w-[340px]"
                            : c.key === "customer" ? "max-w-[220px]" : "")}>
                      {c.render(r)}
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
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
            <span className="px-2">Page {page} of {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>
    </AppShell>
  );
}

function Summary({ label, value, highlight }: {
  label: string; value: string; highlight?: boolean;
}) {
  return (
    <div className="rounded-[14px] border border-line bg-surface p-5 shadow-panel">
      <div className="mb-1.5 text-[12px] text-muted">{label}</div>
      <div className={`text-[22px] font-bold tabular-nums ${highlight ? "text-primary" : ""}`}>{value}</div>
    </div>
  );
}
