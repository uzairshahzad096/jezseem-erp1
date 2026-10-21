"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

/* ---------------------------------------------------------------- types */

export interface FinanceContextInfo {
  company: { id: string; name: string; code: string; currency: string };
  branches: { id: string; code: string; name: string }[];
  branch_id: string | null;
  financial_years: { id: string; name: string; start_date: string; end_date: string; is_current: boolean }[];
  current_period: { id: string; name: string; status: string } | null;
  has_chart: boolean;
}

export interface Account {
  id: string;
  code: string;
  name: string;
  account_type_id: string;
  account_type: string;
  account_type_name: string;
  account_group_id: string | null;
  account_group: string | null;
  parent_id: string | null;
  normal_balance: "DEBIT" | "CREDIT";
  is_postable: boolean;
  is_control_account: boolean;
  control_type: string | null;
  allow_manual_posting: boolean;
  is_active: boolean;
  currency: string | null;
  description: string | null;
  balance: number | null;
  /** Set on a receivable / payable control account: the customers or suppliers behind it. */
  subledger?: { kind: "customer" | "supplier"; count: number } | null;
}

export interface JournalLine {
  id?: string;
  line_number?: number;
  account_id: string;
  account_code?: string | null;
  account_name?: string | null;
  description: string | null;
  debit: number;
  credit: number;
  customer_id?: string | null;
  supplier_id?: string | null;
  party?: string | null;
  item_code?: string | null;
  quantity?: number | null;
  cost_center_id?: string | null;
  cost_center?: string | null;
  branch_id?: string | null;
  branch?: string | null;
}

export interface Journal {
  id: string;
  journal_number: string;
  journal_date: string;
  journal_type: string;
  status: string;
  description: string | null;
  reference: string | null;
  event_code: string | null;
  document_type: string | null;
  document_id: string | null;
  source_module: string | null;
  source_reference: string | null;
  branch_id: string | null;
  branch: string | null;
  currency: string;
  total_debit: number;
  total_credit: number;
  created_by: string | null;
  created_at: string;
  posted_by: string | null;
  posted_at: string | null;
}

export interface JournalDetail extends Journal {
  financial_year: string | null;
  period: { id: string; name: string; status: string } | null;
  submitted_by: string | null;
  submitted_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  cancelled_by: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  reversed_entry: { id: string; journal_number: string } | null;
  reversed_by_entry: { id: string; journal_number: string } | null;
  lines: JournalLine[];
}

/* ---------------------------------------------------------------- formatting */

/** 1,234,567.50 — two decimals always, as accounts are read. */
export const money = (n: number | null | undefined): string =>
  typeof n === "number" && Number.isFinite(n)
    ? n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "0.00";

/** Blank rather than 0.00, for the empty side of a debit/credit pair. */
export const moneyOrBlank = (n: number | null | undefined): string =>
  typeof n === "number" && n !== 0 ? money(n) : "";

/** A debit-positive balance written with its side: 1,000.00 Dr / 500.00 Cr. */
export const drcr = (n: number | null | undefined): string => {
  if (typeof n !== "number" || n === 0) return "0.00";
  return `${money(Math.abs(n))} ${n > 0 ? "Dr" : "Cr"}`;
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 15-Jul-2026 */
export const fmtDate = (iso: string | null | undefined): string => {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return d && m && y ? `${d}-${MONTHS[Number(m) - 1] ?? m}-${y}` : iso;
};

export const fmtDateTime = (iso: string | null | undefined): string =>
  iso ? `${fmtDate(iso)} ${new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "";

export const errorText = (err: unknown, fallback: string) =>
  err instanceof Error ? err.message : fallback;

/* ---------------------------------------------------------------- status */

const STATUS_TONE: Record<string, string> = {
  DRAFT: "bg-hover text-muted",
  SUBMITTED: "bg-sky/15 text-sky",
  APPROVED: "bg-violet/15 text-violet",
  POSTED: "bg-success/15 text-success",
  REVERSED: "bg-amber/15 text-amber",
  CANCELLED: "bg-rose/10 text-rose",
  VALIDATED: "bg-sky/15 text-sky",
  COMPLETED: "bg-success/15 text-success",
  OPEN: "bg-success/15 text-success",
  CLOSED: "bg-amber/15 text-amber",
  LOCKED: "bg-rose/10 text-rose",
};

export const statusTone = (status: string) => STATUS_TONE[status] ?? "bg-hover text-muted";

/* ---------------------------------------------------------------- drill-down */

/**
 * Where a journal's source document lives. Phase 1 journals come from the
 * finance module itself; sales, purchase and inventory documents are added
 * here as those modules start posting.
 */
export function sourceLink(documentType: string | null, documentId: string | null): string | null {
  if (!documentType || !documentId) return null;
  switch (documentType) {
    case "OPENING_BALANCE_BATCH":
      return `/finance/opening-balances?batch=${documentId}`;
    case "SALES_ORDER":
    case "SALES_INVOICE":
      return `/inventory/transactions/sales-orders?open=${documentId}`;
    case "GOODS_RECEIPT":
      return `/inventory/inhouse-orders/goods-receipts?open=${documentId}`;
    default:
      return null;
  }
}

/* ---------------------------------------------------------------- downloads */

/** Fetch a file from the API with the session token and save it. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail = `Could not build the file (${res.status}).`;
    try { detail = (await res.json()).detail ?? detail; } catch { /* no body */ }
    throw new Error(detail);
  }
  const named = /filename="?([^"]+)"?/.exec(res.headers.get("content-disposition") ?? "");
  const url = URL.createObjectURL(await res.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = named?.[1] ?? fallbackName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Multipart upload with extra form fields. */
export async function uploadForm<T>(path: string, form: FormData): Promise<T> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST", body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    throw new Error(`Cannot reach the ERP server at ${BASE}.`);
  }
  if (!res.ok) {
    let detail = `Upload failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* no body */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/* ---------------------------------------------------------------- hooks */

/** GET a finance endpoint, with loading/error state and a reload. */
export function useFinance<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!path) { setData(null); setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      setData(await api.get<T>(path));
    } catch (err) {
      setError(errorText(err, "Could not load."));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => { load(); }, [load]);
  return { data, loading, error, reload: load, setData };
}

export function useFinanceContext() {
  return useFinance<FinanceContextInfo>("/finance/context");
}

/** Postable, active accounts as picker options. */
export function useAccountOptions(manualOnly = false) {
  const { data } = useFinance<Account[]>(
    `/finance/accounts?postable_only=true&active_only=true${manualOnly ? "&manual_only=true" : ""}`);
  return (data ?? []).map((a) => ({ value: a.id, label: `${a.code}  ${a.name}`, short: `${a.code} ${a.name}` }));
}
