"use client";

import { useEffect, useState } from "react";
import {
  Pencil, Plus, Banknote, SlidersHorizontal, ArrowLeftRight, History,
  ArrowUp, ArrowDown, Loader2, CheckCircle2,
} from "lucide-react";
import { Modal, Field, TextInput, TextArea, Select } from "@/components/ui/Modal";
import { api } from "@/lib/api";

export interface ActionItem {
  id: string;
  item_code: string;
  description: string;
  uom: string | null;
  currency: string | null;
  price: number | null;
  location_id?: string | null;
}

export interface LocationOption { id: string; label: string }

type Action = "opening" | "price" | "adjustment" | "transfer" | "history";

/**
 * The row of actions under each product card.
 *
 * Everything except Price writes a stock movement: the balance is always the
 * sum of its history, so an opening, a correction and a move between
 * locations are all recorded rather than typed over the top of a number.
 */
export function ItemActions({
  item, locations, onEdit, onChanged,
}: {
  item: ActionItem;
  locations: LocationOption[];
  onEdit: () => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState<Action | null>(null);

  const buttons: { key: Action; title: string; icon: React.ReactNode }[] = [
    { key: "opening", title: "Add opening quantity", icon: <Plus size={13} /> },
    { key: "price", title: "Add price", icon: <Banknote size={13} /> },
    { key: "adjustment", title: "Add adjustment", icon: <SlidersHorizontal size={13} /> },
    { key: "transfer", title: "Transfer item", icon: <ArrowLeftRight size={13} /> },
    { key: "history", title: "Recent transactions", icon: <History size={13} /> },
  ];

  // The dialog stays up after a save to show what the new balance is; the
  // cards behind refresh straight away, so closing it reveals the new figure.
  const done = () => onChanged();

  return (
    <>
      {/* All six on one row, as on the reference card: squared-off buttons
          sized to fit the narrowest column rather than wrapping. */}
      <div className="mt-auto flex items-center gap-1">
        <button
          onClick={onEdit}
          title="Edit product"
          aria-label="Edit product"
          className="flex h-[26px] w-[26px] flex-shrink-0 items-center justify-center rounded-md
                     bg-rose text-white transition-opacity hover:opacity-90"
        >
          <Pencil size={13} />
        </button>
        {buttons.map((b) => (
          <button
            key={b.key}
            onClick={() => setOpen(b.key)}
            title={b.title}
            aria-label={b.title}
            className="flex h-[26px] w-[26px] flex-shrink-0 items-center justify-center rounded-md
                       bg-hover text-muted transition-colors hover:bg-primary/10 hover:text-primary"
          >
            {b.icon}
          </button>
        ))}
      </div>

      {open === "opening" && (
        <OpeningDialog item={item} locations={locations}
          onClose={() => setOpen(null)} onSaved={done} />
      )}
      {open === "price" && (
        <PriceDialog item={item} onClose={() => setOpen(null)} onSaved={done} />
      )}
      {open === "adjustment" && (
        <AdjustmentDialog item={item} locations={locations}
          onClose={() => setOpen(null)} onSaved={done} />
      )}
      {open === "transfer" && (
        <TransferDialog item={item} locations={locations}
          onClose={() => setOpen(null)} onSaved={done} />
      )}
      {open === "history" && (
        <HistoryDialog item={item} onClose={() => setOpen(null)} />
      )}
    </>
  );
}

/** The product's identity, repeated read-only at the top of every dialog. */
function ItemHeader({ item }: { item: ActionItem }) {
  return (
    <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
      <Field label="Itemdtl Code">
        <TextInput value={item.item_code} readOnly className="bg-hover" />
      </Field>
      <Field label="Desc">
        <TextInput value={item.description} readOnly className="bg-hover" />
      </Field>
      <Field label="Uom">
        <TextInput value={item.uom ?? ""} readOnly className="bg-hover" />
      </Field>
    </div>
  );
}

/** The result of a save, shown in the dialog rather than a browser alert. */
function Saved({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 flex items-start gap-2 rounded-lg bg-primary/10 px-3.5 py-2.5
                  text-[12.5px] text-primary">
      <CheckCircle2 size={15} className="mt-px flex-shrink-0" />
      <span className="whitespace-pre-line">{children}</span>
    </p>
  );
}

function LocationField({
  locations, value, onChange, label = "Location",
}: {
  locations: LocationOption[];
  value: string;
  onChange: (v: string) => void;
  label?: string;
}) {
  return (
    <Field label={label}>
      <Select value={value} placeholder="No location"
        options={locations.map((l) => ({ value: l.id, label: l.label }))}
        onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

function OpeningDialog({ item, locations, onClose, onSaved }: {
  item: ActionItem; locations: LocationOption[];
  onClose: () => void; onSaved: () => void;
}) {
  const [locationId, setLocationId] = useState(item.location_id ?? "");
  const [quantity, setQuantity] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const save = async () => {
    if (Number(quantity) <= 0) { setError("Enter a quantity greater than zero."); return; }
    setSaving(true); setError(null);
    try {
      const res = await api.post<{ balance_after: number; location: string | null }>(
        "/inventory/stock/openings",
        { item_id: item.id, location_id: locationId || null, quantity },
      );
      setSaved(`Opening saved. ${item.item_code} is now `
        + `${res.balance_after.toLocaleString()}${res.location ? ` at ${res.location}` : ""}.`);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the opening.");
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Add Opening" open width="md" saving={saving} error={error}
           onClose={onClose} onSave={saved ? undefined : save} saveLabel="Save">
      <div className="space-y-4">
        {saved && <Saved>{saved}</Saved>}
        <ItemHeader item={item} />
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <LocationField locations={locations} value={locationId} onChange={setLocationId} />
          <Field label="Qty" required>
            <TextInput type="number" step="0.01" min="0" value={quantity} disabled={!!saved}
              onChange={(e) => setQuantity(e.target.value)} autoFocus />
          </Field>
        </div>
        <p className="m-0 text-[11px] text-faint">
          Recorded as a stock movement, so the balance stays traceable.
        </p>
      </div>
    </Modal>
  );
}

function PriceDialog({ item, onClose, onSaved }: {
  item: ActionItem; onClose: () => void; onSaved: () => void;
}) {
  const [currency, setCurrency] = useState(item.currency || "PKR");
  const [price, setPrice] = useState(item.price != null ? String(item.price) : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const save = async () => {
    if (price.trim() === "" || Number(price) < 0) { setError("Enter a price."); return; }
    setSaving(true); setError(null);
    try {
      await api.put(`/inventory/items/${item.id}/price`, { currency, price });
      setSaved(`Price saved. ${item.item_code} is ${Number(price).toLocaleString(undefined, {
        minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}.`);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the price.");
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Add Price" open width="md" saving={saving} error={error}
           onClose={onClose} onSave={saved ? undefined : save} saveLabel="Save">
      <div className="space-y-4">
        {saved && <Saved>{saved}</Saved>}
        <ItemHeader item={item} />
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="Currency">
            <Select value={currency} placeholder="PKR" disabled={!!saved}
              options={["PKR", "USD", "EUR", "GBP"].map((c) => ({ value: c, label: c }))}
              onChange={(e) => setCurrency(e.target.value)} />
          </Field>
          <Field label="Price" required>
            <TextInput type="number" step="0.01" min="0" value={price} disabled={!!saved}
              onChange={(e) => setPrice(e.target.value)} autoFocus />
          </Field>
        </div>
      </div>
    </Modal>
  );
}

function AdjustmentDialog({ item, locations, onClose, onSaved }: {
  item: ActionItem; locations: LocationOption[];
  onClose: () => void; onSaved: () => void;
}) {
  const [locationId, setLocationId] = useState(item.location_id ?? "");
  const [direction, setDirection] = useState<"in" | "out">("out");
  const [quantity, setQuantity] = useState("");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const save = async () => {
    if (Number(quantity) <= 0) { setError("Enter a quantity greater than zero."); return; }
    if (remarks.trim().length < 3) { setError("Give a reason for the adjustment."); return; }
    setSaving(true); setError(null);
    try {
      const res = await api.post<{ balance_after: number; location: string | null }>(
        "/inventory/stock/adjustments",
        { item_id: item.id, location_id: locationId || null, direction, quantity,
          remarks: remarks.trim() },
      );
      setSaved(`Adjustment saved. ${item.item_code} is now `
        + `${res.balance_after.toLocaleString()}${res.location ? ` at ${res.location}` : ""}.`);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not adjust the stock.");
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Add Adjustment" open width="md" saving={saving} error={error}
           onClose={onClose} onSave={saved ? undefined : save} saveLabel="Save">
      <div className="space-y-4">
        {saved && <Saved>{saved}</Saved>}
        <ItemHeader item={item} />
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <LocationField locations={locations} value={locationId} onChange={setLocationId} />
          <Field label="Adjustment">
            <div className="flex gap-2">
              {(["out", "in"] as const).map((d) => (
                <button key={d} type="button" disabled={!!saved} onClick={() => setDirection(d)}
                  className={`flex-1 rounded-lg px-3 py-2 text-[12.5px] font-medium transition-colors
                              disabled:opacity-60
                              ${direction === d
                                ? d === "out" ? "bg-rose/15 text-rose" : "bg-success/15 text-success"
                                : "bg-hover text-muted"}`}>
                  {d === "out" ? "Remove" : "Add"}
                </button>
              ))}
            </div>
          </Field>
        </div>
        <Field label="Qty" required>
          <TextInput type="number" step="0.01" min="0" value={quantity} disabled={!!saved}
            onChange={(e) => setQuantity(e.target.value)} />
        </Field>
        <Field label="Reason" required>
          <TextArea rows={2} value={remarks} disabled={!!saved}
            onChange={(e) => setRemarks(e.target.value)}
            placeholder="Damaged in transit, stock count correction, …" />
        </Field>
      </div>
    </Modal>
  );
}

function TransferDialog({ item, locations, onClose, onSaved }: {
  item: ActionItem; locations: LocationOption[];
  onClose: () => void; onSaved: () => void;
}) {
  const [fromId, setFromId] = useState(item.location_id ?? "");
  const [toId, setToId] = useState("");
  const [entryDate, setEntryDate] = useState(new Date().toISOString().slice(0, 10));
  const [quantity, setQuantity] = useState("");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const save = async () => {
    if (!fromId || !toId) { setError("Choose both locations."); return; }
    if (fromId === toId) { setError("Choose two different locations."); return; }
    if (Number(quantity) <= 0) { setError("Enter a quantity greater than zero."); return; }
    setSaving(true); setError(null);
    try {
      const res = await api.post<{
        from: { location: string; balance_after: number };
        to: { location: string; balance_after: number };
      }>("/inventory/stock/transfers", {
        item_id: item.id, from_location_id: fromId, to_location_id: toId,
        quantity, entry_date: entryDate, remarks: remarks.trim() || null,
      });
      setSaved(`${item.item_code} moved.\n`
        + `${res.from.location}: ${res.from.balance_after.toLocaleString()}\n`
        + `${res.to.location}: ${res.to.balance_after.toLocaleString()}`);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not transfer the stock.");
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Transfer Item" open width="md" saving={saving} error={error}
           onClose={onClose} onSave={saved ? undefined : save} saveLabel="Save">
      <div className="space-y-4">
        {saved && <Saved>{saved}</Saved>}
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <LocationField locations={locations} value={fromId} onChange={setFromId}
            label="From Location" />
          <LocationField locations={locations} value={toId} onChange={setToId}
            label="To Location" />
        </div>
        <ItemHeader item={item} />
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="Date">
            <TextInput type="date" value={entryDate} disabled={!!saved}
              onChange={(e) => setEntryDate(e.target.value)} />
          </Field>
          <Field label="Qty" required>
            <TextInput type="number" step="0.01" min="0" value={quantity} disabled={!!saved}
              onChange={(e) => setQuantity(e.target.value)} />
          </Field>
        </div>
        <Field label="Reason">
          <TextArea rows={2} value={remarks} disabled={!!saved}
            onChange={(e) => setRemarks(e.target.value)}
            placeholder="Parts issued to the technician, moved to the branch, …" />
        </Field>
        <p className="m-0 text-[11px] text-faint">
          The total stock of this product does not change — a transfer only moves
          it between locations.
        </p>
      </div>
    </Modal>
  );
}

interface Movement {
  id: string;
  entry_date: string;
  direction: string;
  quantity: number;
  source_type: string;
  source_number: string | null;
  location: string | null;
  remarks: string | null;
}

/** How each movement is described in the history. */
const SOURCE_LABEL: Record<string, string> = {
  opening: "OPENING QUANTITY ENTERED",
  opening_balance: "OPENING BALANCE LOADED",
  adjustment: "PRODUCT STOCK ADJUSTMENT IS PERFORMED",
  transfer: "STOCK TRANSFERRED BETWEEN LOCATIONS",
  sales_order: "SOLD ON SALES ORDER",
  gate_pass_outward: "ISSUED ON OUTWARD GATE PASS",
  gate_pass_inward: "RECEIVED ON INWARD GATE PASS",
};

function HistoryDialog({ item, onClose }: { item: ActionItem; onClose: () => void }) {
  const [data, setData] = useState<{ balance: number; items: Movement[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ balance: number; items: Movement[] }>(
      `/inventory/items/${item.id}/transactions`)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load."));
  }, [item.id]);

  return (
    <Modal title="Recent Transactions" open width="lg" onClose={onClose}>
      <div className="mb-3 rounded-lg border border-line bg-bg px-3.5 py-2.5 text-[12.5px]">
        <div className="font-medium">{item.description}</div>
        <div className="text-muted">
          {item.item_code}
          {data && <> · balance <b>{data.balance.toLocaleString()}</b> {item.uom ?? ""}</>}
        </div>
      </div>

      {error && <p className="rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>}
      {!data && !error && (
        <div className="flex justify-center py-10">
          <Loader2 size={18} className="animate-spin text-primary" />
        </div>
      )}

      {data && data.items.length === 0 && (
        <p className="py-10 text-center text-[12.8px] text-faint">
          Nothing has moved this product yet.
        </p>
      )}

      {data && data.items.length > 0 && (
        <div className="overflow-hidden rounded-[10px] border border-line">
          {data.items.map((movement, index) => {
            const incoming = movement.direction === "in";
            return (
              <div key={movement.id}
                className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-0">
                <div className={`flex h-7 w-7 flex-shrink-0 items-center justify-center
                                 rounded-full ${incoming ? "bg-success" : "bg-rose"} text-white`}>
                  {incoming ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[12px] font-semibold">
                      {data.items.length - index}
                    </span>
                    <span className="text-[11.5px] text-faint">{movement.entry_date}</span>
                    <span className={`rounded px-2 py-0.5 text-[10.5px] font-semibold text-white
                                      ${incoming ? "bg-success" : "bg-rose"}`}>
                      {SOURCE_LABEL[movement.source_type] ?? movement.source_type.toUpperCase()}
                      {movement.remarks ? ` — ${movement.remarks}` : ""}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted">
                    {movement.location ?? "No location"}
                    {movement.source_number ? ` · ${movement.source_number}` : ""}
                  </div>
                </div>
                <div className="whitespace-nowrap text-right">
                  <div className="text-[13px] font-semibold tabular-nums">
                    {movement.quantity.toLocaleString()}
                  </div>
                  <div className="text-[11px] text-faint">{item.uom ?? ""}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
