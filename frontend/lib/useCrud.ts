"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePageSize } from "@/lib/usePageSize";

export interface PagedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * List + create + edit + delete against one inventory endpoint.
 * Keeps every Setup Form screen down to its columns and its form.
 */
export function useCrud<T extends { id: string }>(path: string, defaultPageSize = 25) {
  const [pageSize, setPageSize] = usePageSize(path, defaultPageSize);
  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search) qs.set("search", search);
      const data = await api.get<PagedResponse<T>>(`${path}?${qs}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load records.");
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [path, page, pageSize, search]);

  // Debounce so typing in the search box does not fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  const create = async (body: unknown) => {
    await api.post(path, body);
    await load();
  };

  const update = async (id: string, body: unknown) => {
    await api.put(`${path}/${id}`, body);
    await load();
  };

  const remove = async (id: string) => {
    await api.del(`${path}/${id}`);
    await load();
  };

  const onSearch = (value: string) => {
    setSearch(value);
    setPage(1);
  };

  return { rows, total, page, pageSize, search, loading, error,
           setPage, onSearch, reload: load, create, update, remove,
           setPageSize: (n: number) => { setPageSize(n); setPage(1); } };
}
