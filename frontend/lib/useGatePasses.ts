"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePageSize } from "@/lib/usePageSize";

export interface GatePassSummary {
  id: string;
  doc_number: string;
  doc_date: string;
  pass_type: string;
  party_id: string | null;
  party_name: string | null;
  party_address: string | null;
  vehicle_number: string | null;
  driver: string | null;
  issue_type: string | null;
  issue_to: string | null;
  location: string | null;
  dc_number: string | null;
  challan_number: string | null;
  container_number: string | null;
  po_number: string | null;
  reference_number: string | null;
  ntn: string | null;
  gst_number: string | null;
  status: string;
  is_approved: boolean;
  currency: string;
  excluding_tax_value: number;
  sales_tax_value: number;
  gross_amount: number;
  discount_amount: number;
  freight_amount: number;
  total_amount: number;
  payment_status: string | null;
  payment_reference: string | null;
  total_items: number;
  total_quantity: number;
  item_description: string | null;
  remarks: string | null;
  reference_gate_pass_id: string | null;
  reference_gate_pass_number: string | null;
  expected_return_date: string | null;
  /** Outward, issued as Returnable or Repair: expected to come back. */
  returnable: boolean;
  /** Outward: Pending return / Partly returned / Fully returned, or null when nothing is due back. */
  return_status: string | null;
  returned_quantity: number;
  pending_quantity: number;
}

export interface GatePassLine {
  id?: string;
  item_id: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  hs_code: string | null;
  quantity: string;
  unit_price: string;
  remarks: string | null;
  /** Inward: the outward line this returns against, and that line's figures. */
  reference_line_id?: string | null;
  sent?: number;
  returned?: number;
  still_out?: number;
  /** Outward: stock on hand of the chosen product, and whether it is shelf stock. */
  stock?: number | null;
  stocked?: boolean;
}

export interface GatePassDetail extends GatePassSummary {
  lines: (Omit<GatePassLine, "quantity" | "unit_price"> & {
    line_number: number;
    quantity: number;
    returned_quantity: number;
    pending_quantity: number;
    unit_price: number;
    net_amount: number;
  })[];
}

export const emptyLine = (): GatePassLine => ({
  item_id: null, item_code: null, description: "", uom: null, hs_code: null,
  quantity: "1", unit_price: "0", remarks: null,
});

/** Listing state for one gate pass type: search, status filter, paging. */
export function useGatePasses(passType: "outward" | "inward", defaultPageSize = 25) {
  const path = `/gate-passes/${passType}`;
  const [pageSize, setPageSize] = usePageSize(path, defaultPageSize);
  const [rows, setRows] = useState<GatePassSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statuses, setStatuses] = useState<string[]>([]);
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
      const data = await api.get<{ items: GatePassSummary[]; total: number }>(`${path}?${qs}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load gate passes.");
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

  return {
    rows, total, page, pageSize, search, statuses, sort, direction, loading, error,
    setPageSize: (n: number) => { setPageSize(n); setPage(1); },
    setPage, setSearch: (v: string) => { setSearch(v); setPage(1); },
    toggleStatus: (value: string) => {
      setStatuses((s) => (s.includes(value) ? s.filter((v) => v !== value) : [...s, value]));
      setPage(1);
    },
    toggleSort: (column: string) => {
      if (sort === column) setDirection((d) => (d === "asc" ? "desc" : "asc"));
      else { setSort(column); setDirection("desc"); }
    },
    reload: load,
    // Back to the view the screen opens with, for the grid's Reset button.
    reset: () => {
      setSearch("");
      setStatuses([]);
      setSort("doc_date");
      setDirection("desc");
      setPage(1);
    },
    dirty: Boolean(search) || statuses.length > 0
      || sort !== "doc_date" || direction !== "desc",
  };
}

/** Opens a gate pass PDF in a new tab, carrying the bearer token. */
export async function openGatePassPdf(passId: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
  const win = window.open("", "_blank");
  try {
    const token = sessionStorage.getItem("jezseem-access-token");
    const res = await fetch(`${base}/documents/gate-passes/${passId}.pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let detail = `Could not generate the gate pass (${res.status}).`;
      try { detail = (await res.json()).detail ?? detail; } catch { /* no body */ }
      win?.close();
      alert(detail);
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    if (win) win.location.href = url;
    else window.open(url, "_blank");
  } catch {
    win?.close();
    alert("Could not reach the server to generate this gate pass.");
  }
}
