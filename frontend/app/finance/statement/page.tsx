"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Card, EmptyState, ErrorNote, PageHeader, PartnerPicker, Spinner, filterClass } from "@/components/finance/ui";
import { JournalView } from "@/components/finance/JournalView";
import { ExportButtons } from "@/components/receivables/ExportButtons";
import { api } from "@/lib/api";
import { drcr, errorText, fmtDate, money, moneyOrBlank, useFinanceContext } from "@/lib/finance";

interface Statement {
  customer: { id: string; code: string; name: string; address: string | null; ntn: string | null };
  date_from: string | null; date_to: string | null;
  opening_balance: number; total_debit: number; total_credit: number; closing_balance: number;
  rows: { date: string; journal_id: string; journal_number: string; document_type: string | null; document_id: string | null;
          document: string; reference: string | null; description: string | null; account: string;
          debit: number; credit: number; balance: number }[];
}

const DOC_LINKS: Record<string, string> = {
  SALES_INVOICE: "/finance/invoices?open=", SALES_CREDIT_NOTE: "/finance/credit-notes?open=",
  SALES_DEBIT_NOTE: "/finance/debit-notes?open=", CUSTOMER_RECEIPT: "/finance/receipts?open=",
  OPENING_BALANCE_BATCH: "/finance/opening-balances?batch=",
};

function StatementScreen() {
  const params = useSearchParams();
  const { data: ctx } = useFinanceContext();
  const fy = ctx?.financial_years.find((y) => y.is_current);
  const [customerId, setCustomerId] = useState<string | null>(params.get("customer"));
  const [label, setLabel] = useState<string | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [branch, setBranch] = useState("");
  const [data, setData] = useState<Statement | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [journal, setJournal] = useState<string | null>(null);

  useEffect(() => { if (fy && !from) setFrom(fy.start_date); }, [fy, from]);
  useEffect(() => {
    if (!customerId) { setData(null); return; }
    const qs = new URLSearchParams({ customer_id: customerId });
    if (from) qs.set("date_from", from);
    if (to) qs.set("date_to", to);
    if (branch) qs.set("branch_id", branch);
    setLoading(true);
    setError(null);
    api.get<Statement>(`/ar/statement?${qs}`).then((s) => { setData(s); setLabel(`${s.customer.code} ${s.customer.name}`); })
      .catch((err) => setError(errorText(err, "Could not load the statement."))).finally(() => setLoading(false));
  }, [customerId, from, to, branch]);

  const query = new URLSearchParams([...(customerId ? [["customer_id", customerId]] : []),
    ...(from ? [["date_from", from]] : []), ...(to ? [["date_to", to]] : [])]).toString();

  return (
    <AppShell title="Customer Statement">
      <PageHeader title="Customer Statement" subtitle="From the posted ledger: receivable and advance postings for the customer.">
        {data && <ExportButtons report="statement" query={query} />}
      </PageHeader>
      <Card>
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3.5">
          <div className="w-72"><PartnerPicker role="customer" value={customerId} label={label}
            onChange={(id, l) => { setCustomerId(id); setLabel(l); }} /></div>
          <input type="date" className={filterClass} value={from} onChange={(e) => setFrom(e.target.value)} />
          <input type="date" className={filterClass} value={to} onChange={(e) => setTo(e.target.value)} />
          <select className={filterClass} value={branch} onChange={(e) => setBranch(e.target.value)}>
            <option value="">All branches</option>
            {(ctx?.branches ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <ErrorNote message={error} />
        {!customerId && <EmptyState>Choose a customer.</EmptyState>}
        {loading && <Spinner />}
        {data && !loading && (
          <div className="overflow-x-auto">
            <div className="flex flex-wrap gap-x-8 gap-y-1 px-5 py-3 text-[12.5px]">
              <span><b>{data.customer.name}</b> {data.customer.ntn && <span className="text-muted">NTN {data.customer.ntn}</span>}</span>
              <span className="text-muted">{data.customer.address}</span>
            </div>
            <table className="w-full min-w-[900px] border-collapse text-left">
              <thead><tr className="border-b border-line">
                <GridTh>Date</GridTh><GridTh>Document</GridTh><GridTh>Reference</GridTh><GridTh>Description</GridTh>
                <GridTh numeric>Debit</GridTh><GridTh numeric>Credit</GridTh><GridTh numeric>Balance</GridTh>
              </tr></thead>
              <tbody>
                <tr className="border-b border-line bg-bg/60 text-[12.5px] font-medium">
                  <td className={gridCellClass()} colSpan={6}>Opening balance{data.date_from ? ` at ${fmtDate(data.date_from)}` : ""}</td>
                  <td className={gridCellClass(true)}>{drcr(data.opening_balance)}</td>
                </tr>
                {data.rows.map((r, i) => (
                  <tr key={`${r.journal_id}-${i}`} className={gridRowClass(i)}>
                    <td className={gridCellClass()}>{fmtDate(r.date)}</td>
                    <td className={gridCellClass()}>
                      {r.document_type && DOC_LINKS[r.document_type] && r.document_id
                        ? <Link className="font-medium text-primary hover:underline" href={`${DOC_LINKS[r.document_type]}${r.document_id}`}>{r.document}</Link>
                        : <button className="font-medium text-primary hover:underline" onClick={() => setJournal(r.journal_id)}>{r.document}</button>}
                      {r.account === "Advance" && <span className="ml-1.5 text-[11px] text-faint">advance</span>}
                    </td>
                    <td className={gridCellClass(false, "text-muted")}>{r.reference}</td>
                    <td className={gridCellClass(false, "max-w-[320px] truncate")} title={r.description ?? ""}>{r.description}</td>
                    <td className={gridCellClass(true)}>{moneyOrBlank(r.debit)}</td>
                    <td className={gridCellClass(true)}>{moneyOrBlank(r.credit)}</td>
                    <td className={gridCellClass(true)}>{drcr(r.balance)}</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-line text-[12.5px] font-semibold">
                  <td className={gridCellClass()} colSpan={4}>Closing balance</td>
                  <td className={gridCellClass(true)}>{money(data.total_debit)}</td>
                  <td className={gridCellClass(true)}>{money(data.total_credit)}</td>
                  <td className={gridCellClass(true)}>{drcr(data.closing_balance)}</td>
                </tr>
              </tbody>
            </table>
            <p className="m-0 px-5 py-3 text-[11.5px] text-faint">A credit balance means the customer has paid in advance or holds unapplied credit.</p>
          </div>
        )}
      </Card>
      {journal && <JournalView journalId={journal} onClose={() => setJournal(null)} onOpen={setJournal} />}
    </AppShell>
  );
}

export default function StatementPage() {
  return <Suspense><StatementScreen /></Suspense>;
}
