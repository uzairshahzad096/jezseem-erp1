"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Plus, Search } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { ImportedVouchers, type ImportedVoucherList } from "@/components/finance/ImportedVouchers";
import { JournalForm } from "@/components/finance/JournalForm";
import { JournalView } from "@/components/finance/JournalView";
import { Button, EmptyState, PageHeader, Spinner, StatusBadge, filterClass } from "@/components/finance/ui";
import { api } from "@/lib/api";
import { errorText, fmtDate, money, useFinance, useFinanceContext, type Journal, type JournalDetail } from "@/lib/finance";

const STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "POSTED", "REVERSED", "CANCELLED"];
const TYPES = ["MANUAL", "ADJUSTMENT", "OPENING", "REVERSAL", "SYSTEM"];

function JournalsScreen() {
  const params = useSearchParams();
  const { data: ctx } = useFinanceContext();
  const [rows, setRows] = useState<Journal[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [source, setSource] = useState("");
  const [fy, setFy] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(params.get("open"));
  const [editing, setEditing] = useState<JournalDetail | null | "new">(null);
  const pageSize = 25;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search) qs.set("search", search);
      if (status) qs.set("status", status);
      if (type) qs.set("journal_type", type);
      if (source) qs.set("document_type", source);
      if (fy) qs.set("financial_year_id", fy);
      if (from) qs.set("date_from", from);
      if (to) qs.set("date_to", to);
      const data = await api.get<{ items: Journal[]; total: number }>(`/finance/journals?${qs}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(errorText(err, "Could not load journals."));
      setRows([]); setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, search, status, type, source, fy, from, to]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  // Vouchers carried over from the previous ERP have their own tab: they are
  // headers without account lines, so they are listed but not posted. With no
  // journals yet, that tab opens first, since it is where the data is.
  const imported = useFinance<ImportedVoucherList>("/finance/imported-vouchers?page_size=1");
  const importedCount = imported.data?.all_count ?? 0;
  const [tab, setTab] = useState<"journals" | "imported" | null>(null);
  const shown = tab ?? (!loading && total === 0 && importedCount > 0 && !params.get("open") ? "imported" : "journals");

  const dirty = Boolean(search || status || type || source || fy || from || to);
  const reset = () => { setSearch(""); setStatus(""); setType(""); setSource(""); setFy(""); setFrom(""); setTo(""); setPage(1); };
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <AppShell title="Journal Entries">
      <PageHeader title="Journal Entries"
        subtitle="Draft → Submitted → Approved → Posted. Posted journals are corrected by reversal, never edited.">
        <Button tone="primary" onClick={() => setEditing("new")}><Plus size={14} /> New journal</Button>
      </PageHeader>

      {importedCount > 0 && (
        <div className="mb-5 flex flex-wrap gap-1.5">
          {([["journals", "Journals", total], ["imported", "Imported vouchers (old ERP)", importedCount]] as const).map(([key, text, count]) => (
            <button key={key} onClick={() => setTab(key)}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-[12.8px] font-medium transition-colors
                          ${shown === key ? "bg-primary/15 text-primary" : "bg-surface text-muted hover:text-text"}`}>
              {text}
              <span className="rounded-full bg-hover px-1.5 text-[10.5px] font-semibold text-muted">{count.toLocaleString()}</span>
            </button>
          ))}
        </div>
      )}

      {shown === "imported" && <ImportedVouchers />}

      <section className={`rounded-[14px] border border-line bg-surface shadow-panel ${shown === "imported" ? "hidden" : ""}`}>
        <GridHeader count={total} noun="Journal" onReset={reset} resettable={dirty} />
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder="Number, narration, reference…"
              className="w-52 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint" />
          </div>
          <select className={filterClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className={filterClass} value={source} onChange={(e) => { setSource(e.target.value); setPage(1); }}>
            <option value="">Vouchers and invoices</option>
            <option value="CUSTOMER_RECEIPT">Vouchers (receipts)</option>
            <option value="SALES_ORDER,SALES_INVOICE">Sales invoices</option>
          </select>
          <select className={filterClass} value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
            <option value="">All types</option>
            {TYPES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className={filterClass} value={fy} onChange={(e) => { setFy(e.target.value); setPage(1); }}>
            <option value="">All years</option>
            {(ctx?.financial_years ?? []).map((y) => <option key={y.id} value={y.id}>FY {y.name}</option>)}
          </select>
          <input type="date" className={filterClass} value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} title="From" />
          <input type="date" className={filterClass} value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} title="To" />
        </div>

        {error && <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line">
                <GridTh>Journal No</GridTh><GridTh>Date</GridTh><GridTh>Type</GridTh>
                <GridTh>Narration</GridTh><GridTh>Source</GridTh><GridTh>Branch</GridTh>
                <GridTh numeric>Amount</GridTh><GridTh>Status</GridTh><GridTh>Prepared by</GridTh>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={9}><Spinner /></td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={9}>
                  <EmptyState>
                    {dirty ? "No journals match these filters."
                      : "No journals yet. The ledger starts with the accountant-approved opening balances."}
                  </EmptyState>
                </td></tr>
              )}
              {!loading && rows.map((j, i) => (
                <tr key={j.id} className={`${gridRowClass(i)} cursor-pointer`} onClick={() => setViewing(j.id)}>
                  <td className={gridCellClass(false, "font-medium text-primary")}>{j.journal_number}</td>
                  <td className={gridCellClass()}>{fmtDate(j.journal_date)}</td>
                  <td className={gridCellClass(false, "text-muted")}>{j.journal_type}</td>
                  <td className={gridCellClass(false, "max-w-[320px] truncate")} title={j.description ?? ""}>{j.description}</td>
                  <td className={gridCellClass(false, "text-muted")}>{j.source_reference ?? j.source_module}</td>
                  <td className={gridCellClass(false, "text-muted")}>{j.branch ?? "—"}</td>
                  <td className={gridCellClass(true)}>{money(j.total_debit)}</td>
                  <td className={gridCellClass()}><StatusBadge status={j.status} /></td>
                  <td className={gridCellClass(false, "text-muted")}>{j.created_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{total.toLocaleString()} journals</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
            <span className="px-2">Page {page} of {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>

      {viewing && (
        <JournalView journalId={viewing} onClose={() => setViewing(null)} onChanged={load}
          onOpen={(id) => setViewing(id)}
          onEdit={(j) => { setViewing(null); setEditing(j); }} />
      )}
      {editing && (
        <JournalForm journal={editing === "new" ? null : editing} onClose={() => setEditing(null)}
          onSaved={(id) => { setEditing(null); load(); setViewing(id); }} />
      )}
    </AppShell>
  );
}

export default function JournalsPage() {
  return <Suspense><JournalsScreen /></Suspense>;
}
