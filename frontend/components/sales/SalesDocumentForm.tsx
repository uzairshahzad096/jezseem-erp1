"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, Trash2, Loader2, X } from "lucide-react";
import { Combobox } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { useLookups } from "@/lib/useLookups";
import { UomPicker } from "@/components/ui/UomPicker";
import {
  CURRENCIES, DEFAULT_CURRENCY, currencyOptions, money,
} from "@/lib/currency";

export interface DocLine {
  item_id: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  hs_code: string | null;
  quantity: string;
  unit_price: string;
  discount_percent: string;
  tax_percent: string;
  /** Per-line currency. The old grid lets a line differ from the document. */
  currency: string;
  /** Filled in from the chosen product and shown read-only — the grid is for
   *  writing a document, not for editing the item master. */
  rack_name: string | null;
  stock: number | null;
  /** A product kept on the shelf (not a service, software or CAD job), so its quantity may not exceed the stock. */
  stocked?: boolean;
  /** Looked up on pick: the last price this item was quoted at to this customer. */
  last_rate: number | null;
  /** The price the line was started at, and why: this customer's last
   *  quoted price, or the price most other customers were quoted. Kept so
   *  the line can be re-priced if the customer changes, unless typed over. */
  suggested_rate?: number | null;
  rate_basis?: RateBasis;
  /** Tooltip detail: how many customers share that price, and the range. */
  rate_note?: string | null;
  /** The product's own selling price from Product Details. Unit Price starts
   *  from it and can then be typed over, so the two are kept apart. */
  sale_rate: number | null;
}

export interface DocHeader {
  doc_date: string;
  dc_number: string;
  customer_id: string;
  status: string;
  remarks: string;
  demand_number: string;
  customer_po_number: string;
  delivery_person: string;
  vehicle_number: string;
  location: string;
  with_sales_tax: boolean;
  /** A service order, printed as a Service Invoice. */
  is_service: boolean;
  currency: string;
  payment_terms: string;
  payment_status: string;
  payment_reference: string;
  freight_amount: string;
  document_discount: string;
}

export const emptyLine = (currency = DEFAULT_CURRENCY): DocLine => ({
  item_id: null, item_code: null, description: "", uom: null, hs_code: null,
  quantity: "1", unit_price: "0", discount_percent: "0", tax_percent: "0",
  currency, rack_name: null, stock: null, last_rate: null, sale_rate: null,
});

export const emptyHeader = (): DocHeader => ({
  doc_date: new Date().toISOString().slice(0, 10),
  customer_id: "", status: "Draft", remarks: "", demand_number: "", dc_number: "",
  customer_po_number: "", delivery_person: "", vehicle_number: "", location: "",
  with_sales_tax: true, is_service: false, currency: DEFAULT_CURRENCY, payment_terms: "", payment_status: "PENDING",
  payment_reference: "", freight_amount: "0", document_discount: "0",
});

const num = (v: string) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/**
 * Mirrors app/common/calculations.py exactly, purely so the user sees totals
 * update while typing. The server recalculates on save and its answer is the
 * one stored — this is feedback, not the source of truth.
 */
export function computeTotals(lines: DocLine[], freight: string, docDiscount: string) {
  const perLine = lines.map((l) => {
    const gross = num(l.quantity) * num(l.unit_price);
    const discount = Math.min((gross * num(l.discount_percent)) / 100, gross);
    const taxable = gross - discount;
    const tax = (taxable * num(l.tax_percent)) / 100;
    return { gross, discount, taxable, tax, net: taxable + tax };
  });

  const excludingTax = perLine.reduce((s, l) => s + l.taxable, 0);
  const taxTotal = perLine.reduce((s, l) => s + l.tax, 0);
  const lineDiscounts = perLine.reduce((s, l) => s + l.discount, 0);
  const grossAmount = excludingTax + taxTotal;

  return {
    perLine,
    excludingTax,
    taxTotal,
    discountTotal: lineDiscounts + num(docDiscount),
    freight: num(freight),
    grossAmount,
    netReceivable: grossAmount + num(freight) - num(docDiscount),
  };
}

const input =
  "w-full rounded-md border border-line bg-bg px-2.5 py-1.5 text-[12.5px] outline-none " +
  "transition-colors focus:border-primary";

/** A ledger account. These are the fields the PDF's Bill To block prints. */
export interface Customer {
  id: string;
  name: string;
  code?: string;
  address?: string | null;
  phone?: string | null;
  cell?: string | null;
  ntn?: string | null;
  stn?: string | null;
}

interface ItemOption {
  id: string; item_code: string; description: string; uom: string | null;
  price: number | null; opening_stock: number; rack_name: string | null;
  main_product_name?: string | null;
}

// Main categories that are not goods on a shelf; the server skips the stock check for them too.
const NOT_STOCKED = ["SERVICES", "SOFTWARE", "CAD"];

type RateBasis = "customer_last" | "product_price" | "most_common_other_customers" | null;

interface Rates {
  last_rate: number | null;
  suggested_rate: number | null;
  basis: RateBasis;
  customers_at_price?: number | null;
  customers_compared?: number | null;
  price_range?: [number, number] | null;
}

const NO_RATES: Rates = { last_rate: null, suggested_rate: null, basis: null };

function rateNote(r: Rates): string | null {
  if (r.basis !== "most_common_other_customers" || !r.customers_compared) return null;
  const [lo, hi] = r.price_range ?? [null, null];
  const range = lo != null && hi != null && lo !== hi
    ? ` (prices range ${lo.toLocaleString()} to ${hi.toLocaleString()})` : "";
  return `${r.customers_at_price} of ${r.customers_compared} other customers were last quoted this price${range}`;
}

/** Price history for an item: this customer's last quoted price, or the
 *  price most other customers were quoted. A failed lookup leaves it open. */
async function fetchRates(itemId: string, customerId: string, currency: string): Promise<Rates> {
  const qs = new URLSearchParams({ currency: currency || DEFAULT_CURRENCY });
  if (customerId) qs.set("customer_id", customerId);
  try {
    return await api.get<Rates>(`/sales/items/${itemId}/last-rate?${qs}`);
  } catch {
    return NO_RATES;
  }
}

/** The price a new line starts at, the same on quotations and sales orders:
 *  this customer's own previous price for the item; if they never had one,
 *  the product's price; only if the product has no price, the price most
 *  other customers were quoted. Always typeable over. */
function startingPrice(rates: Rates, productPrice: number | null): { price: number | null; basis: RateBasis } {
  if (rates.basis === "customer_last" && rates.suggested_rate != null) return { price: rates.suggested_rate, basis: "customer_last" };
  if (productPrice != null && productPrice > 0) return { price: productPrice, basis: "product_price" };
  return { price: rates.suggested_rate, basis: rates.basis };
}

const BASIS_HINT: Record<string, string> = {
  customer_last: "This customer's previous price for this product",
  product_price: "No previous price for this customer: the product's price",
  most_common_other_customers: "First time for this customer: the price most other customers were quoted",
};

export function SalesDocumentForm({
  kind, header, lines, customers, onHeader, onLines,
}: {
  kind: "quotation" | "sales_order";
  header: DocHeader;
  lines: DocLine[];
  customers: Customer[];
  onHeader: (h: DocHeader) => void;
  onLines: (l: DocLine[]) => void;
}) {
  const { locations, uoms } = useLookups();

  const totals = useMemo(
    () => computeTotals(lines, header.freight_amount, header.document_discount),
    [lines, header.freight_amount, header.document_discount],
  );

  // The ledger code goes in the label so it is searchable too — staff often
  // know an account by its number rather than its full registered name.
  const customerOptions = useMemo(
    () => customers.map((c) => ({
      value: c.id,
      label: c.code ? `${c.name} — ${c.code}` : c.name,
    })),
    [customers],
  );

  const selectedCustomer = useMemo(
    () => customers.find((c) => c.id === header.customer_id) ?? null,
    [customers, header.customer_id],
  );

  const setH = (key: keyof DocHeader, value: string | boolean) =>
    onHeader({ ...header, [key]: value } as DocHeader);

  /**
   * Changing the document's currency re-tags its lines.
   *
   * A line carries its own currency — the old grid allows one to differ —
   * but every line here was created in the document's currency, so leaving
   * them behind would price the document in dollars while its lines still
   * said PKR. Only lines that still match the old currency are moved, so a
   * line deliberately set to something else is left alone.
   */
  const setCurrency = (next: string) => {
    const code = next.trim().toUpperCase();
    onHeader({ ...header, currency: code });
    onLines(lines.map((l) =>
      !l.currency || l.currency === header.currency ? { ...l, currency: code } : l));
  };

  const setLine = (index: number, patch: Partial<DocLine>) =>
    onLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  /**
   * Choosing (or changing) the customer on a quotation re-prices the lines
   * from that customer's history. Only lines still at the price they were
   * started at move: a price someone typed is theirs and is left alone.
   */
  const setCustomer = async (customerId: string) => {
    onHeader({ ...header, customer_id: customerId });
    const repriceable = lines.filter((l) => l.item_id && l.suggested_rate != null
      && num(l.unit_price) === l.suggested_rate);
    if (repriceable.length === 0) return;
    const rates = await Promise.all(lines.map((l) => (repriceable.includes(l)
      ? fetchRates(l.item_id!, customerId, l.currency || header.currency) : Promise.resolve(null))));
    onLines(lines.map((l, i) => {
      const r = rates[i];
      if (!r) return l;
      const { price, basis } = startingPrice(r, l.sale_rate);
      return { ...l, last_rate: r.last_rate, suggested_rate: price, rate_basis: basis,
               rate_note: basis === "most_common_other_customers" ? rateNote(r) : null,
               unit_price: price != null ? String(price) : l.unit_price };
    }));
  };

  const removeLine = (index: number) => onLines(lines.filter((_, i) => i !== index));

  return (
    <div className="space-y-5">
      {/* ---------- header fields ---------- */}
      <div className="grid grid-cols-3 gap-4 max-sm:grid-cols-1">
        <Labelled label={kind === "quotation" ? "Quotation Date" : "Sale Date"} required>
          <input type="date" className={input} value={header.doc_date}
            onChange={(e) => setH("doc_date", e.target.value)} />
        </Labelled>

        <div className="col-span-2 max-sm:col-span-1">
          <Labelled label="Customer" required>
            {/* Type-to-search over the whole ledger: a plain dropdown of a
                thousand accounts cannot be navigated. The document stores
                only the id — the address, phone, NTN and STN printed on the
                PDF are read from the ledger account at render time. */}
            <Combobox
              value={header.customer_id}
              options={customerOptions}
              placeholder="Type a customer name or code, or pick from the list…"
              emptyMessage="No customer matches that name or code."
              onChange={(v) => { setCustomer(v); }}
            />
          </Labelled>
          <CustomerCard customer={selectedCustomer} />
        </div>

        <Labelled label="Status">
          <select className={input} value={header.status}
            onChange={(e) => setH("status", e.target.value)}>
            {(kind === "quotation"
              ? ["Draft", "Sent", "Approved", "Rejected", "Closed"]
              : ["Draft", "Posted", "Delivered", "Cancelled"]
            ).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Labelled>

        {kind === "quotation" ? (
          <Labelled label="Demand #">
            <input className={input} value={header.demand_number}
              onChange={(e) => setH("demand_number", e.target.value)} />
          </Labelled>
        ) : (
          <Labelled label="PO NO#">
            <input className={input} value={header.customer_po_number}
              onChange={(e) => setH("customer_po_number", e.target.value)} />
          </Labelled>
        )}

        <Labelled label="Gst">
          <select className={input} value={header.is_service ? "service" : header.with_sales_tax ? "yes" : "no"}
            onChange={(e) => onHeader({ ...header, is_service: e.target.value === "service",
                                        with_sales_tax: e.target.value === "yes" })}>
            <option value="yes">With Sale Tax</option>
            <option value="no">Without Sale Tax</option>
            <option value="service">Service</option>
          </select>
        </Labelled>

        {kind === "sales_order" && (
          <>
            <Labelled label="Dc No">
              <input className={input} value={header.dc_number}
                onChange={(e) => setH("dc_number", e.target.value)} />
            </Labelled>
            <Labelled label="Delivery Person">
              <input className={input} value={header.delivery_person}
                onChange={(e) => setH("delivery_person", e.target.value)} />
            </Labelled>
            <Labelled label="Vehicle No">
              <input className={input} value={header.vehicle_number}
                onChange={(e) => setH("vehicle_number", e.target.value)} />
            </Labelled>
            <Labelled label="Location">
              {/* Offers the Item Locations list but still accepts anything
                  typed: this column stores the location text, not an id, and
                  documents written before the list existed must keep theirs. */}
              <Combobox
                value={header.location}
                options={locations.map((l) => ({ value: l.label, label: l.label }))}
                placeholder="Type a location or pick from Item Locations…"
                emptyMessage="Not in Item Locations — it will be saved as typed."
                allowCustom
                onChange={(v) => setH("location", v)}
              />
            </Labelled>
          </>
        )}

        <Labelled label="Payment Terms">
          <input className={input} value={header.payment_terms}
            onChange={(e) => setH("payment_terms", e.target.value)} />
        </Labelled>
        <Labelled label="Currency">
          {/* Type or pick. The list is offered because it is what is used;
              anything else typed is still accepted and normalised by the
              server, so a one-off currency does not need a code change. */}
          <Combobox
            value={header.currency}
            options={currencyOptions}
            placeholder="PKR"
            emptyMessage="Not a listed currency — it will be saved as typed."
            allowCustom
            onChange={setCurrency}
          />
        </Labelled>
        <Labelled label="Payment Status">
          <select className={input} value={header.payment_status}
            onChange={(e) => setH("payment_status", e.target.value)}>
            {["PENDING", "PARTIAL", "PAID"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Labelled>

        <div className="col-span-3 max-sm:col-span-1">
          <Labelled label="Remarks">
            <textarea rows={2} className={`${input} resize-y`} value={header.remarks}
              onChange={(e) => setH("remarks", e.target.value)} />
          </Labelled>
        </div>
      </div>

      {/* ---------- line items ---------- */}
      <div className="overflow-hidden rounded-[10px] border border-line">
        <div className="flex items-center gap-3 bg-primary px-4 py-2.5 text-on-primary">
          <h4 className="m-0 text-[13px] font-semibold">
            {kind === "quotation" ? "Products For Quotations" : "Products For Sale Order"}
          </h4>
          <button
            type="button"
            onClick={() => onLines([...lines, emptyLine(header.currency)])}
            className="ml-auto flex items-center gap-1.5 rounded-md bg-white/20 px-2.5 py-1
                       text-[11.5px] font-medium transition-colors hover:bg-white/30"
          >
            <Plus size={13} strokeWidth={2.4} /> Add row
          </button>
        </div>

        {/* Columns follow the old ERP's Products grid. Rack, Stock and Last
            Rate are read-only: they come from the product and from earlier
            documents, and are here to inform the price being typed. */}
        <div className="overflow-x-auto">
          <table className={`w-full ${kind === "sales_order" ? "min-w-[1780px]" : "min-w-[1640px]"}
                             border-collapse text-left`}>
            <thead>
              <tr className="border-b border-line bg-hover">
                {["Item Code", "Description", "Rack", "Stock", "Uom", "HS Code", "Qty",
                  "Last Rate",
                  // Sale Rate is the item master's own price, on the order
                  // form only — it is what the sale should be struck at,
                  // beside what it last went out at.
                  ...(kind === "sales_order" ? ["Sale Rate"] : []),
                  "Unit Price", "Currency", "Salestex",
                  "XTAX Amount", "STAX Amount", "Inc Stax Amount", ""].map((h) => (
                  <th key={h} className="whitespace-nowrap px-2 py-2 text-[10.5px] font-semibold
                                          uppercase tracking-wide text-faint">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lines.map((line, i) => (
                <tr key={i} className="border-b border-line last:border-0 align-top">
                  <td className="w-[200px] px-2 py-2">
                    <ItemPicker
                      value={line.item_code}
                      customerId={header.customer_id}
                      currency={line.currency || header.currency}
                      onPick={(item, rates) => {
                        // A quotation starts from what this customer was last
                        // quoted, or the price most other customers were
                        // quoted the first time; the item master price if it was never
                        // quoted. A sales order keeps the item master price
                        // first. Either way the price stays typeable.
                        const { price, basis } = startingPrice(rates, item.price);
                        setLine(i, {
                          item_id: item.id,
                          item_code: item.item_code,
                          description: item.description,
                          uom: item.uom,
                          rack_name: item.rack_name,
                          stock: item.opening_stock,
                          stocked: !NOT_STOCKED.includes((item.main_product_name ?? "").trim().toUpperCase()),
                          last_rate: rates.last_rate,
                          suggested_rate: price,
                          rate_basis: price != null ? basis : null,
                          rate_note: basis === "most_common_other_customers" ? rateNote(rates) : null,
                          sale_rate: item.price,
                          unit_price: price != null ? String(price) : line.unit_price,
                        });
                      }}
                    />
                  </td>
                  <td className="min-w-[300px] px-2 py-2">
                    <textarea rows={2} className={`${input} resize-y leading-snug`}
                      value={line.description}
                      onChange={(e) => setLine(i, { description: e.target.value })} />
                  </td>
                  <ReadCell muted>{line.rack_name ?? "—"}</ReadCell>
                  <ReadCell muted>{line.stock != null ? line.stock.toLocaleString() : "—"}</ReadCell>
                  <td className="w-[110px] px-2 py-2">
                    <UomPicker value={line.uom} uoms={uoms}
                      onChange={(v) => setLine(i, { uom: v })} />
                  </td>
                  <td className="w-[130px] px-2 py-2">
                    <input className={input} value={line.hs_code ?? ""}
                      onChange={(e) => setLine(i, { hs_code: e.target.value })} />
                  </td>
                  <NumCell value={line.quantity} onChange={(v) => setLine(i, { quantity: v })}
                    hint={kind === "sales_order" && line.stocked && !header.is_service && line.stock != null && num(line.quantity) > line.stock ? (
                      <p className="m-0 mt-1 text-[10.5px] font-medium leading-tight text-rose">
                        Only {Math.max(line.stock, 0).toLocaleString()} in stock
                      </p>
                    ) : undefined} />
                  <ReadCell muted>
                    {line.last_rate != null ? money(line.last_rate, line.currency) : "—"}
                  </ReadCell>
                  {kind === "sales_order" && (
                    <td className="w-[120px] whitespace-nowrap px-2 py-3 text-right text-[12px] tabular-nums">
                      {line.sale_rate != null ? (
                        // Click to take it: the price is filled in from the
                        // product already, so this is for putting it back
                        // after the line has been priced by hand.
                        <button
                          type="button"
                          title="Use this as the unit price"
                          onClick={() => setLine(i, { unit_price: String(line.sale_rate) })}
                          className="rounded px-1.5 py-0.5 text-primary transition-colors hover:bg-primary/10"
                        >
                          {money(line.sale_rate, line.currency)}
                        </button>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                  )}
                  <NumCell value={line.unit_price} onChange={(v) => setLine(i, { unit_price: v })} wide
                    hint={line.rate_basis && line.suggested_rate != null && num(line.unit_price) === line.suggested_rate ? (
                      <div title={line.rate_note || BASIS_HINT[line.rate_basis]}
                        className={`mt-0.5 text-right text-[10px] ${line.rate_basis === "customer_last" ? "text-success" : line.rate_basis === "product_price" ? "text-muted" : "text-amber"}`}>
                        {line.rate_basis === "customer_last" ? "customer's last price" : line.rate_basis === "product_price" ? "product price" : "most customers' price"}
                      </div>
                    ) : null} />
                  <td className="w-[110px] px-2 py-2">
                    {/* Per-line currency, from the same list as the document's.
                        It starts as the document's and rarely moves. */}
                    <select className={input} value={line.currency}
                      onChange={(e) => setLine(i, { currency: e.target.value })}>
                      {(CURRENCIES.some((c) => c.code === line.currency)
                        ? CURRENCIES
                        : [{ code: line.currency, symbol: line.currency, name: line.currency },
                           ...CURRENCIES]
                      ).map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.symbol === c.code ? c.code : `${c.symbol} ${c.code}`}
                        </option>
                      ))}
                    </select>
                  </td>
                  <NumCell value={line.tax_percent} onChange={(v) => setLine(i, { tax_percent: v })} />
                  <ReadCell>
                    {money(totals.perLine[i]?.taxable ?? 0, line.currency)}
                    {num(line.discount_percent) > 0 && (
                      // Written before discounts moved to the document. Shown
                      // rather than hidden: it is still being applied, and a
                      // taxable amount that does not match qty x price with no
                      // visible reason is worse than an explanation.
                      <span
                        className="block text-[10px] font-normal text-amber"
                        title={"A line discount from before discounts moved to the "
                          + "document. It is still applied; new discounts go on the "
                          + "document instead."}
                      >
                        less {line.discount_percent}% line discount
                      </span>
                    )}
                  </ReadCell>
                  <ReadCell>{money(totals.perLine[i]?.tax ?? 0, line.currency)}</ReadCell>
                  <ReadCell strong>{money(totals.perLine[i]?.net ?? 0, line.currency)}</ReadCell>
                  <td className="px-2 py-2">
                    <button type="button" onClick={() => removeLine(i)} aria-label="Remove line"
                      className="rounded-md p-1.5 text-muted transition-colors hover:bg-rose/10 hover:text-rose">
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
              {lines.length === 0 && (
                <tr>
                  <td colSpan={kind === "sales_order" ? 16 : 15}
                      className="px-4 py-8 text-center text-[12.5px] text-faint">
                    No lines yet. Use &ldquo;Add row&rdquo; to start.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---------- totals ---------- */}
      <div className="ml-auto w-full max-w-sm space-y-2 rounded-[10px] border border-line bg-surface p-4">
        <TotalRow label="Excluding Tax Value" value={money(totals.excludingTax, header.currency)} />
        <TotalRow label="Sale Tax Value" value={money(totals.taxTotal, header.currency)} />
        <TotalRow label="Gross Amount" value={money(totals.grossAmount, header.currency)} />

        <div className="flex items-center gap-3 pt-1">
          <span className="flex-1 text-[12px] text-muted">Freight</span>
          <input type="number" step="0.01" value={header.freight_amount}
            onChange={(e) => setH("freight_amount", e.target.value)}
            className="w-28 rounded-md border border-line bg-bg px-2 py-1 text-right text-[12.5px] outline-none focus:border-primary" />
        </div>
        <DocumentDiscount
          gross={totals.grossAmount}
          currency={header.currency}
          amount={header.document_discount}
          onChange={(value) => setH("document_discount", value)}
        />

        <div className="flex items-center gap-3 border-t border-line pt-2.5">
          <span className="flex-1 text-[13px] font-semibold">Net Receivable</span>
          <span className="text-[15px] font-bold text-primary">
            {money(totals.netReceivable, header.currency)}
          </span>
        </div>
        <p className="m-0 pt-1 text-[10.5px] leading-snug text-faint">
          Shown live as you type. The server recalculates on save and its figures
          are the ones stored.
        </p>
      </div>
    </div>
  );
}

/**
 * What the picked ledger account will print in the document's Bill To block.
 *
 * The document stores only the customer id; the PDF reads these fields from
 * the ledger when it renders. Showing them here means the person quoting can
 * see they picked the right account, and can see a missing NTN before the
 * document goes out rather than after.
 */
function CustomerCard({ customer }: { customer: Customer | null }) {
  if (!customer) return null;

  const phone = customer.phone || customer.cell;
  const missing = [
    !customer.address && "address",
    !phone && "phone",
    !customer.ntn && "NTN",
    !customer.stn && "STN",
  ].filter(Boolean) as string[];

  return (
    <div className="mt-2 rounded-lg border border-line bg-bg px-3 py-2.5 text-[11.5px] leading-relaxed">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-semibold text-muted">Bill To (from ledger account)</span>
        {customer.code && <span className="text-faint">{customer.code}</span>}
      </div>
      <div className="text-text">{customer.name}</div>
      {customer.address && <div className="text-muted">{customer.address}</div>}
      {phone && <div className="text-muted">Phone: {phone}</div>}
      <div className="text-muted">
        {customer.ntn && <span>NTN# {customer.ntn}</span>}
        {customer.ntn && customer.stn && <span className="px-2 text-faint">·</span>}
        {customer.stn && <span>STN# {customer.stn}</span>}
      </div>
      {missing.length > 0 && (
        <div className="mt-1.5 text-rose">
          Not on this account: {missing.join(", ")} — it will be left off the printed document.
        </div>
      )}
    </div>
  );
}

function Labelled({ label, required, children }: {
  label: string; required?: boolean; children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium text-muted">
        {label} {required && <span className="text-rose">*</span>}
      </span>
      {children}
    </label>
  );
}

function NumCell({ value, onChange, wide, hint }: {
  value: string; onChange: (v: string) => void; wide?: boolean;
  /** A small note under the box, e.g. where a suggested price came from. */
  hint?: React.ReactNode;
}) {
  return (
    <td className={`px-2 py-2 ${wide ? "w-[130px]" : "w-[95px]"}`}>
      {/* Typed only: no spinner arrows, and a zero shows as an empty box to type into.
          Anything but digits and one decimal point is ignored. */}
      <input type="text" inputMode="decimal" value={value === "0" ? "" : value} placeholder="0"
        onFocus={(e) => e.target.select()}
        onChange={(e) => {
          const typed = e.target.value.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1");
          onChange(typed === "" ? "0" : typed);
        }}
        className="w-full rounded-md border border-line bg-bg px-2 py-1.5 text-right
                   text-[12.5px] outline-none transition-colors placeholder:text-faint focus:border-primary" />
      {hint}
    </td>
  );
}

function ReadCell({ children, strong, muted }: {
  children: React.ReactNode; strong?: boolean; muted?: boolean;
}) {
  return (
    <td className={`whitespace-nowrap px-2 py-3 text-right text-[12px] tabular-nums
                    ${strong ? "font-semibold" : "text-muted"} ${muted ? "text-center" : ""}`}>
      {children}
    </td>
  );
}

/**
 * The discount on the whole document, entered as a percentage or as an amount.
 *
 * Only the amount is stored, because that is what the document is actually
 * reduced by and what every later report has to reconcile to. The percentage
 * is a way of arriving at it: typing 5 works out 5% of the gross and writes
 * that figure, so a quotation discounted "five percent" and one discounted
 * "PKR 12,000" are the same kind of record afterwards.
 *
 * Discount lives here rather than on each line: one number the customer can
 * see and argue about, instead of a percentage repeated down the grid.
 */
function DocumentDiscount({ gross, currency, amount, onChange }: {
  gross: number;
  currency: string;
  amount: string;
  onChange: (amount: string) => void;
}) {
  const [mode, setMode] = useState<"amount" | "percent">("amount");
  const [percent, setPercent] = useState("");

  // Re-deriving the amount as the lines change is the whole point of a
  // percentage: 5% of a document that has grown should grow with it.
  useEffect(() => {
    if (mode !== "percent") return;
    const rate = num(percent);
    onChange(rate > 0 ? String(Math.round(gross * rate) / 100) : "0");
    // onChange is recreated each render by the parent; depending on it here
    // would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, percent, gross]);

  const applied = num(amount);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-3">
        <span className="flex-1 text-[12px] text-muted">Discount</span>

        {/* Which way the number being typed should be read. */}
        <div className="flex overflow-hidden rounded-md border border-line">
          {(["amount", "percent"] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setMode(option)}
              className={`px-2 py-1 text-[11px] font-medium transition-colors
                          ${mode === option
                            ? "bg-primary text-on-primary"
                            : "bg-bg text-muted hover:text-text"}`}
            >
              {option === "amount" ? currency : "%"}
            </button>
          ))}
        </div>

        {mode === "percent" ? (
          <input
            type="number" step="0.01" min="0" max="100" value={percent}
            placeholder="0"
            onChange={(e) => setPercent(e.target.value)}
            className="w-20 rounded-md border border-line bg-bg px-2 py-1 text-right
                       text-[12.5px] outline-none focus:border-primary"
          />
        ) : (
          <input
            type="number" step="0.01" min="0" value={amount}
            onChange={(e) => onChange(e.target.value)}
            className="w-28 rounded-md border border-line bg-bg px-2 py-1 text-right
                       text-[12.5px] outline-none focus:border-primary"
          />
        )}
      </div>

      {mode === "percent" && applied > 0 && (
        <div className="text-right text-[11px] text-muted">
          {percent}% of {money(gross, currency)} = {money(applied, currency)}
        </div>
      )}
      {mode === "amount" && gross > 0 && applied > 0 && (
        <div className="text-right text-[11px] text-muted">
          {Math.round((applied / gross) * 1000) / 10}% of the gross
        </div>
      )}
    </div>
  );
}


function TotalRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex-1 text-[12px] text-muted">{label}</span>
      <span className="text-[12.5px] tabular-nums">{value}</span>
    </div>
  );
}

/** Type-ahead product lookup that queries the server rather than loading
 *  all ~5,000 items into the browser. */
function ItemPicker({ value, customerId, currency, onPick }: {
  value: string | null;
  customerId: string;
  currency: string;
  onPick: (item: ItemOption, rates: Rates) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ItemOption[]>([]);
  const [busy, setBusy] = useState(false);

  /** Resolve the item's price history for this customer before handing it
   *  back, so the row arrives complete rather than filling in a moment later.
   *  A failed lookup is not worth blocking the pick over. */
  const choose = async (item: ItemOption) => {
    setOpen(false);
    setQuery("");
    onPick(item, await fetchRates(item.id, customerId, currency));
  };

  useEffect(() => {
    if (!open || query.trim().length < 2) { setResults([]); return; }
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const data = await api.get<{ items: ItemOption[] }>(
          `/inventory/items?search=${encodeURIComponent(query)}&page_size=15`,
        );
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
      <button type="button" onClick={() => setOpen(true)}
        className="w-full truncate rounded-md border border-line bg-bg px-2.5 py-1.5
                   text-left text-[12px] transition-colors hover:border-primary">
        {value || <span className="text-faint">Pick item…</span>}
      </button>

      {open && (
        <div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/50 p-4 pt-24">
          <div className="w-full max-w-lg rounded-[12px] border border-line bg-surface shadow-xl">
            <div className="flex items-center gap-2 border-b border-line px-4 py-3">
              <h4 className="m-0 text-[13.5px] font-semibold">Select product</h4>
              <button onClick={() => setOpen(false)} aria-label="Close"
                className="ml-auto rounded-md p-1 text-muted hover:bg-hover">
                <X size={16} />
              </button>
            </div>
            <div className="p-4">
              <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="Type at least 2 characters…"
                className="w-full rounded-lg border border-line bg-bg px-3.5 py-2.5 text-[13px]
                           outline-none focus:border-primary" />
              <div className="mt-3 max-h-72 overflow-y-auto">
                {busy && <p className="py-6 text-center"><Loader2 size={16} className="mx-auto animate-spin text-primary" /></p>}
                {!busy && query.length >= 2 && results.length === 0 && (
                  <p className="py-6 text-center text-[12.5px] text-faint">No matching products.</p>
                )}
                {results.map((item) => (
                  <button key={item.id} type="button"
                    onClick={() => void choose(item)}
                    className="block w-full border-b border-line px-2 py-2.5 text-left
                               last:border-0 hover:bg-hover">
                    <div className="text-[12.5px] font-medium">{item.description}</div>
                    <div className="text-[11px] text-faint">
                      {item.item_code} · {item.uom ?? "—"} · Stock {item.opening_stock}
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
