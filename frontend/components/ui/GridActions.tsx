"use client";

/**
 * The Actions menu of the previous ERP's reports, for any large list:
 * Columns, Filter, Data (sort), Format (Control Break, Highlight, Rows Per
 * Page), Chart, Group By, Pivot, Report (save / reset) and Help.
 *
 * Filters, highlights, control breaks, charts, group-by and pivot work on the
 * rows the list has loaded; Rows Per Page decides how many that is, so "All"
 * brings every record in and they then cover the whole report. A screen's
 * settings are remembered in this browser, per screen.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3, Check, ChevronDown, ChevronRight, Columns3, Filter, HelpCircle, Highlighter, LayoutList,
  ListTree, Rows3, Save, Settings2, SortAsc, Table2, Wrench, X,
} from "lucide-react";

export interface GridColumn<T = unknown> {
  key: string;
  label: string;
  numeric?: boolean;
  /** The raw value used by filters, sorting, grouping and charts. Defaults to row[key]. */
  value?: (row: T) => unknown;
}

type Operator = "contains" | "=" | "!=" | ">" | "<" | ">=" | "<=" | "is empty" | "is not empty";
const OPERATORS: Operator[] = ["contains", "=", "!=", ">", "<", ">=", "<=", "is empty", "is not empty"];

interface Rule { id: string; column: string; op: Operator; value: string; enabled: boolean }
interface HighlightRule extends Rule { color: string }
type Aggregate = "count" | "sum" | "avg" | "min" | "max";

interface Settings {
  filters: Rule[];
  highlights: HighlightRule[];
  sort: { column: string; direction: "asc" | "desc" } | null;
  controlBreak: string | null;
  view: "report" | "chart" | "group" | "pivot";
  chart: { label: string; value: string; agg: Aggregate };
  group: { column: string; value: string; agg: Aggregate };
  pivot: { row: string; column: string; value: string; agg: Aggregate };
}

const EMPTY: Settings = {
  filters: [], highlights: [], sort: null, controlBreak: null, view: "report",
  chart: { label: "", value: "", agg: "count" },
  group: { column: "", value: "", agg: "count" },
  pivot: { row: "", column: "", value: "", agg: "count" },
};

export const ROWS_PER_PAGE = [1, 5, 10, 15, 20, 25, 50, 100, 1000];
/** "All": the most a list endpoint hands over in one request. */
export const ALL_ROWS = 5000;

const COLORS = [
  { name: "Green", value: "#DCF2E3" }, { name: "Red", value: "#F8D9D9" }, { name: "Yellow", value: "#FBF1C7" },
  { name: "Blue", value: "#DCEBFA" }, { name: "Purple", value: "#EADFF8" }, { name: "Grey", value: "#ECEEF0" },
];

const uid = () => Math.random().toString(36).slice(2, 9);

function raw<T>(row: T, column: GridColumn<T> | undefined): unknown {
  if (!column) return undefined;
  return column.value ? column.value(row) : (row as Record<string, unknown>)[column.key];
}
const text = (v: unknown) => (v == null ? "" : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v));
/** A number, or null for anything that is not one ("Closed" is not 0). Commas and a currency prefix are allowed. */
const asNumber = (v: unknown) => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const t = String(v ?? "").replace(/,/g, "").replace(/^[A-Z]{3}\s*/, "").trim();
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : null;
};

function matches(v: unknown, op: Operator, wanted: string): boolean {
  const have = text(v).trim();
  if (op === "is empty") return have === "";
  if (op === "is not empty") return have !== "";
  if (op === "contains") return have.toLowerCase().includes(wanted.trim().toLowerCase());
  const a = asNumber(v), b = asNumber(wanted);
  const numeric = a != null && b != null && wanted.trim() !== "" && have !== "";
  const cmp = numeric ? (a as number) - (b as number) : have.toLowerCase().localeCompare(wanted.trim().toLowerCase());
  switch (op) {
    case "=": return cmp === 0;
    case "!=": return cmp !== 0;
    case ">": return cmp > 0;
    case "<": return cmp < 0;
    case ">=": return cmp >= 0;
    case "<=": return cmp <= 0;
    default: return true;
  }
}

function aggregate(values: unknown[], agg: Aggregate): number {
  if (agg === "count") return values.length;
  const nums = values.map(asNumber).filter((n): n is number => n != null);
  if (nums.length === 0) return 0;
  if (agg === "sum") return nums.reduce((s, n) => s + n, 0);
  if (agg === "avg") return nums.reduce((s, n) => s + n, 0) / nums.length;
  if (agg === "min") return Math.min(...nums);
  return Math.max(...nums);
}
const fmt = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });

/** State and row processing for one screen's Actions menu. */
export function useGridActions<T>(storageKey: string, columns: GridColumn<T>[]) {
  const [settings, setSettings] = useState<Settings>(EMPTY);
  const [saved, setSaved] = useState(false);
  const key = `grid-actions.${storageKey}`;

  useEffect(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored) { setSettings({ ...EMPTY, ...JSON.parse(stored) }); setSaved(true); }
    } catch { /* storage unavailable: start clean */ }
  }, [key]);

  const update = (patch: Partial<Settings>) => setSettings((s) => ({ ...s, ...patch }));
  const byKey = useMemo(() => new Map(columns.map((c) => [c.key, c])), [columns]);

  /** The loaded rows after the filters and the sort. */
  const apply = (rows: T[]): T[] => {
    let out = rows.filter((row) => settings.filters.every((f) =>
      !f.enabled || !byKey.has(f.column) || matches(raw(row, byKey.get(f.column)), f.op, f.value)));
    const sort = settings.sort;
    if (sort && byKey.has(sort.column)) {
      const col = byKey.get(sort.column);
      out = [...out].sort((a, b) => {
        const x = raw(a, col), y = raw(b, col);
        const nx = asNumber(x), ny = asNumber(y);
        const cmp = col?.numeric && nx != null && ny != null ? nx - ny : text(x).localeCompare(text(y), undefined, { numeric: true });
        return sort.direction === "asc" ? cmp : -cmp;
      });
    }
    if (settings.controlBreak && byKey.has(settings.controlBreak)) {
      const col = byKey.get(settings.controlBreak);
      out = [...out].sort((a, b) => text(raw(a, col)).localeCompare(text(raw(b, col)), undefined, { numeric: true }));
    }
    return out;
  };

  /** The background a highlight rule gives this row, if any. */
  const rowStyle = (row: T): React.CSSProperties | undefined => {
    const hit = settings.highlights.find((h) => h.enabled && byKey.has(h.column)
      && matches(raw(row, byKey.get(h.column)), h.op, h.value));
    // Dark text on the light highlight colours, so a highlighted row reads in dark mode too.
    return hit ? { backgroundColor: hit.color, color: "#1A1A1A" } : undefined;
  };

  /** With a control break: the heading to print before this row, when the group changes. */
  const breakBefore = (rows: T[], index: number): string | null => {
    if (!settings.controlBreak) return null;
    const col = byKey.get(settings.controlBreak);
    if (!col) return null;
    const now = text(raw(rows[index], col));
    if (index > 0 && text(raw(rows[index - 1], col)) === now) return null;
    const count = rows.filter((r) => text(raw(r, col)) === now).length;
    return `${col.label}: ${now || "(blank)"} · ${count} row${count === 1 ? "" : "s"}`;
  };

  const save = () => {
    try { localStorage.setItem(key, JSON.stringify(settings)); setSaved(true); } catch { /* not kept */ }
  };
  const reset = () => {
    setSettings(EMPTY);
    try { localStorage.removeItem(key); } catch { /* nothing kept */ }
    setSaved(false);
  };

  const active = settings.filters.length + settings.highlights.length
    + (settings.sort ? 1 : 0) + (settings.controlBreak ? 1 : 0);
  return { settings, update, apply, rowStyle, breakBefore, save, reset, saved, active, columns, byKey };
}

export type GridActionsState<T> = ReturnType<typeof useGridActions<T>>;

/** The Actions button and its menu, plus the dialogs behind each entry. */
export function GridActions<T>({
  state, pageSize, onPageSize, hidden, onToggleColumn, onShowAllColumns,
}: {
  state: GridActionsState<T>;
  pageSize?: number;
  onPageSize?: (n: number) => void;
  hidden?: Set<string>;
  onToggleColumn?: (key: string) => void;
  onShowAllColumns?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [sub, setSub] = useState<"data" | "format" | "rows" | "report" | null>(null);
  const [dialog, setDialog] = useState<null | "columns" | "filter" | "sort" | "break" | "highlight" | "chart" | "group" | "pivot" | "help">(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) { setOpen(false); setSub(null); } };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (d: typeof dialog) => { setDialog(d); setOpen(false); setSub(null); };
  const item = "flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12.5px] hover:bg-hover";
  const subItem = (name: typeof sub) =>
    `${item} ${sub === name ? "bg-primary text-on-primary hover:bg-primary" : ""}`;

  return (
    <div ref={ref} className="relative">
      <button onClick={() => { setOpen((v) => !v); setSub(null); }}
        className="flex items-center gap-1.5 rounded-lg bg-hover px-3.5 py-2 text-[12.8px] font-medium text-muted transition-colors hover:text-text">
        <Settings2 size={14} /> Actions {state.active > 0 && <span className="rounded-full bg-primary px-1.5 text-[10.5px] text-on-primary">{state.active}</span>}
        <ChevronDown size={13} />
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-52 rounded-lg border border-line bg-surface py-1 shadow-xl">
          {onToggleColumn && <button className={item} onClick={() => pick("columns")}><Columns3 size={14} /> Columns</button>}
          <button className={item} onClick={() => pick("filter")}><Filter size={14} /> Filter</button>
          <div className="relative">
            <button className={subItem("data")} onMouseEnter={() => setSub("data")} onClick={() => setSub("data")}>
              <Table2 size={14} /> Data <ChevronRight size={13} className="ml-auto" /></button>
            {sub === "data" && (
              <div className="absolute right-full top-0 mr-1 w-44 rounded-lg border border-line bg-surface py-1 shadow-xl">
                <button className={item} onClick={() => pick("sort")}><SortAsc size={14} /> Sort</button>
              </div>
            )}
          </div>
          <div className="relative">
            <button className={subItem("format")} onMouseEnter={() => setSub("format")} onClick={() => setSub("format")}>
              <Wrench size={14} /> Format <ChevronRight size={13} className="ml-auto" /></button>
            {sub === "format" && (
              <div className="absolute right-full top-0 mr-1 w-48 rounded-lg border border-line bg-surface py-1 shadow-xl">
                <button className={item} onClick={() => pick("break")}><ListTree size={14} /> Control Break</button>
                <button className={item} onClick={() => pick("highlight")}><Highlighter size={14} /> Highlight</button>
                {onPageSize && (
                  <div className="border-t border-line pt-1">
                    <p className="m-0 flex items-center gap-2.5 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
                      <Rows3 size={13} /> Rows Per Page</p>
                    <div className="grid grid-cols-2 px-1 pb-1">
                      {[...ROWS_PER_PAGE, ALL_ROWS].map((n) => (
                        <button key={n} onClick={() => { onPageSize(n); setOpen(false); setSub(null); }}
                          className={`flex items-center gap-1.5 rounded px-2 py-1 text-left text-[12px] hover:bg-hover ${pageSize === n ? "font-semibold text-primary" : ""}`}>
                          {pageSize === n ? <Check size={11} /> : <span className="w-[11px]" />}{n === ALL_ROWS ? "All" : n}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="my-1 border-t border-line" />
          <button className={item} onClick={() => pick("chart")}><BarChart3 size={14} /> Chart</button>
          <button className={item} onClick={() => pick("group")}><LayoutList size={14} /> Group By</button>
          <button className={item} onClick={() => pick("pivot")}><Table2 size={14} /> Pivot</button>
          <div className="my-1 border-t border-line" />
          <div className="relative">
            <button className={subItem("report")} onMouseEnter={() => setSub("report")} onClick={() => setSub("report")}>
              <Save size={14} /> Report <ChevronRight size={13} className="ml-auto" /></button>
            {sub === "report" && (
              <div className="absolute right-full top-0 mr-1 w-48 rounded-lg border border-line bg-surface py-1 shadow-xl">
                <button className={item} onClick={() => { state.save(); setOpen(false); setSub(null); }}>Save report settings</button>
                <button className={item} onClick={() => { state.reset(); setOpen(false); setSub(null); }}>Reset to default</button>
              </div>
            )}
          </div>
          <button className={item} onClick={() => pick("help")}><HelpCircle size={14} /> Help</button>
        </div>
      )}

      {dialog === "columns" && onToggleColumn && (
        <Dialog title="Columns" onClose={() => setDialog(null)}>
          <div className="grid max-h-[60vh] grid-cols-2 gap-1 overflow-y-auto">
            {state.columns.map((c) => {
              const shown = !hidden?.has(c.key);
              return (
                <button key={c.key} onClick={() => onToggleColumn(c.key)}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] hover:bg-hover">
                  <span className={`flex h-3.5 w-3.5 items-center justify-center rounded border ${shown ? "border-primary bg-primary text-on-primary" : "border-line"}`}>
                    {shown && <Check size={10} strokeWidth={3} />}</span>
                  <span className={shown ? "" : "text-faint"}>{c.label}</span>
                </button>
              );
            })}
          </div>
          {onShowAllColumns && <button onClick={onShowAllColumns} className="mt-3 text-[12px] font-medium text-primary hover:underline">Show all columns</button>}
        </Dialog>
      )}
      {(dialog === "filter" || dialog === "highlight") && (
        <RuleDialog state={state} kind={dialog} onClose={() => setDialog(null)} />
      )}
      {dialog === "sort" && <SortDialog state={state} onClose={() => setDialog(null)} />}
      {dialog === "break" && <BreakDialog state={state} onClose={() => setDialog(null)} />}
      {(dialog === "chart" || dialog === "group" || dialog === "pivot") && (
        <ViewDialog state={state} kind={dialog} onClose={() => setDialog(null)} />
      )}
      {dialog === "help" && (
        <Dialog title="Actions — help" onClose={() => setDialog(null)}>
          <ul className="m-0 space-y-1.5 pl-4 text-[12.5px] leading-relaxed text-muted">
            <li><b>Columns</b> — show or hide columns.</li>
            <li><b>Filter</b> — keep only rows where a column matches, e.g. Status = Closed. Several filters all apply.</li>
            <li><b>Data → Sort</b> — order the rows by any column.</li>
            <li><b>Format → Control Break</b> — group the rows under a heading per value of a column.</li>
            <li><b>Format → Highlight</b> — colour the rows that match a rule.</li>
            <li><b>Format → Rows Per Page</b> — how many rows load at once. Choose <b>All</b> so filters, charts and totals cover every record.</li>
            <li><b>Chart / Group By / Pivot</b> — totals of the rows by one or two columns.</li>
            <li><b>Report</b> — keep these settings for next time on this computer, or go back to the default.</li>
          </ul>
        </Dialog>
      )}
    </div>
  );
}

/** The active filters and highlights as chips under the toolbar, each can be switched off or removed. */
export function GridActionChips<T>({ state }: { state: GridActionsState<T> }) {
  const { settings, update, byKey } = state;
  const chips = [
    ...settings.filters.map((f) => ({ ...f, kind: "filter" as const, color: "" })),
    ...settings.highlights.map((h) => ({ ...h, kind: "highlight" as const })),
  ];
  if (!chips.length && !settings.sort && !settings.controlBreak) return null;
  const toggle = (kind: "filter" | "highlight", id: string) => update(kind === "filter"
    ? { filters: settings.filters.map((f) => (f.id === id ? { ...f, enabled: !f.enabled } : f)) }
    : { highlights: settings.highlights.map((h) => (h.id === id ? { ...h, enabled: !h.enabled } : h)) });
  const remove = (kind: "filter" | "highlight", id: string) => update(kind === "filter"
    ? { filters: settings.filters.filter((f) => f.id !== id) }
    : { highlights: settings.highlights.filter((h) => h.id !== id) });
  const describe = (c: Rule) => `${byKey.get(c.column)?.label ?? c.column} ${c.op}${c.op.startsWith("is ") ? "" : ` '${c.value}'`}`;
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-2.5">
      {chips.map((c) => (
        <span key={c.id} className={`flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11.5px] ${c.enabled ? "" : "opacity-50"}`}
          style={c.kind === "highlight" ? { backgroundColor: c.color } : undefined}>
          <input type="checkbox" checked={c.enabled} onChange={() => toggle(c.kind, c.id)} aria-label="Apply" />
          {c.kind === "filter" ? <Filter size={11} /> : <Highlighter size={11} />}
          {describe(c)}
          <button onClick={() => remove(c.kind, c.id)} aria-label="Remove" className="text-faint hover:text-rose"><X size={12} /></button>
        </span>
      ))}
      {settings.sort && (
        <span className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11.5px]">
          <SortAsc size={11} /> Sorted by {byKey.get(settings.sort.column)?.label} {settings.sort.direction === "asc" ? "↑" : "↓"}
          <button onClick={() => update({ sort: null })} aria-label="Remove" className="text-faint hover:text-rose"><X size={12} /></button>
        </span>
      )}
      {settings.controlBreak && (
        <span className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11.5px]">
          <ListTree size={11} /> Break on {byKey.get(settings.controlBreak)?.label}
          <button onClick={() => update({ controlBreak: null })} aria-label="Remove" className="text-faint hover:text-rose"><X size={12} /></button>
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- dialogs

function Dialog({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center bg-black/40 p-4 pt-20" onMouseDown={onClose}>
      <div className={`w-full ${wide ? "max-w-4xl" : "max-w-lg"} rounded-[12px] border border-line bg-surface shadow-xl`}
        onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center border-b border-line px-4 py-3">
          <h4 className="m-0 text-[13.5px] font-semibold">{title}</h4>
          <button onClick={onClose} aria-label="Close" className="ml-auto rounded-md p-1 text-muted hover:bg-hover"><X size={16} /></button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

const field = "w-full rounded-md border border-line bg-bg px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary";

function ColumnSelect<T>({ state, value, onChange, numericOnly, placeholder }: {
  state: GridActionsState<T>; value: string; onChange: (v: string) => void; numericOnly?: boolean; placeholder?: string;
}) {
  return (
    <select className={field} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder ?? "Choose a column…"}</option>
      {state.columns.filter((c) => !numericOnly || c.numeric).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
    </select>
  );
}

function RuleDialog<T>({ state, kind, onClose }: { state: GridActionsState<T>; kind: "filter" | "highlight"; onClose: () => void }) {
  const [column, setColumn] = useState("");
  const [op, setOp] = useState<Operator>(kind === "filter" ? "contains" : "=");
  const [value, setValue] = useState("");
  const [color, setColor] = useState(COLORS[0].value);
  const add = () => {
    if (!column) return;
    if (kind === "filter") state.update({ filters: [...state.settings.filters, { id: uid(), column, op, value, enabled: true }] });
    else state.update({ highlights: [...state.settings.highlights, { id: uid(), column, op, value, enabled: true, color }] });
    onClose();
  };
  return (
    <Dialog title={kind === "filter" ? "Filter" : "Highlight"} onClose={onClose}>
      <div className="grid grid-cols-[1.4fr_1fr_1.4fr] gap-2">
        <ColumnSelect state={state} value={column} onChange={setColumn} />
        <select className={field} value={op} onChange={(e) => setOp(e.target.value as Operator)}>
          {OPERATORS.map((o) => <option key={o}>{o}</option>)}
        </select>
        <input className={field} value={value} disabled={op.startsWith("is ")} placeholder="Value"
          onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
      </div>
      {kind === "highlight" && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px]">
          <span className="text-muted">Row colour</span>
          {COLORS.map((c) => (
            <button key={c.value} onClick={() => setColor(c.value)} title={c.name}
              className={`h-6 w-10 rounded border ${color === c.value ? "border-text ring-2 ring-primary/40" : "border-line"}`}
              style={{ backgroundColor: c.value }} />
          ))}
        </div>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg bg-hover px-3.5 py-1.5 text-[12.5px] text-muted">Cancel</button>
        <button onClick={add} disabled={!column}
          className="rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-on-primary disabled:opacity-50">Apply</button>
      </div>
    </Dialog>
  );
}

function SortDialog<T>({ state, onClose }: { state: GridActionsState<T>; onClose: () => void }) {
  const [column, setColumn] = useState(state.settings.sort?.column ?? "");
  const [direction, setDirection] = useState<"asc" | "desc">(state.settings.sort?.direction ?? "asc");
  return (
    <Dialog title="Sort" onClose={onClose}>
      <div className="grid grid-cols-[2fr_1fr] gap-2">
        <ColumnSelect state={state} value={column} onChange={setColumn} />
        <select className={field} value={direction} onChange={(e) => setDirection(e.target.value as "asc" | "desc")}>
          <option value="asc">Ascending</option><option value="desc">Descending</option>
        </select>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={() => { state.update({ sort: null }); onClose(); }} className="rounded-lg bg-hover px-3.5 py-1.5 text-[12.5px] text-muted">Clear</button>
        <button onClick={() => { state.update({ sort: column ? { column, direction } : null }); onClose(); }}
          className="rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-on-primary">Apply</button>
      </div>
    </Dialog>
  );
}

function BreakDialog<T>({ state, onClose }: { state: GridActionsState<T>; onClose: () => void }) {
  const [column, setColumn] = useState(state.settings.controlBreak ?? "");
  return (
    <Dialog title="Control Break" onClose={onClose}>
      <p className="mb-2 mt-0 text-[12px] text-muted">The rows are grouped under a heading for each value of this column.</p>
      <ColumnSelect state={state} value={column} onChange={setColumn} />
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={() => { state.update({ controlBreak: null }); onClose(); }} className="rounded-lg bg-hover px-3.5 py-1.5 text-[12.5px] text-muted">Clear</button>
        <button onClick={() => { state.update({ controlBreak: column || null }); onClose(); }}
          className="rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-on-primary">Apply</button>
      </div>
    </Dialog>
  );
}

const AGGS: Aggregate[] = ["count", "sum", "avg", "min", "max"];

/** Chart, Group By and Pivot: chosen here, shown over the list by GridActionView. */
function ViewDialog<T>({ state, kind, onClose }: { state: GridActionsState<T>; kind: "chart" | "group" | "pivot"; onClose: () => void }) {
  const s = state.settings;
  const [a, setA] = useState(kind === "chart" ? s.chart.label : kind === "group" ? s.group.column : s.pivot.row);
  const [b, setB] = useState(kind === "pivot" ? s.pivot.column : "");
  const [value, setValue] = useState(kind === "chart" ? s.chart.value : kind === "group" ? s.group.value : s.pivot.value);
  const [agg, setAgg] = useState<Aggregate>(kind === "chart" ? s.chart.agg : kind === "group" ? s.group.agg : s.pivot.agg);
  const apply = () => {
    if (!a || (kind === "pivot" && !b)) return;
    const v = agg === "count" ? "" : value;
    if (kind === "chart") state.update({ view: "chart", chart: { label: a, value: v, agg } });
    else if (kind === "group") state.update({ view: "group", group: { column: a, value: v, agg } });
    else state.update({ view: "pivot", pivot: { row: a, column: b, value: v, agg } });
    onClose();
  };
  return (
    <Dialog title={kind === "chart" ? "Chart" : kind === "group" ? "Group By" : "Pivot"} onClose={onClose}>
      <div className="space-y-2.5 text-[12px]">
        <label className="block"><span className="text-muted">{kind === "chart" ? "Label (one bar per value)" : kind === "pivot" ? "Row column" : "Group by"}</span>
          <ColumnSelect state={state} value={a} onChange={setA} /></label>
        {kind === "pivot" && <label className="block"><span className="text-muted">Pivot column (one column per value)</span>
          <ColumnSelect state={state} value={b} onChange={setB} /></label>}
        <div className="grid grid-cols-[1fr_2fr] gap-2">
          <label className="block"><span className="text-muted">Function</span>
            <select className={field} value={agg} onChange={(e) => setAgg(e.target.value as Aggregate)}>
              {AGGS.map((x) => <option key={x} value={x}>{x === "count" ? "Count rows" : x[0].toUpperCase() + x.slice(1)}</option>)}
            </select></label>
          <label className="block"><span className="text-muted">Of column</span>
            <select className={field} value={value} disabled={agg === "count"} onChange={(e) => setValue(e.target.value)}>
              <option value="">{agg === "count" ? "—" : "Choose a number column…"}</option>
              {state.columns.filter((c) => c.numeric).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select></label>
        </div>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg bg-hover px-3.5 py-1.5 text-[12.5px] text-muted">Cancel</button>
        <button onClick={apply} className="rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-on-primary">Show</button>
      </div>
    </Dialog>
  );
}

/** The chart, group-by or pivot result over the (filtered) loaded rows, with a way back to the report. */
export function GridActionView<T>({ state, rows, total }: { state: GridActionsState<T>; rows: T[]; total?: number }) {
  const s = state.settings;
  if (s.view === "report") return null;
  const col = (k: string) => state.byKey.get(k);
  const label = (k: string) => col(k)?.label ?? k;
  const back = () => state.update({ view: "report" });
  const partial = total != null && total > rows.length;
  const note = (
    <p className="m-0 mt-2 text-[11px] text-faint">
      Over {rows.length.toLocaleString()} loaded row{rows.length === 1 ? "" : "s"}
      {partial ? ` of ${total!.toLocaleString()} — set Format → Rows Per Page → All to include every record.` : "."}
    </p>
  );
  const groups = (by: string) => {
    const map = new Map<string, T[]>();
    for (const r of rows) {
      const k = text(raw(r, col(by))) || "(blank)";
      map.set(k, [...(map.get(k) ?? []), r]);
    }
    return map;
  };
  const measure = (list: T[], value: string, agg: Aggregate) => aggregate(list.map((r) => raw(r, col(value))), agg);
  const header = (title: string) => (
    <div className="mb-3 flex items-center gap-3">
      <b className="text-[13px]">{title}</b>
      <button onClick={back} className="ml-auto rounded-lg bg-hover px-3 py-1.5 text-[12px] font-medium text-muted hover:text-text">Back to report</button>
    </div>
  );
  const what = (agg: Aggregate, value: string) => (agg === "count" ? "Count" : `${agg[0].toUpperCase()}${agg.slice(1)} of ${label(value)}`);

  if (s.view === "chart") {
    const data = [...groups(s.chart.label)].map(([k, list]) => [k, measure(list, s.chart.value, s.chart.agg)] as const)
      .sort((x, y) => y[1] - x[1]).slice(0, 40);
    const top = Math.max(...data.map((d) => d[1]), 0);
    return (
      <div className="border-b border-line px-5 py-4">
        {header(`Chart — ${what(s.chart.agg, s.chart.value)} by ${label(s.chart.label)}`)}
        <ul className="m-0 list-none space-y-1 p-0">
          {data.map(([k, v]) => (
            <li key={k} className="grid grid-cols-[minmax(0,220px)_1fr_auto] items-center gap-3 text-[12px]">
              <span className="truncate" title={k}>{k}</span>
              <div className="h-[16px]"><div className="h-full rounded-r-[4px] bg-primary" style={{ width: `${top > 0 ? Math.max(1, (v / top) * 100) : 0}%` }} /></div>
              <span className="text-right font-semibold tabular-nums">{fmt(v)}</span>
            </li>
          ))}
        </ul>
        {note}
      </div>
    );
  }
  if (s.view === "group") {
    const data = [...groups(s.group.column)].map(([k, list]) => [k, list.length, measure(list, s.group.value, s.group.agg)] as const)
      .sort((x, y) => x[0].localeCompare(y[0], undefined, { numeric: true }));
    return (
      <div className="border-b border-line px-5 py-4">
        {header(`Group By — ${label(s.group.column)}`)}
        <table className="w-full max-w-2xl border-collapse text-left text-[12.5px]">
          <thead><tr className="border-b border-line text-[11.5px] text-primary">
            <th className="py-1.5 pr-3">{label(s.group.column)}</th><th className="py-1.5 pr-3 text-right">Rows</th>
            {s.group.agg !== "count" && <th className="py-1.5 text-right">{what(s.group.agg, s.group.value)}</th>}
          </tr></thead>
          <tbody>
            {data.map(([k, n, v]) => (
              <tr key={k} className="border-b border-line last:border-0">
                <td className="py-1.5 pr-3">{k}</td><td className="py-1.5 pr-3 text-right tabular-nums">{n.toLocaleString()}</td>
                {s.group.agg !== "count" && <td className="py-1.5 text-right font-medium tabular-nums">{fmt(v)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {note}
      </div>
    );
  }
  // pivot
  const across = [...new Set(rows.map((r) => text(raw(r, col(s.pivot.column))) || "(blank)"))]
    .sort((x, y) => x.localeCompare(y, undefined, { numeric: true })).slice(0, 30);
  const down = groups(s.pivot.row);
  return (
    <div className="border-b border-line px-5 py-4">
      {header(`Pivot — ${what(s.pivot.agg, s.pivot.value)}: ${label(s.pivot.row)} × ${label(s.pivot.column)}`)}
      <div className="overflow-x-auto">
        <table className="border-collapse text-left text-[12px]">
          <thead><tr className="border-b border-line text-[11px] text-primary">
            <th className="py-1.5 pr-4">{label(s.pivot.row)}</th>
            {across.map((a) => <th key={a} className="whitespace-nowrap px-3 py-1.5 text-right">{a}</th>)}
            <th className="px-3 py-1.5 text-right">Total</th>
          </tr></thead>
          <tbody>
            {[...down].sort((x, y) => x[0].localeCompare(y[0], undefined, { numeric: true })).map(([k, list]) => (
              <tr key={k} className="border-b border-line last:border-0">
                <td className="py-1.5 pr-4">{k}</td>
                {across.map((a) => {
                  const cell = list.filter((r) => (text(raw(r, col(s.pivot.column))) || "(blank)") === a);
                  return <td key={a} className="px-3 py-1.5 text-right tabular-nums">{cell.length ? fmt(measure(cell, s.pivot.value, s.pivot.agg)) : ""}</td>;
                })}
                <td className="px-3 py-1.5 text-right font-semibold tabular-nums">{fmt(measure(list, s.pivot.value, s.pivot.agg))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note}
    </div>
  );
}
