"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CheckCircle2, AlertTriangle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Button, Card, EmptyState, ErrorNote, PageHeader, Spinner, filterClass } from "@/components/finance/ui";
import { api } from "@/lib/api";
import { download, errorText, fmtDate, money, moneyOrBlank, useFinance, useFinanceContext } from "@/lib/finance";

interface Row {
  account_id: string; account_code: string; account_name: string; account_type: string;
  account_type_name: string; opening_debit: number; opening_credit: number;
  period_debit: number; period_credit: number; closing_debit: number; closing_credit: number;
  debit: number; credit: number; balance: number;
  /** Set on a customer's row when customers are shown in detail. */
  customer_id?: string | null; sub_group?: string; is_subtotal?: boolean;
}
interface TB {
  date_from: string | null; date_to: string | null; rows: Row[];
  totals: Record<string, number>; is_balanced: boolean; difference: number;
}
interface Year { id: string; name: string; is_current: boolean; periods: { id: string; name: string }[] }

export default function TrialBalancePage() {
  const { data: ctx } = useFinanceContext();
  const { data: years } = useFinance<Year[]>("/finance/financial-years");
  const [fy, setFy] = useState("");
  const [period, setPeriod] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [branch, setBranch] = useState("");
  const [detailed, setDetailed] = useState(true);
  const [includeZero, setIncludeZero] = useState(false);
  // As on the previous ERP: each customer on its own line instead of the receivable and advance accounts.
  const [byCustomer, setByCustomer] = useState(true);
  const [tb, setTb] = useState<TB | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fy && years?.length) setFy((years.find((y) => y.is_current) ?? years[0]).id);
  }, [years, fy]);

  const qs = useMemo(() => {
    const q = new URLSearchParams();
    if (period) q.set("period_id", period);
    else if (fy) q.set("financial_year_id", fy);
    if (from) q.set("date_from", from);
    if (to) q.set("date_to", to);
    if (branch) q.set("branch_id", branch);
    if (byCustomer) q.set("by_customer", "true");
    return q;
  }, [fy, period, from, to, branch, byCustomer]);

  useEffect(() => {
    if (!fy && !from && !to) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const q = new URLSearchParams(qs);
        if (includeZero) q.set("include_zero", "true");
        const data = await api.get<TB>(`/finance/trial-balance?${q}`);
        if (!cancelled) setTb(data);
      } catch (err) {
        if (!cancelled) setError(errorText(err, "Could not load the trial balance."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [qs, includeZero, fy, from, to]);

  const exportAs = async (format: string) => {
    try {
      const q = new URLSearchParams(qs);
      q.set("format", format);
      await download(`/finance/trial-balance/export?${q}`, `trial-balance.${format}`);
    } catch (err) { setError(errorText(err, "Export failed.")); }
  };

  const ledgerLink = (accountId: string) => {
    const q = new URLSearchParams({ account: accountId });
    if (fy) q.set("fy", fy);
    if (period) q.set("period", period);
    if (from) q.set("from", from);
    if (to) q.set("to", to);
    if (branch) q.set("branch", branch);
    return `/finance/ledger?${q}`;
  };

  const periods = years?.find((y) => y.id === fy)?.periods ?? [];
  const groups = useMemo(() => {
    const out: { type: string; rows: Row[] }[] = [];
    for (const r of tb?.rows ?? []) {
      const last = out[out.length - 1];
      if (last && last.type === r.account_type_name) last.rows.push(r);
      else out.push({ type: r.account_type_name, rows: [r] });
    }
    return out;
  }, [tb]);

  const t = tb?.totals ?? {};
  const cols = detailed ? 8 : 4;

  return (
    <AppShell title="Trial Balance">
      <PageHeader title="Trial Balance"
        subtitle={tb ? `${ctx?.company.name ?? ""} · ${tb.date_from ? fmtDate(tb.date_from) : "start"} to ${tb.date_to ? fmtDate(tb.date_to) : "today"} · ${ctx?.company.currency ?? "PKR"}` : "From posted journals only."}>
        {tb && ["xlsx", "pdf", "csv"].map((f) => <Button key={f} onClick={() => exportAs(f)}>{f.toUpperCase()}</Button>)}
      </PageHeader>

      <Card>
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3.5">
          <select className={filterClass} value={fy} onChange={(e) => { setFy(e.target.value); setPeriod(""); }}>
            <option value="">All years</option>
            {(years ?? []).map((y) => <option key={y.id} value={y.id}>FY {y.name}</option>)}
          </select>
          <select className={filterClass} value={period} onChange={(e) => setPeriod(e.target.value)} disabled={!fy}>
            <option value="">Whole year</option>
            {periods.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input type="date" className={filterClass} value={from} onChange={(e) => setFrom(e.target.value)} title="From" />
          <input type="date" className={filterClass} value={to} onChange={(e) => setTo(e.target.value)} title="To" />
          <select className={filterClass} value={branch} onChange={(e) => setBranch(e.target.value)}>
            <option value="">All branches</option>
            {(ctx?.branches ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-[12.5px] text-muted">
            <input type="checkbox" checked={detailed} onChange={(e) => setDetailed(e.target.checked)} /> Opening &amp; movement columns
          </label>
          <label className="flex items-center gap-1.5 text-[12.5px] text-muted">
            <input type="checkbox" checked={includeZero} onChange={(e) => setIncludeZero(e.target.checked)} /> Zero balances
          </label>
          <label className="flex items-center gap-1.5 text-[12.5px] text-muted" title="List each customer instead of the receivable and advance accounts">
            <input type="checkbox" checked={byCustomer} onChange={(e) => setByCustomer(e.target.checked)} /> Customers in detail
          </label>
          {tb && (
            <span className={`ml-auto flex items-center gap-1.5 text-[12.5px] font-medium ${tb.is_balanced ? "text-success" : "text-rose"}`}>
              {tb.is_balanced ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
              {tb.is_balanced ? "Debits equal credits" : `Out of balance by ${money(Math.abs(tb.difference))}`}
            </span>
          )}
        </div>
        <ErrorNote message={error} />
        {loading && <Spinner />}
        {!loading && tb && tb.rows.length === 0 && (
          <EmptyState>Nothing posted in this range. The ledger begins with the approved opening balances.</EmptyState>
        )}
        {!loading && tb && tb.rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left">
              <thead>
                <tr className="border-b border-line">
                  <GridTh>Account Code</GridTh><GridTh>Account Name</GridTh>
                  {detailed && <><GridTh numeric>Opening Dr</GridTh><GridTh numeric>Opening Cr</GridTh>
                    <GridTh numeric>Period Dr</GridTh><GridTh numeric>Period Cr</GridTh></>}
                  <GridTh numeric>Debit</GridTh><GridTh numeric>Credit</GridTh><GridTh numeric>Balance</GridTh>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <GroupRows key={g.type} title={g.type} rows={g.rows} detailed={detailed} cols={cols} link={ledgerLink} />
                ))}
                <tr className="border-t-2 border-line text-[12.8px] font-semibold">
                  <td className={gridCellClass()} colSpan={2}>Total</td>
                  {detailed && <>
                    <td className={gridCellClass(true)}>{money(t.opening_debit)}</td>
                    <td className={gridCellClass(true)}>{money(t.opening_credit)}</td>
                    <td className={gridCellClass(true)}>{money(t.period_debit)}</td>
                    <td className={gridCellClass(true)}>{money(t.period_credit)}</td>
                  </>}
                  <td className={gridCellClass(true)}>{money(t.closing_debit)}</td>
                  <td className={gridCellClass(true)}>{money(t.closing_credit)}</td>
                  <td className={gridCellClass(true, tb.is_balanced ? "text-success" : "text-rose")}>{money(tb.difference)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="mt-3 text-[11.5px] text-faint">
        Click an account to open its general ledger, then a journal to see its lines and source document.
        Until year-end closing is built, profit and loss accounts carry their totals across years.
      </p>
    </AppShell>
  );
}

function GroupRows({ title, rows, detailed, cols, link }: {
  title: string; rows: Row[]; detailed: boolean; cols: number; link: (id: string) => string;
}) {
  return (
    <>
      <tr className="border-b border-line bg-bg/60">
        <td colSpan={cols + 1} className="px-4 py-2 text-[11.5px] font-semibold uppercase tracking-wide text-muted">{title}</td>
      </tr>
      {rows.map((r, i) => (
        <Fragment key={r.account_id}>
        {r.sub_group && rows[i - 1]?.sub_group !== r.sub_group && (
          <tr className="border-b border-line">
            <td colSpan={cols + 1} className="px-4 py-1.5 pl-7 text-[11px] font-semibold uppercase tracking-wide text-faint">
              {r.sub_group} · {rows.filter((x) => x.sub_group === r.sub_group && x.customer_id).length} with a balance
            </td>
          </tr>
        )}
        <tr className={r.is_subtotal ? "border-y-2 border-line bg-primary/5 font-semibold" : gridRowClass(i)}>
          <td className={gridCellClass()}>
            {r.account_code && (
              <Link href={r.customer_id ? `/finance/ledger?customer=${r.customer_id}` : link(r.account_id)}
                className="font-medium text-primary hover:underline">{r.account_code}</Link>
            )}
          </td>
          <td className={gridCellClass()}>{r.account_name}</td>
          {detailed && <>
            <td className={gridCellClass(true)}>{moneyOrBlank(r.opening_debit)}</td>
            <td className={gridCellClass(true)}>{moneyOrBlank(r.opening_credit)}</td>
            <td className={gridCellClass(true)}>{moneyOrBlank(r.period_debit)}</td>
            <td className={gridCellClass(true)}>{moneyOrBlank(r.period_credit)}</td>
          </>}
          <td className={gridCellClass(true)}>{moneyOrBlank(r.debit)}</td>
          <td className={gridCellClass(true)}>{moneyOrBlank(r.credit)}</td>
          <td className={gridCellClass(true, "text-muted")}>{money(r.balance)}</td>
        </tr>
        </Fragment>
      ))}
    </>
  );
}
