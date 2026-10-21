"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Search, Sparkles, Target, Trophy } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { LeadDrawer } from "@/components/leads/LeadDrawer";
import { LeadForm } from "@/components/leads/LeadForm";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { useCustomers } from "@/lib/calibration";
import {
  RATING_TONE, STAGE_TONE, compact, fmtDate, money, relDay, useFetch, useLeadLookups, type Lead,
} from "@/lib/leads";

/**
 * Opportunities: new business with customers we already have. These are the
 * leads linked to a customer — the same records as on the Leads board, seen
 * customer by customer.
 */
export default function OpportunitiesPage() {
  const lookups = useLeadLookups();
  const customers = useCustomers();
  const [status, setStatus] = useState("open");
  const [search, setSearch] = useState("");
  const [opened, setOpened] = useState<string | null>(null);
  const [editing, setEditing] = useState<Lead | "new" | null>(null);
  const list = useFetch<{ items: Lead[]; total: number }>(
    `/leads?customers_only=true&page_size=2000${status ? `&status=${status}` : ""}${search ? `&search=${encodeURIComponent(search)}` : ""}`);
  const rows = list.data?.items ?? [];

  // Customer by customer: who has the most riding on them.
  const byCustomer = useMemo(() => {
    const map = new Map<string, { id: string; name: string; leads: Lead[]; value: number; weighted: number }>();
    for (const l of rows) {
      const key = l.customer_id ?? l.company_name;
      const g = map.get(key) ?? { id: l.customer_id ?? "", name: l.customer_name ?? l.company_name, leads: [], value: 0, weighted: 0 };
      g.leads.push(l);
      if (l.currency === "PKR") { g.value += l.estimated_value; g.weighted += l.weighted_value; }
      map.set(key, g);
    }
    return [...map.values()].sort((a, b) => b.value - a.value);
  }, [rows]);
  const total = byCustomer.reduce((a, g) => a + g.value, 0);
  const weighted = byCustomer.reduce((a, g) => a + g.weighted, 0);

  return (
    <AppShell title="Opportunities">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="m-0 text-[19px] font-semibold">Opportunities</h1>
          <p className="m-0 text-[12px] text-muted">New business with customers we already have — the same leads as on the Leads board, customer by customer.</p>
        </div>
        <button onClick={() => setEditing("new")}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary to-primary-dark px-4 py-2 text-[12.8px] font-medium text-on-primary">
          <Plus size={14} /> New opportunity</button>
      </div>

      <div className="mb-5 grid grid-cols-3 gap-4 max-md:grid-cols-1">
        {[[<Target key="t" size={14} />, "Customers with opportunities", byCustomer.length, `${rows.length} opportunities`, "bg-sky/10 text-sky"],
          [<Sparkles key="s" size={14} />, "Total value", `PKR ${compact(total)}`, "PKR only", "bg-violet/10 text-violet"],
          [<Trophy key="w" size={14} />, "Likely to close", `PKR ${compact(weighted)}`, "weighted by stage", "bg-primary/10 text-primary"]]
          .map(([icon, label, value, note, tone]) => (
            <div key={label as string} className="rounded-[14px] border border-line bg-surface p-4 shadow-panel">
              <div className="flex items-center gap-2 text-[12px] text-muted"><span className={`rounded-lg p-1.5 ${tone}`}>{icon}</span>{label}</div>
              <div className="mt-2 text-[22px] font-semibold leading-none">{value}</div>
              <div className="mt-1.5 text-[11.5px] text-muted">{note}</div>
            </div>
          ))}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <div className="flex overflow-hidden rounded-lg border border-line bg-surface">
          {[["open", "Open"], ["won", "Won"], ["lost", "Lost"], ["", "All"]].map(([v, l]) => (
            <button key={v} onClick={() => setStatus(v)}
              className={`px-3.5 py-2 text-[12.5px] font-medium ${status === v ? "bg-primary text-on-primary" : "text-muted hover:bg-hover"}`}>{l}</button>
          ))}
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2">
          <Search size={14} className="text-faint" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Customer, product…"
            className="w-56 border-none bg-transparent text-[12.8px] outline-none" />
        </div>
      </div>

      {byCustomer.length === 0 && !list.loading && (
        <div className="rounded-[14px] border border-dashed border-line bg-surface px-5 py-16 text-center">
          <Sparkles size={26} className="mx-auto text-primary" />
          <p className="m-0 mt-3 text-[14px] font-semibold">No opportunities with our customers yet</p>
          <p className="m-0 mt-1 text-[12.5px] text-muted">Start one here, from a customer&apos;s page, or from Leads → Opportunities in our customers.</p>
        </div>
      )}

      <div className="space-y-4">
        {byCustomer.map((g) => (
          <section key={g.id || g.name} className="rounded-[14px] border border-line bg-surface shadow-panel">
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
              {g.id ? <Link href={`/crm/customers/${g.id}`} className="text-[14px] font-semibold hover:text-primary">{g.name}</Link>
                : <b className="text-[14px]">{g.name}</b>}
              <span className="text-[12px] text-muted">{g.leads.length} opportunit{g.leads.length === 1 ? "y" : "ies"}</span>
              <span className="ml-auto text-[13px] font-semibold">PKR {money(g.value)}</span>
            </div>
            <table className="w-full border-collapse text-left">
              <thead><tr className="border-b border-line">
                {["Lead", "What they want", "Stage", "Rating", "Value", "Expected close", "Next follow-up", "Owner"].map((h, i) => <GridTh key={h} numeric={i === 4}>{h}</GridTh>)}
              </tr></thead>
              <tbody>
                {g.leads.map((l, i) => (
                  <tr key={l.id} onClick={() => setOpened(l.id)} className={`${gridRowClass(i)} cursor-pointer`}>
                    <td className={gridCellClass(false, "font-medium")}>{l.lead_number}</td>
                    <td className={gridCellClass(false, "max-w-[280px]")}>{l.title}</td>
                    <td className={gridCellClass()}><span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${STAGE_TONE[l.stage]?.chip}`}>{l.stage}</span></td>
                    <td className={gridCellClass()}><span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${RATING_TONE[l.rating]}`}>{l.rating}</span></td>
                    <td className={gridCellClass(true)}>{l.currency} {money(l.estimated_value)}</td>
                    <td className={gridCellClass()}>{l.expected_close_date ? fmtDate(l.expected_close_date) : "—"}</td>
                    <td className={gridCellClass(false, l.overdue ? "font-semibold text-rose" : "")}>{l.next_follow_up ? relDay(l.next_follow_up) : "—"}</td>
                    <td className={gridCellClass()}>{l.owner ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
      </div>

      {opened && <LeadDrawer leadId={opened} lookups={lookups} onClose={() => setOpened(null)} onChanged={list.reload}
        onEdit={(l) => { setOpened(null); setEditing(l); }} />}
      {editing && (
        <LeadForm lead={editing === "new" ? null : editing} lookups={lookups} customers={customers}
          preset={editing === "new" ? { source_id: lookups?.sources.find((x) => x.name === "Existing Customer")?.id ?? "" } : undefined}
          onClose={() => setEditing(null)} onSaved={(l) => { setEditing(null); list.reload(); setOpened(l.id); }} />
      )}
    </AppShell>
  );
}
