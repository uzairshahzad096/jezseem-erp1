"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowDownRight, ArrowUpRight, Banknote, Boxes, CalendarCheck2, ChevronRight, CircleDollarSign, FileText,
  Eye, HandCoins, Loader2, PackageSearch, Plus, ReceiptText, ShoppingCart, Sparkles, Target, TrendingUp, Users,
} from "lucide-react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Topbar } from "@/components/layout/Topbar";
import { EChart } from "@/components/dashboard/EChart";
import { lineOption } from "@/lib/chartOptions";
import { useTheme } from "@/lib/useTheme";
import { api, clearToken, type DashboardSummary } from "@/lib/api";

interface Simple {
  mode: "simple"; as_of: string; financial_year: string | null; can_see_business: boolean;
  follow_ups: { id: string; activity_type: string; summary: string; due_date: string; overdue: boolean; today: boolean;
                lead_id: string | null; lead_number: string | null; lead_title: string | null; who: string | null;
                customer_id: string | null }[];
  work: { key: string; label: string; count: number; href: string; tone: string }[];
  my_leads: { id: string; lead_number: string; title: string; company_name: string; stage: string; rating: string }[];
  my_leads_count: number; my_hot_leads: number;
  done_recently: { id: string; activity_type: string; summary: string; who: string | null; done_at: string }[];
}

interface Overview {
  mode?: "business";
  as_of: string; financial_year: string | null; fy_start: string;
  kpis: {
    sales_month: number; sales_month_orders: number; sales_month_delta: number | null; sales_last_month: number;
    sales_year: number; sales_year_orders: number; sales_year_delta: number | null; received_month: number;
    receivables: number; cash: number; bank: number; stock_value: number; stock_products: number;
    stock_without_cost: number; pipeline: number; weighted_pipeline: number; open_leads: number;
    customers_month: number; customers_90d: number;
  };
  sales_trend: { month: string; value: number; previous: number }[];
  top_customers: { id: string; name: string; value: number; orders: number }[];
  owing: { id: string; name: string; balance: number }[];
  top_products: { description: string; quantity: number; value: number }[];
  todo: { key: string; label: string; count: number; href: string; tone: string }[];
  recent_orders: { id: string; doc_number: string; doc_date: string; customer: string; customer_id: string; value: number; status: string }[];
  recent_receipts: { id: string; receipt_number: string; receipt_date: string; customer: string; customer_id: string; amount: number }[];
}

/** 4,80,46,530 the way the business says it: 4.8 Cr, 48 Lac. */
const short = (n: number) => {
  const a = Math.abs(n);
  const s = a >= 10000000 ? `${(a / 10000000).toFixed(2)} Cr` : a >= 100000 ? `${(a / 100000).toFixed(1)} Lac`
    : a.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return n < 0 ? `-${s}` : s;
};
const full = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => { const [, m, d] = iso.split("-"); return `${Number(d)} ${MONTHS[Number(m) - 1]}`; };
const TONE: Record<string, string> = {
  rose: "bg-rose/10 text-rose", amber: "bg-amber/10 text-amber", sky: "bg-sky/10 text-sky",
  violet: "bg-violet/10 text-violet", primary: "bg-primary/10 text-primary",
};

export default function DashboardPage() {
  const router = useRouter();
  const { theme, toggle } = useTheme();
  const [navOpen, setNavOpen] = useState(false);
  const [me, setMe] = useState<DashboardSummary | null>(null);
  const [data, setData] = useState<Overview | null>(null);
  const [simple, setSimple] = useState<Simple | null>(null);
  const [staffView, setStaffView] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Loads without a token while AUTH_DISABLED is on; a 401 means sign-in is
    // switched back on, so go to the login page then — not before.
    api.dashboardSummary().then(setMe).catch((err) => {
      if (err?.status === 401) { clearToken(); router.replace("/login"); }
    });
  }, [router]);

  // The server decides which dashboard this user gets; the figures never reach a
  // user who is not allowed them. staffView previews the simple one.
  useEffect(() => {
    // A load still in flight when the view changes must not land on the new view.
    let live = true;
    setData(null); setSimple(null);
    api.get<Overview | Simple>(`/dashboard/overview${staffView ? "?view=simple" : ""}`)
      .then((d) => {
        if (!live) return;
        if ((d as Simple).mode === "simple") { setSimple(d as Simple); setData(null); }
        else { setData(d as Overview); setSimple(null); }
      })
      .catch((err) => { if (live) setError(err?.message ?? "Could not load the dashboard."); });
    return () => { live = false; };
  }, [staffView]);

  const trend = useMemo(() => {
    if (!data) return null;
    const option = lineOption(data.sales_trend.map((m) => m.month), [
      { name: "Last 12 months", data: data.sales_trend.map((m) => m.value) },
      { name: "Year before", data: data.sales_trend.map((m) => m.previous) },
    ]);
    // Crores need room and short labels: "1.5 Cr", "60 Lac".
    const y = option.yAxis as { axisLabel?: Record<string, unknown> };
    y.axisLabel = { ...(y.axisLabel ?? {}), formatter: (v: number) => (v ? short(v) : "0") };
    option.grid = { ...(option.grid as object), left: 66 };
    option.tooltip = { trigger: "axis", valueFormatter: (v) => `PKR ${full(Number(v))}` };
    return option;
  }, [data, theme]);   // eslint-disable-line react-hooks/exhaustive-deps

  const firstName = me?.user_full_name?.split(" ")[0] ?? "";
  const initials = (me?.user_full_name ?? "").split(" ").slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "--";
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const k = data?.kpis;
  const attention = (data?.todo ?? []).filter((t) => t.count > 0);
  const clear = (data?.todo ?? []).filter((t) => t.count === 0);

  return (
    <div className="min-h-screen bg-bg text-text">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      {navOpen && <div onClick={() => setNavOpen(false)} className="fixed inset-0 z-35 bg-black/40 lg:hidden" />}
      <Topbar title="Dashboard" userName={firstName} userInitials={initials}
        onToggleNav={() => setNavOpen((v) => !v)} onToggleTheme={toggle} />

      <main className="px-6 pb-9 pt-[86px] lg:ml-62 max-sm:px-4">
        {/* greeting and quick actions */}
        <div className="mb-6 flex flex-wrap items-end gap-4">
          <div>
            <h2 className="m-0 text-[21px] font-semibold">{greeting}{firstName && `, ${firstName}`}</h2>
            <p className="m-0 mt-0.5 text-[12.8px] text-muted">
              {[me?.company_name, (data ?? simple)?.financial_year && `FY ${(data ?? simple)?.financial_year}`,
                new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })]
                .filter(Boolean).join(" · ")}
            </p>
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            {(data || simple?.can_see_business) && (
              <button onClick={() => setStaffView((v) => !v)}
                title="What employees without the business figures see"
                className="flex items-center gap-1.5 rounded-lg bg-hover px-3 py-2 text-[12.5px] font-medium text-muted hover:text-text">
                <Eye size={13} />{staffView ? "Back to business dashboard" : "Preview staff dashboard"}
              </button>
            )}
            {!simple && [["/inventory/transactions/quotations", <FileText key="q" size={14} />, "Quotation"],
              ["/inventory/transactions/sales-orders", <ShoppingCart key="s" size={14} />, "Sales order"],
              ["/finance/receipts", <HandCoins key="r" size={14} />, "Payment receipt"],
              ["/leads", <Sparkles key="l" size={14} />, "Lead"]].map(([href, icon, label]) => (
              <Link key={href as string} href={href as string}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] font-medium text-muted shadow-sm hover:border-primary/40 hover:text-primary">
                <Plus size={13} />{icon}{label}
              </Link>
            ))}
          </div>
        </div>

        {error && <p className="mb-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>}
        {!data && !simple && !error && <div className="flex justify-center py-24"><Loader2 size={22} className="animate-spin text-primary" /></div>}
        {simple && <StaffDashboard d={simple} />}

        {!simple && data && k && (
          <>
            {/* the three numbers that matter most */}
            <section className="mb-[18px] grid grid-cols-3 gap-[18px] max-[1100px]:grid-cols-2 max-sm:grid-cols-1">
              <Big href="/inventory/reports/product-sales" icon={<ShoppingCart size={18} />} tone="from-primary to-primary-dark"
                label="Sales this month" value={`PKR ${short(k.sales_month)}`}
                delta={k.sales_month_delta} deltaNote="vs same days last month"
                note={`${k.sales_month_orders} orders · last month PKR ${short(k.sales_last_month)}`} />
              <Big href="/finance" icon={<TrendingUp size={18} />} tone="from-sky to-[#2f6fb8]"
                label={`Sales this year${data.financial_year ? ` (FY ${data.financial_year})` : ""}`} value={`PKR ${short(k.sales_year)}`}
                delta={k.sales_year_delta} deltaNote="vs last year to date" note={`${k.sales_year_orders} orders since ${day(data.fy_start)}`} />
              <Big href="/finance/aging" icon={<ReceiptText size={18} />} tone="from-violet to-[#6b3fc9]"
                label="Customers owe us" value={`PKR ${short(k.receivables)}`}
                note={`PKR ${short(k.received_month)} collected this month`} />

            </section>

            <section className="mb-[18px] grid grid-cols-4 gap-[18px] max-[1100px]:grid-cols-2 max-sm:grid-cols-1">
              <Small href="/finance/receipts" icon={<Banknote size={15} />} tone="bg-primary/10 text-primary"
                label="Collected this month" value={`PKR ${short(k.received_month)}`} note="posted payment receipts" />
              <Small href="/inventory/reports/inventory-valuation" icon={<Boxes size={15} />} tone="bg-sky/10 text-sky"
                label="Stock on hand" value={`${k.stock_products} products`}
                note={k.stock_without_cost ? `PKR ${short(k.stock_value)} valued · ${k.stock_without_cost} without a cost yet` : `worth PKR ${short(k.stock_value)}`} />
              <Small href="/leads" icon={<Target size={15} />} tone="bg-violet/10 text-violet"
                label="Sales pipeline" value={`PKR ${short(k.pipeline)}`}
                note={k.open_leads ? `${k.open_leads} open leads · PKR ${short(k.weighted_pipeline)} likely` : "no open leads yet"} />
              <Small href="/crm/customers" icon={<Users size={15} />} tone="bg-amber/10 text-amber"
                label="Customers buying" value={`${k.customers_month} this month`}
                note={`${k.customers_90d} bought in the last 3 months`} />
            </section>

            {/* sales trend and best customers */}
            <section className="mb-[18px] grid grid-cols-[1fr_380px] gap-[18px] max-[1250px]:grid-cols-1">
              <Panel title="Sales — last 12 months" note="from posted sales orders, against the same months a year before">
                {trend && <EChart option={trend} height={290} themeKey={theme} />}
              </Panel>
              <Panel title="Best customers this year" link={["/crm/customers", "All customers"]}>
                <Bars rows={data.top_customers.map((c) => ({ key: c.id, label: c.name, value: c.value, sub: `${c.orders} orders`,
                  href: `/crm/customers/${c.id}` }))} color="bg-primary" />
              </Panel>
            </section>

            {/* what needs doing, and who owes */}
            <section className="mb-[18px] grid grid-cols-[1fr_380px] gap-[18px] max-[1250px]:grid-cols-1">
              <Panel title="Needs attention" note={attention.length ? `${attention.length} things waiting` : "all clear"}>
                {attention.length === 0 ? (
                  <div className="flex items-center gap-3 rounded-xl bg-primary/5 p-4 text-[13px] text-primary">
                    <CalendarCheck2 size={18} /> Nothing waiting — every list is clear.
                  </div>
                ) : (
                  <div className="grid grid-cols-3 gap-3 max-xl:grid-cols-2 max-sm:grid-cols-1">
                    {attention.map((t) => (
                      <Link key={t.key} href={t.href}
                        className="group flex items-center gap-3 rounded-xl border border-line p-3.5 transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
                        <span className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl text-[17px] font-bold ${TONE[t.tone]}`}>{t.count}</span>
                        <span className="flex-1 text-[12.5px] leading-snug">{t.label}</span>
                        <ChevronRight size={14} className="text-faint group-hover:text-primary" />
                      </Link>
                    ))}
                  </div>
                )}
                {clear.length > 0 && (
                  <p className="m-0 mt-3 text-[11.5px] text-faint">Clear: {clear.map((t) => t.label.toLowerCase()).join(" · ")}.</p>
                )}
              </Panel>
              <Panel title="Who owes us most" link={["/finance/aging", "AR aging"]}>
                <Bars rows={data.owing.map((c) => ({ key: c.id, label: c.name, value: c.balance, href: `/crm/customers/${c.id}` }))} color="bg-violet" />
              </Panel>
            </section>

            {/* products, orders, money in */}
            <section className="grid grid-cols-3 gap-[18px] max-[1250px]:grid-cols-1">
              <Panel title="Selling most — last 90 days" link={["/inventory/reports/product-sales", "Product sales"]}>
                {data.top_products.length === 0 ? <Muted text="No sales in the last 90 days." /> : (
                  <ol className="m-0 list-none space-y-2.5 p-0">
                    {data.top_products.map((p, i) => (
                      <li key={p.description} className="flex items-center gap-3 text-[12.5px]">
                        <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-hover text-[11px] font-semibold text-muted">{i + 1}</span>
                        <span className="flex-1 truncate" title={p.description}>{p.description}</span>
                        <span className="text-[11.5px] text-muted">{full(p.quantity)}</span>
                        <b className="w-20 text-right tabular-nums">{short(p.value)}</b>
                      </li>
                    ))}
                  </ol>
                )}
              </Panel>
              <Panel title="Latest sales orders" link={["/inventory/transactions/sales-orders", "All orders"]}>
                <List rows={data.recent_orders.map((o) => ({ key: o.id, title: o.customer, sub: `${o.doc_number} · ${day(o.doc_date)} · ${o.status}`,
                  value: o.value, href: `/crm/customers/${o.customer_id}` }))} icon={<PackageSearch size={13} />} tone="bg-primary/10 text-primary" />
              </Panel>
              <Panel title="Latest payments received" link={["/finance/receipts", "All receipts"]}>
                <List rows={data.recent_receipts.map((r) => ({ key: r.id, title: r.customer, sub: `${r.receipt_number} · ${day(r.receipt_date)}`,
                  value: r.amount, href: `/crm/customers/${r.customer_id}` }))} icon={<CircleDollarSign size={13} />} tone="bg-violet/10 text-violet" />
              </Panel>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function Big({ href, icon, tone, label, value, note, delta, deltaNote }: {
  href: string; icon: React.ReactNode; tone: string; label: string; value: string; note: string;
  delta?: number | null; deltaNote?: string;
}) {
  return (
    <Link href={href} className={`group relative overflow-hidden rounded-[16px] bg-gradient-to-br ${tone} p-5 text-white shadow-panel transition hover:-translate-y-0.5 hover:shadow-lg`}>
      <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-white/10" />
      <div className="flex items-center gap-2 text-[12.5px] text-white/85"><span className="rounded-lg bg-white/20 p-1.5">{icon}</span>{label}</div>
      <div className="mt-3 text-[26px] font-semibold leading-none">{value}</div>
      {delta != null && (
        <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-white/20 px-2 py-0.5 text-[11.5px] font-semibold">
          {delta >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{Math.abs(delta)}% {deltaNote}
        </div>
      )}
      <div className="mt-2 text-[11.5px] text-white/80">{note}</div>
    </Link>
  );
}

function Small({ href, icon, tone, label, value, note }: {
  href: string; icon: React.ReactNode; tone: string; label: string; value: string; note: string;
}) {
  return (
    <Link href={href} className="rounded-[14px] border border-line bg-surface p-4 shadow-panel transition hover:border-primary/40">
      <div className="flex items-center gap-2 text-[12px] text-muted"><span className={`rounded-lg p-1.5 ${tone}`}>{icon}</span>{label}</div>
      <div className="mt-2 text-[19px] font-semibold leading-none">{value}</div>
      <div className="mt-1.5 text-[11.5px] text-muted">{note}</div>
    </Link>
  );
}

function Panel({ title, note, link, children }: { title: string; note?: string; link?: [string, string]; children: React.ReactNode }) {
  return (
    <section className="rounded-[14px] border border-line bg-surface shadow-panel">
      <div className="flex items-baseline gap-3 px-5 pb-1 pt-4">
        <h3 className="m-0 text-[14.5px] font-semibold">{title}</h3>
        {note && <span className="text-[11.5px] text-muted">{note}</span>}
        {link && <Link href={link[0]} className="ml-auto flex items-center gap-0.5 text-[11.5px] font-medium text-primary hover:underline">{link[1]}<ChevronRight size={12} /></Link>}
      </div>
      <div className="px-5 pb-5 pt-3">{children}</div>
    </section>
  );
}

function Bars({ rows, color }: { rows: { key: string; label: string; value: number; sub?: string; href: string }[]; color: string }) {
  if (rows.length === 0) return <Muted text="Nothing to show yet." />;
  const top = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="space-y-3">
      {rows.map((r) => (
        <Link key={r.key} href={r.href} className="block text-[12.5px] hover:text-primary">
          <div className="flex gap-2"><span className="flex-1 truncate" title={r.label}>{r.label}</span>
            {r.sub && <span className="text-[11px] text-muted">{r.sub}</span>}<b className="tabular-nums">{short(r.value)}</b></div>
          <div className="mt-1 h-1.5 rounded-full bg-hover"><div className={`h-full rounded-full ${color}`} style={{ width: `${(r.value / top) * 100}%` }} /></div>
        </Link>
      ))}
    </div>
  );
}

function List({ rows, icon, tone }: { rows: { key: string; title: string; sub: string; value: number; href: string }[]; icon: React.ReactNode; tone: string }) {
  if (rows.length === 0) return <Muted text="Nothing yet." />;
  return (
    <ul className="m-0 list-none space-y-3 p-0">
      {rows.map((r) => (
        <li key={r.key}>
          <Link href={r.href} className="flex items-center gap-3 text-[12.5px] hover:text-primary">
            <span className={`rounded-lg p-1.5 ${tone}`}>{icon}</span>
            <span className="min-w-0 flex-1"><span className="block truncate font-medium">{r.title}</span>
              <span className="block text-[11px] text-muted">{r.sub}</span></span>
            <b className="tabular-nums">{short(r.value)}</b>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Muted({ text }: { text: string }) {
  return <p className="m-0 py-6 text-center text-[12.5px] text-faint">{text}</p>;
}

/** For staff who do not see the business figures: the modules, as tiles — as the
 *  previous ERP's home page laid them out — and nothing else. */
const MODULE_TILES: { href: string; label: string; note: string; color: string; icon: React.ReactNode }[] = [
  { href: "/leads", label: "Leads", note: "Prospects, pipeline and follow-ups", color: "#4F9BDC", icon: <Sparkles size={26} strokeWidth={1.5} /> },
  { href: "/finance", label: "Finance", note: "Accounts, receipts and ledgers", color: "#4BB3CF", icon: <CircleDollarSign size={26} strokeWidth={1.5} /> },
  { href: "/inventory", label: "Inventory", note: "Products, sales, purchasing and stock", color: "#57BFB9", icon: <Boxes size={26} strokeWidth={1.5} /> },
  { href: "/crm/customers", label: "CRM", note: "Customers, contacts and activities", color: "#56AE82", icon: <Users size={26} strokeWidth={1.5} /> },
  { href: "/hrms", label: "HRMS", note: "Employees, attendance, leave and payroll", color: "#8BBE5E", icon: <CalendarCheck2 size={26} strokeWidth={1.5} /> },
  { href: "/calibration", label: "Calibration / Services", note: "Machines, contracts and certificates", color: "#D9C93F", icon: <Target size={26} strokeWidth={1.5} /> },
];

function StaffDashboard({ d: _d }: { d: Simple }) {
  return (
    <section className="grid grid-cols-4 gap-5 max-[1100px]:grid-cols-3 max-md:grid-cols-2 max-sm:grid-cols-1">
      {MODULE_TILES.map((m) => (
        <Link key={m.href} href={m.href}
          className="group overflow-hidden rounded-[6px] bg-surface shadow-[0_2px_6px_rgba(0,0,0,0.12)] transition hover:-translate-y-1 hover:shadow-[0_8px_18px_rgba(0,0,0,0.16)]">
          <div className="flex h-[126px] items-center justify-center" style={{ backgroundColor: m.color }}>
            <span className="flex h-[72px] w-[72px] items-center justify-center rounded-full bg-black/10 text-white transition group-hover:scale-105">{m.icon}</span>
          </div>
          <div className="border-b border-line px-4 py-6 text-center text-[16px] font-semibold">{m.label}</div>
          <div className="px-4 py-4 text-[12.5px] text-muted">{m.note}</div>
        </Link>
      ))}
    </section>
  );
}