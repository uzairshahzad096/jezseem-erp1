"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * The listing behaviour every procurement screen shares: search, status
 * filters, sorting, paging, and a Reset that returns the view to how the
 * screen opens.
 *
 * Like `useSalesDocs`, the initial statuses are seeded rather than toggled
 * from a mount effect — a toggle runs twice under React's development
 * double-invoke and cancels itself out.
 */
export function useProcurementList<T>(
  path: string,
  {
    pageSize = 25,
    initialStatuses = [],
    initialSort = "doc_date",
    extraParams,
  }: {
    pageSize?: number;
    initialStatuses?: string[];
    initialSort?: string;
    /** Fixed query parameters, e.g. `{ in_transit_only: "true" }`. */
    extraParams?: Record<string, string>;
  } = {},
) {
  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statuses, setStatuses] = useState<string[]>(initialStatuses);
  const [sort, setSort] = useState(initialSort);
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const extra = JSON.stringify(extraParams ?? {});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        page: String(page), page_size: String(pageSize), sort, direction,
      });
      if (search) qs.set("search", search);
      statuses.forEach((s) => qs.append("status", s));
      Object.entries(JSON.parse(extra) as Record<string, string>)
        .forEach(([k, v]) => qs.set(k, v));
      const data = await api.get<{ items: T[]; total: number }>(`${path}?${qs}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load records.");
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [path, page, pageSize, search, statuses, sort, direction, extra]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  const dirty =
    Boolean(search) ||
    statuses.join() !== initialStatuses.join() ||
    sort !== initialSort ||
    direction !== "desc";

  return {
    rows, total, page, pageSize, search, statuses, sort, direction, loading, error,
    setPage,
    setSearch: (v: string) => { setSearch(v); setPage(1); },
    toggleStatus: (value: string) => {
      setStatuses((s) => (s.includes(value) ? s.filter((v) => v !== value) : [...s, value]));
      setPage(1);
    },
    toggleSort: (column: string) => {
      if (sort === column) setDirection((d) => (d === "asc" ? "desc" : "asc"));
      else { setSort(column); setDirection("desc"); }
      setPage(1);
    },
    reload: load,
    dirty,
    reset: () => {
      setSearch("");
      setStatuses(initialStatuses);
      setSort(initialSort);
      setDirection("desc");
      setPage(1);
    },
  };
}

export interface Supplier {
  id: string;
  code: string;
  name: string;
  country?: string | null;
  country_of_origin?: string | null;
  is_international?: boolean;
  currency?: string | null;
  incoterm?: string | null;
  payment_terms?: string | null;
  credit_days?: number | null;
  address?: string | null;
  phone?: string | null;
  ntn?: string | null;
  bank_name?: string | null;
}

/**
 * Every supplier, not the first page.
 *
 * A capped request silently hides the account being looked for, and the
 * picker filters in the browser. Suppliers are a small slice of the 1,110
 * partners, so this is cheap.
 */
export function useSuppliers() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);

  useEffect(() => {
    (async () => {
      const all: Supplier[] = [];
      try {
        for (let page = 1; ; page += 1) {
          const d = await api.get<{ items: Supplier[]; total: number }>(
            `/partners?role=supplier&page=${page}&page_size=500`);
          all.push(...d.items);
          if (d.items.length === 0 || all.length >= d.total) break;
        }
        setSuppliers(all);
      } catch {
        setSuppliers([]);
      }
    })();
  }, []);

  return suppliers;
}

/** Countries offered on an import order. Free text is still accepted. */
export const COUNTRIES = [
  "China", "United Arab Emirates", "Germany", "Italy", "Japan", "Turkey",
  "United Kingdom", "United States", "Spain", "South Korea", "Taiwan",
  "India", "Singapore", "Malaysia", "Thailand", "Netherlands", "France",
  "Switzerland", "Sweden", "Belgium", "Pakistan",
];

/** Incoterms 2020. */
export const INCOTERMS = [
  "EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP",
];

export const SHIPPING_MODES = ["Sea", "Air", "Road", "Rail", "Courier"];

/** The ports an importer into Pakistan actually uses. */
export const PAKISTAN_PORTS = [
  "Karachi Port", "Port Qasim", "Gwadar", "Lahore Dry Port",
  "Faisalabad Dry Port", "Sialkot Dry Port", "Jinnah International Airport",
  "Allama Iqbal International Airport", "Islamabad International Airport",
];
