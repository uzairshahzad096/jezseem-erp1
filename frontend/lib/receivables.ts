"use client";

/** Types and helpers for sales invoices, notes, receipts and AR reports. */

export type DocType = "sales_invoice" | "credit_note" | "debit_note";

export const DOC_META: Record<DocType, { path: string; label: string; plural: string; perm: string }> = {
  sales_invoice: { path: "invoices", label: "Sales Invoice", plural: "Sales Invoices", perm: "sales.invoice" },
  credit_note: { path: "credit-notes", label: "Credit Note", plural: "Credit Notes", perm: "ar.credit_note" },
  debit_note: { path: "debit-notes", label: "Debit Note", plural: "Debit Notes", perm: "ar.credit_note" },
};

export interface DocLine {
  id?: string;
  item_id: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  lot_number?: string | null;
  quantity: number | string;
  unit_price: number | string;
  discount_percent: number | string;
  tax_code_id: string | null;
  tax_percent?: number;
  taxable_amount?: number;
  tax_amount?: number;
  net_amount?: number;
  source_line_id?: string | null;
  gate_pass_line_id?: string | null;
  max_quantity?: number | null;
}

export interface DocSummary {
  id: string;
  doc_type: DocType;
  doc_number: string;
  doc_date: string;
  due_date: string | null;
  customer_id: string;
  customer_name: string | null;
  customer_code: string | null;
  status: string;
  payment_status: string | null;
  overdue: boolean;
  currency: string;
  excluding_tax_value: number;
  sales_tax_value: number;
  discount_amount: number;
  freight_amount: number;
  net_total: number;
  paid: number;
  outstanding: number;
  is_cash_sale: boolean;
  credit_check_status: string | null;
}

export interface DocDetail extends DocSummary {
  customer: { id: string; code: string; name: string; address: string | null; ntn: string | null;
              stn: string | null; credit_limit: number | null };
  exchange_rate: number;
  payment_term_id: string | null;
  payment_terms: string | null;
  due_date_overridden: boolean;
  billing_address: string | null;
  shipping_address: string | null;
  customer_po_number: string | null;
  location: string | null;
  remarks: string | null;
  tax_inclusive: boolean;
  cash_account_id: string | null;
  reason_code: string | null;
  reason: string | null;
  cancel_reason: string | null;
  source_document_id: string | null;
  quotation_id: string | null;
  gate_pass_id: string | null;
  branch_id: string | null;
  references: Record<string, { id: string; doc_type?: string; doc_number: string } | null>;
  journal?: { id: string; journal_number: string };
  cancel_journal?: { id: string; journal_number: string };
  created_by: string | null; created_at: string;
  confirmed_by: string | null; confirmed_at: string | null;
  posted_by: string | null; posted_at: string | null;
  cancelled_by: string | null; cancelled_at: string | null;
  credit_approved_by: string | null;
  allocations: { id: string; document_number: string; item_type: string; receipt_id: string | null;
                 sales_document_id: string | null; amount: number; date: string; status: string;
                 reason: string | null }[];
  order_progress: { line_id: string; description: string; ordered: number; delivered: number;
                    invoiced: number; remaining: number }[] | null;
  lines: DocLine[];
  credit_check?: { policy: string; credit_limit: number | null; current_outstanding: number;
                   document_total: number; after_posting: number; exceeded: boolean; message?: string } | null;
}

export interface OpenItem {
  item_id: string;
  item_type: string;
  kind: string;
  document_number: string;
  document_date: string;
  due_date: string | null;
  sales_document_id: string | null;
  receipt_id: string | null;
  currency: string;
  amount: number;
  outstanding: number;
  is_credit: boolean;
  overdue: boolean;
}

export interface Receipt {
  id: string;
  receipt_number: string;
  receipt_date: string;
  customer_id: string;
  customer_name: string;
  customer_code: string;
  payment_method_id: string;
  payment_method: string;
  method_kind: string;
  deposit_account_id: string;
  deposit_account: string;
  amount: number;
  currency: string;
  exchange_rate: number;
  amount_base: number;
  reference: string | null;
  cheque_number: string | null;
  cheque_date: string | null;
  /** Tax the customer withheld, included in `amount`. */
  wht_amount: number;
  bank_name: string | null;
  notes: string | null;
  status: string;
  planned_allocations: { item_id: string; amount: string; document_number: string }[];
  allocations: { id: string; item_id: string; document_number: string; sales_document_id: string | null;
                 amount: number; date: string; status: string; reason: string | null }[];
  allocated: number;
  unallocated: number;
  allocation_status: string;
  journal?: { id: string; journal_number: string };
  reversal_journal?: { id: string; journal_number: string };
  created_by: string | null; created_at: string;
  posted_by: string | null; posted_at: string | null;
  reversed_by: string | null; reversed_at: string | null; reverse_reason: string | null;
}

export interface TaxCode { id: string; code: string; name: string; tax_type: string; rate: number;
                           is_active: boolean; output_account_id: string | null;
                           effective_from: string | null; effective_to: string | null; description: string | null }
export interface PaymentTerm { id: string; code: string; name: string; days: number; is_cash: boolean;
                               is_active: boolean; sort_order: number }
export interface PaymentMethod { id: string; code: string; name: string; kind: string; requires_reference: boolean;
                                 default_account_id: string | null; is_active: boolean; sort_order: number }
export interface ARSettings { credit_limit_policy: string; sales_order_cutoff_date: string | null;
                              allow_quotation_invoice: boolean; default_payment_term_id: string | null;
                              aging_buckets: string; cash_accounts: { id: string; label: string; control_type: string }[] }

const PAYMENT_TONE: Record<string, string> = {
  OPEN: "bg-sky/15 text-sky",
  PARTIALLY_PAID: "bg-amber/15 text-amber",
  PAID: "bg-success/15 text-success",
  UNAPPLIED: "bg-sky/15 text-sky",
  PARTLY_APPLIED: "bg-amber/15 text-amber",
  APPLIED: "bg-success/15 text-success",
  FULLY_ALLOCATED: "bg-success/15 text-success",
  PARTLY_ALLOCATED: "bg-amber/15 text-amber",
  UNALLOCATED: "bg-sky/15 text-sky",
  PLANNED: "bg-hover text-muted",
  REVERSED: "bg-rose/10 text-rose",
};
export const paymentTone = (s: string | null) => (s ? PAYMENT_TONE[s] ?? "bg-hover text-muted" : "");
export const paymentLabel = (s: string | null) => (s ? s.replace(/_/g, " ") : "");

/**
 * Client-side preview of the server's line maths (app/common/calculations.py),
 * for feedback while typing only. The server recalculates on save and its
 * figures are the ones stored.
 */
export function previewLine(qty: number, price: number, discPct: number, rate: number, inclusive: boolean) {
  const r2 = (n: number) => Math.round(n * 100) / 100;
  const gross = r2(qty * price);
  const discount = Math.min(r2((gross * discPct) / 100), gross);
  if (inclusive) {
    const total = r2(gross - discount);
    const taxable = r2((total * 100) / (100 + rate));
    return { taxable, tax: r2(total - taxable), total };
  }
  const taxable = r2(gross - discount);
  const tax = r2((taxable * rate) / 100);
  return { taxable, tax, total: r2(taxable + tax) };
}

export const CREDIT_REASONS = [
  ["SALES_RETURN", "Sales return"], ["PRICE_CORRECTION", "Pricing correction"], ["DISCOUNT", "Discount adjustment"],
  ["TAX_CORRECTION", "Tax correction"], ["CANCELLATION", "Invoice cancellation adjustment"], ["OTHER", "Other"],
] as const;
