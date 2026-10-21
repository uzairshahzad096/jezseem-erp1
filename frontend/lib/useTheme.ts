"use client";

import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

/** Persists the chosen theme per browser and exposes a key charts can watch. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    let saved: Theme = "light";
    try {
      saved = (localStorage.getItem("jezseem-theme") as Theme) || "light";
    } catch {
      /* storage unavailable — fall back to light */
    }
    setTheme(saved);
    document.documentElement.classList.toggle("dark", saved === "dark");
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      document.documentElement.classList.toggle("dark", next === "dark");
      try {
        localStorage.setItem("jezseem-theme", next);
      } catch {
        /* not persisted */
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}
