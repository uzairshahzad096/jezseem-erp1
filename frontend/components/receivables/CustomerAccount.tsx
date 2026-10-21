"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Field, Modal, Select, TextInput } from "@/components/ui/Modal";
import { Button, ErrorNote } from "@/components/finance/ui";
import { errorText, money, useFinance } from "@/lib/finance";
import type { PaymentTerm } from "@/lib/receivables";

interface Profile {
  customer_id: string; customer_code: string; customer_name: string;
  invoiced: number; credit_notes: number; receipts: number; total_paid: number; receivable: number;
  advances: number; overdue: number; net_balance: number; open_invoices: number; partly_paid: number;
  gross_outstanding: number; unallocated_receipts: number;
  credit_limit: number | null; available_credit: number | null;
  ledger_receivable: number; ledger_advances: number; payment_term_id: string | null;
}

/** A customer's receivable position, from the subledger, with the ledger figure beside it. */
export function CustomerAccount({ customerId, onClose }: { customerId: string; onClose: () => void }) {
  const { data: terms } = useFinance<PaymentTerm[]>("/ar/payment-terms");
  const [p, setP] = useState<Profile | null>(null);
  const [limit, setLimit] = useState("");
  const [term, setTerm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<Profile>(`/ar/customers/${customerId}/profile`).then((d) => {
      setP(d); setLimit(d.credit_limit != null ? String(d.credit_limit) : ""); setTerm(d.payment_term_id ?? "");
    }).catch((e) => setError(errorText(e, "Could not load the account.")));
  }, [customerId]);

  const save = async () => {
    setSaving(true); setError(null);
    try {
      setP(await api.put<Profile>(`/ar/customers/${customerId}/credit`, {
        credit_limit: limit === "" ? null : limit, default_payment_term_id: term || null }));
    } catch (e) { setError(errorText(e, "Could not save.")); } finally { setSaving(false); }
  };

  const stat = (label: string, value: string, tone = "") => (
    <div className="rounded-lg border border-line bg-bg px-3.5 py-2.5">
      <div className="text-[11px] text-faint">{label}</div>
      <div className={`text-[15px] font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );

  return (
    <Modal title={p ? `Account — ${p.customer_code} ${p.customer_name}` : "Customer account"} open width="md" onClose={onClose}>
      <ErrorNote message={error} />
      {p && (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3 max-sm:grid-cols-2">
            {stat("Total invoiced", money(p.invoiced))}
            {stat("Total received", money(p.total_paid))}
            {stat("Credit notes", money(p.credit_notes))}
            {stat("Invoices outstanding", money(p.gross_outstanding), p.gross_outstanding ? "" : "text-faint")}
        {stat("Receipts on account", money(p.unallocated_receipts), p.unallocated_receipts ? "" : "text-faint")}
            {stat("Overdue", money(p.overdue), p.overdue ? "text-rose" : "text-faint")}
            {stat("Advances held", money(p.advances))}
            {stat("Net balance", money(p.net_balance))}
            {stat("Credit limit", p.credit_limit != null ? money(p.credit_limit) : "No limit")}
            {stat("Available credit", p.available_credit != null ? money(p.available_credit) : "—",
              p.available_credit != null && p.available_credit < 0 ? "text-rose" : "")}
          </div>
          <p className="m-0 text-[11.5px] text-faint">
            {p.open_invoices} open invoice(s), {p.partly_paid} partly paid. Ledger check: receivable {money(p.ledger_receivable)},
            advances {money(p.ledger_advances)}{p.ledger_receivable === p.receivable && p.ledger_advances === p.advances ? " — agrees." : " — differs; see AR Reconciliation."}
          </p>
          <div className="grid grid-cols-[1fr_1fr_auto] items-end gap-3 max-sm:grid-cols-1">
            <Field label="Credit limit (blank = none)"><TextInput inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} /></Field>
            <Field label="Default payment terms">
              <Select value={term} placeholder="Company default" onChange={(e) => setTerm(e.target.value)}
                options={(terms ?? []).filter((t) => t.is_active).map((t) => ({ value: t.id, label: t.name }))} />
            </Field>
            <Button tone="primary" busy={saving} onClick={save}>Save</Button>
          </div>
          <div className="flex flex-wrap gap-2 border-t border-line pt-3 text-[12.5px]">
            <Link className="text-primary hover:underline" href={`/finance/statement?customer=${p.customer_id}`}>Statement</Link>
            <span className="text-faint">·</span>
            <Link className="text-primary hover:underline" href={`/finance/receipts?new=1&customer=${p.customer_id}`}>Record a receipt</Link>
            <span className="text-faint">·</span>
            <Link className="text-primary hover:underline" href="/finance/aging">Aging</Link>
          </div>
        </div>
      )}
    </Modal>
  );
}
