"use client";

import type { LucideIcon } from "lucide-react";
import { Combobox } from "@/components/ui/Modal";
import { hrTone, label, type Lookups } from "@/lib/hrms";

/** ACTIVE / PENDING / PAID … as a small coloured pill. */
export function HrBadge({ status, text }: { status: string; text?: string }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11px] font-semibold ${hrTone(status)}`}>
      {text ?? label(status)}
    </span>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: readonly (readonly [T, string, number?])[]; value: T; onChange: (tab: T) => void;
}) {
  return (
    <div className="mb-5 flex flex-wrap gap-1.5">
      {tabs.map(([key, text, count]) => (
        <button key={key} onClick={() => onChange(key)}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 text-[12.8px] font-medium transition-colors
                      ${value === key ? "bg-primary/15 text-primary" : "bg-surface text-muted hover:text-text"}`}>
          {text}
          {typeof count === "number" && count > 0 && (
            <span className="rounded-full bg-amber/20 px-1.5 text-[10.5px] font-semibold text-amber">{count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

const TILE_TONE = {
  green: "bg-success/10 text-success", rose: "bg-rose/10 text-rose", amber: "bg-amber/15 text-amber",
  sky: "bg-sky/15 text-sky", violet: "bg-violet/15 text-violet", plain: "bg-hover text-muted",
};

/** A headline figure. With `onClick` it doubles as a filter. */
export function Tile({ icon: Icon, label: text, value, note, tone = "green", active, onClick }: {
  icon: LucideIcon; label: string; value: React.ReactNode; note?: React.ReactNode;
  tone?: keyof typeof TILE_TONE; active?: boolean; onClick?: () => void;
}) {
  const body = (
    <>
      <span className={`flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full ${TILE_TONE[tone]}`}>
        <Icon size={19} strokeWidth={1.8} />
      </span>
      <span className="min-w-0 text-left">
        <span className="block text-[11.8px] text-muted">{text}</span>
        <span className="block text-[21px] font-bold leading-tight">{value}</span>
        {note && <span className="block truncate text-[11px] text-faint">{note}</span>}
      </span>
    </>
  );
  const frame = `flex items-center gap-3.5 rounded-[14px] border bg-surface px-5 py-4 shadow-panel
                 ${active ? "border-primary" : "border-line"}`;
  return onClick
    ? <button type="button" onClick={onClick} className={`${frame} transition-colors hover:border-primary/60`}>{body}</button>
    : <div className={frame}>{body}</div>;
}

/** Pick an employee by code or name. Former employees are left out unless asked for. */
export function EmployeePicker({ lookups, value, onChange, includeLeft = false, placeholder }: {
  lookups: Lookups | null; value: string; onChange: (id: string) => void; includeLeft?: boolean; placeholder?: string;
}) {
  const options = (lookups?.employees ?? [])
    .filter((e) => includeLeft || e.id === value || !["RESIGNED", "TERMINATED"].includes(e.status))
    .map((e) => ({ value: e.id, label: `${e.code}  ${e.name}`, short: `${e.code} ${e.name}` }));
  return <Combobox value={value} options={options} onChange={onChange}
    placeholder={placeholder ?? "Type a name or code…"} emptyMessage="No employee matches." />;
}

/** A label over a value, for read-only profile panels. */
export function Fact({ label: text, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-faint">{text}</div>
      {/* 0 is a real value here (0 late arrivals); only a missing one shows as a dash. */}
      <div className="break-words text-[12.8px]">
        {children === null || children === undefined || children === "" || children === false
          ? <span className="text-faint">—</span> : children}
      </div>
    </div>
  );
}

export const selectClass =
  "rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] outline-none focus:border-primary";
