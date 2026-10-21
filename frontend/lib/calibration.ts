"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/** Calibration / Services: shared types and lookups for the six screens. */

export interface Lookups {
  machine_statuses: string[];
  billing_frequencies: string[];
  contract_statuses: string[];
  contract_types: string[];
  service_types: string[];
  overall_results: string[];
  report_statuses: string[];
}

export interface Option { value: string; label: string }

export const API = "/calibration";

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export const todayIso = () => new Date().toISOString().slice(0, 10);

export const opts = (values: string[] | undefined): Option[] =>
  (values ?? []).map((v) => ({ value: v, label: v }));

/** Blank form text goes to the server as nothing. */
export const orNull = (v: string | null | undefined) => (v && String(v).trim() ? String(v).trim() : null);

export function useLookups(): Lookups | null {
  const [data, setData] = useState<Lookups | null>(null);
  useEffect(() => { api.get<Lookups>(`${API}/lookups`).then(setData).catch(() => setData(null)); }, []);
  return data;
}

/** Every customer, for the pickers. */
export function useCustomers(): Option[] {
  const [rows, setRows] = useState<Option[]>([]);
  useEffect(() => {
    (async () => {
      const all: { id: string; name: string }[] = [];
      try {
        for (let page = 1; ; page += 1) {
          const d = await api.get<{ items: { id: string; name: string }[]; total: number }>(
            `/partners?role=customer&page=${page}&page_size=1000`);
          all.push(...d.items);
          if (d.items.length === 0 || all.length >= d.total) break;
        }
      } catch { /* the picker stays empty and the form says so */ }
      setRows(all.map((p) => ({ value: p.id, label: p.name })).sort((a, b) => a.label.localeCompare(b.label)));
    })();
  }, []);
  return rows;
}

/** Any list endpoint of the module as picker options. */
export function useOptions<T extends { id: string }>(path: string | null, label: (row: T) => string): { options: Option[]; rows: T[] } {
  const [rows, setRows] = useState<T[]>([]);
  useEffect(() => {
    if (!path) { setRows([]); return; }
    const sep = path.includes("?") ? "&" : "?";
    api.get<{ items: T[] }>(`${path}${sep}page_size=5000`).then((d) => setRows(d.items)).catch(() => setRows([]));
  }, [path]);
  return { rows, options: rows.map((r) => ({ value: r.id, label: label(r) })) };
}

export const money = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
