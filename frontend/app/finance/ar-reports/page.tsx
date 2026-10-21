"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Card, EmptyState, ErrorNote, PageHeader, Spinner, filterClass } from "@/components/finance/ui";
import { ExportButtons } from "@/components/receivables/ExportButtons";
import { api } from "@/lib/api";
import { errorText, fmtDate, money } from "@/lib/finance";

const TABS = [
  ["invoices", "Sales Invoice Register"], ["receipts", "Receipts Register"], ["credit-notes", "Credit Note Register"],
  ["debit-notes", "Debit Note Register"], ["balances", "Customer Balances"], ["sales-summary", "Sales Summary"],
] as const;
type Tab = (typeof TABS)[number][0];

const DATE_KEYS = new Set(["doc_date", "due_date", "receipt_date"]);
const TEXT_KEYS = new Set(["doc_number", "receipt_number", "customer", "status", "payment_status", "currency", "journal_number",
  "method", "deposit_account", "reference", "customer_code", "customer_name", "allocation_status"]);

export default function ARReportsPage() {
  const [tab, setTab] = useState<Tab>("invoices");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState("");
  const [data, setData] = useState<{ columns: { key: string; label: string }[]; rows: Record<string, unknown>[] } | null>(null);
  const [summary, setSummary] = useState<{ net_sales: number; by_month: { month: string; net_sales: number }[];
    by_customer: { customer_id: string | null; customer_name: string; net_sales: number }[];
    by_product: { item_code: string | null; description: string; quantity: number; net_sales: number }[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const query = new URLSearchParams([...(from ? [["date_from", from]] : []), ...(to ? [["date_to", to]] : []),
    ...(status ? [["status", status]] : [])]).toString();

  useEffect(() => {
    setLoading(true);
    setError(null);
    const run = async () => {
      if (tab === "sales-summary") {
        setSummary(await api.get(`/ar/sales-summary?${query}`));
      } else if (tab === "balances") {
        const rows = await api.get<Record<string, unknown>[]>("/ar/balances");
        setData({ rows, columns: [
          { key: "customer_code", label: "Code" }, { key: "customer_name", label: "Customer" },
          { key: "invoiced", label: "Invoiced" }, { key: "credit_notes", label: "Credit notes" },
          { key: "receipts", label: "Received" }, { key: "receivable", label: "Receivable" },
          { key: "advances", label: "Advances" }, { key: "net_balance", label: "Net balance" },
          { key: "overdue", label: "Overdue" }, { key: "credit_limit", label: "Credit limit" },
          { key: "available_credit", label: "Available" }] });
      } else {
        setData(await api.get(`/ar/registers/${tab}?${query}`));
      }
    };
    run().catch((e) => setError(errorText(e, "Could not load the report."))).finally(() => setLoading(false));
  }, [tab, query]);

  const cell = (key: string, value: unknown) => {
    if (value == null || value === "") return "";
    if (DATE_KEYS.has(key)) return fmtDate(String(value));
    if (TEXT_KEYS.has(key) || typeof value !== "number") return String(value);
    return money(value);
  };

  return (
    <AppShell title="Receivables Reports">
      <PageHeader title="Receivables Reports" subtitle="Registers list documents with their posting status; totals and sales come from posted entries.">
        <ExportButtons report={tab} query={query} />
      </PageHeader>
      <div className="mb-4 flex flex-wrap gap-1.5">
        {TABS.map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`rounded-lg px-3.5 py-2 text-[12.5px] font-medium ${tab === key ? "bg-primary/15 text-primary" : "bg-surface text-muted hover:text-text"}`}>
            {label}
          </button>
        ))}
      </div>
      <Card>
        {tab !== "balances" && (
          <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3.5">
            <input type="date" className={filterClass} value={from} onChange={(e) => setFrom(e.target.value)} />
            <input type="date" className={filterClass} value={to} onChange={(e) => setTo(e.target.value)} />
            {tab !== "sales-summary" && (
              <select className={filterClass} value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">All statuses</option>
                {(tab === "receipts" ? ["DRAFT", "POSTED", "REVERSED", "CANCELLED"] : ["DRAFT", "CONFIRMED", "POSTED", "CANCELLED"])
                  .map((s) => <option key={s}>{s}</option>)}
              </select>
            )}
          </div>
        )}
        <ErrorNote message={error} />
        {loading && <Spinner />}
        {!loading && tab === "sales-summary" && summary && (
          <div className="grid grid-cols-3 gap-0 max-xl:grid-cols-1">
            <Summary title={`Net sales ${money(summary.net_sales)}`} rows={summary.by_month.map((m) => [m.month, m.net_sales])} />
            <Summary title="By customer" rows={summary.by_customer.map((c) => [
              c.customer_id ? <Link key={c.customer_id} className="hover:text-primary" href={`/finance/statement?customer=${c.customer_id}`}>{c.customer_name}</Link> : c.customer_name,
              c.net_sales])} />
            <Summary title="By product" rows={summary.by_product.map((p) => [`${p.item_code ? p.item_code + " · " : ""}${p.description}`, p.net_sales])} />
          </div>
        )}
        {!loading && tab !== "sales-summary" && data && (data.rows.length === 0 ? <EmptyState>No records.</EmptyState> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                {data.columns.map((c) => <GridTh key={c.key} numeric={!TEXT_KEYS.has(c.key) && !DATE_KEYS.has(c.key)}>{c.label}</GridTh>)}
              </tr></thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={String(r.id ?? r.customer_id ?? i)} className={gridRowClass(i)}>
                    {data.columns.map((c) => (
                      <td key={c.key} className={gridCellClass(!TEXT_KEYS.has(c.key) && !DATE_KEYS.has(c.key))}>{cell(c.key, r[c.key])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </Card>
    </AppShell>
  );
}

function Summary({ title, rows }: { title: string; rows: [React.ReactNode, number][] }) {
  return (
    <div className="border-r border-line last:border-0">
      <div className="border-b border-line px-5 py-3 text-[13px] font-semibold">{title}</div>
      {rows.length === 0 ? <p className="px-5 py-6 text-[12.5px] text-faint">No posted sales in this range.</p> : (
        <ul className="m-0 max-h-[480px] list-none overflow-y-auto p-0 text-[12.5px]">
          {rows.map(([label, value], i) => (
            <li key={i} className="flex gap-3 border-b border-line px-5 py-2 last:border-0">
              <span className="flex-1 truncate">{label}</span><span className="tabular-nums">{money(value)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
