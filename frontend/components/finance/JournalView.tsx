"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { Modal, Field, TextInput } from "@/components/ui/Modal";
import { gridCellClass, gridRowClass, GridTh } from "@/components/ui/grid";
import { Button, ReasonDialog, StatusBadge } from "@/components/finance/ui";
import {
  errorText, fmtDate, fmtDateTime, money, moneyOrBlank, sourceLink, type JournalDetail,
} from "@/lib/finance";

interface AuditRow { id: string; occurred_at: string; username: string | null; action: string; reason: string | null }

/**
 * One journal: header, lines, who did what, and the actions its status
 * allows. Opened from the journal list, the general ledger and the trial
 * balance, so a figure can always be traced back to its entry.
 */
export function JournalView({
  journalId, onClose, onChanged, onEdit, onOpen,
}: {
  journalId: string;
  onClose: () => void;
  onChanged?: () => void;
  onEdit?: (journal: JournalDetail) => void;
  /** Open another journal (a reversal, say) in place. */
  onOpen?: (id: string) => void;
}) {
  const [journal, setJournal] = useState<JournalDetail | null>(null);
  const [history, setHistory] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"cancel" | "reject" | "reverse" | null>(null);
  const [reversalDate, setReversalDate] = useState(new Date().toISOString().slice(0, 10));

  const load = async () => {
    setError(null);
    try {
      setJournal(await api.get<JournalDetail>(`/finance/journals/${journalId}`));
      try {
        const audit = await api.get<{ items: AuditRow[] }>(
          `/finance/audit-logs?entity=journal_entries&entity_id=${journalId}&page_size=50`);
        setHistory(audit.items);
      } catch { setHistory([]); /* the audit log needs its own permission */ }
    } catch (err) {
      setError(errorText(err, "Could not load the journal."));
    }
  };

  useEffect(() => { load(); }, [journalId]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (step: string, body?: unknown) => {
    setBusy(step);
    setError(null);
    try {
      const updated = await api.post<JournalDetail>(`/finance/journals/${journalId}/${step}`, body ?? {});
      onChanged?.();
      if (step === "reverse") { onOpen?.(updated.id); return; }
      await load();
    } catch (err) {
      setError(errorText(err, `Could not ${step} the journal.`));
      throw err;
    } finally {
      setBusy(null);
    }
  };
  const quiet = (step: string) => () => { act(step).catch(() => undefined); };

  const j = journal;
  const source = j ? sourceLink(j.document_type, j.document_id) : null;
  const canReverse = j?.status === "POSTED" && !["REVERSAL", "OPENING"].includes(j.journal_type);

  return (
    <>
      <Modal title={j ? `Journal ${j.journal_number}` : "Journal"} open width="lg" error={error} onClose={onClose}>
        {!j ? (
          <p className="text-[12.5px] text-faint">Loading…</p>
        ) : (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2.5">
              <StatusBadge status={j.status} />
              <span className="rounded-full bg-hover px-2.5 py-[3px] text-[11px] font-medium text-muted">
                {j.journal_type}
              </span>
              <div className="ml-auto flex flex-wrap gap-2">
                {j.status === "DRAFT" && onEdit && ["MANUAL", "ADJUSTMENT"].includes(j.journal_type) && (
                  <Button onClick={() => onEdit(j)}>Edit</Button>
                )}
                {j.status === "DRAFT" && <Button tone="soft" busy={busy === "submit"} onClick={quiet("submit")}>Submit for approval</Button>}
                {j.status === "SUBMITTED" && <Button tone="soft" busy={busy === "approve"} onClick={quiet("approve")}>Approve</Button>}
                {j.status === "APPROVED" && <Button tone="primary" busy={busy === "post"} onClick={quiet("post")}>Post to ledger</Button>}
                {["SUBMITTED", "APPROVED"].includes(j.status) && <Button onClick={() => setDialog("reject")}>Reject</Button>}
                {["DRAFT", "SUBMITTED", "APPROVED"].includes(j.status) && <Button tone="danger" onClick={() => setDialog("cancel")}>Cancel journal</Button>}
                {canReverse && <Button tone="danger" onClick={() => setDialog("reverse")}>Reverse</Button>}
              </div>
            </div>

            <dl className="grid grid-cols-4 gap-x-5 gap-y-3 text-[12.5px] max-md:grid-cols-2">
              <Fact label="Date">{fmtDate(j.journal_date)}</Fact>
              <Fact label="Period">{j.period ? `${j.period.name} (${j.period.status})` : "—"}</Fact>
              <Fact label="Financial year">{j.financial_year ?? "—"}</Fact>
              <Fact label="Branch">{j.branch ?? "Company level"}</Fact>
              <Fact label="Reference">{j.reference ?? "—"}</Fact>
              <Fact label="Source">
                {j.source_reference || j.source_module || "—"}
                {source && (
                  <Link href={source} className="ml-1.5 inline-flex items-center gap-0.5 text-primary hover:underline">
                    open <ExternalLink size={11} />
                  </Link>
                )}
              </Fact>
              <Fact label="Event">{j.event_code ?? "—"}</Fact>
              <Fact label="Currency">{j.currency}</Fact>
              {j.reversed_entry && (
                <Fact label="Reverses">
                  <button className="text-primary hover:underline" onClick={() => onOpen?.(j.reversed_entry!.id)}>
                    {j.reversed_entry.journal_number}
                  </button>
                </Fact>
              )}
              {j.reversed_by_entry && (
                <Fact label="Reversed by">
                  <button className="text-primary hover:underline" onClick={() => onOpen?.(j.reversed_by_entry!.id)}>
                    {j.reversed_by_entry.journal_number}
                  </button>
                </Fact>
              )}
            </dl>
            {j.description && <p className="m-0 rounded-lg bg-bg px-3.5 py-2.5 text-[12.5px]">{j.description}</p>}
            {j.cancel_reason && (
              <p className="m-0 rounded-lg bg-rose/10 px-3.5 py-2.5 text-[12.5px] text-rose">
                Cancelled: {j.cancel_reason}
              </p>
            )}

            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full min-w-[720px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-line">
                    <GridTh>#</GridTh><GridTh>Account</GridTh><GridTh>Description</GridTh>
                    <GridTh>Party / Item</GridTh><GridTh>Cost Centre</GridTh>
                    <GridTh numeric>Debit</GridTh><GridTh numeric>Credit</GridTh>
                  </tr>
                </thead>
                <tbody>
                  {j.lines.map((l, i) => (
                    <tr key={l.id} className={gridRowClass(i)}>
                      <td className={gridCellClass()}>{l.line_number}</td>
                      <td className={gridCellClass()}>
                        <span className="font-medium">{l.account_code}</span>{" "}
                        <span className="text-muted">{l.account_name}</span>
                      </td>
                      <td className={gridCellClass()}>{l.description}</td>
                      <td className={gridCellClass()}>
                        {l.party ?? (l.item_code ? `${l.item_code}${l.quantity ? ` × ${l.quantity}` : ""}` : "")}
                      </td>
                      <td className={gridCellClass()}>{l.cost_center ?? ""}</td>
                      <td className={gridCellClass(true)}>{moneyOrBlank(l.debit)}</td>
                      <td className={gridCellClass(true)}>{moneyOrBlank(l.credit)}</td>
                    </tr>
                  ))}
                  <tr className="border-t-2 border-line font-semibold">
                    <td className={gridCellClass()} colSpan={5}>Total</td>
                    <td className={gridCellClass(true)}>{money(j.total_debit)}</td>
                    <td className={gridCellClass(true)}>{money(j.total_credit)}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="grid grid-cols-2 gap-5 max-md:grid-cols-1">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
                <Fact label="Created">{j.created_by ?? "—"} · {fmtDateTime(j.created_at)}</Fact>
                <Fact label="Submitted">{j.submitted_by ? `${j.submitted_by} · ${fmtDateTime(j.submitted_at)}` : "—"}</Fact>
                <Fact label="Approved">{j.approved_by ? `${j.approved_by} · ${fmtDateTime(j.approved_at)}` : "—"}</Fact>
                <Fact label="Posted">{j.posted_by ? `${j.posted_by} · ${fmtDateTime(j.posted_at)}` : "—"}</Fact>
              </dl>
              {history.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[11.5px] font-medium text-muted">Audit trail</div>
                  <ul className="m-0 max-h-40 list-none space-y-1 overflow-y-auto p-0 text-[12px]">
                    {history.map((h) => (
                      <li key={h.id} className="flex gap-2">
                        <span className="w-32 flex-shrink-0 text-faint">{fmtDateTime(h.occurred_at)}</span>
                        <span className="font-medium">{h.action}</span>
                        <span className="text-muted">{h.username}</span>
                        {h.reason && <span className="truncate text-muted" title={h.reason}>— {h.reason}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            {j.status === "POSTED" && (
              <p className="m-0 text-[11.5px] text-faint">
                A posted journal cannot be edited or deleted. Correct it with a reversal or an adjustment journal.
              </p>
            )}
          </div>
        )}
      </Modal>

      <ReasonDialog open={dialog === "cancel"} title="Cancel journal" confirmLabel="Cancel journal"
        onClose={() => setDialog(null)} onConfirm={(reason) => act("cancel", { reason })} />
      <ReasonDialog open={dialog === "reject"} title="Reject journal" confirmLabel="Return to draft"
        onClose={() => setDialog(null)} onConfirm={(reason) => act("reject", { reason })} />
      <ReasonDialog open={dialog === "reverse"} title={`Reverse ${j?.journal_number ?? ""}`}
        confirmLabel="Post reversal" onClose={() => setDialog(null)}
        onConfirm={(reason) => act("reverse", { reason, reversal_date: reversalDate })}>
        <p className="m-0 text-[12.5px] text-muted">
          A mirror-image journal is posted on the date below. The original stays in the ledger,
          marked reversed, and the two are linked.
        </p>
        <Field label="Reversal date" required>
          <TextInput type="date" value={reversalDate} onChange={(e) => setReversalDate(e.target.value)} />
        </Field>
      </ReasonDialog>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-faint">{label}</dt>
      <dd className="m-0 truncate">{children}</dd>
    </div>
  );
}
