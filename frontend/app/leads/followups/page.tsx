"use client";

import { useState } from "react";
import { AlarmClock, CalendarCheck2, CalendarClock, CalendarDays, Check, ListTodo, Phone } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { LeadDrawer } from "@/components/leads/LeadDrawer";
import { LeadForm } from "@/components/leads/LeadForm";
import { api } from "@/lib/api";
import { useCustomers } from "@/lib/calibration";
import {
  API, RATING_TONE, STAGE_TONE, addDays, errorText, fmtDate, relDay, useFetch, useLeadLookups, type Lead,
} from "@/lib/leads";

interface FollowUp {
  id: string; lead_id: string; lead_number: string; title: string; company_name: string; contact_person: string | null;
  phone: string | null; stage: string; rating: string; activity_type: string; summary: string; due_date: string;
  days_late: number; owner: string | null;
}
type Scope = "due" | "overdue" | "today" | "upcoming" | "all";

export default function FollowUpsPage() {
  const lookups = useLeadLookups();
  const customers = useCustomers();
  const [scope, setScope] = useState<Scope>("due");
  const [owner, setOwner] = useState("");
  const [opened, setOpened] = useState<string | null>(null);
  const [editing, setEditing] = useState<Lead | null>(null);
  const [closing, setClosing] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const list = useFetch<{ items: FollowUp[]; counts: { overdue: number; today: number; upcoming: number } }>(
    `${API}/followups?scope=${scope}${owner ? `&owner_id=${owner}` : ""}`);
  const items = list.data?.items ?? [];
  const c = list.data?.counts;

  const done = async (f: FollowUp) => {
    setBusy(true); setError(null);
    try {
      await api.post(`${API}/activities/${f.id}/done`, { outcome, next_follow_up_date: next, next_follow_up_type: f.activity_type });
      setClosing(null); setOutcome(""); setNext(""); list.reload();
    } catch (err) { setError(errorText(err, "Could not save.")); } finally { setBusy(false); }
  };

  // Grouped by day, so the list reads like a diary.
  const groups = items.reduce<Record<string, FollowUp[]>>((acc, f) => {
    const key = f.days_late > 0 ? "Overdue" : f.due_date;
    (acc[key] ??= []).push(f);
    return acc;
  }, {});

  const tab = (value: Scope, icon: React.ReactNode, label: string, count?: number, tone = "") => (
    <button onClick={() => setScope(value)}
      className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-[12.8px] font-medium transition-colors ${
        scope === value ? "border-primary bg-primary text-on-primary" : "border-line bg-surface text-muted hover:text-text"}`}>
      {icon}{label}
      {count != null && <span className={`rounded-full px-2 text-[11px] ${scope === value ? "bg-white/25" : tone || "bg-hover"}`}>{count}</span>}
    </button>
  );

  return (
    <AppShell title="Follow-ups">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="m-0 text-[19px] font-semibold">Follow-ups</h1>
          <p className="m-0 text-[12px] text-muted">Every promised call, visit and message. Tick it off, say how it went, and plan the next one in one go.</p>
        </div>
        <select value={owner} onChange={(e) => setOwner(e.target.value)}
          className="ml-auto rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] text-muted outline-none">
          <option value="">Everyone</option>
          {(lookups?.users ?? []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select>
      </div>

      <div className="mb-5 flex flex-wrap gap-2">
        {tab("due", <ListTodo size={14} />, "To do now", c ? c.overdue + c.today : undefined, c?.overdue ? "bg-rose/15 text-rose" : "")}
        {tab("overdue", <AlarmClock size={14} />, "Overdue", c?.overdue, c?.overdue ? "bg-rose/15 text-rose" : "")}
        {tab("today", <CalendarCheck2 size={14} />, "Today", c?.today)}
        {tab("upcoming", <CalendarDays size={14} />, "Next 14 days", c?.upcoming)}
        {tab("all", <CalendarClock size={14} />, "All open")}
      </div>
      {error && <p className="mb-3 rounded-lg bg-rose/10 px-4 py-2 text-[12.5px] text-rose">{error}</p>}

      {!list.loading && items.length === 0 && (
        <div className="rounded-[14px] border border-dashed border-line bg-surface px-5 py-16 text-center">
          <CalendarCheck2 size={28} className="mx-auto text-primary" />
          <p className="m-0 mt-3 text-[14px] font-semibold">Nothing waiting</p>
          <p className="m-0 mt-1 text-[12.5px] text-muted">No follow-ups here. Plan the next step on a lead and it shows up in this list.</p>
        </div>
      )}

      {Object.entries(groups).map(([day, fs]) => (
        <section key={day} className="mb-5">
          <h3 className={`m-0 mb-2 text-[12px] font-semibold uppercase tracking-wide ${day === "Overdue" ? "text-rose" : "text-muted"}`}>
            {day === "Overdue" ? "Overdue" : `${fmtDate(day)} · ${relDay(day)}`}
          </h3>
          <div className="grid grid-cols-2 gap-3 max-lg:grid-cols-1">
            {fs.map((f) => (
              <div key={f.id} className={`rounded-[14px] border bg-surface p-4 shadow-panel ${f.days_late ? "border-rose/40" : "border-line"}`}>
                <div className="flex items-start gap-3">
                  <span className={`mt-0.5 rounded-lg p-2 ${f.days_late ? "bg-rose/10 text-rose" : "bg-amber/10 text-amber"}`}>
                    <CalendarClock size={15} /></span>
                  <div className="min-w-0 flex-1">
                    <button onClick={() => setOpened(f.lead_id)} className="text-left text-[13.5px] font-semibold hover:text-primary">{f.company_name}</button>
                    <div className="text-[12.5px]"><b>{f.activity_type}</b> · {f.summary}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                      <span className={`rounded px-1.5 py-0.5 font-semibold ${STAGE_TONE[f.stage]?.chip}`}>{f.stage}</span>
                      <span className={`rounded px-1.5 py-0.5 font-semibold ${RATING_TONE[f.rating]}`}>{f.rating}</span>
                      <span className="text-muted">{f.lead_number} · {f.title}</span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11.5px] text-muted">
                      {f.contact_person && <span>{f.contact_person}</span>}
                      {f.phone && <a href={`tel:${f.phone}`} className="flex items-center gap-1 hover:text-primary"><Phone size={11} />{f.phone}</a>}
                      {f.owner && <span>· {f.owner}</span>}
                      {f.days_late > 0 && <span className="font-semibold text-rose">{f.days_late} days late</span>}
                    </div>
                  </div>
                  {closing !== f.id && (
                    <button onClick={() => { setClosing(f.id); setOutcome(""); setNext(""); }}
                      className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-on-primary">
                      <Check size={13} /> Done</button>
                  )}
                </div>
                {closing === f.id && (
                  <div className="mt-3 space-y-2 rounded-lg bg-hover/60 p-3">
                    <input autoFocus value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder="How did it go?"
                      className="w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary" />
                    <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
                      Next
                      <input type="date" value={next} onChange={(e) => setNext(e.target.value)}
                        className="rounded-md border border-line bg-surface px-2 py-1 text-[12px]" />
                      {[["Tomorrow", 1], ["3 days", 3], ["Next week", 7], ["2 weeks", 14]].map(([l, d]) => (
                        <button key={l} type="button" onClick={() => setNext(addDays(d as number))}
                          className={`rounded-full px-2 py-0.5 text-[11px] ${next === addDays(d as number) ? "bg-primary text-on-primary" : "bg-surface hover:text-text"}`}>{l}</button>
                      ))}
                      <button onClick={() => setClosing(null)} className="ml-auto hover:text-text">Cancel</button>
                      <button disabled={busy} onClick={() => void done(f)}
                        className="rounded-md bg-primary px-3 py-1 font-semibold text-on-primary disabled:opacity-50">Save</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      ))}

      {opened && (
        <LeadDrawer leadId={opened} lookups={lookups} onClose={() => setOpened(null)} onChanged={list.reload}
          onEdit={(l) => { setOpened(null); setEditing(l); }} />
      )}
      {editing && (
        <LeadForm lead={editing} lookups={lookups} customers={customers} onClose={() => setEditing(null)}
          onSaved={(l) => { setEditing(null); list.reload(); setOpened(l.id); }} />
      )}
    </AppShell>
  );
}
