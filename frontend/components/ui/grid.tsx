"use client";

import { RotateCcw, ArrowUp, ArrowDown } from "lucide-react";

/**
 * The shared look of every data window, taken from the Product Sales Report:
 * a row count above the grid with Reset opposite it, blue column headings that
 * sort when clicked, ruled cells and banded rows.
 *
 * Kept here rather than repeated per screen so the modules cannot drift apart
 * again — a change to the grid is a change in one file.
 */

/** The bar above a grid: how many rows, and a way back to the default view. */
export function GridHeader({
  count, noun = "Row", onReset, resettable = true, children,
}: {
  count: number;
  /** "Row" gives "Total Row Count"; pass another word where it reads better. */
  noun?: string;
  onReset?: () => void;
  /** False greys out Reset — nothing has been changed, so there is nothing
   *  to go back to. */
  resettable?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-5 pb-1 pt-4">
      <h2 className="m-0 text-[16px] font-semibold">
        Total {noun} Count {count.toLocaleString()}
      </h2>
      <div className="ml-auto flex flex-wrap items-center gap-2.5">
        {children}
        {onReset && (
          <button
            onClick={onReset}
            disabled={!resettable}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12.5px] font-medium
                       text-muted transition-colors hover:bg-hover hover:text-text
                       disabled:opacity-40 disabled:hover:bg-transparent"
          >
            <RotateCcw size={13} /> Reset
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * A column heading. Blue and clickable where the server can sort on it, plain
 * blue where it cannot — the colour says "this is a column", the underline on
 * hover says "and this one sorts".
 */
export function GridTh({
  children, numeric, sortKey, sort, direction, onSort, className = "",
}: {
  children: React.ReactNode;
  numeric?: boolean;
  sortKey?: string;
  sort?: string;
  direction?: "asc" | "desc";
  onSort?: (key: string) => void;
  className?: string;
}) {
  const active = Boolean(sortKey) && sort === sortKey;
  return (
    <th className={`border-r border-line px-4 py-3 align-bottom text-[11.5px] font-semibold
                    last:border-r-0 ${numeric ? "text-right" : ""} ${className}`}>
      {sortKey && onSort ? (
        <button
          onClick={() => onSort(sortKey)}
          className={`inline-flex items-center gap-1 text-primary hover:underline
                      ${numeric ? "flex-row-reverse" : ""}`}
        >
          {children}
          {active && (direction === "asc" ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
        </button>
      ) : (
        <span className="text-primary">{children}</span>
      )}
    </th>
  );
}

/** Row banding and hover. `index` decides which band the row falls in. */
export function gridRowClass(index: number): string {
  return `border-b border-line last:border-0 hover:bg-primary/5 ${
    index % 2 === 1 ? "bg-hover/50" : ""}`;
}

/** A body cell: ruled, with numbers right-aligned on figures. */
export function gridCellClass(numeric?: boolean, extra = ""): string {
  return `border-r border-line px-4 py-2.5 text-[12.5px] last:border-r-0 ${
    numeric ? "whitespace-nowrap text-right tabular-nums" : ""} ${extra}`;
}

/**
 * Amounts as the reports print them: 53200 rather than 53,200.00, and 1.01
 * keeping its pence. Trailing zeros are dropped because most figures are
 * whole rupees and a column of ".00" only hides the real decimals.
 */
export const gridAmount = (n: number | null | undefined): string =>
  typeof n === "number" && Number.isFinite(n) ? String(Math.round(n * 100) / 100) : "0";

/**
 * A grouped amount, for a headline figure rather than a grid cell.
 *
 * `gridAmount` deliberately drops separators so a column matches the printed
 * reports, but "10451784.25" in a summary tile is unreadable — the one number
 * on the page people actually look at.
 */
export const gridMoney = (n: number | null | undefined): string =>
  typeof n === "number" && Number.isFinite(n)
    ? n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "0.00";

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** 23-SEP-2026, as the printed reports carry dates. */
export const gridDate = (iso: string | null | undefined): string => {
  const [y, m, d] = (iso ?? "").split("-");
  if (!y || !m || !d) return iso ?? "";
  return `${d}-${MONTHS[Number(m) - 1] ?? m}-${y}`;
};
