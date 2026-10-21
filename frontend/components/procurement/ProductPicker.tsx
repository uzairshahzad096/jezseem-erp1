"use client";

import { useEffect, useState } from "react";
import { Loader2, X, Search } from "lucide-react";
import { api } from "@/lib/api";

export interface PickedProduct {
  id: string;
  item_code: string;
  description: string;
  uom: string | null;
  price: number | null;
  opening_stock: number;
  rack_name: string | null;
}

/** What the availability endpoint says about one product. */
export interface Availability {
  item_id: string;
  item_code: string | null;
  description: string | null;
  uom: string | null;
  stock_on_hand: number;
  reserved_stock: number;
  available_stock: number;
  stock_other_warehouses: number;
  stock_on_order: number;
  goods_in_transit: number;
  expected_stock: number;
  reorder_level: number | null;
  min_level: number | null;
  max_level: number | null;
  required_quantity: number;
  shortfall: number;
  needs_purchase: boolean;
  transfer_options: {
    warehouse_id: string; warehouse: string; available: number; can_cover: boolean;
  }[];
}

export async function fetchAvailability(
  itemId: string, warehouseId?: string | null, required?: string | number,
): Promise<Availability | null> {
  const qs = new URLSearchParams({ item_id: itemId });
  if (warehouseId) qs.set("warehouse_id", warehouseId);
  if (required) qs.set("required_quantity", String(required));
  try {
    return await api.get<Availability>(`/procurement/availability?${qs}`);
  } catch {
    return null;
  }
}

/**
 * Type-ahead product lookup that queries the server rather than loading all
 * ~5,000 items into the browser.
 *
 * The result list shows stock and rack, because the question being answered
 * while raising a requirement is "have we got this already?" — the same
 * reason the picker exists at all.
 */
export function ProductPicker({
  value, onPick, disabled,
}: {
  value: string | null;
  onPick: (product: PickedProduct) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PickedProduct[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || query.trim().length < 2) { setResults([]); return; }
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const data = await api.get<{ items: PickedProduct[] }>(
          `/inventory/items?search=${encodeURIComponent(query)}&page_size=15`);
        setResults(data.items);
      } catch {
        setResults([]);
      } finally {
        setBusy(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [query, open]);

  return (
    <>
      <button type="button" disabled={disabled} onClick={() => setOpen(true)}
        className="w-full truncate rounded-md border border-line bg-bg px-2.5 py-1.5
                   text-left text-[12px] transition-colors hover:border-primary
                   disabled:opacity-60">
        {value || <span className="text-faint">Pick item…</span>}
      </button>

      {open && (
        <div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/50 p-4 pt-24">
          {/* Announced as its own dialog: it opens over a form that is already
              one, and without a role nothing can address or label it. */}
          <div role="dialog" aria-modal="true" aria-label="Select product"
               className="w-full max-w-xl rounded-[12px] border border-line bg-surface shadow-xl">
            <div className="flex items-center gap-2 border-b border-line px-4 py-3">
              <h4 className="m-0 text-[13.5px] font-semibold">Select product</h4>
              <button onClick={() => setOpen(false)} aria-label="Close"
                className="ml-auto rounded-md p-1 text-muted hover:bg-hover">
                <X size={16} />
              </button>
            </div>
            <div className="p-4">
              <div className="flex items-center gap-2 rounded-lg border border-line bg-bg px-3 py-2.5">
                <Search size={14} className="text-faint" />
                <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
                  placeholder="Type at least 2 characters…"
                  className="w-full border-none bg-transparent text-[13px] outline-none
                             placeholder:text-faint" />
              </div>
              <div className="mt-3 max-h-72 overflow-y-auto">
                {busy && (
                  <p className="py-6 text-center">
                    <Loader2 size={16} className="mx-auto animate-spin text-primary" />
                  </p>
                )}
                {!busy && query.length >= 2 && results.length === 0 && (
                  <p className="py-6 text-center text-[12.5px] text-faint">
                    No matching products.
                  </p>
                )}
                {results.map((item) => (
                  <button key={item.id} type="button"
                    onClick={() => { onPick(item); setOpen(false); setQuery(""); }}
                    className="block w-full border-b border-line px-2 py-2.5 text-left
                               last:border-0 hover:bg-hover">
                    <div className="text-[12.5px] font-medium">{item.description}</div>
                    <div className="text-[11px] text-faint">
                      {item.item_code} · {item.uom ?? "—"} ·{" "}
                      <span className={item.opening_stock > 0 ? "text-success" : "text-rose"}>
                        Stock {item.opening_stock}
                      </span>
                      {item.rack_name ? ` · Rack ${item.rack_name}` : ""}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/**
 * The stock position behind one requirement line.
 *
 * Shown inline while the quantity is being typed, because the decision it
 * informs — buy, or move stock from another warehouse — is being made at
 * that moment. `shortfall` is the figure that matters: what is still missing
 * after everything held, ordered or afloat is counted.
 */
export function AvailabilityStrip({ picture }: { picture: Availability | null }) {
  if (!picture) return null;

  const cells: { label: string; value: number; tone?: string }[] = [
    { label: "On hand", value: picture.stock_on_hand },
    { label: "Reserved", value: picture.reserved_stock, tone: "text-amber" },
    { label: "Available", value: picture.available_stock, tone: "text-primary" },
    { label: "Other warehouses", value: picture.stock_other_warehouses },
    { label: "On order", value: picture.stock_on_order },
    { label: "In transit", value: picture.goods_in_transit },
    { label: "Expected", value: picture.expected_stock, tone: "text-sky" },
  ];

  return (
    <div className="rounded-lg border border-line bg-bg px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
        {cells.map((cell) => (
          <span key={cell.label} className="text-[11px] text-muted">
            {cell.label}{" "}
            <b className={`tabular-nums ${cell.tone ?? "text-text"}`}>
              {cell.value.toLocaleString()}
            </b>
          </span>
        ))}
        {picture.reorder_level != null && (
          <span className="text-[11px] text-muted">
            Reorder <b className="tabular-nums">{picture.reorder_level.toLocaleString()}</b>
          </span>
        )}
      </div>

      {picture.required_quantity > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 border-t border-line pt-1.5">
          {picture.needs_purchase ? (
            <span className="text-[11.5px]">
              Short by{" "}
              <b className="text-rose tabular-nums">
                {picture.shortfall.toLocaleString()}
              </b>{" "}
              — this much needs procuring.
            </span>
          ) : (
            <span className="text-[11.5px] text-primary">
              Nothing to procure: {picture.expected_stock.toLocaleString()} is expected
              against {picture.required_quantity.toLocaleString()} required.
            </span>
          )}

          {/* Moving stock the company already owns beats buying more of it. */}
          {picture.transfer_options.length > 0 && (
            <span className="text-[11.5px] text-muted">
              Held elsewhere:{" "}
              {picture.transfer_options.slice(0, 3).map((o, i) => (
                <span key={o.warehouse_id}>
                  {i > 0 && ", "}
                  <b className={o.can_cover ? "text-primary" : ""}>{o.warehouse}</b>{" "}
                  {o.available.toLocaleString()}
                </span>
              ))}
              {picture.transfer_options.some((o) => o.can_cover) &&
                " — a transfer could cover this."}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
