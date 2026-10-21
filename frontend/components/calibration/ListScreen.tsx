"use client";

/**
 * The list half of every Calibration / Services screen, as on the previous
 * ERP: search and Go, the Actions menu, Create New; Edit (and Print, where the
 * record prints) as the first columns.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Pencil, Plus, Printer, Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import {
  GridActionChips, GridActionView, GridActions, useGridActions, type GridColumn,
} from "@/components/ui/GridActions";
import { useHiddenColumns } from "@/components/ui/TableTools";
import { api } from "@/lib/api";
import { usePageSize } from "@/lib/usePageSize";
import { openPdf } from "@/lib/openPdf";

export interface ListColumn<T> extends GridColumn<T> {
  render?: (row: T) => React.ReactNode;
}

export function ListScreen<T extends { id: string }>({
  title, subtitle, endpoint, storageKey, columns, createLabel = "Create New", onCreate, onEdit,
  printPath, printTitle, rowActions, actionsLabel = "Actions", reloadKey = 0, query = "", toolbar, noun = "Row",
  empty, footnote, children,
}: {
  title: string;
  subtitle?: string;
  endpoint: string;
  storageKey: string;
  columns: ListColumn<T>[];
  createLabel?: string;
  onCreate?: () => void;
  onEdit: (row: T) => void;
  /** The row's PDF, when it prints. */
  printPath?: (row: T) => string | null;
  printTitle?: string;
  /** Buttons for the row (post, cancel, invoice…), shown in their own column. */
  rowActions?: (row: T, reload: () => void) => React.ReactNode;
  actionsLabel?: string;
  /** Bump to reload, e.g. after a save. */
  reloadKey?: number;
  /** Extra query string, e.g. "&customer_id=…". */
  query?: string;
  toolbar?: React.ReactNode;
  noun?: string;
  empty?: string;
  footnote?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = usePageSize(storageKey, 25);
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const grid = useGridActions<T>(storageKey, columns);
  const cols = useHiddenColumns(`${storageKey}.columns`);
  const visible = columns.filter((c) => !cols.hidden.has(c.key));
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.get<{ items: T[]; total: number }>(
      `${endpoint}?page=${page}&page_size=${pageSize}${search ? `&search=${encodeURIComponent(search)}` : ""}${query}`)
      .then((d) => { if (live) { setRows(d.items); setTotal(d.total); setError(null); } })
      .catch((err) => { if (live) setError(err instanceof Error ? err.message : "Could not load the list."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [endpoint, page, pageSize, search, query, reloadKey, tick]);

  const shown = useMemo(() => grid.apply(rows), [grid, rows]);
  const fixed = 1 + (printPath ? 1 : 0) + (rowActions ? 1 : 0);
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <AppShell title={title}>
      <div className="mb-5 flex flex-wrap items-baseline gap-3">
        <h1 className="m-0 text-[19px] font-semibold">{title}</h1>
        {subtitle && <p className="m-0 text-[12px] text-muted">{subtitle}</p>}
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={total} noun={noun} onReset={() => { setTyped(""); setSearch(""); setPage(1); grid.reset(); }}
          resettable={Boolean(search) || grid.active > 0} />

        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
          <form className="flex items-center overflow-hidden rounded-lg border border-line bg-bg"
            onSubmit={(e) => { e.preventDefault(); setPage(1); setSearch(typed.trim()); }}>
            <Search size={14} className="ml-3 text-faint" />
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Search…"
              className="w-60 border-none bg-transparent px-2.5 py-2 text-[12.8px] outline-none placeholder:text-faint" />
            <button type="submit" className="border-l border-line px-3.5 py-2 text-[12.5px] font-semibold hover:bg-hover">Go</button>
          </form>
          <GridActions state={grid} pageSize={pageSize} onPageSize={(n) => { setPageSize(n); setPage(1); }}
            hidden={cols.hidden} onToggleColumn={cols.toggle} onShowAllColumns={cols.reset} />
          {toolbar}
          {onCreate && (
            <button onClick={onCreate}
              className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary to-primary-dark px-3.5 py-2 text-[12.8px] font-medium text-on-primary">
              <Plus size={14} strokeWidth={2.4} /> {createLabel}
            </button>
          )}
        </div>

        <GridActionChips state={grid} />
        <GridActionView state={grid} rows={shown} total={total} />

        {error && <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>}

        {grid.settings.view === "report" && (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left" style={{ minWidth: `${120 + visible.length * 130}px` }}>
              <thead>
                <tr className="border-b border-line">
                  <GridTh>Edit</GridTh>
                  {printPath && <GridTh>{printTitle ?? "Print"}</GridTh>}
                  {rowActions && <GridTh>{actionsLabel}</GridTh>}
                  {visible.map((c) => <GridTh key={c.key} numeric={c.numeric}>{c.label}</GridTh>)}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={visible.length + fixed} className="px-5 py-12 text-center">
                    <Loader2 size={18} className="mx-auto animate-spin text-primary" /></td></tr>
                )}
                {!loading && shown.length === 0 && (
                  <tr><td colSpan={visible.length + fixed} className="px-5 py-12 text-center text-[12.8px] text-faint">
                    {search || grid.active ? "Nothing matches." : (empty ?? "Nothing here yet.")}</td></tr>
                )}
                {!loading && shown.map((row, index) => {
                  const heading = grid.breakBefore(shown, index);
                  const pdf = printPath?.(row);
                  return [
                    heading && (
                      <tr key={`${row.id}-break`} className="border-b border-line bg-hover">
                        <td colSpan={visible.length + fixed} className="px-4 py-2 text-[12px] font-semibold">{heading}</td>
                      </tr>
                    ),
                    <tr key={row.id} className={`align-top ${gridRowClass(index)}`} style={grid.rowStyle(row)}>
                      <td className={gridCellClass()}>
                        <button onClick={() => onEdit(row)} aria-label="Edit" title="Edit"
                          className="rounded-md p-1.5 text-muted hover:bg-primary/10 hover:text-primary">
                          <Pencil size={14} />
                        </button>
                      </td>
                      {printPath && (
                        <td className={gridCellClass()}>
                          {pdf && (
                            <button onClick={() => openPdf(pdf)} title="Print" aria-label="Print"
                              className="rounded-full bg-sky p-1.5 text-white shadow-sm hover:bg-sky/85">
                              <Printer size={13} />
                            </button>
                          )}
                        </td>
                      )}
                      {rowActions && <td className={gridCellClass()}><div className="flex items-center gap-1">{rowActions(row, reload)}</div></td>}
                      {visible.map((c) => (
                        <td key={c.key} className={gridCellClass(c.numeric)}>
                          {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "")}
                        </td>
                      ))}
                    </tr>,
                  ];
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-3.5 text-[12.3px] text-muted">
          <span>{total === 0 ? "0" : `${(page - 1) * pageSize + 1} - ${Math.min(page * pageSize, total)}`} of {total.toLocaleString()}</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}
              className="rounded-lg px-3 py-1.5 hover:bg-hover disabled:opacity-40">Previous</button>
            <span>Page {page} of {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)}
              className="rounded-lg px-3 py-1.5 hover:bg-hover disabled:opacity-40">Next</button>
          </div>
        </div>
        {footnote && <div className="border-t border-line px-5 py-3 text-[11.5px] leading-relaxed text-faint">{footnote}</div>}
      </section>
      {children}
    </AppShell>
  );
}

/** Dates as the previous ERP's lists show them: 09/09/2026. */
export const dmy = (iso: string | null | undefined) => {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
};
export const dmyTime = (iso: string | null | undefined) => {
  if (!iso) return "";
  const t = new Date(iso);
  return `${dmy(iso)} ${t.toTimeString().slice(0, 8)}`;
};
export const yesNo = (v: boolean | null | undefined) => (v ? "Yes" : "No");

/** A small coloured pill for a status. */
export function Pill({ value }: { value: string | null | undefined }) {
  const tone: Record<string, string> = {
    ACTIVE: "bg-primary/10 text-primary", Posted: "bg-primary/10 text-primary", PASS: "bg-primary/10 text-primary",
    ISSUED: "bg-primary/10 text-primary", COMPLETED: "bg-sky/10 text-sky",
    DRAFT: "bg-amber/10 text-amber", Draft: "bg-amber/10 text-amber", PENDING: "bg-amber/10 text-amber",
    "UNDER SERVICE": "bg-amber/10 text-amber",
    FAIL: "bg-rose/10 text-rose", Cancelled: "bg-rose/10 text-rose", CANCELLED: "bg-rose/10 text-rose",
    TERMINATED: "bg-rose/10 text-rose", EXPIRED: "bg-hover text-muted", INACTIVE: "bg-hover text-muted",
    DECOMMISSIONED: "bg-hover text-muted",
  };
  if (!value) return null;
  return <span className={`whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-medium ${tone[value] ?? "bg-hover text-muted"}`}>{value}</span>;
}
