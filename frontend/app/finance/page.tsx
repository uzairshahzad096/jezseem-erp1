"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Banknote, Boxes, Building2, HandCoins, Landmark, Receipt, TrendingDown, TrendingUp,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard, type StatTone } from "@/components/dashboard/StatCard";
import { Card, ErrorNote, PageHeader, Spinner, StatusBadge, filterClass } from "@/components/finance/ui";
import { money, useFinance } from "@/lib/finance";

interface Dashboard {
  as_of: string;
  financial_year: string | null;
  current_period: { id: string; name: string; status: string } | null;
  has_postings: boolean;
  posted_journals: number;
  cash: number; bank: number; receivables: number; payables: number; inventory_value: number;
  revenue: number; expenses: number; profit_loss: number;
  pending: { draft: number; submitted: number; approved_not_posted: number; opening_batches: number };
}

interface SalesRow { sales: number; sales_tax: number; total: number; invoices: number }
interface SalesMonth extends SalesRow { month: string }
interface SalesYear extends SalesRow { id: string; name: string; months: SalesMonth[] }
interface SalesSummary { years: SalesYear[]; totals: SalesRow }

const monthName = (iso: string) =>
  new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", { month: "short", year: "numeric" });

/** Sales from the ledger: one table by financial year, one by month. */
function SalesTables() {
  const { data } = useFinance<SalesSummary>("/finance/sales-summary");
  const [picked, setPicked] = useState("");
  if (!data || data.years.length === 0) return null;
  const year = data.years.find((y) => y.id === picked) ?? data.years[data.years.length - 1];
  const head = "px-5 py-2.5 text-[11.5px] font-semibold text-muted";
  const cell = "px-5 py-2.5 text-[12.8px] tabular-nums";
  const bar = (value: number, top: number) => (
    <div className="h-1.5 w-full rounded-full bg-hover">
      <div className="h-1.5 rounded-full bg-primary" style={{ width: `${top > 0 ? Math.max(0, Math.min(100, (value / top) * 100)) : 0}%` }} />
    </div>
  );
  const table = (rows: (SalesRow & { key: string; label: string })[], total: SalesRow, first: string) => {
    const top = Math.max(...rows.map((r) => r.total), 0);
    return (
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line">
              <th className={`${head} whitespace-nowrap`}>{first}</th><th className={`${head} text-right`}>Invoices</th>
              <th className={`${head} text-right`}>Sales</th><th className={`${head} text-right`}>Sales tax</th>
              <th className={`${head} text-right`}>Total</th><th className={`${head} w-[22%]`} />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-b border-line last:border-0">
                <td className={`${cell} whitespace-nowrap font-medium`}>{r.label}</td>
                <td className={`${cell} text-right text-muted`}>{r.invoices.toLocaleString()}</td>
                <td className={`${cell} text-right`}>{money(r.sales)}</td>
                <td className={`${cell} text-right text-muted`}>{money(r.sales_tax)}</td>
                <td className={`${cell} text-right font-semibold`}>{money(r.total)}</td>
                <td className="px-5">{bar(r.total, top)}</td>
              </tr>
            ))}
            <tr className="border-t-2 border-line">
              <td className={`${cell} font-semibold`}>Total</td>
              <td className={`${cell} text-right font-semibold`}>{total.invoices.toLocaleString()}</td>
              <td className={`${cell} text-right font-semibold`}>{money(total.sales)}</td>
              <td className={`${cell} text-right font-semibold`}>{money(total.sales_tax)}</td>
              <td className={`${cell} text-right font-semibold`}>{money(total.total)}</td><td />
            </tr>
          </tbody>
        </table>
      </div>
    );
  };
  return (
    <div className="mb-5 grid grid-cols-2 gap-[18px] max-xl:grid-cols-1">
      <Card title="Sales by year">
        {table(data.years.map((y) => ({ ...y, key: y.id, label: `FY ${y.name}` })), data.totals, "Financial year")}
      </Card>
      <Card title={`Sales by month — FY ${year.name}`}>
        <div className="border-b border-line px-5 py-2.5">
          <select className={filterClass} value={year.id} onChange={(e) => setPicked(e.target.value)}>
            {data.years.map((y) => <option key={y.id} value={y.id}>FY {y.name}</option>)}
          </select>
        </div>
        {table(year.months.map((m) => ({ ...m, key: m.month, label: monthName(m.month) })), year, "Month")}
      </Card>
    </div>
  );
}

interface LargeBalances {
  minimum: number; total: number;
  customers: { customer_id: string; customer_code: string; customer_name: string; balance: number }[];
}

/** Customers owing 20 lakh or more, largest first: one bar each, scaled to the largest. */
function LargeBalancesChart({ receivables }: { receivables: number }) {
  const { data } = useFinance<LargeBalances>("/ar/large-balances?minimum=2000000");
  const [hover, setHover] = useState<string | null>(null);
  if (!data) return null;
  const top = Math.max(...data.customers.map((c) => c.balance), 0);
  const share = (v: number) => (receivables > 0 ? `${((v / receivables) * 100).toFixed(1)}% of receivables` : "");
  return (
    <Card title="Customers owing PKR 20 lakh or more">
      <div className="border-b border-line px-5 py-2.5 text-[12.5px] text-muted">
        {data.customers.length} customers · together <b className="tabular-nums text-text">PKR {money(data.total)}</b>
        {receivables > 0 && <> · {share(data.total)}</>} · balance from each customer&apos;s General Ledger
      </div>
      {data.customers.length === 0 ? (
        <div className="px-5 py-6 text-[12.8px] text-muted">No customer owes PKR 20 lakh or more.</div>
      ) : (
        <ul className="px-5 py-3">
          {data.customers.map((c) => (
            <li key={c.customer_id} className="relative grid grid-cols-[minmax(0,240px)_1fr_auto] items-center gap-3 py-[3px] max-sm:grid-cols-[1fr_auto]"
              onMouseEnter={() => setHover(c.customer_id)} onMouseLeave={() => setHover(null)}>
              <Link href={`/finance/ledger?customer=${c.customer_id}`} title="Open this customer's General Ledger"
                className="truncate text-[12.5px] font-medium hover:text-primary hover:underline">{c.customer_name}</Link>
              <div className="h-[18px] max-sm:col-span-2 max-sm:row-start-2">
                <div className={`h-full rounded-r-[4px] bg-primary transition-opacity ${hover && hover !== c.customer_id ? "opacity-50" : ""}`}
                  style={{ width: `${top > 0 ? Math.max(1, (c.balance / top) * 100) : 0}%` }} />
              </div>
              <span className="text-right text-[12.5px] font-semibold tabular-nums">{money(c.balance)}</span>
              {hover === c.customer_id && (
                <div className="pointer-events-none absolute right-[120px] top-1/2 z-10 -translate-y-1/2 rounded-lg border border-line bg-surface px-3 py-2 text-[12px] shadow-lg max-sm:left-0">
                  <div className="font-semibold">{c.customer_name}</div>
                  <div className="text-muted">{c.customer_code}</div>
                  <div className="tabular-nums">PKR {money(c.balance)} · {share(c.balance)}</div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const TILES: { key: keyof Dashboard; label: string; tone: StatTone; icon: typeof Banknote }[] = [
  { key: "cash", label: "Cash", tone: "green", icon: Banknote },
  { key: "bank", label: "Bank", tone: "sky", icon: Landmark },
  { key: "receivables", label: "Receivables", tone: "violet", icon: HandCoins },
  { key: "payables", label: "Payables", tone: "rose", icon: Receipt },
  { key: "inventory_value", label: "Inventory value", tone: "sky", icon: Boxes },
  { key: "revenue", label: "Revenue (year to date)", tone: "green", icon: TrendingUp },
  { key: "expenses", label: "Expenses (year to date)", tone: "rose", icon: TrendingDown },
  { key: "profit_loss", label: "Profit / loss (year to date)", tone: "violet", icon: Building2 },
];

const MORE_TILES = "finance-dashboard.more-tiles";


export default function FinanceDashboardPage() {
  const { data, loading, error } = useFinance<Dashboard>("/finance/dashboard");
  // The second row of figures is hidden until asked for; the choice is remembered on this browser.
  const [showAll, setShowAll] = useState(false);
  useEffect(() => {
    try { setShowAll(localStorage.getItem(MORE_TILES) === "1"); } catch { /* storage unavailable */ }
  }, []);
  const toggle = (on: boolean) => {
    setShowAll(on);
    try { localStorage.setItem(MORE_TILES, on ? "1" : "0"); } catch { /* storage unavailable */ }
  };

  return (
    <AppShell title="Finance">
      <PageHeader title="Finance"
        subtitle={data ? `FY ${data.financial_year ?? "—"} · figures from posted journals as of today` : undefined} />
      <ErrorNote message={error} />
      {loading && <Spinner />}

      {data && !data.has_postings && (
        <div className="mb-5 rounded-[14px] border border-amber/40 bg-amber/10 px-5 py-4 text-[12.8px]">
          <b>Nothing has been posted to the ledger yet.</b> The figures below are zero because the
          accounting ledger starts from the accountant-approved opening balances, not from the old
          system&apos;s sales orders or stock counts.{" "}
          <Link href="/finance/opening-balances" className="font-medium text-primary hover:underline">
            Prepare the opening balances →
          </Link>
        </div>
      )}

      {data && (
        <>
          <div className="mb-2 grid grid-cols-4 gap-[18px] max-xl:grid-cols-2 max-sm:grid-cols-1">
            {TILES.slice(0, showAll ? TILES.length : 4).map((t) => (
              <StatCard key={t.key} label={t.label} tone={t.tone} icon={t.icon} roomy
                value={`PKR ${money(data[t.key] as number)}`} />
            ))}
          </div>
          <div className="mb-5 flex justify-end">
            <button className="text-[12.5px] font-medium text-primary hover:underline" onClick={() => toggle(!showAll)}>
              {showAll ? "Hide inventory, revenue, expenses and profit" : "Show inventory, revenue, expenses and profit"}
            </button>
          </div>

          <div className="mb-5"><LargeBalancesChart receivables={data.receivables} /></div>

          <SalesTables />

          <div className="grid grid-cols-2 gap-[18px] max-xl:grid-cols-1">
            <Card title="Current period">
              <div className="space-y-2 px-5 py-4 text-[12.8px]">
                {data.current_period ? (
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{data.current_period.name}</span>
                    <StatusBadge status={data.current_period.status} />
                  </div>
                ) : <p className="m-0 text-faint">No accounting period covers today.</p>}
                <p className="m-0 text-muted">{data.posted_journals} posted journal(s) in the ledger.</p>
                <Link href="/finance/periods" className="text-[12.5px] text-primary hover:underline">Manage periods →</Link>
              </div>
            </Card>
          </div>
        </>
      )}
    </AppShell>
  );
}
