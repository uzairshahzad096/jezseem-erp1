"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Card, EmptyState, ErrorNote, PageHeader, Spinner, filterClass } from "@/components/finance/ui";
import { ExportButtons } from "@/components/receivables/ExportButtons";
import { api } from "@/lib/api";
import { errorText, fmtDate, money, moneyOrBlank } from "@/lib/finance";

interface Aging {
  as_of: string;
  labels: string[];
  customers: { customer_id: string; customer_code: string; customer_name: string; buckets: number[];
               on_account: number; credit_balance: number; total_due: number; net: number }[];
  invoices: { customer_id: string; customer_name: string; document_number: string; sales_document_id: string | null;
              item_type: string; document_date: string; due_date: string | null; original: number; paid: number;
              outstanding: number; days_overdue: number; bucket: string }[];
  totals: { buckets: number[]; total_due: number; on_account: number; credit_balance: number; net: number };
}

export default function AgingPage() {
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [view, setView] = useState<"customers" | "invoices">("customers");
  const [customer, setCustomer] = useState<string | null>(null);
  const [data, setData] = useState<Aging | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api.get<Aging>(`/ar/aging?as_of=${asOf}`).then(setData).catch((e) => setError(errorText(e, "Could not load aging.")))
      .finally(() => setLoading(false));
  }, [asOf]);

  const invoices = (data?.invoices ?? []).filter((i) => !customer || i.customer_id === customer);

  return (
    <AppShell title="AR Aging">
      <PageHeader title="Accounts Receivable Aging" subtitle="What each customer still owes, by age. Payments are taken off the oldest invoices first, so every balance equals the customer's ledger.">
        <ExportButtons report="aging" query={`as_of=${asOf}`} />
      </PageHeader>
      <Card>
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3.5">
          <label className="text-[12.5px] text-muted">As at</label>
          <input type="date" className={filterClass} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          {(["customers", "invoices"] as const).map((v) => (
            <button key={v} onClick={() => setView(v)}
              className={`rounded-lg px-3 py-1.5 text-[12.5px] font-medium ${view === v ? "bg-primary/15 text-primary" : "text-muted hover:bg-hover"}`}>
              {v === "customers" ? "By customer" : "By invoice"}
            </button>
          ))}
          {customer && <button className="text-[12px] text-primary hover:underline" onClick={() => setCustomer(null)}>Show all customers</button>}
          {data && <span className="ml-auto text-[12.5px]">Total due <b className="tabular-nums">{money(data.totals.total_due)}</b> · ledger balance <b className="tabular-nums">{money(data.totals.net)}</b></span>}
        </div>
        <ErrorNote message={error} />
        {loading && <Spinner />}
        {data && !loading && (data.customers.length === 0 ? <EmptyState>Nothing outstanding.</EmptyState> : view === "customers" ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                <GridTh>Customer</GridTh>{data.labels.map((l) => <GridTh key={l} numeric>{l}</GridTh>)}
                <GridTh numeric>Total due</GridTh><GridTh numeric>Credit balance</GridTh><GridTh numeric>Ledger balance</GridTh>
              </tr></thead>
              <tbody>
                {data.customers.map((c, i) => (
                  <tr key={c.customer_id} className={gridRowClass(i)}>
                    <td className={gridCellClass()}>
                      <button className="font-medium text-primary hover:underline" onClick={() => { setCustomer(c.customer_id); setView("invoices"); }}>{c.customer_name}</button>
                      <Link className="ml-2 text-[11px] text-muted hover:text-primary hover:underline" href={`/finance/ledger?customer=${c.customer_id}`} title="Open this customer's General Ledger">Ledger</Link>
                    </td>
                    {c.buckets.map((b, n) => <td key={n} className={gridCellClass(true, n >= 3 && b ? "text-rose" : "")}>{moneyOrBlank(b)}</td>)}
                    <td className={gridCellClass(true, "font-medium")}>{money(c.total_due)}</td>
                    <td className={gridCellClass(true, "text-muted")}>{moneyOrBlank(-c.credit_balance)}</td>
                    <td className={gridCellClass(true, "font-semibold")}>{money(c.net)}</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-line text-[12.5px] font-semibold">
                  <td className={gridCellClass()}>Total</td>
                  {data.totals.buckets.map((b, n) => <td key={n} className={gridCellClass(true)}>{money(b)}</td>)}
                  <td className={gridCellClass(true)}>{money(data.totals.total_due)}</td>
                  <td className={gridCellClass(true)}>{money(-data.totals.credit_balance)}</td>
                  <td className={gridCellClass(true)}>{money(data.totals.net)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                <GridTh>Customer</GridTh><GridTh>Document</GridTh><GridTh>Date</GridTh><GridTh>Due</GridTh>
                <GridTh numeric>Original</GridTh><GridTh numeric>Paid</GridTh><GridTh numeric>Outstanding</GridTh>
                <GridTh numeric>Days overdue</GridTh><GridTh>Bucket</GridTh>
              </tr></thead>
              <tbody>
                {invoices.map((i, n) => (
                  <tr key={`${i.document_number}-${n}`} className={gridRowClass(n)}>
                    <td className={gridCellClass()}>{i.customer_name}</td>
                    <td className={gridCellClass()}>
                      {i.sales_document_id ? <Link className="text-primary hover:underline" href={`/finance/${i.item_type === "DEBIT_NOTE" ? "debit-notes" : "invoices"}?open=${i.sales_document_id}`}>{i.document_number}</Link>
                        : <span>{i.document_number} <span className="text-[11px] text-faint">opening</span></span>}
                    </td>
                    <td className={gridCellClass()}>{fmtDate(i.document_date)}</td>
                    <td className={gridCellClass()}>{fmtDate(i.due_date)}</td>
                    <td className={gridCellClass(true)}>{money(i.original)}</td>
                    <td className={gridCellClass(true)}>{money(i.paid)}</td>
                    <td className={gridCellClass(true, "font-medium")}>{money(i.outstanding)}</td>
                    <td className={gridCellClass(true, i.days_overdue > 60 ? "text-rose" : "")}>{i.days_overdue}</td>
                    <td className={gridCellClass(false, "text-muted")}>{i.bucket}</td>
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
