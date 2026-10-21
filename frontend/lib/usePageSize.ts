"use client";

import { useEffect, useState } from "react";

/** A list's rows-per-page, remembered per screen in this browser. */
export function usePageSize(storageKey: string, initial: number) {
  const key = `page-size.${storageKey}`;
  const [size, setSize] = useState(initial);
  useEffect(() => {
    try {
      const saved = Number(localStorage.getItem(key));
      if (saved > 0) setSize(saved);
    } catch { /* storage unavailable: the default stands */ }
  }, [key]);
  const change = (n: number) => {
    setSize(n);
    try { localStorage.setItem(key, String(n)); } catch { /* not kept */ }
  };
  return [size, change] as const;
}