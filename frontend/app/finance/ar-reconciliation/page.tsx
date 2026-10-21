"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { GridTh, gridCellClass, gridRowClass } from "@/components/ui/grid";
import { Card, ErrorNote, PageHeader, Spinner, filterClass } from "@/components/finance/ui";
import { ExportButtons } from "@/components/receivables/ExportButtons";
import { api } from "@/lib/api";
import { errorText, money } from "@/lib/finance";

interface Recon {
  as_of: string; reconciled: boolean;
  receivable: { subledger: number; control_account: number; difference: number };
  advances: { subledger: number; control_account: number; difference: number };
  differences: Row[]; customers: Row[];
}
interface Row { customer_id: string | null; customer_name: string; sub_receivable: number; gl_receivable: number;
                receivable_difference: number; sub_advances: number; gl_advances: number; advances_difference: number }

export default function ARReconciliationPage() {
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<Recon | null>(null);
  const [all, setAll] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api.get<Recon>(`/ar/reconciliation?as_of=${asOf}`).then(setData).catch((e) => setError(errorText(e, "Could not load.")));
  }, [asOf]);

  const rows = data ? (all ? data.customers : data.differences) : [];
  return (
    <AppShell title="AR Reconciliation">
      <PageHeader title="AR Reconciliation" subtitle="Receivables subledger against the general-ledger control accounts, in total and customer by customer.">
        <ExportButtons report="reconciliation" query={`as_of=${asOf}`} />
      </PageHeader>
      <ErrorNote message={error} />
      <div className="mb-4 flex items-center gap-2.5">
        <label className="text-[12.5px] text-muted">As at</label>
        <input type="date" className={filterClass} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        {data && (
          <span className={`ml-2 flex items-center gap-1.5 text-[13px] font-medium ${data.reconciled ? "text-success" : "text-rose"}`}>
            {data.reconciled ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            {data.reconciled ? "Subledger and ledger agree" : "Differences found — see below"}
          </span>
        )}
      </div>
      {!data ? <Spinner /> : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-[18px] max-lg:grid-cols-1">
            {([["Accounts receivable", data.receivable], ["Customer advances", data.advances]] as const).map(([label, v]) => (
              <Card key={label} title={label}>
                <dl className="m-0 grid grid-cols-3 gap-3 px-5 py-4 text-[12.5px]">
                  <div><dt className="text-faint">Subledger</dt><dd className="m-0 text-[16px] font-semibold tabular-nums">{money(v.subledger)}</dd></div>
                  <div><dt className="text-faint">Control account (GL)</dt><dd className="m-0 text-[16px] font-semibold tabular-nums">{money(v.control_account)}</dd></div>
                  <div><dt className="text-faint">Difference</dt><dd className={`m-0 text-[16px] font-semibold tabular-nums ${v.difference ? "text-rose" : "text-success"}`}>{money(v.difference)}</dd></div>
                </dl>
              </Card>
            ))}
          </div>
          <Card title={all ? "All customers" : "Customers with a difference"}
            action={<button className="text-[12px] text-primary hover:underline" onClick={() => setAll(!all)}>{all ? "Differences only" : "Show all customers"}</button>}>
            {rows.length === 0 ? <p className="px-5 py-6 text-[12.5px] text-faint">{all ? "No customer balances." : "No differences."}</p> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] border-collapse text-left">
                  <thead><tr className="border-b border-line">
                    <GridTh>Customer</GridTh><GridTh numeric>Subledger AR</GridTh><GridTh numeric>GL AR</GridTh><GridTh numeric>Difference</GridTh>
                    <GridTh numeric>Subledger advances</GridTh><GridTh numeric>GL advances</GridTh><GridTh numeric>Difference</GridTh>
                  </tr></thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={r.customer_id ?? `none-${i}`} className={gridRowClass(i)}>
                        <td className={gridCellClass()}>{r.customer_name}</td>
                        <td className={gridCellClass(true)}>{money(r.sub_receivable)}</td>
                        <td className={gridCellClass(true)}>{money(r.gl_receivable)}</td>
                        <td className={gridCellClass(true, r.receivable_difference ? "text-rose font-semibold" : "text-faint")}>{money(r.receivable_difference)}</td>
                        <td className={gridCellClass(true)}>{money(r.sub_advances)}</td>
                        <td className={gridCellClass(true)}>{money(r.gl_advances)}</td>
                        <td className={gridCellClass(true, r.advances_difference ? "text-rose font-semibold" : "text-faint")}>{money(r.advances_difference)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </AppShell>
  );
}
