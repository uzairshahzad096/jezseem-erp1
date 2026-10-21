"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft, BookOpen, CalendarClock, Check, ClipboardList, Cog, FileText, Mail, MapPin, MessageCircle, Pencil,
  Phone, Plus, Printer, Receipt, ShoppingCart, Sparkles, Star, UserPlus, Wallet, Wrench,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ContactForm } from "@/components/crm/ContactForm";
import { ACTIVITY_ICON, LogActivity } from "@/components/crm/LogActivity";
import { LeadDrawer } from "@/components/leads/LeadDrawer";
import { LeadForm } from "@/components/leads/LeadForm";
import { PartnerModal, type Partner } from "@/components/partners/PartnerModal";
import { api } from "@/lib/api";
import { useCustomers } from "@/lib/calibration";
import { SEGMENT_TONE, type Contact, type Customer360 } from "@/lib/crm";
import {
  RATING_TONE, STAGE_TONE, addDays, compact, errorText, fmtDate, money, relDay, timeAgo, useFetch, useLeadLookups,
} from "@/lib/leads";
import { openPdf } from "@/lib/openPdf";

type Tab = "overview" | "sales" | "service" | "people" | "activity";

export default function Customer360Page() {
  const { id } = useParams<{ id: string }>();
  const view = useFetch<Customer360>(`/crm/customers/${id}`);
  const lookups = useLeadLookups();
  const customers = useCustomers();
  const [tab, setTab] = useState<Tab>("overview");
  const [editing, setEditing] = useState(false);
  const [contact, setContact] = useState<Contact | "new" | null>(null);
  const [logging, setLogging] = useState(false);
  const [newLead, setNewLead] = useState(false);
  const [openLead, setOpenLead] = useState<string | null>(null);
  const [closing, setClosing] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);

  const d = view.data;
  if (!d) {
    return <AppShell title="Customer"><p className="text-[13px] text-muted">{view.error ?? "Opening…"}</p></AppShell>;
  }
  const c = d.customer;
  const k = d.kpis;
  const top = Math.max(1, ...d.sales_by_month.map((m) => m.value));
  const todo = d.activities.filter((a) => a.open);
  const phone = c.cell || c.phone;
  const wa = phone ? `https://wa.me/${phone.replace(/\D/g, "").replace(/^0/, "92")}` : null;

  const done = async (activityId: string) => {
    setError(null);
    try {
      await api.post(`/crm/activities/${activityId}/done`, { outcome, next_follow_up_date: next });
      setClosing(null); setOutcome(""); setNext(""); view.reload();
    } catch (err) { setError(errorText(err, "Could not save.")); }
  };

  const tile = (icon: React.ReactNode, label: string, value: React.ReactNode, note: React.ReactNode, tone: string) => (
    <div className="rounded-[14px] border border-line bg-surface p-4 shadow-panel">
      <div className="flex items-center gap-2 text-[12px] text-muted"><span className={`rounded-lg p-1.5 ${tone}`}>{icon}</span>{label}</div>
      <div className="mt-2 text-[20px] font-semibold leading-none">{value}</div>
      <div className="mt-1.5 text-[11.5px] text-muted">{note}</div>
    </div>
  );
  const card = (title: string, icon: React.ReactNode, children: React.ReactNode, action?: React.ReactNode) => (
    <section className="rounded-[14px] border border-line bg-surface shadow-panel">
      <div className="flex items-center gap-2 border-b border-line px-5 py-3">
        <span className="text-muted">{icon}</span><b className="text-[13.5px]">{title}</b>
        <div className="ml-auto">{action}</div>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
  const small = "rounded-lg bg-hover px-2.5 py-1.5 text-[11.5px] font-medium text-muted hover:text-text";
  const empty = (text: string) => <p className="m-0 text-[12.5px] text-faint">{text}</p>;

  const docTable = (rows: Customer360["orders"], kind: "quotation" | "order") => rows.length === 0 ? empty(kind === "order" ? "No sales orders yet." : "No quotations yet.") : (
    <table className="w-full border-collapse text-[12.5px]">
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="border-b border-line last:border-0">
            <td className="py-2 pr-3 font-medium">{r.doc_number}</td>
            <td className="py-2 pr-3 text-muted">{fmtDate(r.doc_date)}</td>
            <td className="py-2 pr-3">{kind === "order" && r.customer_po_number ? <span className="text-muted">PO {r.customer_po_number}</span> : null}
              {kind === "quotation" && r.converted && <span className="rounded bg-primary/10 px-1.5 text-[10.5px] font-semibold text-primary">ordered</span>}</td>
            <td className="py-2 pr-3 text-right tabular-nums">PKR {money(r.net_receivable)}</td>
            <td className="py-2 pr-3 text-muted">{r.status}</td>
            <td className="py-2 text-right">
              {kind === "quotation" && (
                <button onClick={() => openPdf(`/documents/sales/${r.id}/quotation.pdf`)} title="Print"
                  className="rounded-full bg-sky p-1 text-white"><Printer size={11} /></button>)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <AppShell title={c.name}>
      <Link href="/crm/customers" className="mb-3 inline-flex items-center gap-1 text-[12px] text-muted hover:text-primary"><ArrowLeft size={13} /> Customers</Link>

      {/* header */}
      <div className="mb-5 rounded-[16px] border border-line bg-surface p-5 shadow-panel">
        <div className="flex flex-wrap items-start gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-primary-dark text-[20px] font-semibold text-on-primary">
            {c.name.replace(/[^A-Za-z\s]/g, " ").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="m-0 text-[21px] font-semibold">{c.name}</h1>
              <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${SEGMENT_TONE[k.segment]}`}>{k.segment}</span>
              {c.is_supplier && <span className="rounded-md bg-sky/10 px-2 py-0.5 text-[11px] font-semibold text-sky">also a supplier</span>}
              {!c.is_active && <span className="rounded-md bg-rose/10 px-2 py-0.5 text-[11px] font-semibold text-rose">inactive</span>}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-muted">
              <span>{c.code}</span>
              {(c.city || c.address) && <span className="flex items-center gap-1"><MapPin size={12} />{c.city ?? c.address}</span>}
              {phone && <a href={`tel:${phone}`} className="flex items-center gap-1 hover:text-primary"><Phone size={12} />{phone}</a>}
              {wa && <a href={wa} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-primary"><MessageCircle size={12} />WhatsApp</a>}
              {c.email && <a href={`mailto:${c.email}`} className="flex items-center gap-1 hover:text-primary"><Mail size={12} />{c.email}</a>}
              {c.ntn && <span>NTN {c.ntn}</span>}
              {c.payment_terms && <span>Terms: {c.payment_terms}</span>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setLogging(true)} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-[12.5px] font-semibold text-on-primary"><ClipboardList size={14} /> Log activity</button>
            <button onClick={() => setNewLead(true)} className="flex items-center gap-1.5 rounded-lg bg-violet/10 px-3 py-2 text-[12.5px] font-semibold text-violet"><Sparkles size={14} /> New lead</button>
            <Link href="/inventory/transactions/quotations" className="flex items-center gap-1.5 rounded-lg bg-hover px-3 py-2 text-[12.5px] font-medium text-muted hover:text-text"><FileText size={14} /> Quotation</Link>
            <Link href={`/finance/statement?customer=${c.id}`} className="flex items-center gap-1.5 rounded-lg bg-hover px-3 py-2 text-[12.5px] font-medium text-muted hover:text-text"><BookOpen size={14} /> Statement</Link>
            <button onClick={() => setEditing(true)} className="flex items-center gap-1.5 rounded-lg bg-hover px-3 py-2 text-[12.5px] font-medium text-muted hover:text-text"><Pencil size={14} /> Edit</button>
          </div>
        </div>
      </div>

      {/* figures */}
      <div className="mb-5 grid grid-cols-5 gap-4 max-xl:grid-cols-3 max-md:grid-cols-1">
        {tile(<Wallet size={14} />, "Balance", <span className={k.balance > 0 ? "text-rose" : k.balance < 0 ? "text-primary" : ""}>
          PKR {money(Math.abs(k.balance))}{k.balance < 0 ? " Cr" : ""}</span>,
          k.last_receipt_date ? `last paid ${fmtDate(k.last_receipt_date)} · PKR ${money(k.last_receipt_amount)}` : "no receipt yet", "bg-violet/10 text-violet")}
        {tile(<ShoppingCart size={14} />, "Sales — last 12 months", `PKR ${compact(k.sales_12m)}`,
          `PKR ${compact(k.sales_total)} all time`, "bg-primary/10 text-primary")}
        {tile(<Receipt size={14} />, "Orders", k.orders, k.orders ? `average PKR ${compact(k.average_order)} · since ${fmtDate(k.first_order_date)}` : "none yet", "bg-sky/10 text-sky")}
        {tile(<CalendarClock size={14} />, "Last order", k.last_order_date ? fmtDate(k.last_order_date) : "—",
          k.days_since_order != null ? `${k.days_since_order} days ago` : "never ordered", k.segment === "Active" ? "bg-primary/10 text-primary" : "bg-amber/10 text-amber")}
        {tile(<Sparkles size={14} />, "Open opportunities", k.open_leads, k.open_leads ? `PKR ${compact(k.pipeline_value)} in the pipeline` :
          `${k.quotations} quotations${k.quotation_conversion != null ? ` · ${k.quotation_conversion}% ordered` : ""}`, "bg-amber/10 text-amber")}
      </div>

      {/* tabs */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {([["overview", "Overview"], ["sales", `Sales (${k.orders})`], ["service", `Machines & service (${k.machines})`],
           ["people", `Contacts (${d.contacts.length})`], ["activity", `Activity${todo.length ? ` · ${todo.length} to do` : ""}`]] as const)
          .map(([v, l]) => (
            <button key={v} onClick={() => setTab(v)}
              className={`rounded-lg px-3.5 py-2 text-[12.5px] font-medium ${tab === v ? "bg-primary text-on-primary" : "bg-surface text-muted hover:text-text"}`}>{l}</button>
          ))}
      </div>
      {error && <p className="mb-3 rounded-lg bg-rose/10 px-4 py-2 text-[12.5px] text-rose">{error}</p>}

      {tab === "overview" && (
        <div className="grid grid-cols-3 gap-4 max-xl:grid-cols-1">
          <div className="col-span-2 space-y-4 max-xl:col-span-1">
            {card("Sales by month — last 12 months", <ShoppingCart size={15} />, (
              <div className="flex h-44 items-end gap-2">
                {d.sales_by_month.map((m) => (
                  <div key={m.month} className="flex flex-1 flex-col items-center gap-1" title={`${m.month}: PKR ${money(m.value)}`}>
                    <span className="text-[10px] text-muted">{m.value ? compact(m.value) : ""}</span>
                    <div className="w-full rounded-t-md bg-primary/80" style={{ height: `${Math.max(m.value ? 4 : 1, (m.value / top) * 130)}px`, opacity: m.value ? 1 : 0.25 }} />
                    <span className="text-[10px] text-faint">{m.month}</span>
                  </div>
                ))}
              </div>
            ))}
            {card("What they buy most", <Star size={15} />, d.top_products.length === 0 ? empty("Nothing bought yet.") : (
              <div className="space-y-2.5">
                {d.top_products.map((p) => (
                  <div key={p.description} className="text-[12.5px]">
                    <div className="flex gap-3"><span className="flex-1 truncate" title={p.description}>{p.description}</span>
                      <span className="text-muted">{money(p.quantity)} pcs</span><b className="tabular-nums">PKR {compact(p.value)}</b></div>
                    <div className="mt-1 h-1.5 rounded-full bg-hover"><div className="h-full rounded-full bg-sky" style={{ width: `${(p.value / d.top_products[0].value) * 100}%` }} /></div>
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div className="space-y-4">
            {card("To do", <CalendarClock size={15} />, todo.length === 0 ? empty("Nothing planned.") : (
              <div className="space-y-2">
                {todo.map((a) => (
                  <div key={a.id} className={`rounded-lg border p-2.5 text-[12.5px] ${relDay(a.due_date).includes("late") ? "border-rose/40 bg-rose/5" : "border-amber/40 bg-amber/5"}`}>
                    <div className="flex items-start gap-2">
                      <span className="flex-1"><b>{a.activity_type}</b> · {a.summary}
                        <span className="block text-[11px] text-muted">{relDay(a.due_date)}{a.lead_number ? ` · ${a.lead_number}` : ""}{a.contact ? ` · ${a.contact}` : ""}</span></span>
                      {closing !== a.id && <button onClick={() => { setClosing(a.id); setOutcome(""); setNext(""); }} className="rounded-md bg-primary p-1 text-on-primary"><Check size={12} /></button>}
                    </div>
                    {closing === a.id && (
                      <div className="mt-2 space-y-1.5">
                        <input value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder="How did it go?"
                          className="w-full rounded-md border border-line bg-surface px-2 py-1 text-[12px] outline-none" />
                        <div className="flex items-center gap-1.5 text-[11.5px]">
                          <input type="date" value={next} onChange={(e) => setNext(e.target.value)} className="rounded-md border border-line bg-surface px-1.5 py-0.5" />
                          <button onClick={() => setNext(addDays(7))} className="rounded-full bg-surface px-2">+1 week</button>
                          <button onClick={() => void done(a.id)} className="ml-auto rounded-md bg-primary px-2.5 py-0.5 font-semibold text-on-primary">Save</button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ), <button onClick={() => setLogging(true)} className={small}><Plus size={11} className="inline" /> Add</button>)}
            {card("Opportunities", <Sparkles size={15} />, d.leads.length === 0 ? empty("No leads with them yet.") : (
              <div className="space-y-2">
                {d.leads.map((l) => (
                  <button key={l.id} onClick={() => setOpenLead(l.id)} className="w-full rounded-lg border border-line p-2.5 text-left text-[12.5px] hover:border-primary/40">
                    <div className="flex items-center gap-2"><b className="flex-1 truncate">{l.title}</b>
                      <span className={`rounded px-1.5 text-[10.5px] font-semibold ${STAGE_TONE[l.stage]?.chip}`}>{l.stage}</span></div>
                    <div className="mt-0.5 text-[11.5px] text-muted">{l.lead_number} · {l.currency} {compact(l.estimated_value)} ·
                      <span className={`ml-1 rounded px-1 ${RATING_TONE[l.rating]}`}>{l.rating}</span>{l.owner ? ` · ${l.owner}` : ""}</div>
                  </button>
                ))}
              </div>
            ), <button onClick={() => setNewLead(true)} className={small}><Plus size={11} className="inline" /> Lead</button>)}
            {card("People", <UserPlus size={15} />, d.contacts.length === 0 ? empty("No contacts recorded.") : (
              <div className="space-y-2">
                {d.contacts.slice(0, 4).map((p) => (
                  <div key={p.id} className="text-[12.5px]"><b>{p.contact_name}</b>{p.is_primary && <Star size={11} className="ml-1 inline text-amber" />}
                    <span className="block text-[11.5px] text-muted">{[p.title, p.cell || p.phone].filter(Boolean).join(" · ")}</span></div>
                ))}
              </div>
            ), <button onClick={() => setContact("new")} className={small}><Plus size={11} className="inline" /> Contact</button>)}
          </div>
        </div>
      )}

      {tab === "sales" && (
        <div className="grid grid-cols-2 gap-4 max-xl:grid-cols-1">
          {card("Sales orders", <ShoppingCart size={15} />, docTable(d.orders, "order"))}
          {card("Quotations", <FileText size={15} />, docTable(d.quotations, "quotation"))}
          {card("Receipts", <Receipt size={15} />, d.receipts.length === 0 ? empty("No receipts yet.") : (
            <table className="w-full border-collapse text-[12.5px]"><tbody>
              {d.receipts.map((r) => (
                <tr key={r.id} className="border-b border-line last:border-0">
                  <td className="py-2 pr-3 font-medium">{r.receipt_number}</td><td className="py-2 pr-3 text-muted">{fmtDate(r.receipt_date)}</td>
                  <td className="py-2 text-right tabular-nums">PKR {money(r.amount)}</td>
                </tr>))}
            </tbody></table>
          ), <Link href={`/finance/statement?customer=${c.id}`} className={small}>Full statement</Link>)}
          {card("Service invoices", <Wrench size={15} />, d.service_invoices.length === 0 ? empty("No service invoices.") : (
            <table className="w-full border-collapse text-[12.5px]"><tbody>
              {d.service_invoices.map((r) => (
                <tr key={r.id} className="border-b border-line last:border-0">
                  <td className="py-2 pr-3 font-medium">{r.invoice_number}</td><td className="py-2 pr-3 text-muted">{fmtDate(r.invoice_date)}</td>
                  <td className="py-2 pr-3">{r.service_type}</td><td className="py-2 pr-3 text-right tabular-nums">PKR {money(r.net_receivable)}</td>
                  <td className="py-2 text-muted">{r.status}</td>
                </tr>))}
            </tbody></table>
          ), <Link href="/calibration/invoices" className={small}>Invoices</Link>)}
        </div>
      )}

      {tab === "service" && (
        <div className="grid grid-cols-2 gap-4 max-xl:grid-cols-1">
          {card("Machines at this customer", <Cog size={15} />, d.machines.length === 0 ? empty("No machines recorded.") : (
            <table className="w-full border-collapse text-[12.5px]"><tbody>
              {d.machines.map((m) => {
                const due = m.next_calibration ?? m.certificate_expiry;
                return (
                  <tr key={m.id} className="border-b border-line last:border-0">
                    <td className="py-2 pr-3"><b>{m.category}</b><span className="block text-[11px] text-muted">{m.vendor} {m.model}{m.serial_number ? ` · S/N ${m.serial_number}` : ""}</span></td>
                    <td className="py-2 pr-3 text-muted">{m.location ?? ""}</td>
                    <td className="py-2 pr-3 text-muted">{m.status}</td>
                    <td className={`py-2 text-right text-[11.5px] ${due && relDay(due).includes("late") ? "font-semibold text-rose" : "text-muted"}`}>
                      {due ? `calibration ${relDay(due)}` : "no certificate"}</td>
                  </tr>);
              })}
            </tbody></table>
          ), <Link href="/calibration/customer-machines" className={small}>Manage</Link>)}
          {card("Contracts", <ClipboardList size={15} />, d.contracts.length === 0 ? empty("No contracts.") : (
            <table className="w-full border-collapse text-[12.5px]"><tbody>
              {d.contracts.map((x) => (
                <tr key={x.id} className="border-b border-line last:border-0">
                  <td className="py-2 pr-3 font-medium">{x.contract_number}<span className="block text-[11px] font-normal text-muted">{x.contract_type}</span></td>
                  <td className="py-2 pr-3 text-muted">{fmtDate(x.start_date)} – {x.end_date ? fmtDate(x.end_date) : "open"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">PKR {money(x.charge_amount)} / {x.billing_frequency.toLowerCase()}</td>
                  <td className="py-2 text-muted">{x.status}</td>
                </tr>))}
            </tbody></table>
          ), <Link href="/calibration/contracts" className={small}>Contracts</Link>)}
        </div>
      )}

      {tab === "people" && card("Contacts", <UserPlus size={15} />, d.contacts.length === 0 ? empty("No contacts recorded. Add the buyer, the cutting manager and accounts.") : (
        <div className="grid grid-cols-3 gap-3 max-xl:grid-cols-2 max-md:grid-cols-1">
          {d.contacts.map((p) => {
            const w = p.whatsapp || p.cell;
            return (
              <div key={p.id} className={`rounded-xl border p-4 ${p.is_active ? "border-line" : "border-line opacity-50"}`}>
                <div className="flex items-start gap-2">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 text-[12px] font-semibold text-primary">
                    {p.contact_name.split(/\s+/).filter((x) => !/^(mr|mrs|ms|dr)\.?$/i.test(x)).slice(0, 2).map((x) => x[0]).join("").toUpperCase()}</div>
                  <div className="min-w-0 flex-1"><b className="text-[13px]">{p.contact_name}</b>{p.is_primary && <span className="ml-1.5 rounded bg-amber/10 px-1.5 text-[10px] font-semibold text-amber">main</span>}
                    <div className="text-[11.5px] text-muted">{[p.title, p.department].filter(Boolean).join(" · ")}</div></div>
                  <button onClick={() => setContact(p)} className="rounded-md p-1 text-muted hover:bg-hover"><Pencil size={12} /></button>
                </div>
                <div className="mt-3 space-y-1 text-[12px]">
                  {(p.cell || p.phone) && <a href={`tel:${p.cell || p.phone}`} className="flex items-center gap-1.5 hover:text-primary"><Phone size={11} />{p.cell || p.phone}</a>}
                  {w && <a href={`https://wa.me/${w.replace(/\D/g, "").replace(/^0/, "92")}`} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 text-primary"><MessageCircle size={11} />WhatsApp</a>}
                  {p.email && <a href={`mailto:${p.email}`} className="flex items-center gap-1.5 hover:text-primary"><Mail size={11} />{p.email}</a>}
                </div>
              </div>);
          })}
        </div>
      ), <button onClick={() => setContact("new")} className={small}><Plus size={11} className="inline" /> Contact</button>)}

      {tab === "activity" && card("Everything with them", <ClipboardList size={15} />, d.activities.length === 0 ? empty("Nothing logged yet.") : (
        <ol className="relative m-0 list-none border-l border-line pl-5">
          {d.activities.map((a) => (
            <li key={a.id} className="relative mb-4">
              <span className={`absolute -left-[29px] top-0 flex h-[18px] w-[18px] items-center justify-center rounded-full border bg-surface ${a.open ? "border-amber text-amber" : "border-line text-muted"}`}>
                {ACTIVITY_ICON[a.activity_type] ?? <Pencil size={11} />}</span>
              <div className="text-[12.5px]"><b>{a.activity_type}</b> · {a.summary}
                {a.open && <span className="ml-1.5 rounded bg-amber/10 px-1.5 text-[10.5px] font-semibold text-amber">to do {relDay(a.due_date)}</span>}</div>
              {a.outcome && <div className="mt-0.5 text-[12px]">→ {a.outcome}</div>}
              <div className="text-[11px] text-faint">{a.open ? fmtDate(a.due_date) : timeAgo(a.done_at ?? a.activity_at)}
                {a.contact ? ` · with ${a.contact}` : ""}{a.lead_number ? ` · ${a.lead_number}` : ""}{a.created_by ? ` · ${a.created_by}` : ""}</div>
            </li>
          ))}
        </ol>
      ), <button onClick={() => setLogging(true)} className={small}><Plus size={11} className="inline" /> Log</button>)}

      {editing && (
        <PartnerModal open partner={c as unknown as Partner} onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); view.reload(); }} />
      )}
      {contact && (
        <ContactForm contact={contact === "new" ? null : contact} customerId={c.id} onClose={() => setContact(null)}
          onSaved={() => { setContact(null); view.reload(); }} />
      )}
      {logging && <LogActivity customerId={c.id} onClose={() => setLogging(false)} onSaved={() => { setLogging(false); view.reload(); }} />}
      {newLead && (
        <LeadForm lead={null} lookups={lookups} customers={customers}
          preset={{ customer_id: c.id, source_id: lookups?.sources.find((x) => x.name === "Existing Customer")?.id ?? "" }}
          onClose={() => setNewLead(false)} onSaved={(l) => { setNewLead(false); view.reload(); setOpenLead(l.id); }} />
      )}
      {openLead && <LeadDrawer leadId={openLead} lookups={lookups} onClose={() => setOpenLead(null)} onChanged={view.reload}
        onEdit={() => setOpenLead(null)} />}
    </AppShell>
  );
}
