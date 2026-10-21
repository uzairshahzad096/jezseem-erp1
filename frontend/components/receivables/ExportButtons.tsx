"use client";

import { useState } from "react";
import { Button } from "@/components/finance/ui";
import { download, errorText } from "@/lib/finance";

/** XLSX / PDF / CSV buttons for an /ar/export/{report} file with the screen's filters. */
export function ExportButtons({ report, query = "" }: { report: string; query?: string }) {
  const [error, setError] = useState<string | null>(null);
  const get = async (format: string) => {
    setError(null);
    try {
      await download(`/ar/export/${report}?format=${format}${query ? `&${query}` : ""}`, `${report}.${format}`);
    } catch (err) {
      setError(errorText(err, "Export failed."));
    }
  };
  return (
    <>
      {["xlsx", "pdf", "csv"].map((f) => <Button key={f} onClick={() => get(f)}>{f.toUpperCase()}</Button>)}
      {error && <span className="text-[12px] text-rose">{error}</span>}
    </>
  );
}
