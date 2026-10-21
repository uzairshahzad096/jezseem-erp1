"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export interface Lookup { id: string; label: string; parentId?: string }

/** A unit of measure, with the description the picker shows beside the code. */
export interface UomLookup {
  code: string;
  description: string;
  category: string | null;
  decimalPlaces: number;
}

/** The API's maximum page_size. */
const MAX_PAGE_SIZE = 200;

/**
 * Every row of a lookup endpoint, following pagination to the end.
 *
 * A single capped request is wrong for a dropdown: once the table passes one
 * page the options past it silently vanish, and the user concludes the rack
 * they need was never created. Lookup rows are small, so fetching all of
 * them is cheap.
 */
async function loadAll<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  for (let page = 1; ; page += 1) {
    const separator = path.includes("?") ? "&" : "?";
    const data = await api.get<{ items: T[]; total: number }>(
      `${path}${separator}page=${page}&page_size=${MAX_PAGE_SIZE}`,
    );
    rows.push(...data.items);
    if (data.items.length === 0 || rows.length >= data.total) return rows;
  }
}

/** Loads the category/rack dropdown sources used by the inventory forms. */
export function useLookups() {
  const [mainProducts, setMainProducts] = useState<Lookup[]>([]);
  const [subCategories, setSubCategories] = useState<Lookup[]>([]);
  const [detailCategories, setDetailCategories] = useState<Lookup[]>([]);
  const [racks, setRacks] = useState<Lookup[]>([]);
  const [locations, setLocations] = useState<Lookup[]>([]);
  const [uoms, setUoms] = useState<UomLookup[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const [mp, sc, sd, rk, lc, um] = await Promise.all([
          loadAll<{ id: string; description: string }>("/inventory/main-products"),
          loadAll<{ id: string; description: string; main_product_id: string }>("/inventory/sub-categories"),
          loadAll<{ id: string; description: string; sub_category_id: string }>("/inventory/sub-detail-categories"),
          loadAll<{ id: string; rack_name: string }>("/inventory/racks"),
          loadAll<{ id: string; location: string }>("/inventory/locations"),
          loadAll<{ code: string; description: string; category: string | null;
                    decimal_places: number }>("/inventory/uoms"),
        ]);
        setMainProducts(mp.map((r) => ({ id: r.id, label: r.description })));
        setSubCategories(sc.map((r) => ({ id: r.id, label: r.description, parentId: r.main_product_id })));
        setDetailCategories(sd.map((r) => ({ id: r.id, label: r.description, parentId: r.sub_category_id })));
        setRacks(rk.map((r) => ({ id: r.id, label: r.rack_name })));
        setLocations(lc.map((r) => ({ id: r.id, label: r.location })));
        setUoms(um.map((r) => ({
          code: r.code, description: r.description,
          category: r.category, decimalPlaces: r.decimal_places,
        })));
      } catch {
        // Dropdowns stay empty; the form still shows its validation message.
      }
    })();
  }, []);

  return { mainProducts, subCategories, detailCategories, racks, locations, uoms };
}

export const toOptions = (items: Lookup[]) =>
  items.map((i) => ({ value: i.id, label: i.label }));
