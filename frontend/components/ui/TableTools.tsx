"use client";

import { useEffect, useRef, useState } from "react";
import { Download, Columns3, Check, Loader2 } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

const FORMATS = [
  { key: "xlsx", label: "Excel (.xlsx)" },
  { key: "csv", label: "CSV (.csv)" },
  { key: "pdf", label: "PDF (.pdf)" },
] as const;

/** Close a popover when the click lands outside it. */
function useOutsideClose(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);
  return ref;
}

/**
 * Download the whole filtered listing, not just the page on screen.
 *
 * The file is fetched rather than linked to, because the API needs the bearer
 * token and a plain <a href> would not carry it. The blob is then handed to
 * the browser as a download.
 */
export function DownloadMenu({
  dataset, query = "", label = "Download",
}: {
  /** Dataset name as registered in app/exports/router.py. */
  dataset: string;
  /** Extra query string (without a leading ?) so the export matches the
   *  filters currently applied on screen. */
  query?: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const ref = useOutsideClose(() => setOpen(false));

  const download = async (format: string) => {
    setBusy(format);
    try {
      const token = sessionStorage.getItem("jezseem-access-token");
      const separator = query ? "&" : "";
      const res = await fetch(
        `${BASE}/exports/${dataset}?format=${format}${separator}${query}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!res.ok) {
        let detail = `Could not build the file (${res.status}).`;
        try { detail = (await res.json()).detail ?? detail; } catch { /* no body */ }
        alert(detail);
        return;
      }

      const disposition = res.headers.get("content-disposition") ?? "";
      const named = /filename="?([^"]+)"?/.exec(disposition);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = named?.[1] ?? `${dataset}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setOpen(false);
    } catch {
      alert("Could not reach the server to build that file.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg bg-hover px-3.5 py-2 text-[12.8px]
                   font-medium text-muted transition-colors hover:text-text"
      >
        <Download size={14} /> {label}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-1 w-52 rounded-lg border border-line
                        bg-surface p-1 shadow-xl">
          {FORMATS.map((f) => (
            <button
              key={f.key}
              onClick={() => download(f.key)}
              disabled={busy !== null}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left
                         text-[12.5px] transition-colors hover:bg-primary/10 hover:text-primary
                         disabled:opacity-50"
            >
              {busy === f.key
                ? <Loader2 size={13} className="animate-spin" />
                : <Download size={13} />}
              {f.label}
            </button>
          ))}
          <p className="px-3 py-1.5 text-[10.5px] leading-snug text-faint">
            Exports every record matching the current filters, not just this page.
          </p>
        </div>
      )}
    </div>
  );
}

/** Show or hide listing columns. The choice is remembered per screen. */
export function ColumnPicker<T extends { key: string; label: string }>({
  columns, hidden, onToggle, onReset,
}: {
  columns: T[];
  hidden: Set<string>;
  onToggle: (key: string) => void;
  onReset: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(() => setOpen(false));
  const shown = columns.length - hidden.size;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg bg-hover px-3.5 py-2 text-[12.8px]
                   font-medium text-muted transition-colors hover:text-text"
      >
        <Columns3 size={14} /> Columns
        <span className="text-faint">{shown}/{columns.length}</span>
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-1 max-h-80 w-60 overflow-y-auto rounded-lg
                        border border-line bg-surface p-1 shadow-xl">
          {columns.map((c) => {
            const visible = !hidden.has(c.key);
            return (
              <button
                key={c.key}
                onClick={() => onToggle(c.key)}
                className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left
                           text-[12.3px] transition-colors hover:bg-hover"
              >
                <span className={`flex h-3.5 w-3.5 flex-shrink-0 items-center justify-center
                                  rounded border ${visible
                                    ? "border-primary bg-primary text-on-primary"
                                    : "border-line"}`}>
                  {visible && <Check size={10} strokeWidth={3} />}
                </span>
                <span className={visible ? "" : "text-faint"}>{c.label}</span>
              </button>
            );
          })}
          <button
            onClick={onReset}
            className="mt-1 w-full rounded-md px-3 py-1.5 text-left text-[11.5px]
                       font-medium text-primary hover:bg-primary/10"
          >
            Show all columns
          </button>
        </div>
      )}
    </div>
  );
}

/** Remembers hidden columns for one screen, in this browser. */
export function useHiddenColumns(storageKey: string, initiallyHidden: string[] = []) {
  const [hidden, setHidden] = useState<Set<string>>(new Set(initiallyHidden));

  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) setHidden(new Set(JSON.parse(saved) as string[]));
    } catch {
      /* private window or blocked storage — the defaults stand */
    }
  }, [storageKey]);

  const persist = (next: Set<string>) => {
    setHidden(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify([...next]));
    } catch {
      /* nothing to do; the choice just will not survive a reload */
    }
  };

  return {
    hidden,
    toggle: (key: string) => {
      const next = new Set(hidden);
      if (next.has(key)) next.delete(key); else next.add(key);
      persist(next);
    },
    reset: () => persist(new Set<string>()),
  };
}
