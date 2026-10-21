"use client";

import Link from "next/link";
import { AlarmClock, Banknote, FileWarning, HandCoins, Receipt as ReceiptIcon, TrendingUp, Users, Wallet } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard, type StatTone } from "@/components/dashboard/StatCard";
import { Card, EmptyState, ErrorNote, PageHeader, Spinner } from "@/components/finance/ui";
import { money, useFinance } from "@/lib/finance";

interface Dash {
  as_of: string;
  sales_today: number; sales_this_month: number; outstanding_ar: number; customer_advances: number;
  overdue_ar: number; receipts_today: number; unpaid_invoices: number; partially_paid_invoices: number;
  customers_with_balance: number; customer_count: number;
  top_customers: { customer_id: string | null; customer_name: string; net_sales: number }[];
  top_products: { item_id: string | null; item_code: string | null; description: string; quantity: number; net_sales: number }[];
  sales_by_month: { month: string; net_sales: number }[];
}

export default function ReceivablesDashboard() {
  const { data, loading, error } = useFinance<Dash>("/ar/dashboard");
  const tiles: { label: string; value: string; tone: StatTone; icon: typeof Wallet }[] = data ? [
    { label: "Sales today", value: `PKR ${money(data.sales_today)}`, tone: "green", icon: TrendingUp },
    { label: "Sales this month", value: `PKR ${money(data.sales_this_month)}`, tone: "sky", icon: TrendingUp },
    { label: "Outstanding receivables", value: `PKR ${money(data.outstanding_ar)}`, tone: "violet", icon: HandCoins },
    { label: "Overdue receivables", value: `PKR ${money(data.overdue_ar)}`, tone: "rose", icon: AlarmClock },
    { label: "Receipts today", value: `PKR ${money(data.receipts_today)}`, tone: "green", icon: Banknote },
    { label: "Received, not matched to invoices", value: `PKR ${money(data.customer_advances)}`, tone: "sky", icon: Wallet },
    { label: "Unpaid / partly paid invoices", value: `${data.unpaid_invoices} / ${data.partially_paid_invoices}`, tone: "rose", icon: FileWarning },
    { label: "Customers with a balance", value: `${data.customers_with_balance} of ${data.customer_count}`, tone: "violet", icon: Users },
  ] : [];
  const max = Math.max(1, ...(data?.sales_by_month ?? []).map((m) => Math.abs(m.net_sales)));

  return (
    <AppShell title="Sales & Receivables">
      <PageHeader title="Sales & Receivables" subtitle="Posted transactions only — drafts and confirmed invoices do not count until they post." />
      <ErrorNote message={error} />
      {loading && <Spinner />}
      {data && (
        <>
          <div className="mb-5 grid grid-cols-4 gap-[18px] max-xl:grid-cols-2 max-sm:grid-cols-1">
            {tiles.map((t) => <StatCard key={t.label} label={t.label} value={t.value} tone={t.tone} icon={t.icon} />)}
          </div>
          <div className="grid grid-cols-3 gap-[18px] max-xl:grid-cols-1">
            <Card title="Net sales by month">
              {data.sales_by_month.length === 0 ? <EmptyState>No posted sales yet.</EmptyState> : (
                <ul className="m-0 list-none space-y-1.5 px-5 py-4 text-[12px]">
                  {data.sales_by_month.map((m) => (
                    <li key={m.month} className="flex items-center gap-3">
                      <span className="w-16 text-muted">{m.month}</span>
                      <span className="h-2.5 rounded-full bg-primary/70" style={{ width: `${Math.max(2, (Math.abs(m.net_sales) / max) * 60)}%` }} />
                      <span className="ml-auto tabular-nums">{money(m.net_sales)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Top customers this month" action={<Link href="/finance/ar-reports" className="text-[12px] text-primary hover:underline">Sales summary</Link>}>
              {data.top_customers.length === 0 ? <EmptyState>No posted sales this month.</EmptyState> : (
                <ul className="m-0 list-none p-0 text-[12.5px]">
                  {data.top_customers.map((c) => (
                    <li key={c.customer_id ?? "x"} className="flex border-b border-line px-5 py-2 last:border-0">
                      {c.customer_id ? <Link className="flex-1 hover:text-primary" href={`/finance/statement?customer=${c.customer_id}`}>{c.customer_name}</Link> : <span className="flex-1">{c.customer_name}</span>}
                      <span className="tabular-nums">{money(c.net_sales)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Top products this month">
              {data.top_products.length === 0 ? <EmptyState>No posted sales this month.</EmptyState> : (
                <ul className="m-0 list-none p-0 text-[12.5px]">
                  {data.top_products.map((p) => (
                    <li key={p.item_id ?? "x"} className="flex gap-2 border-b border-line px-5 py-2 last:border-0">
                      <span className="flex-1 truncate">{p.item_code && <span className="text-muted">{p.item_code} · </span>}{p.description}</span>
                      <span className="tabular-nums">{money(p.net_sales)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
          <div className="mt-5 flex flex-wrap gap-2 text-[12.5px]">
            {[["Sales invoices", "/finance/invoices"], ["Payment receipts", "/finance/receipts"], ["Credit notes", "/finance/credit-notes"],
              ["AR aging", "/finance/aging"], ["Customer statement", "/finance/statement"], ["AR reconciliation", "/finance/ar-reconciliation"]]
              .map(([label, href]) => <Link key={href} href={href} className="rounded-lg bg-surface px-3.5 py-2 font-medium text-primary shadow-panel hover:bg-primary/10"><ReceiptIcon size={13} className="mr-1.5 inline" />{label}</Link>)}
          </div>
        </>
      )}
    </AppShell>
  );
}
