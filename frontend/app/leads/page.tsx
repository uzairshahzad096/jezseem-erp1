"use client";

import { useMemo, useState } from "react";
import {
  AlarmClock, CalendarClock, Columns3, Flame, LayoutList, Plus, Search, Sparkles, Target, Trophy, Users,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { LeadDrawer } from "@/components/leads/LeadDrawer";
import { LeadForm } from "@/components/leads/LeadForm";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { api } from "@/lib/api";
import { useCustomers } from "@/lib/calibration";
import {
  API, RATING_TONE, STAGE_TONE, compact, errorText, fmtDate, initials, money, relDay,
  useFetch, useLeadLookups, type Lead,
} from "@/lib/leads";

interface Summary {
  open_count: number; pipeline_value: number; weighted_value: number; won_month_count: number;
  won_month_value: number; lost_month_count: number; win_rate: number | null; overdue_follow_ups: number;
  today_follow_ups: number; hot_open: number; by_stage: { stage: string; count: number; value: number }[];
  other_currencies: string[];
}
interface Opportunity {
  customer_id: string; name: string; city: string | null; phone: string | null; last_order_date: string;
  days_since: number; orders: number; total_sales: number; open_leads: number;
}

type View = "board" | "list" | "customers";

export default function LeadsPage() {
  const lookups = useLeadLookups();
  const customers = useCustomers();
  const [view, setView] = useState<View>("board");
  const [search, setSearch] = useState("");
  const [owner, setOwner] = useState("");
  const [source, setSource] = useState("");
  const [rating, setRating] = useState("");
  const [opened, setOpened] = useState<string | null>(null);
  const [editing, setEditing] = useState<Lead | "new" | null>(null);
  const [preset, setPreset] = useState<Record<string, string> | undefined>(undefined);
  const [dragging, setDragging] = useState<string | null>(null);
  const [overStage, setOverStage] = useState<string | null>(null);
  const [minDays, setMinDays] = useState("90");
  const [oppSearch, setOppSearch] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const query = new URLSearchParams({ page_size: "2000", ...(search ? { search } : {}), ...(owner ? { owner_id: owner } : {}),
    ...(source ? { source_id: source } : {}), ...(rating ? { rating } : {}) }).toString();
  const leads = useFetch<{ items: Lead[]; total: number }>(`${API}?${query}`);
  const summary = useFetch<Summary>(`${API}/summary${owner ? `?owner_id=${owner}` : ""}`);
  const opps = useFetch<{ items: Opportunity[]; total: number }>(view === "customers"
    ? `${API}/customer-opportunities?min_days=${minDays}&page_size=200${oppSearch ? `&search=${encodeURIComponent(oppSearch)}` : ""}`
    : null);
  const reload = () => { leads.reload(); summary.reload(); };

  const rows = leads.data?.items ?? [];
  const recentlyClosed = (l: Lead) => !l.closed_at || Date.now() - new Date(l.closed_at).getTime() < 60 * 86400000;
  const byStage = useMemo(() => {
    const map = new Map<string, Lead[]>();
    for (const s of lookups?.stages ?? []) map.set(s.name, []);
    for (const l of rows) if (l.stage === "Won" || l.stage === "Lost" ? recentlyClosed(l) : true) map.get(l.stage)?.push(l);
    return map;
  }, [rows, lookups]);   // eslint-disable-line react-hooks/exhaustive-deps

  const drop = async (stage: string) => {
    const id = dragging;
    setDragging(null); setOverStage(null);
    const lead = rows.find((l) => l.id === id);
    if (!lead || lead.stage === stage) return;
    if (stage === "Lost") { setOpened(lead.id); setNotice("Say why it was lost — use the Lost button."); return; }
    try { await api.post(`${API}/${lead.id}/stage`, { stage }); reload(); }
    catch (err) { setNotice(errorText(err, "Could not move the lead.")); }
  };

  const s = summary.data;
  const tile = (icon: React.ReactNode, label: string, value: React.ReactNode, note: React.ReactNode, tone: string) => (
    <div className="rounded-[14px] border border-line bg-surface p-4 shadow-panel">
      <div className="flex items-center gap-2 text-[12px] text-muted">
        <span className={`rounded-lg p-1.5 ${tone}`}>{icon}</span>{label}
      </div>
      <div className="mt-2 text-[22px] font-semibold leading-none">{value}</div>
      <div className="mt-1.5 text-[11.5px] text-muted">{note}</div>
    </div>
  );

  return (
    <AppShell title="Leads">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="m-0 text-[19px] font-semibold">Leads</h1>
          <p className="m-0 text-[12px] text-muted">Every opportunity from first call to order — new prospects and new business with our own customers.</p>
        </div>
        <button onClick={() => { setPreset(undefined); setEditing("new"); }}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary to-primary-dark px-4 py-2 text-[12.8px] font-medium text-on-primary">
          <Plus size={14} strokeWidth={2.4} /> New lead
        </button>
      </div>

      {/* headline figures */}
      <div className="mb-5 grid grid-cols-5 gap-4 max-xl:grid-cols-3 max-md:grid-cols-1">
        {tile(<Target size={14} />, "Open pipeline", `PKR ${compact(s?.pipeline_value ?? 0)}`,
          <>{s?.open_count ?? 0} open lead{(s?.open_count ?? 0) === 1 ? "" : "s"}{s?.other_currencies.length ? ` (+ ${s.other_currencies.join(", ")})` : ""}</>, "bg-sky/10 text-sky")}
        {tile(<Sparkles size={14} />, "Likely to close", `PKR ${compact(s?.weighted_value ?? 0)}`,
          "value weighted by each stage's chance", "bg-violet/10 text-violet")}
        {tile(<Trophy size={14} />, "Won this month", `PKR ${compact(s?.won_month_value ?? 0)}`,
          <>{s?.won_month_count ?? 0} won · {s?.lost_month_count ?? 0} lost</>, "bg-primary/10 text-primary")}
        {tile(<Flame size={14} />, "Win rate", s?.win_rate != null ? `${s.win_rate}%` : "—",
          <>last 90 days · {s?.hot_open ?? 0} hot leads open</>, "bg-amber/10 text-amber")}
        {tile(<AlarmClock size={14} />, "Follow-ups due", (s?.overdue_follow_ups ?? 0) + (s?.today_follow_ups ?? 0),
          <span className={s?.overdue_follow_ups ? "text-rose" : ""}>{s?.overdue_follow_ups ?? 0} overdue · {s?.today_follow_ups ?? 0} today</span>,
          s?.overdue_follow_ups ? "bg-rose/10 text-rose" : "bg-primary/10 text-primary")}
      </div>

      {/* toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <div className="flex overflow-hidden rounded-lg border border-line bg-surface">
          {([["board", <Columns3 key="b" size={14} />, "Board"], ["list", <LayoutList key="l" size={14} />, "List"],
             ["customers", <Users key="c" size={14} />, "Opportunities in our customers"]] as const).map(([v, icon, label]) => (
            <button key={v} onClick={() => setView(v)}
              className={`flex items-center gap-1.5 px-3.5 py-2 text-[12.5px] font-medium ${view === v ? "bg-primary text-on-primary" : "text-muted hover:bg-hover"}`}>
              {icon}{label}
            </button>
          ))}
        </div>
        {view !== "customers" && (
          <>
            <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2">
              <Search size={14} className="text-faint" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Company, contact, city, product…"
                className="w-56 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint" />
            </div>
            {[["Owner", owner, setOwner, (lookups?.users ?? []).map((u) => [u.id, u.name])],
              ["Source", source, setSource, (lookups?.sources ?? []).map((x) => [x.id, x.name])],
              ["Rating", rating, setRating, (lookups?.ratings ?? []).map((r) => [r, r])]].map(([label, value, setter, opts]) => (
              <select key={label as string} value={value as string} onChange={(e) => (setter as (v: string) => void)(e.target.value)}
                className="rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] text-muted outline-none">
                <option value="">All {(label as string).toLowerCase()}s</option>
                {(opts as string[][]).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            ))}
          </>
        )}
      </div>
      {notice && <p className="mb-3 rounded-lg bg-amber/10 px-4 py-2 text-[12.5px] text-amber" onClick={() => setNotice(null)}>{notice}</p>}
      {leads.error && <p className="mb-3 rounded-lg bg-rose/10 px-4 py-2 text-[12.5px] text-rose">{leads.error}</p>}

      {/* board */}
      {view === "board" && (
        <div className="grid grid-cols-4 gap-3 pb-4 max-lg:grid-cols-2 max-sm:grid-cols-1">
          {(lookups?.stages ?? []).map((st) => {
            const items = byStage.get(st.name) ?? [];
            const total = items.filter((l) => l.currency === "PKR").reduce((a, l) => a + l.estimated_value, 0);
            return (
              <div key={st.name}
                onDragOver={(e) => { e.preventDefault(); setOverStage(st.name); }}
                onDragLeave={() => setOverStage((o) => (o === st.name ? null : o))}
                onDrop={() => void drop(st.name)}
                className={`flex min-w-0 flex-col rounded-[14px] border bg-hover/40 transition-colors ${
                  overStage === st.name ? "border-primary bg-primary/5" : "border-line"}`}>
                <div className="px-3 pt-3">
                  <div className={`mb-2 h-1 rounded-full ${STAGE_TONE[st.name]?.bar}`} />
                  <div className="flex items-baseline gap-2">
                    <b className="text-[13px]">{st.name}</b>
                    <span className="rounded-full bg-surface px-2 text-[11px] text-muted">{items.length}</span>
                    <span className="ml-auto text-[11px] text-muted">{st.open ? `${st.probability}%` : st.name === "Won" ? "60 days" : "60 days"}</span>
                  </div>
                  <p className="m-0 mb-2 mt-0.5 text-[11.5px] font-medium text-muted">PKR {compact(total)}</p>
                </div>
                <div className="flex min-h-[120px] flex-col gap-2 px-2.5 pb-3">
                  {items.map((l) => (
                    <button key={l.id} draggable onDragStart={() => setDragging(l.id)} onDragEnd={() => { setDragging(null); setOverStage(null); }}
                      onClick={() => setOpened(l.id)}
                      className={`rounded-xl border bg-surface p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
                        dragging === l.id ? "opacity-40" : ""} ${l.overdue ? "border-rose/40" : "border-line"}`}>
                      <div className="flex items-start gap-2">
                        <span className="flex-1 text-[12.8px] font-semibold leading-snug">{l.company_name}</span>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${RATING_TONE[l.rating]}`}>{l.rating}</span>
                      </div>
                      <p className="m-0 mt-1 line-clamp-2 text-[11.8px] text-muted">{l.title}</p>
                      <div className="mt-2.5 flex items-center gap-2">
                        <span className="text-[12.5px] font-semibold">{l.currency === "PKR" ? "PKR" : l.currency} {compact(l.estimated_value)}</span>
                        {l.is_customer && <span className="rounded bg-primary/10 px-1.5 text-[10px] font-semibold text-primary">customer</span>}
                        <span title={l.owner ?? "Unassigned"}
                          className="ml-auto flex h-6 w-6 items-center justify-center rounded-full bg-primary/15 text-[10px] font-semibold text-primary">
                          {initials(l.owner)}</span>
                      </div>
                      {l.next_follow_up && (
                        <div className={`mt-2 flex items-center gap-1 text-[11px] ${l.overdue ? "font-semibold text-rose" : "text-amber"}`}>
                          <CalendarClock size={11} /> {relDay(l.next_follow_up)}
                        </div>
                      )}
                      {!l.next_follow_up && st.open && (
                        <div className="mt-2 text-[11px] text-faint">No follow-up planned</div>
                      )}
                    </button>
                  ))}
                  {items.length === 0 && <p className="m-0 py-6 text-center text-[11.5px] text-faint">Drop a lead here</p>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* list */}
      {view === "list" && (
        <section className="overflow-hidden rounded-[14px] border border-line bg-surface shadow-panel">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                {["Lead", "Company", "What they want", "Stage", "Rating", "Value", "Next follow-up", "Owner", "Source", "Created"]
                  .map((h, i) => <GridTh key={h} numeric={i === 5}>{h}</GridTh>)}
              </tr></thead>
              <tbody>
                {rows.map((l, i) => (
                  <tr key={l.id} onClick={() => setOpened(l.id)} className={`${gridRowClass(i)} cursor-pointer`}>
                    <td className={gridCellClass(false, "whitespace-nowrap font-medium")}>{l.lead_number}</td>
                    <td className={gridCellClass()}>{l.company_name}
                      <span className="block text-[11px] text-faint">{[l.contact_person, l.city].filter(Boolean).join(" · ")}</span></td>
                    <td className={gridCellClass(false, "max-w-[260px] text-muted")}>{l.title}</td>
                    <td className={gridCellClass()}><span className={`whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-semibold ${STAGE_TONE[l.stage]?.chip}`}>{l.stage}</span></td>
                    <td className={gridCellClass()}><span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${RATING_TONE[l.rating]}`}>{l.rating}</span></td>
                    <td className={gridCellClass(true)}>{l.currency} {money(l.estimated_value)}</td>
                    <td className={gridCellClass(false, `whitespace-nowrap ${l.overdue ? "font-semibold text-rose" : ""}`)}>
                      {l.next_follow_up ? `${fmtDate(l.next_follow_up)} · ${relDay(l.next_follow_up)}` : "—"}</td>
                    <td className={gridCellClass()}>{l.owner ?? "—"}</td>
                    <td className={gridCellClass()}>{l.source ?? "—"}</td>
                    <td className={gridCellClass(false, "whitespace-nowrap")}>{fmtDate(l.lead_date)}</td>
                  </tr>
                ))}
                {!leads.loading && rows.length === 0 && (
                  <tr><td colSpan={10} className="px-5 py-12 text-center text-[12.8px] text-faint">No leads yet — press New lead, or start from Opportunities in our customers.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* our customers gone quiet */}
      {view === "customers" && (
        <section className="overflow-hidden rounded-[14px] border border-line bg-surface shadow-panel">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
            <div>
              <h2 className="m-0 text-[15px] font-semibold">Customers who have stopped ordering</h2>
              <p className="m-0 text-[12px] text-muted">From the sales orders: customers who bought before but not lately — worth a call. Biggest buyers first.</p>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <div className="flex items-center gap-2 rounded-lg border border-line bg-bg px-3 py-2">
                <Search size={14} className="text-faint" />
                <input value={oppSearch} onChange={(e) => setOppSearch(e.target.value)} placeholder="Customer…"
                  className="w-40 border-none bg-transparent text-[12.5px] outline-none" />
              </div>
              <select value={minDays} onChange={(e) => setMinDays(e.target.value)}
                className="rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] outline-none">
                {[["60", "No order in 2 months"], ["90", "No order in 3 months"], ["180", "No order in 6 months"],
                  ["365", "No order in a year"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                {["", "Customer", "City", "Last order", "Quiet for", "Orders", "Total bought (PKR)", "Open leads"]
                  .map((h, i) => <GridTh key={i} numeric={i >= 5}>{h}</GridTh>)}
              </tr></thead>
              <tbody>
                {(opps.data?.items ?? []).map((o, i) => (
                  <tr key={o.customer_id} className={gridRowClass(i)}>
                    <td className={gridCellClass()}>
                      <button onClick={() => { setPreset({ customer_id: o.customer_id, title: "Re-order / new requirement", source_id:
                          lookups?.sources.find((x) => x.name === "Existing Customer")?.id ?? "", rating: "Warm",
                          follow_up_note: `Call — last order ${fmtDate(o.last_order_date)}` }); setEditing("new"); }}
                        className="flex items-center gap-1 whitespace-nowrap rounded-md bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary hover:bg-primary/20">
                        <Plus size={11} /> Lead</button>
                    </td>
                    <td className={gridCellClass(false, "font-medium")}>{o.name}<span className="block text-[11px] text-faint">{o.phone}</span></td>
                    <td className={gridCellClass()}>{o.city ?? "—"}</td>
                    <td className={gridCellClass(false, "whitespace-nowrap")}>{fmtDate(o.last_order_date)}</td>
                    <td className={gridCellClass(false, `whitespace-nowrap ${o.days_since > 365 ? "text-rose" : "text-amber"}`)}>
                      {o.days_since >= 60 ? `${Math.round(o.days_since / 30)} months` : `${o.days_since} days`}</td>
                    <td className={gridCellClass(true)}>{o.orders}</td>
                    <td className={gridCellClass(true, "font-semibold")}>{money(o.total_sales)}</td>
                    <td className={gridCellClass(true)}>{o.open_leads ? <span className="text-primary">{o.open_leads}</span> : "—"}</td>
                  </tr>
                ))}
                {!opps.loading && (opps.data?.items ?? []).length === 0 && (
                  <tr><td colSpan={8} className="px-5 py-12 text-center text-[12.8px] text-faint">Every customer has ordered within this period.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {opps.data && <p className="m-0 border-t border-line px-5 py-3 text-[11.5px] text-faint">{opps.data.total} customers.</p>}
        </section>
      )}

      {opened && (
        <LeadDrawer leadId={opened} lookups={lookups} onClose={() => setOpened(null)} onChanged={reload}
          onEdit={(l) => { setOpened(null); setEditing(l); }} />
      )}
      {editing && (
        <LeadForm lead={editing === "new" ? null : editing} lookups={lookups} customers={customers} preset={preset}
          onClose={() => setEditing(null)}
          onSaved={(l) => { setEditing(null); reload(); opps.reload(); setOpened(l.id); }} />
      )}
    </AppShell>
  );
}
