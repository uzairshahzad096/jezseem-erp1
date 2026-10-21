"use client";

import { useState } from "react";
import { ArrowRightLeft, UserRound } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { LeadDrawer } from "@/components/leads/LeadDrawer";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { api } from "@/lib/api";
import {
  API, RATING_TONE, STAGE_TONE, compact, errorText, initials, money, relDay, useFetch, useLeadLookups, type Lead,
} from "@/lib/leads";

interface Owner {
  owner_id: string | null; owner: string; open: number; hot: number; pipeline_value: number;
  won: number; lost: number; win_rate: number | null; overdue_follow_ups: number;
}

export default function AssignmentsPage() {
  const lookups = useLeadLookups();
  const owners = useFetch<{ items: Owner[] }>(`${API}/assignments`);
  const [selected, setSelected] = useState<string>("");            // owner id, or "none" for unassigned
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  const leads = useFetch<{ items: Lead[] }>(selected
    ? `${API}?status=open&page_size=2000${selected === "none" ? "" : `&owner_id=${selected}`}` : null);
  const shown = (leads.data?.items ?? []).filter((l) => selected !== "none" || !l.owner_id);
  const top = Math.max(1, ...(owners.data?.items ?? []).map((o) => o.pipeline_value));

  const reassign = async () => {
    if (!picked.size) return;
    setBusy(true); setError(null);
    try {
      await api.post(`${API}/reassign`, { lead_ids: [...picked], owner_id: target || null, move_follow_ups: true });
      setPicked(new Set()); owners.reload(); leads.reload();
    } catch (err) { setError(errorText(err, "Could not reassign.")); } finally { setBusy(false); }
  };

  return (
    <AppShell title="Lead Assignments">
      <div className="mb-5">
        <h1 className="m-0 text-[19px] font-semibold">Assignments</h1>
        <p className="m-0 text-[12px] text-muted">Who is working on what: each salesperson&apos;s open leads, what they are worth, and follow-ups gone overdue. Pick someone to see and hand over their leads.</p>
      </div>

      <div className="mb-5 grid grid-cols-3 gap-4 max-xl:grid-cols-2 max-md:grid-cols-1">
        {(owners.data?.items ?? []).map((o) => {
          const key = o.owner_id ?? "none";
          return (
            <button key={key} onClick={() => { setSelected(key); setPicked(new Set()); }}
              className={`rounded-[14px] border bg-surface p-4 text-left shadow-panel transition ${
                selected === key ? "border-primary ring-2 ring-primary/20" : "border-line hover:border-primary/40"}`}>
              <div className="flex items-center gap-3">
                <span className={`flex h-9 w-9 items-center justify-center rounded-full text-[12px] font-semibold ${
                  o.owner_id ? "bg-primary/15 text-primary" : "bg-hover text-muted"}`}>
                  {o.owner_id ? initials(o.owner) : <UserRound size={15} />}</span>
                <div>
                  <b className="text-[13.5px]">{o.owner}</b>
                  <div className="text-[11.5px] text-muted">{o.open} open · {o.hot} hot · {o.won} won{o.win_rate != null ? ` · ${o.win_rate}% win rate` : ""}</div>
                </div>
                {o.overdue_follow_ups > 0 && (
                  <span className="ml-auto rounded-full bg-rose/10 px-2 py-0.5 text-[11px] font-semibold text-rose">{o.overdue_follow_ups} overdue</span>
                )}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-hover">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${(o.pipeline_value / top) * 100}%` }} />
                </div>
                <span className="text-[12px] font-semibold">PKR {compact(o.pipeline_value)}</span>
              </div>
            </button>
          );
        })}
      </div>

      {selected && (
        <section className="rounded-[14px] border border-line bg-surface shadow-panel">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
            <b className="text-[14px]">Open leads — {(owners.data?.items ?? []).find((o) => (o.owner_id ?? "none") === selected)?.owner}</b>
            <span className="text-[12px] text-muted">{picked.size} selected</span>
            <div className="ml-auto flex items-center gap-2">
              <ArrowRightLeft size={14} className="text-muted" />
              <select value={target} onChange={(e) => setTarget(e.target.value)}
                className="rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] outline-none">
                <option value="">Unassigned</option>
                {(lookups?.users ?? []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
              <button disabled={!picked.size || busy} onClick={() => void reassign()}
                className="rounded-lg bg-primary px-3.5 py-2 text-[12.5px] font-semibold text-on-primary disabled:opacity-40">
                Hand over {picked.size || ""}</button>
            </div>
          </div>
          {error && <p className="m-4 rounded-lg bg-rose/10 px-4 py-2 text-[12.5px] text-rose">{error}</p>}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                <GridTh>
                  <input type="checkbox" checked={shown.length > 0 && picked.size === shown.length}
                    onChange={(e) => setPicked(e.target.checked ? new Set(shown.map((l) => l.id)) : new Set())} />
                </GridTh>
                {["Lead", "Company", "Stage", "Rating", "Value", "Next follow-up"].map((h, i) => <GridTh key={h} numeric={i === 4}>{h}</GridTh>)}
              </tr></thead>
              <tbody>
                {shown.map((l, i) => (
                  <tr key={l.id} className={gridRowClass(i)}>
                    <td className={gridCellClass()}>
                      <input type="checkbox" checked={picked.has(l.id)} onChange={(e) => setPicked((s) => {
                        const n = new Set(s); if (e.target.checked) n.add(l.id); else n.delete(l.id); return n; })} />
                    </td>
                    <td className={gridCellClass(false, "font-medium")}>
                      <button onClick={() => setOpened(l.id)} className="hover:text-primary">{l.lead_number}</button></td>
                    <td className={gridCellClass()}>{l.company_name}<span className="block text-[11px] text-faint">{l.title}</span></td>
                    <td className={gridCellClass()}><span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${STAGE_TONE[l.stage]?.chip}`}>{l.stage}</span></td>
                    <td className={gridCellClass()}><span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${RATING_TONE[l.rating]}`}>{l.rating}</span></td>
                    <td className={gridCellClass(true)}>{l.currency} {money(l.estimated_value)}</td>
                    <td className={gridCellClass(false, l.overdue ? "font-semibold text-rose" : "")}>{l.next_follow_up ? relDay(l.next_follow_up) : "—"}</td>
                  </tr>
                ))}
                {!leads.loading && shown.length === 0 && (
                  <tr><td colSpan={7} className="px-5 py-10 text-center text-[12.5px] text-faint">No open leads.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {opened && (
        <LeadDrawer leadId={opened} lookups={lookups} onClose={() => setOpened(null)}
          onChanged={() => { owners.reload(); leads.reload(); }} onEdit={() => setOpened(null)} />
      )}
    </AppShell>
  );
}
