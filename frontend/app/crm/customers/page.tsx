"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, AlertTriangle, Moon, Plus, Search, Sparkles, UserX, Users, Wallet } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { DataTable } from "@/components/ui/DataTable";
import { DownloadMenu } from "@/components/ui/TableTools";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { useCrud } from "@/lib/useCrud";
import { CustomerAccount } from "@/components/receivables/CustomerAccount";
import { PartnerModal, type Partner } from "@/components/partners/PartnerModal";
import { compact, fmtDate, money, useFetch } from "@/lib/leads";
import { usePageSize } from "@/lib/usePageSize";
import { SEGMENT_TONE } from "@/lib/crm";

interface Row {
  id: string; code: string; name: string; city: string | null; address: string | null; phone: string | null; email: string | null;
  orders: number; last_order_date: string | null; days_since_order: number | null; sales_total: number;
  sales_12m: number; segment: string; balance: number; open_leads: number; contacts: number;
}
interface Summary {
  customers: number; segments: Record<string, number>; receivable: number; sales_12m: number; buying_12m: number;
}


export default function CustomersPage() {
  const [tab, setTab] = useState<"customers" | "partners">("customers");
  return (
    <AppShell title="Customers">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="m-0 text-[19px] font-semibold">Customers</h1>
          <p className="m-0 text-[12px] text-muted">Every customer with what they owe, what they buy and how recently. Open one to see everything about them.</p>
        </div>
        <div className="ml-auto flex overflow-hidden rounded-lg border border-line bg-surface">
          {([["customers", "Customers"], ["partners", "All partners (customers & suppliers)"]] as const).map(([v, l]) => (
            <button key={v} onClick={() => setTab(v)}
              className={`px-3.5 py-2 text-[12.5px] font-medium ${tab === v ? "bg-primary text-on-primary" : "text-muted hover:bg-hover"}`}>{l}</button>
          ))}
        </div>
      </div>
      {tab === "customers" ? <CustomerList /> : <Partners />}
    </AppShell>
  );
}

function CustomerList() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [typed, setTyped] = useState("");
  const [segment, setSegment] = useState("");
  const [sort, setSort] = useState("sales_12m");
  const [page, setPage] = useState(1);
  const [pageSize] = usePageSize("crm.customers", 50);
  const [adding, setAdding] = useState(false);
  useEffect(() => { const t = setTimeout(() => { setSearch(typed); setPage(1); }, 350); return () => clearTimeout(t); }, [typed]);
  const summary = useFetch<Summary>("/crm/customers/summary");
  const list = useFetch<{ items: Row[]; total: number }>(`/crm/customers?page=${page}&page_size=${pageSize}&sort=${sort}`
    + `${search ? `&search=${encodeURIComponent(search)}` : ""}${segment ? `&segment=${encodeURIComponent(segment)}` : ""}`);
  const s = summary.data;
  const rows = list.data?.items ?? [];
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / pageSize));

  const seg = (name: string, icon: React.ReactNode, note: string) => (
    <button onClick={() => { setSegment(segment === name ? "" : name); setPage(1); }}
      className={`rounded-[14px] border bg-surface p-4 text-left shadow-panel transition ${
        segment === name ? "border-primary ring-2 ring-primary/20" : "border-line hover:border-primary/40"}`}>
      <div className="flex items-center gap-2 text-[12px] text-muted">
        <span className={`rounded-lg p-1.5 ${SEGMENT_TONE[name]}`}>{icon}</span>{name}
      </div>
      <div className="mt-2 text-[22px] font-semibold leading-none">{s?.segments[name] ?? "—"}</div>
      <div className="mt-1.5 text-[11.5px] text-muted">{note}</div>
    </button>
  );

  return (
    <>
      <div className="mb-5 grid grid-cols-6 gap-4 max-xl:grid-cols-3 max-md:grid-cols-1">
        <div className="rounded-[14px] border border-line bg-surface p-4 shadow-panel">
          <div className="flex items-center gap-2 text-[12px] text-muted"><span className="rounded-lg bg-sky/10 p-1.5 text-sky"><Users size={14} /></span>Customers</div>
          <div className="mt-2 text-[22px] font-semibold leading-none">{s?.customers ?? "—"}</div>
          <div className="mt-1.5 text-[11.5px] text-muted">{s?.buying_12m ?? 0} bought in the last year</div>
        </div>
        <div className="rounded-[14px] border border-line bg-surface p-4 shadow-panel">
          <div className="flex items-center gap-2 text-[12px] text-muted"><span className="rounded-lg bg-violet/10 p-1.5 text-violet"><Wallet size={14} /></span>Receivable</div>
          <div className="mt-2 text-[22px] font-semibold leading-none">PKR {compact(s?.receivable ?? 0)}</div>
          <div className="mt-1.5 text-[11.5px] text-muted">owed to us, from the ledger</div>
        </div>
        {seg("Active", <Activity size={14} />, "ordered in the last 3 months")}
        {seg("Slowing", <AlertTriangle size={14} />, "last order 3–6 months ago")}
        {seg("Dormant", <Moon size={14} />, "no order for 6 months +")}
        {seg("Never ordered", <UserX size={14} />, "no sales order yet")}
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          <div className="flex items-center gap-2 rounded-lg border border-line bg-bg px-3 py-2">
            <Search size={14} className="text-faint" />
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Name, code, city, phone, NTN…"
              className="w-64 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint" />
          </div>
          <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}
            className="rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] text-muted outline-none">
            <option value="sales_12m">Biggest buyers this year</option>
            <option value="sales_total">Biggest buyers ever</option>
            <option value="balance">Owe us the most</option>
            <option value="last_order">Ordered most recently</option>
            <option value="name">Name A–Z</option>
          </select>
          {segment && <button onClick={() => setSegment("")} className={`rounded-md px-2.5 py-1 text-[11.5px] font-semibold ${SEGMENT_TONE[segment]}`}>{segment} ✕</button>}
          <span className="text-[12px] text-muted">{(list.data?.total ?? 0).toLocaleString()} customers</span>
          <button onClick={() => setAdding(true)}
            className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary to-primary-dark px-3.5 py-2 text-[12.8px] font-medium text-on-primary">
            <Plus size={14} /> New customer</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1150px] border-collapse text-left">
            <thead><tr className="border-b border-line">
              {["Customer", "City", "Health", "Last order", "Orders", "Sales — last 12 months", "Sales — all time", "Balance (PKR)", "Open leads", "Contacts"]
                .map((h, i) => <GridTh key={h} numeric={[4, 5, 6, 7, 8, 9].includes(i)}>{h}</GridTh>)}
            </tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.id} onClick={() => router.push(`/crm/customers/${r.id}`)} className={`${gridRowClass(i)} cursor-pointer`}>
                  <td className={gridCellClass(false, "font-medium")}>{r.name}<span className="block text-[11px] font-normal text-faint">{r.code}{r.phone ? ` · ${r.phone}` : ""}</span></td>
                  <td className={gridCellClass(false, "max-w-[180px] truncate text-muted")} title={r.address ?? ""}>{r.city ?? r.address ?? "—"}</td>
                  <td className={gridCellClass()}><span className={`whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-semibold ${SEGMENT_TONE[r.segment]}`}>{r.segment}</span></td>
                  <td className={gridCellClass(false, "whitespace-nowrap")}>{r.last_order_date ? fmtDate(r.last_order_date) : "—"}
                    {r.days_since_order != null && <span className="block text-[11px] text-faint">{r.days_since_order} days ago</span>}</td>
                  <td className={gridCellClass(true)}>{r.orders}</td>
                  <td className={gridCellClass(true, "font-semibold")}>{money(r.sales_12m)}</td>
                  <td className={gridCellClass(true)}>{money(r.sales_total)}</td>
                  <td className={gridCellClass(true, r.balance > 0 ? "font-semibold text-rose" : r.balance < 0 ? "text-primary" : "text-faint")}>
                    {r.balance < 0 ? `${money(-r.balance)} Cr` : money(r.balance)}</td>
                  <td className={gridCellClass(true)}>{r.open_leads ? <span className="inline-flex items-center gap-1 text-primary"><Sparkles size={11} />{r.open_leads}</span> : "—"}</td>
                  <td className={gridCellClass(true)}>{r.contacts || "—"}</td>
                </tr>
              ))}
              {!list.loading && rows.length === 0 && (
                <tr><td colSpan={10} className="px-5 py-12 text-center text-[12.8px] text-faint">No customer matches.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center gap-3 border-t border-line px-5 py-3 text-[12.3px] text-muted">
          <span>Page {page} of {pages}</span>
          <div className="ml-auto flex gap-1.5">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-lg px-3 py-1.5 hover:bg-hover disabled:opacity-40">Previous</button>
            <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded-lg px-3 py-1.5 hover:bg-hover disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>

      <PartnerModal open={adding} partner={null} onClose={() => setAdding(false)}
        onSaved={(p) => { setAdding(false); router.push(`/crm/customers/${p.id}`); }} />
    </>
  );
}

/** The partner master as it was: customers and suppliers, edited here. */
function Partners() {
  const crud = useCrud<Partner>("/partners", 25);
  const [editing, setEditing] = useState<Partner | null>(null);
  const [isOpen, setOpen] = useState(false);
  const [accountOf, setAccountOf] = useState<string | null>(null);
  return (
    <>
      <DataTable<Partner>
        title="Partners"
        createLabel="Add Partner"
        emptyMessage="No partners yet. Import the contacts export or add one."
        columns={[
          { key: "code", header: "Code" },
          { key: "name", header: "Name" },
          { key: "territory", header: "Territory", render: (p) => p.territory ?? "—" },
          { key: "phone", header: "Phone", render: (p) => p.phone ?? "—" },
          { key: "ntn", header: "NTN", render: (p) => p.ntn ?? "—" },
          {
            key: "roles", header: "Role",
            render: (p) => (
              <div className="flex gap-1.5">
                {p.is_customer && <span className="rounded-md bg-primary/15 px-2 py-0.5 text-[10.5px] font-semibold text-primary">Customer</span>}
                {p.is_supplier && <span className="rounded-md bg-sky/15 px-2 py-0.5 text-[10.5px] font-semibold text-sky">Supplier</span>}
              </div>
            ),
          },
          {
            key: "account", header: "Account",
            render: (p) => (p.is_customer ? (
              <button onClick={() => setAccountOf(p.id)}
                className="rounded-md bg-hover px-2.5 py-1 text-[11.5px] font-medium text-muted hover:bg-primary/10 hover:text-primary">
                Balance
              </button>
            ) : null),
          },
        ]}
        rows={crud.rows} total={crud.total} page={crud.page} pageSize={crud.pageSize} onPageSize={crud.setPageSize}
        loading={crud.loading} error={crud.error} search={crud.search}
        onSearch={crud.onSearch} onPage={crud.setPage}
        toolbar={<DownloadMenu dataset="customers" />}
        columnsKey="customers.columns"
        onCreate={() => { setEditing(null); setOpen(true); }} onEdit={(p) => { setEditing(p); setOpen(true); }}
      />
      {accountOf && <CustomerAccount customerId={accountOf} onClose={() => setAccountOf(null)} />}
      <PartnerModal open={isOpen} partner={editing} onClose={() => setOpen(false)}
        onSaved={() => { setOpen(false); void crud.reload(); }} />
    </>
  );
}
