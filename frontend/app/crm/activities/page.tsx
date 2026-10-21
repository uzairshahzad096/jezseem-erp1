"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlarmClock, Check, ClipboardList, History, ListTodo, Pencil, Plus, Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ACTIVITY_ICON, LogActivity } from "@/components/crm/LogActivity";
import { LeadDrawer } from "@/components/leads/LeadDrawer";
import { api } from "@/lib/api";
import { useCustomers } from "@/lib/calibration";
import type { CrmActivity } from "@/lib/crm";
import { addDays, errorText, fmtDate, relDay, timeAgo, useFetch, useLeadLookups } from "@/lib/leads";

type Scope = "all" | "todo" | "overdue" | "done";

/** Everything done and planned with customers and leads, in one log. */
export default function ActivitiesPage() {
  const lookups = useLeadLookups();
  const customers = useCustomers();
  const [scope, setScope] = useState<Scope>("all");
  const [type, setType] = useState("");
  const [owner, setOwner] = useState("");
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [logging, setLogging] = useState(false);
  const [opened, setOpened] = useState<string | null>(null);
  const [closing, setClosing] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { const t = setTimeout(() => setSearch(typed), 350); return () => clearTimeout(t); }, [typed]);
  const list = useFetch<{ items: CrmActivity[]; total: number; counts: { overdue: number; todo: number; last_7_days: number } }>(
    `/crm/activities?scope=${scope}&page_size=300${type ? `&activity_type=${encodeURIComponent(type)}` : ""}`
    + `${owner ? `&owner_id=${owner}` : ""}${search ? `&search=${encodeURIComponent(search)}` : ""}`);
  const rows = list.data?.items ?? [];
  const c = list.data?.counts;

  const done = async (id: string) => {
    setError(null);
    try { await api.post(`/crm/activities/${id}/done`, { outcome, next_follow_up_date: next }); setClosing(null); list.reload(); }
    catch (err) { setError(errorText(err, "Could not save.")); }
  };

  // A log reads by day.
  const groups = rows.reduce<[string, CrmActivity[]][]>((acc, a) => {
    const day = a.open ? (a.overdue ? "Overdue" : `Due ${fmtDate(a.due_date)}`) : fmtDate((a.done_at ?? a.activity_at).slice(0, 10));
    const last = acc[acc.length - 1];
    if (last && last[0] === day) last[1].push(a); else acc.push([day, [a]]);
    return acc;
  }, []);

  const tab = (value: Scope, icon: React.ReactNode, label: string, count?: number, hot = false) => (
    <button onClick={() => setScope(value)}
      className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-[12.8px] font-medium ${
        scope === value ? "border-primary bg-primary text-on-primary" : "border-line bg-surface text-muted hover:text-text"}`}>
      {icon}{label}{count != null && <span className={`rounded-full px-2 text-[11px] ${scope === value ? "bg-white/25" : hot ? "bg-rose/15 text-rose" : "bg-hover"}`}>{count}</span>}
    </button>
  );

  return (
    <AppShell title="Activities">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="m-0 text-[19px] font-semibold">Activities</h1>
          <p className="m-0 text-[12px] text-muted">Every call, visit, message and meeting with customers and leads — {c?.last_7_days ?? 0} in the last 7 days.</p>
        </div>
        <button onClick={() => setLogging(true)}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary to-primary-dark px-4 py-2 text-[12.8px] font-medium text-on-primary">
          <Plus size={14} /> Log activity</button>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {tab("all", <History size={14} />, "Everything")}
        {tab("todo", <ListTodo size={14} />, "To do", c?.todo)}
        {tab("overdue", <AlarmClock size={14} />, "Overdue", c?.overdue, Boolean(c?.overdue))}
        {tab("done", <Check size={14} />, "Done")}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2">
            <Search size={14} className="text-faint" />
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Customer, what was said…"
              className="w-52 border-none bg-transparent text-[12.8px] outline-none" />
          </div>
          <select value={type} onChange={(e) => setType(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] text-muted outline-none">
            <option value="">All kinds</option>
            {(lookups?.activity_types ?? []).map((t) => <option key={t}>{t}</option>)}
          </select>
          <select value={owner} onChange={(e) => setOwner(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] text-muted outline-none">
            <option value="">Everyone</option>
            {(lookups?.users ?? []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </div>
      </div>
      {error && <p className="mb-3 rounded-lg bg-rose/10 px-4 py-2 text-[12.5px] text-rose">{error}</p>}

      {!list.loading && rows.length === 0 && (
        <div className="rounded-[14px] border border-dashed border-line bg-surface px-5 py-16 text-center">
          <ClipboardList size={26} className="mx-auto text-primary" />
          <p className="m-0 mt-3 text-[14px] font-semibold">Nothing here yet</p>
          <p className="m-0 mt-1 text-[12.5px] text-muted">Log a call or visit with a customer, or plan the next one.</p>
        </div>
      )}

      <div className="space-y-5">
        {groups.map(([day, items]) => (
          <section key={day}>
            <h3 className={`m-0 mb-2 text-[12px] font-semibold uppercase tracking-wide ${day === "Overdue" ? "text-rose" : "text-muted"}`}>{day}</h3>
            <div className="overflow-hidden rounded-[14px] border border-line bg-surface shadow-panel">
              {items.map((a) => (
                <div key={a.id} className="border-b border-line px-5 py-3 last:border-0">
                  <div className="flex items-start gap-3">
                    <span className={`mt-0.5 rounded-lg p-1.5 ${a.open ? (a.overdue ? "bg-rose/10 text-rose" : "bg-amber/10 text-amber") : "bg-hover text-muted"}`}>
                      {ACTIVITY_ICON[a.activity_type] ?? <Pencil size={13} />}</span>
                    <div className="min-w-0 flex-1 text-[12.8px]">
                      <div><b>{a.activity_type}</b> · {a.summary}</div>
                      {a.outcome && <div className="mt-0.5 text-[12.3px]">→ {a.outcome}</div>}
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11.5px] text-muted">
                        {a.customer_id ? <Link href={`/crm/customers/${a.customer_id}`} className="font-medium text-text hover:text-primary">{a.customer_name}</Link>
                          : a.lead_title ? <span className="font-medium text-text">{a.lead_title}</span> : null}
                        {a.lead_id && <button onClick={() => setOpened(a.lead_id)} className="rounded bg-violet/10 px-1.5 font-semibold text-violet">{a.lead_number}</button>}
                        {a.contact && <span>with {a.contact}</span>}
                        {a.owner && <span>· {a.owner}</span>}
                        <span>· {a.open ? relDay(a.due_date) : timeAgo(a.done_at ?? a.activity_at)}</span>
                      </div>
                    </div>
                    {a.open && closing !== a.id && (
                      <button onClick={() => { setClosing(a.id); setOutcome(""); setNext(""); }}
                        className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-on-primary"><Check size={13} /> Done</button>
                    )}
                  </div>
                  {closing === a.id && (
                    <div className="ml-10 mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-hover/60 p-2.5 text-[12px]">
                      <input autoFocus value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder="How did it go?"
                        className="min-w-[240px] flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 outline-none focus:border-primary" />
                      <span className="text-muted">Next</span>
                      <input type="date" value={next} onChange={(e) => setNext(e.target.value)} className="rounded-md border border-line bg-surface px-2 py-1" />
                      {[["Tomorrow", 1], ["Next week", 7]].map(([l, d]) => (
                        <button key={l} onClick={() => setNext(addDays(d as number))} className="rounded-full bg-surface px-2 py-0.5 text-[11px]">{l}</button>))}
                      <button onClick={() => setClosing(null)} className="text-muted">Cancel</button>
                      <button onClick={() => void done(a.id)} className="rounded-md bg-primary px-3 py-1 font-semibold text-on-primary">Save</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      {logging && <LogActivity customers={customers} onClose={() => setLogging(false)} onSaved={() => { setLogging(false); list.reload(); }} />}
      {opened && <LeadDrawer leadId={opened} lookups={lookups} onClose={() => setOpened(null)} onChanged={list.reload} onEdit={() => setOpened(null)} />}
    </AppShell>
  );
}
