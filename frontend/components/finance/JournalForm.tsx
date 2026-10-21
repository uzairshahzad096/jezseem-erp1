"use client";

import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Combobox, Field, Modal, Select, TextInput } from "@/components/ui/Modal";
import { PartnerPicker } from "@/components/finance/ui";
import { rupeesInWords } from "@/lib/words";
import {
  errorText, money, useFinance, useFinanceContext, type Account, type JournalDetail,
} from "@/lib/finance";

interface Line {
  key: number;
  account_id: string;
  description: string;
  debit: string;
  credit: string;
  cost_center_id: string;
  customer_id: string | null;
  supplier_id: string | null;
  party_label: string | null;
}

let counter = 0;
const blank = (): Line => ({
  key: ++counter, account_id: "", description: "", debit: "", credit: "",
  cost_center_id: "", customer_id: null, supplier_id: null, party_label: null,
});

/** Cents as integers, so the running difference never shows float dust. */
const cents = (s: string) => Math.round((Number(s.replace(/,/g, "")) || 0) * 100);

/**
 * Create or edit a draft manual journal. The totals and the difference are
 * shown live; the server checks everything again, and nothing is posted
 * from here — a saved journal is a draft until it is submitted, approved
 * and posted.
 */
export function JournalForm({
  journal, onClose, onSaved,
}: {
  journal: JournalDetail | null;
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const { data: ctx } = useFinanceContext();
  // Accounts that accept manual posting, plus the customer receivable: its lines
  // name the customer and become items in their account when the journal posts.
  const { data: accounts } = useFinance<Account[]>(
    "/finance/accounts?postable_only=true&active_only=true&journal_lines=true");
  const { data: centers } = useFinance<{ id: string; code: string; name: string; is_active: boolean }[]>(
    "/finance/cost-centers");

  const [date, setDate] = useState(journal?.journal_date ?? new Date().toISOString().slice(0, 10));
  const [type, setType] = useState(journal?.journal_type ?? "MANUAL");
  const [branch, setBranch] = useState(journal?.branch_id ?? "");
  const [reference, setReference] = useState(journal?.reference ?? "");
  const [description, setDescription] = useState(journal?.description ?? "");
  const [lines, setLines] = useState<Line[]>(() => journal?.lines.length
    ? journal.lines.map((l) => ({
        key: ++counter, account_id: l.account_id, description: l.description ?? "",
        debit: l.debit ? String(l.debit) : "", credit: l.credit ? String(l.credit) : "",
        cost_center_id: l.cost_center_id ?? "", customer_id: l.customer_id ?? null,
        supplier_id: l.supplier_id ?? null, party_label: l.party ?? null,
      }))
    : [blank(), blank()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const byId = useMemo(() => new Map((accounts ?? []).map((a) => [a.id, a])), [accounts]);
  const accountOptions = (accounts ?? []).map((a) => ({ value: a.id, label: `${a.code}  ${a.name}`, short: `${a.code} ${a.name}` }));

  const totalDr = lines.reduce((s, l) => s + cents(l.debit), 0);
  const totalCr = lines.reduce((s, l) => s + cents(l.credit), 0);
  const difference = totalDr - totalCr;

  const update = (key: number, patch: Partial<Line>) =>
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const save = async () => {
    const filled = lines.filter((l) => l.account_id || l.debit || l.credit);
    if (filled.length < 2) { setError("A journal needs at least two lines."); return; }
    if (filled.some((l) => !l.account_id)) { setError("Every line needs an account."); return; }
    if (difference !== 0) { setError(`The journal is out by ${money(Math.abs(difference) / 100)}.`); return; }
    setSaving(true);
    setError(null);
    try {
      const body = {
        journal_date: date, journal_type: type, branch_id: branch || null,
        reference: reference.trim() || null, description: description.trim() || null,
        lines: filled.map((l) => ({
          account_id: l.account_id, description: l.description.trim() || null,
          debit: l.debit.replace(/,/g, "") || "0", credit: l.credit.replace(/,/g, "") || "0",
          cost_center_id: l.cost_center_id || null,
          customer_id: l.customer_id, supplier_id: l.supplier_id,
        })),
      };
      const saved = journal
        ? await api.put<JournalDetail>(`/finance/journals/${journal.id}`, body)
        : await api.post<JournalDetail>("/finance/journals", body);
      onSaved(saved.id);
    } catch (err) {
      setError(errorText(err, "Could not save the journal."));
    } finally {
      setSaving(false);
    }
  };

  const cell = "rounded-md border border-line bg-bg px-2 py-1.5 text-[12px] outline-none focus:border-primary";

  return (
    <Modal title={journal ? `Edit ${journal.journal_number}` : "New journal entry"} open width="xl"
           saving={saving} error={error} onClose={onClose} onSave={save}
           saveLabel={journal ? "Save draft" : "Save as draft"}>
      <div className="grid grid-cols-5 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1">
        <Field label="Journal date" required>
          <TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Type">
          <Select value={type} placeholder="Manual" onChange={(e) => setType(e.target.value || "MANUAL")}
            options={[{ value: "MANUAL", label: "Manual journal" }, { value: "ADJUSTMENT", label: "Adjustment" }]} />
        </Field>
        <Field label="Branch">
          <Select value={branch} placeholder="Company level" onChange={(e) => setBranch(e.target.value)}
            options={(ctx?.branches ?? []).map((b) => ({ value: b.id, label: `${b.code} — ${b.name}` }))} />
        </Field>
        <Field label="Reference">
          <TextInput value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Voucher / document no." />
        </Field>
        <Field label="Narration">
          <TextInput value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this entry records" />
        </Field>
      </div>

      {/* Tall enough that an account list opened on the last line has room to drop down
          inside the box, which scrolls sideways and so clips anything below it (owner, 20-Oct-2026). */}
      <div className="mt-5 min-h-[420px] overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[1000px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line text-[11.5px] font-semibold text-primary">
              <th className="w-10 px-2 py-2.5">#</th>
              <th className="w-[300px] px-2 py-2.5">Account</th>
              <th className="px-2 py-2.5">Line description</th>
              <th className="w-[190px] px-2 py-2.5">Party</th>
              <th className="w-[150px] px-2 py-2.5">Cost centre</th>
              <th className="w-[130px] px-2 py-2.5 text-right">Debit</th>
              <th className="w-[130px] px-2 py-2.5 text-right">Credit</th>
              <th className="w-10" />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => {
              const account = byId.get(l.account_id);
              const partyRole = account?.control_type === "RECEIVABLE" ? "customer"
                : account?.control_type === "PAYABLE" ? "supplier" : null;
              return (
                <tr key={l.key} className="border-b border-line last:border-0">
                  <td className="px-2 py-1.5 text-[12px] text-faint">{i + 1}</td>
                  <td className="px-2 py-1.5">
                    <Combobox value={l.account_id} options={accountOptions} placeholder="Account…"
                      onChange={(v) => update(l.key, { account_id: v, customer_id: null, supplier_id: null, party_label: null })} />
                  </td>
                  <td className="px-2 py-1.5">
                    <input className={`${cell} w-full`} value={l.description}
                      onChange={(e) => update(l.key, { description: e.target.value })} />
                  </td>
                  <td className="px-2 py-1.5">
                    {partyRole ? (
                      <PartnerPicker role={partyRole} value={partyRole === "customer" ? l.customer_id : l.supplier_id}
                        label={l.party_label}
                        onChange={(id, label) => update(l.key, partyRole === "customer"
                          ? { customer_id: id, party_label: label } : { supplier_id: id, party_label: label })} />
                    ) : <span className="text-[11.5px] text-faint">—</span>}
                  </td>
                  <td className="px-2 py-1.5">
                    <select className={`${cell} w-full`} value={l.cost_center_id}
                      onChange={(e) => update(l.key, { cost_center_id: e.target.value })}>
                      <option value="">—</option>
                      {(centers ?? []).filter((c) => c.is_active).map((c) => (
                        <option key={c.id} value={c.id}>{c.code} {c.name}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-1.5">
                    <input className={`${cell} w-full text-right tabular-nums`} inputMode="decimal" value={l.debit}
                      onChange={(e) => update(l.key, { debit: e.target.value, credit: e.target.value ? "" : l.credit })} />
                  </td>
                  <td className="px-2 py-1.5">
                    <input className={`${cell} w-full text-right tabular-nums`} inputMode="decimal" value={l.credit}
                      onChange={(e) => update(l.key, { credit: e.target.value, debit: e.target.value ? "" : l.debit })} />
                  </td>
                  <td className="px-1 py-1.5">
                    <button type="button" aria-label="Remove line" disabled={lines.length <= 2}
                      onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
                      className="rounded p-1 text-faint hover:bg-rose/10 hover:text-rose disabled:opacity-30">
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-line text-[12.5px] font-semibold">
              <td colSpan={3} className="px-2 py-2.5">
                <button type="button" onClick={() => setLines((ls) => [...ls, blank()])}
                  className="flex items-center gap-1 text-[12px] font-medium text-primary hover:underline">
                  <Plus size={13} /> Add line
                </button>
              </td>
              <td colSpan={2} className={`px-2 py-2.5 text-right ${difference === 0 ? "text-success" : "text-rose"}`}>
                {difference === 0 ? (totalDr > 0 ? "Balanced" : "") : `Out by ${money(Math.abs(difference) / 100)}`}
              </td>
              <td className="px-2 py-2.5 text-right tabular-nums">{money(totalDr / 100)}</td>
              <td className="px-2 py-2.5 text-right tabular-nums">{money(totalCr / 100)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
        {totalDr > 0 && (
          <p className="m-0 border-t border-line px-3 py-2.5 text-[12.5px]">
            <span className="text-faint">Amount in words: </span>
            <b>{rupeesInWords(Math.max(totalDr, totalCr))}</b>
          </p>
        )}
      </div>
      <p className="mb-0 mt-3 text-[11px] text-faint">
        A line on the customer account (Accounts Receivable) needs the customer named; on posting it goes
        into that customer&apos;s balance, aging and statement. Payables, inventory, GRNI and customer advances
        are posted by their own documents only.
      </p>
    </Modal>
  );
}
