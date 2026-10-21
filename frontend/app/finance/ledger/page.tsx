"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { Combobox } from "@/components/ui/Modal";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { ColumnPicker, useHiddenColumns } from "@/components/ui/TableTools";
import { JournalView } from "@/components/finance/JournalView";
import { Button, Card, EmptyState, ErrorNote, PageHeader, Spinner, StatusBadge, filterClass } from "@/components/finance/ui";
import { api } from "@/lib/api";
import {
  download, drcr, errorText, fmtDate, money, moneyOrBlank, sourceLink, useFinance, useFinanceContext,
  type Account,
} from "@/lib/finance";

interface LedgerRow {
  line_id: string; journal_id: string; journal_number: string; journal_date: string;
  journal_type: string; status: string; document_type: string | null; document_id: string | null;
  source_module: string | null; source_reference: string | null; description: string | null;
  narration: string | null;
  invoice_no: string | null; voucher_no: string | null; cheque_ref: string | null; cheque_date: string | null;
  debit: number; credit: number; running_balance: number;
  customer: string | null; supplier: string | null; branch: string | null; cost_center: string | null;
  account_code: string; account_name: string;
}
interface Party { id: string; code: string; name: string; kind: "customer" | "supplier"; balance: number }
interface Ledger {
  account: { id: string; code: string; name: string; normal_balance: string } | null;
  party: { id: string; code: string; name: string; kind: "customer" | "supplier" } | null;
  date_from: string | null; date_to: string | null;
  opening_balance: number; total_debit: number; total_credit: number; closing_balance: number;
  total: number; rows: LedgerRow[];
}
interface Period { id: string; name: string }
interface Year { id: string; name: string; periods: Period[] }

// Laid out as the previous ERP's ledger: serial, invoice, date, debit, credit,
// narration, cheque / reference, cheque date, voucher, balance. The columns
// after Voucher No are this system's own and start hidden.
const COLUMNS: { key: string; label: string; numeric?: boolean }[] = [
  { key: "sr", label: "Sr No" }, { key: "invoice", label: "Invoice No" }, { key: "date", label: "Voucher Date" },
  { key: "debit", label: "Debit", numeric: true }, { key: "credit", label: "Credit", numeric: true },
  { key: "narration", label: "Narration" }, { key: "cheque_ref", label: "Cheque No / Ref No" },
  { key: "cheque_date", label: "Cheque Date" }, { key: "voucher", label: "Voucher No" },
  { key: "journal", label: "Journal" }, { key: "source", label: "Source document" },
  { key: "account", label: "Account" }, { key: "party", label: "Customer / Supplier" },
  { key: "branch", label: "Branch" }, { key: "cost_center", label: "Cost centre" },
  { key: "balance", label: "Balance", numeric: true },
];
const AMOUNTS = ["debit", "credit", "balance"];
const HIDDEN_AT_FIRST = ["journal", "source", "account", "party", "branch", "cost_center"];

/** The accounts that hold a customer's or supplier's own balance. */
const PARTY_ACCOUNTS = ["RECEIVABLE", "CUSTOMER_ADVANCE", "PAYABLE"];

function LedgerScreen() {
  const params = useSearchParams();
  const { data: ctx } = useFinanceContext();
  const { data: accounts } = useFinance<Account[]>("/finance/accounts?postable_only=true");
  const { data: years } = useFinance<Year[]>("/finance/financial-years");
  const { data: parties } = useFinance<Party[]>("/finance/ledger/parties");
  const [account, setAccount] = useState(params.get("account") ?? "");
  // A customer or supplier: with no account chosen, the ledger is everything
  // posted against them, across accounts.
  const [party, setParty] = useState(params.get("customer") ?? params.get("supplier") ?? "");
  const [fy, setFy] = useState(params.get("fy") ?? "");
  const [period, setPeriod] = useState(params.get("period") ?? "");
  const [from, setFrom] = useState(params.get("from") ?? "");
  const [to, setTo] = useState(params.get("to") ?? "");
  const [branch, setBranch] = useState(params.get("branch") ?? "");
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);

  const query = () => {
    const qs = new URLSearchParams({ page_size: "1000" });
    if (account) qs.set("account_id", account);
    if (party) qs.set(parties?.find((p) => p.id === party)?.kind === "supplier" ? "supplier_id" : "customer_id", party);
    if (period) qs.set("period_id", period);
    else if (fy) qs.set("financial_year_id", fy);
    if (from) qs.set("date_from", from);
    if (to) qs.set("date_to", to);
    if (branch) qs.set("branch_id", branch);
    return qs;
  };

  const load = async () => {
    if (!account && !party) { setLedger(null); return; }
    if (party && !parties) return;   // whether it is a customer or a supplier is not known yet
    setLoading(true);
    setError(null);
    try {
      setLedger(await api.get<Ledger>(`/finance/ledger?${query()}`));
    } catch (err) {
      setError(errorText(err, "Could not load the ledger."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [account, party, parties, fy, period, from, to, branch]); // eslint-disable-line react-hooks/exhaustive-deps

  const exportAs = async (format: string) => {
    try {
      const qs = query();
      qs.delete("page_size");
      qs.set("format", format);
      await download(`/finance/ledger/export?${qs}`, `ledger.${format}`);
    } catch (err) { setError(errorText(err, "Export failed.")); }
  };

  const periods = years?.find((y) => y.id === fy)?.periods ?? [];
  const options = [
    ...(party ? [{ value: "", label: "All accounts" }] : []),
    ...(accounts ?? []).map((a) => ({ value: a.id, label: `${a.code}  ${a.name}`, short: `${a.code} ${a.name}` })),
  ];
  const partyOptions = [
    { value: "", label: "All customers" },
    ...(parties ?? []).map((p) => ({
      value: p.id, short: p.name,
      label: `${p.name}  ·  ${p.code}${p.kind === "supplier" ? "  ·  supplier" : ""}${p.balance ? `  ·  ${drcr(p.balance)}` : ""}`,
    })),
  ];
  const chosen = Boolean(account || party);
  const byParty = Boolean(ledger && !ledger.account);
  const columnState = useHiddenColumns("finance-ledger.columns.v2", HIDDEN_AT_FIRST);
  // The Account column only says something when the lines span several accounts.
  const available = COLUMNS.filter((c) => c.key !== "account" || byParty);
  const visible = available.filter((c) => !columnState.hidden.has(c.key));
  const show = (key: string) => visible.some((c) => c.key === key);

  const openJournal = (r: LedgerRow, label: string) => (
    <button onClick={() => setViewing(r.journal_id)} className="font-medium text-primary hover:underline">{label}</button>
  );
  const cell = (key: string, r: LedgerRow, index: number): React.ReactNode => {
    const link = sourceLink(r.document_type, r.document_id);
    switch (key) {
      case "sr": return index + 1;
      case "invoice": return r.invoice_no && link
        ? <Link href={link} className="text-primary hover:underline">{r.invoice_no}</Link> : (r.invoice_no ?? "");
      case "date": return fmtDate(r.journal_date);
      case "debit": return moneyOrBlank(r.debit);
      case "credit": return moneyOrBlank(r.credit);
      case "narration": return r.narration ?? r.description;
      case "cheque_ref": return r.cheque_ref ?? "";
      case "cheque_date": return r.cheque_date ? fmtDate(r.cheque_date) : "";
      // A receipt keeps its voucher number; anything else is known by its journal.
      case "voucher": return openJournal(r, r.voucher_no ?? r.journal_number);
      case "journal": return (
        <>
          {openJournal(r, r.journal_number)}
          {r.status === "REVERSED" && <span className="ml-1.5"><StatusBadge status="REVERSED" /></span>}
        </>
      );
      case "source": return link
        ? <Link href={link} className="hover:text-primary hover:underline">{r.source_reference}</Link>
        : (r.source_reference ?? r.journal_type);
      case "account": return `${r.account_code} ${r.account_name}`;
      case "party": return r.customer ?? r.supplier ?? ledger?.party?.name ?? "";
      case "branch": return r.branch ?? "";
      case "cost_center": return r.cost_center ?? "";
      case "balance": return drcr(r.running_balance);
      default: return "";
    }
  };
  const cellClass = (key: string) => gridCellClass(AMOUNTS.includes(key),
    // Old narrations run invoice numbers together with no spaces ("202607204||45000202604252||…"),
    // so the text must be allowed to break anywhere or it spills over the next column.
    key === "narration" ? "min-w-[260px] max-w-[460px] text-[12.3px] leading-snug [overflow-wrap:anywhere]"
      : key === "cheque_ref" ? "max-w-[200px] text-[12.3px] leading-snug text-muted [overflow-wrap:anywhere]"
      : ["source", "party", "branch", "cost_center", "sr"].includes(key) ? "whitespace-nowrap text-muted" : "whitespace-nowrap");
  // The closing row: totals under their own columns, the label in the first
  // run of other columns, blanks under the rest.
  const closing: { key: string; span: number; total?: string }[] = [];
  for (const c of visible) {
    const last = closing[closing.length - 1];
    if (AMOUNTS.includes(c.key)) {
      closing.push({ key: c.key, span: 1, total: c.key === "debit" ? money(ledger?.total_debit ?? 0)
        : c.key === "credit" ? money(ledger?.total_credit ?? 0) : drcr(ledger?.closing_balance ?? 0) });
    } else if (last && last.total === undefined) last.span += 1;
    else closing.push({ key: c.key, span: 1 });
  }
  const labelAt = closing.findIndex((g) => g.total === undefined);

  return (
    <AppShell title="General Ledger">
      <PageHeader title="General Ledger" subtitle="Every posted line on an account or a customer, with its running balance.">
        {ledger && (
          <ColumnPicker columns={available} hidden={columnState.hidden} onToggle={columnState.toggle} onReset={columnState.reset} />
        )}
        {ledger && ["xlsx", "pdf", "csv"].map((f) => (
          <Button key={f} onClick={() => exportAs(f)}>{f.toUpperCase()}</Button>
        ))}
      </PageHeader>

      <Card>
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3.5">
          <div className="w-80 max-sm:w-full">
            <Combobox value={account} options={options} onChange={setAccount} placeholder="Choose an account…" />
          </div>
          <div className="w-80 max-sm:w-full">
            <Combobox value={party} options={partyOptions} onChange={setParty} placeholder="Choose a customer…" />
          </div>
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
        </div>
        <ErrorNote message={error} />

        {!chosen && <EmptyState>Choose an account or a customer to see the ledger.</EmptyState>}
        {chosen && loading && <Spinner />}
        {chosen && !loading && ledger && (
          <>
            <div className="flex flex-wrap gap-x-8 gap-y-2 border-b border-line px-5 py-3 text-[12.5px]">
              {ledger.party && (
                <span>
                  <span className="text-faint">{ledger.party.kind === "supplier" ? "Supplier" : "Customer"}</span>{" "}
                  <b>{ledger.party.code} {ledger.party.name}</b>
                </span>
              )}
              <span>
                <span className="text-faint">Account</span>{" "}
                <b>{ledger.account ? `${ledger.account.code} ${ledger.account.name}` : "All accounts"}</b>
              </span>
              <span><span className="text-faint">Opening</span> <b className="tabular-nums">{drcr(ledger.opening_balance)}</b></span>
              <span><span className="text-faint">Debits</span> <b className="tabular-nums">{money(ledger.total_debit)}</b></span>
              <span><span className="text-faint">Credits</span> <b className="tabular-nums">{money(ledger.total_credit)}</b></span>
              <span><span className="text-faint">Closing</span> <b className="tabular-nums">{drcr(ledger.closing_balance)}</b></span>
            </div>
            {ledger.party && ledger.account && !PARTY_ACCOUNTS.includes(accounts?.find((a) => a.id === account)?.control_type ?? "") && (
              <p className="m-0 border-b border-line bg-amber/10 px-5 py-2.5 text-[12.3px]">
                This is the money {ledger.party.name} paid into <b>{ledger.account.name}</b>, so it shows as debits of that account.
                The credit to the customer is on their own account.{" "}
                <button onClick={() => setAccount("")} className="font-semibold text-primary hover:underline">
                  Show the customer&apos;s account
                </button>
              </p>
            )}
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left" style={{ minWidth: Math.max(480, visible.length * 100) }}>
                <thead>
                  <tr className="border-b border-line">
                    {visible.map((c) => <GridTh key={c.key} numeric={c.numeric}>{c.label}</GridTh>)}
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-line bg-bg/60 text-[12.5px] font-medium">
                    <td className={gridCellClass()} colSpan={Math.max(1, visible.length - (show("balance") ? 1 : 0))}>
                      Opening balance{ledger.date_from ? ` at ${fmtDate(ledger.date_from)}` : ""}
                      {!show("balance") && <span className="ml-3 tabular-nums">{drcr(ledger.opening_balance)}</span>}
                    </td>
                    {show("balance") && <td className={gridCellClass(true)}>{drcr(ledger.opening_balance)}</td>}
                  </tr>
                  {ledger.rows.length === 0 && (
                    <tr><td colSpan={Math.max(1, visible.length)}><EmptyState>No postings in this range.</EmptyState></td></tr>
                  )}
                  {ledger.rows.map((r, i) => (
                    <tr key={r.line_id} className={gridRowClass(i)}>
                      {visible.map((c) => <td key={c.key} className={cellClass(c.key)}>{cell(c.key, r, i)}</td>)}
                    </tr>
                  ))}
                  <tr className="border-t-2 border-line text-[12.5px] font-semibold">
                    {closing.map((g, i) => g.total !== undefined
                      ? <td key={g.key} className={gridCellClass(true)}>{g.total}</td>
                      : (
                        <td key={g.key} className={gridCellClass()} colSpan={g.span}>
                          {i === labelAt ? `Closing balance${ledger.date_to ? ` at ${fmtDate(ledger.date_to)}` : ""}` : ""}
                        </td>
                      ))}
                  </tr>
                </tbody>
              </table>
            </div>
            {ledger.total > ledger.rows.length && (
              <p className="px-5 py-3 text-[11.5px] text-faint">
                Showing the first {ledger.rows.length} of {ledger.total} lines. Narrow the dates, or export for the full ledger.
              </p>
            )}
          </>
        )}
      </Card>

      {viewing && (
        <JournalView journalId={viewing} onClose={() => setViewing(null)} onChanged={load} onOpen={setViewing} />
      )}
    </AppShell>
  );
}

export default function LedgerPage() {
  return <Suspense><LedgerScreen /></Suspense>;
}
