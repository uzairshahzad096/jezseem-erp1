"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Info, Search } from "lucide-react";
import { GridHeader, GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { EmptyState, Spinner, filterClass } from "@/components/finance/ui";
import { Modal } from "@/components/ui/Modal";
import { fmtDate, money, useFinance } from "@/lib/finance";

export interface ImportedVoucher {
  id: number; voucher_number: string; voucher_date: string; voucher_type: string; party: string | null;
  debit_total: number; credit_total: number; reference_number: string | null; narration: string | null;
  import_status: string; source_financial_year: string | null;
  posted_receipt_id: string | null; posted_receipt_number: string | null; import_note: string | null;
}
export interface ImportedVoucherList {
  items: ImportedVoucher[]; total: number; page: number; page_size: number; filtered_amount: number;
  all_count: number; all_amount: number;
  types: { voucher_type: string; count: number; amount: number; from: string; to: string }[];
  statuses: Record<string, number>;
  posted_count: number; posted_amount: number;
}

const PAGE_SIZE = 25;
/** BANK RECEIPT VOUCHER -> Bank receipt voucher */
const tidy = (s: string) => s.charAt(0) + s.slice(1).toLowerCase();

/**
 * Vouchers carried over from the previous ERP. Receipt vouchers for a known
 * customer were posted as customer receipts and link to them; the rest are
 * shown for reference with the reason they are not in the ledger.
 */
export function ImportedVouchers() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [posted, setPosted] = useState("");
  const [sort, setSort] = useState("voucher_date");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [viewing, setViewing] = useState<ImportedVoucher | null>(null);

  useEffect(() => { const t = setTimeout(() => { setQuery(search); setPage(1); }, 300); return () => clearTimeout(t); }, [search]);

  const qs = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE), sort, direction });
  if (query) qs.set("search", query);
  if (type) qs.set("voucher_type", type);
  if (from) qs.set("date_from", from);
  if (to) qs.set("date_to", to);
  if (posted) qs.set("posted", posted);
  const list = useFinance<ImportedVoucherList>(`/finance/imported-vouchers?${qs}`);
  const data = list.data;

  const onSort = (key: string) => {
    if (sort === key) setDirection((d) => (d === "asc" ? "desc" : "asc")); else { setSort(key); setDirection(key === "voucher_date" || key === "amount" ? "desc" : "asc"); }
    setPage(1);
  };
  const dirty = Boolean(search || type || from || to || posted);
  const reset = () => { setSearch(""); setType(""); setFrom(""); setTo(""); setPosted(""); setPage(1); };
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));
  const th = (key: string, text: string, numeric = false) => (
    <GridTh sortKey={key} sort={sort} direction={direction} onSort={onSort} numeric={numeric}>{text}</GridTh>
  );

  return (
    <>
      <div className="mb-4 flex gap-3 rounded-[14px] border border-amber/40 bg-amber/10 px-5 py-4 text-[12.8px] leading-relaxed">
        <Info size={17} className="mt-0.5 flex-shrink-0 text-amber" />
        <div>
          <b>These are the vouchers from the previous ERP.</b>{" "}
          {data && data.posted_count > 0 ? (
            <>
              <b>{data.posted_count.toLocaleString()}</b> receipt vouchers (PKR {money(data.posted_amount)}) are posted as customer
              receipts: Bank or Cash is debited and the customer&apos;s advance is credited, so they appear in the General Ledger and
              Trial Balance. The other <b>{(data.all_count - data.posted_count).toLocaleString()}</b> are shown for reference only;
              open one to see why it is not posted.
            </>
          ) : (
            <>Each has its number, date, party and total, but not the account lines behind it, so none is posted to the ledger.</>
          )}
        </div>
      </div>

      <div className="mb-4 grid grid-cols-5 gap-3 max-xl:grid-cols-3 max-sm:grid-cols-1">
        {(data?.types ?? []).map((t) => (
          <button key={t.voucher_type} type="button" onClick={() => { setType(type === t.voucher_type ? "" : t.voucher_type); setPage(1); }}
            className={`rounded-[14px] border bg-surface px-4 py-3 text-left shadow-panel transition-colors hover:border-primary/60
                        ${type === t.voucher_type ? "border-primary" : "border-line"}`}>
            <span className="block truncate text-[11.5px] text-muted">{tidy(t.voucher_type)}</span>
            <span className="block text-[19px] font-bold leading-tight">{t.count.toLocaleString()}</span>
            <span className="block truncate text-[11px] text-faint">PKR {money(t.amount)}</span>
          </button>
        ))}
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={data?.total ?? 0} noun="Voucher" onReset={reset} resettable={dirty} />
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Number, party, narration…"
              className="w-56 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint" />
          </div>
          <select className={filterClass} value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
            <option value="">All voucher types</option>
            {(data?.types ?? []).map((t) => <option key={t.voucher_type} value={t.voucher_type}>{tidy(t.voucher_type)}</option>)}
          </select>
          <select className={filterClass} value={posted} onChange={(e) => { setPosted(e.target.value); setPage(1); }}>
            <option value="">Posted and not posted</option>
            <option value="yes">Posted</option>
            <option value="no">Not posted</option>
          </select>
          <input type="date" className={filterClass} value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} title="From" />
          <input type="date" className={filterClass} value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} title="To" />
        </div>

        {list.error && <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{list.error}</p>}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[1040px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line">
                {th("voucher_number", "Voucher No")}{th("voucher_date", "Date")}{th("voucher_type", "Type")}
                {th("customer_name", "Party")}<GridTh>Narration</GridTh>{th("amount", "Amount", true)}<GridTh>Status</GridTh>
              </tr>
            </thead>
            <tbody>
              {list.loading && !data && <tr><td colSpan={7}><Spinner /></td></tr>}
              {data && data.items.length === 0 && (
                <tr><td colSpan={7}><EmptyState>{dirty ? "No imported voucher matches these filters." : "No vouchers have been imported."}</EmptyState></td></tr>
              )}
              {(data?.items ?? []).map((v, i) => (
                <tr key={v.id} className={`${gridRowClass(i)} cursor-pointer`} onClick={() => setViewing(v)}>
                  <td className={gridCellClass(false, "whitespace-nowrap font-medium text-primary")}>{v.voucher_number}</td>
                  <td className={gridCellClass(false, "whitespace-nowrap")}>{fmtDate(v.voucher_date)}</td>
                  <td className={gridCellClass(false, "whitespace-nowrap text-muted")}>{tidy(v.voucher_type)}</td>
                  <td className={gridCellClass(false, "max-w-[240px] truncate")} title={v.party ?? ""}>{v.party || <span className="text-faint">—</span>}</td>
                  <td className={gridCellClass(false, "max-w-[340px] truncate text-muted")} title={v.narration ?? ""}>{v.narration}</td>
                  <td className={gridCellClass(true, v.debit_total ? "" : "text-faint")}>{money(v.debit_total)}</td>
                  <td className={gridCellClass()}>
                    {v.posted_receipt_id ? (
                      <span className="whitespace-nowrap rounded-full bg-success/15 px-2.5 py-[3px] text-[11px] font-semibold text-success">
                        Posted · {v.posted_receipt_number}
                      </span>
                    ) : (
                      <span className="whitespace-nowrap rounded-full bg-amber/15 px-2.5 py-[3px] text-[11px] font-semibold text-amber">
                        {v.import_status === "PENDING_MAPPING" ? "Not posted" : tidy(v.import_status.replace(/_/g, " "))}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{(data?.total ?? 0).toLocaleString()} vouchers · PKR {money(data?.filtered_amount ?? 0)}</span>
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
        <Modal title={`${viewing.voucher_number} — ${tidy(viewing.voucher_type)}`} open width="md" onClose={() => setViewing(null)}>
          <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-3.5 text-[12.8px] max-sm:grid-cols-1">
            {([
              ["Date", fmtDate(viewing.voucher_date)], ["Party", viewing.party || "—"],
              ["Debit total", `PKR ${money(viewing.debit_total)}`], ["Credit total", `PKR ${money(viewing.credit_total)}`],
              ["Reference", viewing.reference_number || "—"], ["Old ERP voucher id", String(viewing.id)],
            ] as [string, string][]).map(([label, value]) => (
              <div key={label}><dt className="text-[11px] text-faint">{label}</dt><dd className="m-0">{value}</dd></div>
            ))}
            <div className="col-span-2 max-sm:col-span-1">
              <dt className="text-[11px] text-faint">Narration</dt>
              <dd className="m-0 whitespace-pre-wrap break-words">{viewing.narration || "—"}</dd>
            </div>
          </dl>
          <p className="mb-0 mt-4 rounded-lg bg-hover/60 px-3.5 py-2.5 text-[12px] text-muted">
            {viewing.import_note ?? "Imported from the previous ERP as a header only, so it is not posted to the ledger."}
            {viewing.posted_receipt_id && (
              <>
                {" "}
                <Link href={`/finance/receipts?open=${viewing.posted_receipt_id}`} className="font-semibold text-primary hover:underline">
                  Open the receipt
                </Link>
              </>
            )}
          </p>
        </Modal>
      )}
    </>
  );
}
