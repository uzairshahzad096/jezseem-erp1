"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePageSize } from "@/lib/usePageSize";

export interface SalesDocSummary {
  id: string;
  doc_number: string;
  doc_date: string;
  customer_id: string;
  customer_name: string | null;
  status: string;
  payment_status: string | null;
  demand_number: string | null;
  customer_po_number: string | null;
  delivery_person: string | null;
  vehicle_number: string | null;
  location: string | null;
  payment_terms: string | null;
  dc_number: string | null;
  /** Number of the quotation this document was raised from, if any. */
  source_doc_number: string | null;
  /** Taken from the customer's ledger account, for the grid's GST/NTN columns. */
  customer_ntn: string | null;
  customer_stn: string | null;
  gross_amount: number;
  discount_amount: number;
  freight_amount: number;
  with_sales_tax: boolean;
  is_service?: boolean;
  currency: string;
  remarks: string | null;
  /** Every line's description joined together — the old ERP's Detail Items
   *  cell, so the grid says what a document is for without opening it. */
  detail_items: string | null;
  net_receivable: number;
  sales_tax_value: number;
  excluding_tax_value: number;
  total_items: number;
  source_document_id: string | null;
}

export interface SalesDocDetail extends SalesDocSummary {
  lines: {
    id: string;
    item_id: string | null;
    item_code: string | null;
    description: string;
    uom: string | null;
    hs_code: string | null;
    quantity: number;
    unit_price: number;
    currency: string;
    rack_name: string | null;
    stock: number | null;
    /** The product's own selling price, for the Sale Rate column. */
    sale_rate: number | null;
    discount_percent: number;
    tax_percent: number;
    taxable_amount: number;
    tax_amount: number;
    net_amount: number;
  }[];
}

/** Listing state for quotations or sales orders: search, status filter,
 *  sorting and paging, all resolved server-side.
 *
 *  `initialStatuses` seeds the filter so the first request is already
 *  narrowed. Set it here rather than toggling from a mount effect: a toggle
 *  runs twice under React's development double-invoke and cancels itself. */
export function useSalesDocs(
  path: string, defaultPageSize = 25, initialStatuses: string[] = [], initialSearch = "",
) {
  const [pageSize, setPageSize] = usePageSize(path, defaultPageSize);
  const [rows, setRows] = useState<SalesDocSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  // Seeded the same way as the statuses, and for the same reason: arriving
  // from a report's Doc Id link, the first request should already be narrowed.
  const [search, setSearch] = useState(initialSearch);
  const [statuses, setStatuses] = useState<string[]>(initialStatuses);
  const [sort, setSort] = useState("doc_date");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        page: String(page), page_size: String(pageSize), sort, direction,
      });
      if (search) qs.set("search", search);
      statuses.forEach((s) => qs.append("status", s));
      const data = await api.get<{ items: SalesDocSummary[]; total: number }>(`${path}?${qs}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load records.");
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [path, page, pageSize, search, statuses, sort, direction]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  const toggleStatus = (value: string) => {
    setStatuses((s) => (s.includes(value) ? s.filter((v) => v !== value) : [...s, value]));
    setPage(1);
  };

  const toggleSort = (column: string) => {
    if (sort === column) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(column); setDirection("desc"); }
  };

  // Back to the view the screen opens with — the state it was seeded with,
  // not a blank one, so a picker that starts narrowed to Approved stays that
  // way when its filters are cleared.
  const reset = () => {
    setSearch(initialSearch);
    setStatuses(initialStatuses);
    setSort("doc_date");
    setDirection("desc");
    setPage(1);
  };

  const dirty =
    search !== initialSearch ||
    statuses.join() !== initialStatuses.join() ||
    sort !== "doc_date" || direction !== "desc";

  return {
    rows, total, page, pageSize, search, statuses, sort, direction, loading, error,
    setPage, setSearch: (v: string) => { setSearch(v); setPage(1); },
    toggleStatus, toggleSort, reload: load, reset, dirty,
    setPageSize: (n: number) => { setPageSize(n); setPage(1); },
  };
}

/** Opens a generated PDF in a new tab, where the browser's own viewer
 *  provides both print and download. */
export async function openDocumentPdf(docId: string, kind: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
  const url = `${base}/documents/sales/${docId}/${kind}.pdf`;
  const win = window.open("", "_blank");
  try {
    const token = sessionStorage.getItem("jezseem-access-token");
    const res = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let detail = `Could not generate the document (${res.status}).`;
      try { detail = (await res.json()).detail ?? detail; } catch { /* no body */ }
      win?.close();
      alert(detail);
      return;
    }
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    if (win) win.location.href = blobUrl;
    else window.open(blobUrl, "_blank");
  } catch {
    win?.close();
    alert("Could not reach the server to generate this document.");
  }
}
