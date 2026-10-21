"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Building2, CalendarClock, Check, CheckCircle2, ChevronRight, CircleDollarSign, FileText, Flame, Mail,
  MapPin, MessageCircle, Pencil, Phone, Trash2, Trophy, UserRound, X, XCircle,
} from "lucide-react";
import { PartnerModal } from "@/components/partners/PartnerModal";
import { api } from "@/lib/api";
import {
  API, RATING_TONE, STAGE_TONE, addDays, errorText, fmtDate, money, relDay, timeAgo,
  type Activity, type Lead, type LeadLookups,
} from "@/lib/leads";

const ACTIVITY_ICON: Record<string, React.ReactNode> = {
  Call: <Phone size={13} />, Visit: <MapPin size={13} />, WhatsApp: <MessageCircle size={13} />,
  Email: <Mail size={13} />, Meeting: <UserRound size={13} />, Demo: <Flame size={13} />,
  "Quotation Sent": <FileText size={13} />, Note: <Pencil size={13} />,
};

/** The lead, open on the right: where it stands, what was done, and what is next. */
export function LeadDrawer({ leadId, lookups, onClose, onChanged, onEdit }: {
  leadId: string;
  lookups: LeadLookups | null;
  onClose: () => void;
  onChanged: () => void;
  onEdit: (lead: Lead) => void;
}) {
  const [lead, setLead] = useState<Lead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [losing, setLosing] = useState(false);
  const [lostReason, setLostReason] = useState("");
  const [converting, setConverting] = useState(false);
  const [quotes, setQuotes] = useState<{ id: string; doc_number: string; doc_date: string; status: string; net_receivable: number }[]>([]);

  // composer
  const [type, setType] = useState("Call");
  const [summary, setSummary] = useState("");
  const [plan, setPlan] = useState(false);
  const [due, setDue] = useState(addDays(1));
  const [next, setNext] = useState("");
  // completing a follow-up
  const [closing, setClosing] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("");
  const [closingNext, setClosingNext] = useState("");

  const load = async () => {
    try {
      const l = await api.get<Lead>(`${API}/${leadId}`);
      setLead(l);
      if (l.customer_id) setQuotes((await api.get<{ items: typeof quotes }>(`${API}/${leadId}/quotations`)).items);
      else setQuotes([]);
    } catch (err) { setError(errorText(err, "Could not open the lead.")); }
  };
  useEffect(() => { void load(); }, [leadId]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = async (fn: () => Promise<Lead>) => {
    setBusy(true); setError(null);
    try { setLead(await fn()); onChanged(); return true; }
    catch (err) { setError(errorText(err, "Could not save.")); return false; }
    finally { setBusy(false); }
  };

  const move = (stage: string, reason?: string) => run(() => api.post<Lead>(`${API}/${leadId}/stage`, { stage, lost_reason: reason }));

  const log = async () => {
    if (!summary.trim()) { setError(plan ? "Say what is to be done." : "Say what happened."); return; }
    const ok = await run(() => api.post<Lead>(`${API}/${leadId}/activities`, {
      activity_type: type, summary, due_date: plan ? due : "", next_follow_up_date: plan ? "" : next,
      next_follow_up_type: "Call", next_follow_up_note: next ? "Follow up" : "",
    }));
    if (ok) { setSummary(""); setNext(""); setPlan(false); }
  };

  const complete = async (a: Activity) => {
    const ok = await run(() => api.post<Lead>(`${API}/activities/${a.id}/done`, {
      outcome, next_follow_up_date: closingNext, next_follow_up_type: a.activity_type,
    }));
    if (ok) { setClosing(null); setOutcome(""); setClosingNext(""); }
  };

  const linkQuote = (id: string) => lead && run(() => api.put<Lead>(`${API}/${lead.id}`, {
    ...lead, quotation_id: id, customer_id: lead.customer_id ?? "", source_id: lead.source_id ?? "",
    owner_id: lead.owner_id ?? "", expected_close_date: lead.expected_close_date ?? "",
  }));

  const remove = async () => {
    if (!lead || !confirm(`Delete ${lead.lead_number}?`)) return;
    try { await api.del(`${API}/${lead.id}`); onChanged(); onClose(); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  const openStages = (lookups?.stages ?? []).filter((s) => s.open);
  const closed = lead?.stage === "Won" || lead?.stage === "Lost";
  const openFollowUps = lead?.activities?.filter((a) => a.open) ?? [];
  const history = lead?.activities?.filter((a) => !a.open) ?? [];
  const wa = lead?.phone ? `https://wa.me/${lead.phone.replace(/\D/g, "").replace(/^0/, "92")}` : null;

  return (
    <div className="fixed inset-0 z-[45] flex justify-end bg-black/30" onMouseDown={onClose}>
      <aside className="flex h-full w-full max-w-[640px] flex-col bg-surface shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        {!lead ? (
          <div className="p-8 text-[13px] text-muted">{error ?? "Opening…"}</div>
        ) : (
          <>
            {/* header */}
            <div className="border-b border-line px-6 pb-4 pt-5">
              <div className="flex items-center gap-2 text-[11.5px]">
                <span className="font-semibold text-muted">{lead.lead_number}</span>
                <span className={`rounded-md px-2 py-0.5 font-semibold ${STAGE_TONE[lead.stage]?.chip}`}>{lead.stage}</span>
                <span className={`rounded-md px-2 py-0.5 font-semibold ${RATING_TONE[lead.rating]}`}>{lead.rating}</span>
                {lead.is_customer
                  ? <span className="rounded-md bg-primary/10 px-2 py-0.5 font-semibold text-primary">Our customer</span>
                  : <span className="rounded-md bg-hover px-2 py-0.5 font-semibold text-muted">Prospect</span>}
                <button onClick={onClose} aria-label="Close" className="ml-auto rounded-md p-1 text-muted hover:bg-hover"><X size={18} /></button>
              </div>
              <h2 className="m-0 mt-2 text-[19px] font-semibold leading-tight">
                {lead.customer_id
                  ? <Link href={`/crm/customers/${lead.customer_id}`} className="hover:text-primary hover:underline" title="Open the customer">{lead.company_name}</Link>
                  : lead.company_name}
              </h2>
              <p className="m-0 mt-1 text-[13px] text-muted">{lead.title}</p>

              {/* stage stepper */}
              <div className="mt-4 flex items-center gap-1">
                {openStages.map((s, i) => {
                  const reached = !closed && openStages.findIndex((x) => x.name === lead.stage) >= i;
                  return (
                    <button key={s.name} disabled={busy || lead.stage === s.name} onClick={() => void move(s.name)}
                      title={`Move to ${s.name} (${s.probability}%)`}
                      className={`h-7 flex-1 rounded-md text-[11px] font-semibold transition-colors ${
                        reached ? `${STAGE_TONE[s.name].bar} text-white` : "bg-hover text-muted hover:bg-line"}`}>
                      {s.name}
                    </button>
                  );
                })}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {!closed && (
                  <>
                    <button disabled={busy} onClick={() => void move("Won")}
                      className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-on-primary">
                      <Trophy size={13} /> Won
                    </button>
                    <button disabled={busy} onClick={() => setLosing((v) => !v)}
                      className="flex items-center gap-1.5 rounded-lg bg-rose/10 px-3 py-1.5 text-[12px] font-semibold text-rose">
                      <XCircle size={13} /> Lost
                    </button>
                  </>
                )}
                {closed && (
                  <button disabled={busy} onClick={() => void move("Negotiation")}
                    className="rounded-lg bg-hover px-3 py-1.5 text-[12px] font-medium text-muted">Reopen</button>
                )}
                {!lead.is_customer && (
                  <button onClick={() => setConverting(true)}
                    className="flex items-center gap-1.5 rounded-lg bg-violet/10 px-3 py-1.5 text-[12px] font-semibold text-violet">
                    <Building2 size={13} /> Make them a customer
                  </button>
                )}
                <button onClick={() => onEdit(lead)} className="ml-auto flex items-center gap-1.5 rounded-lg bg-hover px-3 py-1.5 text-[12px] font-medium text-muted hover:text-text">
                  <Pencil size={13} /> Edit
                </button>
                {lead.stage === "New" && (
                  <button onClick={() => void remove()} aria-label="Delete" className="rounded-lg bg-hover px-2.5 py-1.5 text-muted hover:text-rose"><Trash2 size={13} /></button>
                )}
              </div>
              {losing && (
                <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-rose/5 p-3">
                  <span className="text-[12px] text-rose">Why was it lost?</span>
                  <select value={lostReason} onChange={(e) => setLostReason(e.target.value)}
                    className="rounded-md border border-line bg-bg px-2 py-1.5 text-[12.5px]">
                    <option value="">Choose…</option>
                    {(lookups?.lost_reasons ?? []).map((r) => <option key={r}>{r}</option>)}
                  </select>
                  <button disabled={!lostReason || busy}
                    onClick={async () => { if (await move("Lost", lostReason)) { setLosing(false); setLostReason(""); } }}
                    className="rounded-md bg-rose px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-50">Mark lost</button>
                </div>
              )}
              {lead.stage === "Lost" && lead.lost_reason && <p className="m-0 mt-2 text-[12px] text-rose">Lost: {lead.lost_reason}</p>}
              {error && <p className="m-0 mt-3 rounded-lg bg-rose/10 px-3 py-2 text-[12px] text-rose">{error}</p>}
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5">
              {/* facts */}
              <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-[12.5px]">
                <Fact label="Contact" value={[lead.contact_person, lead.designation].filter(Boolean).join(", ")} />
                <Fact label="Phone" value={lead.phone ? (
                  <span className="flex items-center gap-2">
                    <a href={`tel:${lead.phone}`} className="hover:text-primary">{lead.phone}</a>
                    {wa && <a href={wa} target="_blank" rel="noreferrer" className="rounded bg-primary/10 px-1.5 text-[10.5px] font-semibold text-primary">WhatsApp</a>}
                  </span>) : null} />
                <Fact label="Email" value={lead.email ? <a href={`mailto:${lead.email}`} className="hover:text-primary">{lead.email}</a> : null} />
                <Fact label="City" value={lead.city} />
                <Fact label="Interested in" value={lead.interest} />
                <Fact label="Source" value={lead.source} />
                <Fact label="Owner" value={lead.owner} />
                <Fact label="Expected to close" value={lead.expected_close_date ? `${fmtDate(lead.expected_close_date)} (${relDay(lead.expected_close_date)})` : null} />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-hover/60 p-3">
                  <p className="m-0 flex items-center gap-1.5 text-[11px] text-muted"><CircleDollarSign size={12} /> Estimated value</p>
                  <p className="m-0 mt-1 text-[17px] font-semibold">{lead.currency} {money(lead.estimated_value)}</p>
                </div>
                <div className="rounded-xl bg-hover/60 p-3">
                  <p className="m-0 text-[11px] text-muted">Weighted at {lead.probability}%</p>
                  <p className="m-0 mt-1 text-[17px] font-semibold text-primary">{lead.currency} {money(lead.weighted_value)}</p>
                </div>
              </div>

              {/* quotation */}
              {lead.is_customer && (
                <div className="mt-4 rounded-xl border border-line p-3 text-[12.5px]">
                  <div className="flex items-center gap-2">
                    <FileText size={14} className="text-muted" />
                    <b>Quotation</b>
                    {lead.quotation ? (
                      <span className="ml-auto">{lead.quotation.doc_number} · {fmtDate(lead.quotation.doc_date)} · PKR {money(lead.quotation.net_receivable)} · {lead.quotation.status}</span>
                    ) : quotes.length ? (
                      <select className="ml-auto max-w-[60%] rounded-md border border-line bg-bg px-2 py-1 text-[12px]" value=""
                        onChange={(e) => e.target.value && void linkQuote(e.target.value)}>
                        <option value="">Link one of their quotations…</option>
                        {quotes.map((q) => <option key={q.id} value={q.id}>{q.doc_number} · {fmtDate(q.doc_date)} · PKR {money(q.net_receivable)}</option>)}
                      </select>
                    ) : <span className="ml-auto text-faint">None yet</span>}
                  </div>
                  <Link href="/inventory/transactions/quotations" className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline">
                    Make a quotation <ChevronRight size={12} />
                  </Link>
                </div>
              )}

              {/* composer */}
              {!closed && (
                <div className="mt-5 rounded-xl border border-line">
                  <div className="flex flex-wrap gap-1.5 border-b border-line px-3 pt-3 pb-2.5">
                    {(lookups?.activity_types ?? []).map((t) => (
                      <button key={t} type="button" onClick={() => setType(t)}
                        className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-[11.5px] font-medium ${
                          type === t ? "bg-primary text-on-primary" : "bg-hover text-muted hover:text-text"}`}>
                        {ACTIVITY_ICON[t]} {t}
                      </button>
                    ))}
                  </div>
                  <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={2}
                    placeholder={plan ? "What is to be done…" : "What happened — who you spoke to, what they said…"}
                    className="w-full resize-none border-none bg-transparent px-3 py-2.5 text-[13px] outline-none placeholder:text-faint" />
                  <div className="flex flex-wrap items-center gap-3 border-t border-line px-3 py-2.5 text-[12px]">
                    <label className="flex items-center gap-1.5 text-muted">
                      <input type="checkbox" checked={plan} onChange={(e) => setPlan(e.target.checked)} /> Plan it for later
                    </label>
                    {plan ? (
                      <input type="date" value={due} onChange={(e) => setDue(e.target.value)}
                        className="rounded-md border border-line bg-bg px-2 py-1 text-[12px]" />
                    ) : (
                      <label className="flex items-center gap-1.5 text-muted">
                        Next follow-up
                        <input type="date" value={next} onChange={(e) => setNext(e.target.value)}
                          className="rounded-md border border-line bg-bg px-2 py-1 text-[12px]" />
                      </label>
                    )}
                    <button disabled={busy} onClick={() => void log()}
                      className="ml-auto rounded-lg bg-primary px-3.5 py-1.5 text-[12px] font-semibold text-on-primary disabled:opacity-50">
                      {plan ? "Add follow-up" : "Log it"}
                    </button>
                  </div>
                </div>
              )}

              {/* open follow-ups */}
              {openFollowUps.length > 0 && (
                <div className="mt-5">
                  <p className="m-0 mb-2 text-[11.5px] font-semibold uppercase tracking-wide text-muted">To do</p>
                  {openFollowUps.map((a) => {
                    const late = a.due_date && relDay(a.due_date).includes("late");
                    return (
                      <div key={a.id} className={`mb-2 rounded-xl border p-3 ${late ? "border-rose/40 bg-rose/5" : "border-amber/40 bg-amber/5"}`}>
                        <div className="flex items-start gap-2.5 text-[12.5px]">
                          <span className={`mt-0.5 rounded-md p-1 ${late ? "bg-rose/15 text-rose" : "bg-amber/15 text-amber"}`}>
                            <CalendarClock size={13} /></span>
                          <div className="flex-1">
                            <b>{a.activity_type}</b> · {a.summary}
                            <div className={`text-[11.5px] ${late ? "text-rose" : "text-amber"}`}>
                              {fmtDate(a.due_date)} — {relDay(a.due_date)}{a.owner ? ` · ${a.owner}` : ""}</div>
                          </div>
                          {closing !== a.id && (
                            <button onClick={() => { setClosing(a.id); setOutcome(""); setClosingNext(""); }}
                              className="flex items-center gap-1 rounded-lg bg-primary px-2.5 py-1 text-[11.5px] font-semibold text-on-primary">
                              <Check size={12} /> Done
                            </button>
                          )}
                        </div>
                        {closing === a.id && (
                          <div className="mt-2.5 space-y-2">
                            <input value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder="How did it go?"
                              className="w-full rounded-md border border-line bg-bg px-2.5 py-1.5 text-[12.5px] outline-none focus:border-primary" />
                            <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
                              Next follow-up
                              <input type="date" value={closingNext} onChange={(e) => setClosingNext(e.target.value)}
                                className="rounded-md border border-line bg-bg px-2 py-1 text-[12px]" />
                              {[["Tomorrow", 1], ["In 3 days", 3], ["Next week", 7]].map(([l, d]) => (
                                <button key={l} type="button" onClick={() => setClosingNext(addDays(d as number))}
                                  className="rounded-full bg-hover px-2 py-0.5 text-[11px] hover:text-text">{l}</button>
                              ))}
                              <button onClick={() => setClosing(null)} className="ml-auto text-[11.5px] hover:text-text">Cancel</button>
                              <button disabled={busy} onClick={() => void complete(a)}
                                className="rounded-md bg-primary px-3 py-1 text-[11.5px] font-semibold text-on-primary">Save</button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* timeline */}
              <p className="m-0 mb-2 mt-5 text-[11.5px] font-semibold uppercase tracking-wide text-muted">History</p>
              <ol className="relative m-0 list-none border-l border-line pl-5">
                {history.map((a) => (
                  <li key={a.id} className="relative mb-4">
                    <span className="absolute -left-[29px] top-0 flex h-[18px] w-[18px] items-center justify-center rounded-full border border-line bg-surface text-muted">
                      {a.is_follow_up ? <CheckCircle2 size={11} className="text-primary" /> : (ACTIVITY_ICON[a.activity_type] ?? <Pencil size={11} />)}
                    </span>
                    <div className="text-[12.5px]"><b>{a.activity_type}</b> · {a.summary}</div>
                    {a.outcome && <div className="mt-0.5 text-[12px] text-text/80">→ {a.outcome}</div>}
                    <div className="text-[11px] text-faint">{timeAgo(a.done_at ?? a.activity_at)}{a.created_by ? ` · ${a.created_by}` : ""}</div>
                  </li>
                ))}
              </ol>
            </div>
          </>
        )}
      </aside>

      {converting && lead && (
        <div onMouseDown={(e) => e.stopPropagation()}>
          <PartnerModal open partner={null}
            prefill={{ name: lead.company_name, phone: lead.phone ?? "", email: lead.email ?? "",
                       city: lead.city ?? "", address: lead.address ?? "" }}
            onClose={() => setConverting(false)}
            onSaved={async (p) => {
              setConverting(false);
              await run(() => api.post<Lead>(`${API}/${lead.id}/customer`, { customer_id: p.id }));
            }} />
        </div>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="m-0 text-[11px] text-muted">{label}</p>
      <div className="mt-0.5 font-medium">{value || <span className="font-normal text-faint">—</span>}</div>
    </div>
  );
}
