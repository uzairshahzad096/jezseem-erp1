"use client";

import { Pencil, Trash2, Plus, Search, Loader2 } from "lucide-react";
import { ColumnPicker, useHiddenColumns } from "@/components/ui/TableTools";
import { GridHeader, GridTh, gridRowClass, gridCellClass } from "@/components/ui/grid";
import { Fragment, useMemo } from "react";
import { GridActionChips, GridActionView, GridActions, useGridActions } from "@/components/ui/GridActions";

export interface Column<T> {
  key: string;
  header: string;
  /** Renders the cell. Defaults to the raw value at `key`. */
  render?: (row: T) => React.ReactNode;
  className?: string;
}

interface DataTableProps<T> {
  title: string;
  columns: Column<T>[];
  rows: T[];
  total: number;
  page: number;
  pageSize: number;
  loading?: boolean;
  error?: string | null;
  search: string;
  createLabel?: string;
  emptyMessage?: string;
  onSearch: (value: string) => void;
  onPage: (page: number) => void;
  onCreate?: () => void;
  onEdit?: (row: T) => void;
  onDelete?: (row: T) => void;
  /** Extra controls for the header bar — a download menu, say. */
  toolbar?: React.ReactNode;
  /** Enables the Columns menu. The key names where the choice is remembered,
   *  so two screens do not share one set of hidden columns. */
  columnsKey?: string;
  /** Columns hidden until someone turns them on. */
  defaultHidden?: string[];
  /** Rows Per Page in the Actions menu. */
  onPageSize?: (n: number) => void;
}

/**
 * Paginated list used by every Setup Form screen. Paging, searching and
 * sorting happen on the server — the browser never receives more than one
 * page of rows (spec section 18).
 */
export function DataTable<T extends { id: string }>({
  title, columns, rows, total, page, pageSize, loading, error,
  search, createLabel, emptyMessage, onSearch, onPage, onCreate, onEdit, onDelete,
  toolbar, columnsKey, defaultHidden = [], onPageSize,
}: DataTableProps<T>) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  // The hook runs whether or not the menu is offered, so the number of hooks
  // stays constant between renders.
  const columnState = useHiddenColumns(columnsKey ?? "", defaultHidden);
  const visible = columnsKey
    ? columns.filter((c) => !columnState.hidden.has(c.key))
    : columns;

  // The Actions menu: filters, highlights, control breaks and summaries over the loaded rows.
  const gridColumns = useMemo(() => columns.map((c) => ({ key: c.key, label: c.header })), [columns]);
  const actions = useGridActions<T>(columnsKey ?? `table.${title}`, gridColumns);
  const shown = actions.apply(rows);

  return (
    <section className="rounded-[14px] border border-line bg-surface shadow-panel">
      {/* The same head as every other data window: the count, then Reset —
          always shown, greyed until there is something to clear. */}
      <GridHeader count={total} onReset={() => onSearch("")}
                  resettable={Boolean(search)} />

      <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
        <h3 className="m-0 text-[13px] font-medium text-muted">{title}</h3>

        <div className="ml-auto flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input
              value={search}
              onChange={(e) => onSearch(e.target.value)}
              placeholder="Search…"
              className="w-40 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint"
            />
          </div>
          {columnsKey && (
            <ColumnPicker
              columns={columns.map((c) => ({ key: c.key, label: c.header }))}
              hidden={columnState.hidden}
              onToggle={columnState.toggle}
              onReset={columnState.reset}
            />
          )}
          <GridActions state={actions} pageSize={pageSize} onPageSize={onPageSize}
            hidden={columnsKey ? columnState.hidden : undefined}
            onToggleColumn={columnsKey ? columnState.toggle : undefined}
            onShowAllColumns={columnsKey ? columnState.reset : undefined} />
          {toolbar}
          {onCreate && (
            <button
              onClick={onCreate}
              className="flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary
                         to-primary-dark px-3.5 py-2 text-[12.8px] font-medium text-on-primary
                         transition-opacity hover:opacity-90"
            >
              <Plus size={14} strokeWidth={2.4} />
              {createLabel ?? "Create"}
            </button>
          )}
        </div>
      </div>

      <GridActionChips state={actions} />
      <GridActionView state={actions} rows={shown} total={total} />

      {error && (
        <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line">
              {/* Edit / delete first, as on every list in the ERP (owner, 19-Oct-2026). */}
              {(onEdit || onDelete) && <GridTh className="w-20">Edit</GridTh>}
              {visible.map((c) => (
                <GridTh key={c.key} className={c.className ?? ""}>{c.header}</GridTh>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={visible.length + 1} className="px-5 py-12 text-center">
                  <Loader2 size={18} className="mx-auto animate-spin text-primary" />
                </td>
              </tr>
            )}

            {!loading && shown.length === 0 && (
              <tr>
                <td
                  colSpan={visible.length + 1}
                  className="px-5 py-12 text-center text-[12.8px] text-faint"
                >
                  {emptyMessage ?? "Nothing here yet."}
                </td>
              </tr>
            )}

            {!loading &&
              shown.map((row, index) => (
                <Fragment key={row.id}>
                {actions.breakBefore(shown, index) && (
                  <tr className="border-b border-line bg-primary/5">
                    <td colSpan={visible.length + 1} className="px-4 py-2 text-[12px] font-semibold text-primary">
                      {actions.breakBefore(shown, index)}</td>
                  </tr>
                )}
                <tr className={gridRowClass(index)} style={actions.rowStyle(row)}>
                  {(onEdit || onDelete) && (
                    <td className="border-r border-line px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        {onEdit && (
                          <button
                            onClick={() => onEdit(row)}
                            aria-label="Edit"
                            className="rounded-md p-1.5 text-muted transition-colors hover:bg-primary/10 hover:text-primary"
                          >
                            <Pencil size={14} />
                          </button>
                        )}
                        {onDelete && (
                          <button
                            onClick={() => onDelete(row)}
                            aria-label="Delete"
                            className="rounded-md p-1.5 text-muted transition-colors hover:bg-rose/10 hover:text-rose"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                  {visible.map((c) => (
                    <td key={c.key} className={gridCellClass(false, c.className ?? "")}>
                      {c.render ? c.render(row) : ((row as never)[c.key] ?? "—")}
                    </td>
                  ))}
                </tr>
                </Fragment>
              ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
        <span>
          {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <PageBtn disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</PageBtn>
          <span className="px-2">Page {page} of {pages}</span>
          <PageBtn disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</PageBtn>
        </div>
      </div>
    </section>
  );
}

function PageBtn({
  disabled, onClick, children,
}: {
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className="rounded-lg bg-hover px-3 py-1.5 text-[12.3px] font-medium transition-opacity
                 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}
