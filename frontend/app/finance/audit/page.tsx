"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { EmptyState, PageHeader, Spinner, filterClass } from "@/components/finance/ui";
import { api } from "@/lib/api";
import { errorText, fmtDateTime } from "@/lib/finance";

interface Entry {
  id: string; occurred_at: string; username: string | null; action: string; module: string;
  entity: string | null; entity_id: string | null; old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null; ip_address: string | null; reason: string | null;
}

const ACTIONS = ["create", "update", "delete", "submit", "approve", "reject", "post", "reverse",
  "cancel", "import", "export", "validate", "close", "reopen", "lock", "login", "login_failed"];
const ENTITIES = ["journal_entries", "accounts", "accounting_periods", "opening_balance_batches",
  "opening_balance_reconciliations", "posting_rules", "document_series", "cost_centers", "users"];

const show = (values: Record<string, unknown> | null) =>
  values ? Object.entries(values).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ") : "";

export default function AuditLogPage() {
  const [rows, setRows] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [entity, setEntity] = useState("");
  const [user, setUser] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 50;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (action) qs.set("action", action);
      if (entity) qs.set("entity", entity);
      if (user) qs.set("username", user);
      if (from) qs.set("date_from", from);
      if (to) qs.set("date_to", to);
      const data = await api.get<{ items: Entry[]; total: number }>(`/finance/audit-logs?${qs}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(errorText(err, "Could not load the audit log."));
    } finally {
      setLoading(false);
    }
  }, [page, action, entity, user, from, to]);

  useEffect(() => {
    const t = setTimeout(load, user ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, user]);

  const dirty = Boolean(action || entity || user || from || to);
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <AppShell title="Audit Log">
      <PageHeader title="Audit Log"
        subtitle="Append-only: the database refuses to change or delete an entry once written." />
      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={total} noun="Entry" resettable={dirty}
          onReset={() => { setAction(""); setEntity(""); setUser(""); setFrom(""); setTo(""); setPage(1); }} />
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 pb-4 pt-2">
          <select className={filterClass} value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
            <option value="">All actions</option>
            {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select className={filterClass} value={entity} onChange={(e) => { setEntity(e.target.value); setPage(1); }}>
            <option value="">All records</option>
            {ENTITIES.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <input className={filterClass} value={user} placeholder="User…" onChange={(e) => { setUser(e.target.value); setPage(1); }} />
          <input type="date" className={filterClass} value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} />
          <input type="date" className={filterClass} value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} />
        </div>
        {error && <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1100px] border-collapse text-left">
            <thead><tr className="border-b border-line">
              <GridTh>When</GridTh><GridTh>User</GridTh><GridTh>Action</GridTh><GridTh>Record</GridTh>
              <GridTh>Before</GridTh><GridTh>After</GridTh><GridTh>Reason</GridTh><GridTh>IP</GridTh>
            </tr></thead>
            <tbody>
              {loading && <tr><td colSpan={8}><Spinner /></td></tr>}
              {!loading && rows.length === 0 && <tr><td colSpan={8}><EmptyState>No entries.</EmptyState></td></tr>}
              {!loading && rows.map((r, i) => (
                <tr key={r.id} className={gridRowClass(i)}>
                  <td className={gridCellClass(false, "whitespace-nowrap")}>{fmtDateTime(r.occurred_at)}</td>
                  <td className={gridCellClass()}>{r.username ?? "system"}</td>
                  <td className={gridCellClass(false, "font-medium")}>{r.action}</td>
                  <td className={gridCellClass(false, "text-muted")}>{r.entity}</td>
                  <td className={gridCellClass(false, "max-w-[260px] truncate text-[12px] text-muted")} title={show(r.old_values)}>{show(r.old_values)}</td>
                  <td className={gridCellClass(false, "max-w-[320px] truncate text-[12px]")} title={show(r.new_values)}>{show(r.new_values)}</td>
                  <td className={gridCellClass(false, "max-w-[220px] truncate text-[12px]")} title={r.reason ?? ""}>{r.reason}</td>
                  <td className={gridCellClass(false, "text-[12px] text-faint")}>{r.ip_address}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{total.toLocaleString()} entries</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
            <span className="px-2">Page {page} of {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>
    </AppShell>
  );
}
