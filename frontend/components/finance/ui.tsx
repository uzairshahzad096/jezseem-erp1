"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, X } from "lucide-react";
import { api } from "@/lib/api";
import { statusTone } from "@/lib/finance";
import { Field, Modal, TextArea } from "@/components/ui/Modal";

/** DRAFT / POSTED / … as a small coloured pill. */
export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11px]
                      font-semibold tracking-wide ${statusTone(status)}`}>
      {status}
    </span>
  );
}

export function PageHeader({ title, subtitle, children }: {
  title: string; subtitle?: React.ReactNode; children?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-center gap-3">
      <div className="min-w-0">
        <h1 className="m-0 text-[19px] font-semibold">{title}</h1>
        {subtitle && <p className="m-0 mt-0.5 text-[12px] text-muted">{subtitle}</p>}
      </div>
      {children && <div className="ml-auto flex flex-wrap items-center gap-2.5">{children}</div>}
    </div>
  );
}

export const filterClass =
  "rounded-lg border border-line bg-bg px-3 py-2 text-[12.5px] outline-none focus:border-primary";

export function Button({
  children, onClick, tone = "plain", disabled, busy, title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  tone?: "primary" | "plain" | "danger" | "soft";
  disabled?: boolean;
  busy?: boolean;
  title?: string;
}) {
  const tones = {
    primary: "bg-gradient-to-br from-primary to-primary-dark text-on-primary hover:opacity-90",
    plain: "bg-hover text-muted hover:text-text",
    soft: "bg-primary/10 text-primary hover:bg-primary/15",
    danger: "bg-rose/10 text-rose hover:bg-rose/20",
  };
  return (
    <button type="button" onClick={onClick} disabled={disabled || busy} title={title}
      className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3.5 py-2 text-[12.5px]
                  font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${tones[tone]}`}>
      {busy && <Loader2 size={13} className="animate-spin" />}
      {children}
    </button>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="mb-4 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{message}</p>;
}

export function Card({ title, action, children, className = "" }: {
  title?: string; action?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-[14px] border border-line bg-surface shadow-panel ${className}`}>
      {(title || action) && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5">
          {title && <h3 className="m-0 text-[14px] font-semibold">{title}</h3>}
          {action && <div className="ml-auto flex flex-wrap items-center gap-2">{action}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/**
 * Ask for a reason before an irreversible or audited action: cancel,
 * reject, reverse, reopen. The reason goes into the audit log.
 */
export function ReasonDialog({
  open, title, label = "Reason", confirmLabel, required = true, onClose, onConfirm, children,
}: {
  open: boolean;
  title: string;
  label?: string;
  confirmLabel: string;
  required?: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void>;
  children?: React.ReactNode;
}) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (open) { setReason(""); setError(null); } }, [open]);

  const confirm = async () => {
    if (required && reason.trim().length < 3) { setError("Give a reason; it is kept in the audit log."); return; }
    setSaving(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The action failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={title} open={open} width="md" saving={saving} error={error}
           onClose={onClose} onSave={confirm} saveLabel={confirmLabel}>
      <div className="space-y-4">
        {children}
        <Field label={label} required={required}>
          <TextArea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

interface PartnerOption { id: string; code: string; name: string }

/**
 * Customer or supplier search. There are over a thousand customers, too
 * many for a dropdown, so it asks the server as you type.
 */
export function PartnerPicker({
  role, value, label, onChange,
}: {
  role: "customer" | "supplier";
  value: string | null | undefined;
  label?: string | null;
  onChange: (id: string | null, label: string | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<PartnerOption[]>([]);
  const [box, setBox] = useState<{ left: number; top: number; width: number } | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(async () => {
      try {
        const qs = new URLSearchParams({ role, page_size: "20" });
        if (query) qs.set("search", query);
        const data = await api.get<{ items: PartnerOption[] }>(`/partners?${qs}`);
        setResults(data.items);
      } catch { setResults([]); }
    }, 250);
    return () => clearTimeout(t);
  }, [query, open, role]);

  useEffect(() => {
    if (!open) return;
    const rect = wrapper.current?.getBoundingClientRect();
    if (rect) setBox({ left: rect.left, top: rect.bottom + 4, width: Math.max(rect.width, 260) });
    const close = (e: MouseEvent) => {
      if (!wrapper.current?.contains(e.target as Node)
          && !(e.target as HTMLElement).closest?.("[data-partner-list]")) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={wrapper} className="relative">
      <input
        value={open ? query : (label ?? "")}
        onFocus={() => { setQuery(""); setOpen(true); }}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={role === "customer" ? "Customer…" : "Supplier…"}
        className="w-full rounded-md border border-line bg-bg px-2 py-1.5 pr-6 text-[12px] outline-none focus:border-primary"
      />
      {value && (
        <button type="button" aria-label="Clear" onClick={() => onChange(null, null)}
          className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 text-faint hover:text-text">
          <X size={12} />
        </button>
      )}
      {open && box && createPortal(
        <ul data-partner-list style={{ left: box.left, top: box.top, width: box.width }}
            className="fixed z-[70] max-h-56 list-none overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-xl">
          {results.length === 0 && <li className="px-3 py-2 text-[12px] text-faint">No match.</li>}
          {results.map((p) => (
            <li key={p.id}>
              <button type="button"
                onClick={() => { onChange(p.id, `${p.code} ${p.name}`); setOpen(false); }}
                className="w-full rounded-md px-3 py-1.5 text-left text-[12.5px] hover:bg-primary/10 hover:text-primary">
                <span className="text-muted">{p.code}</span> {p.name}
              </button>
            </li>
          ))}
        </ul>,
        document.body,
      )}
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-12 text-center text-[12.8px] text-faint">{children}</div>;
}

export function Spinner() {
  return <div className="px-5 py-12 text-center"><Loader2 size={18} className="mx-auto animate-spin text-primary" /></div>;
}
