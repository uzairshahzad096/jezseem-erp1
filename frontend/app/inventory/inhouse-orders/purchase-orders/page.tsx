"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Plus, Search, Loader2, Pencil, Trash2, CheckCircle2, Ship, PackageCheck, Globe, Printer,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal, TextInput, TextArea, Select, Combobox } from "@/components/ui/Modal";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate, gridAmount,
} from "@/components/ui/grid";
import { ProductPicker, type PickedProduct } from "@/components/procurement/ProductPicker";
import {
  useProcurementList, useSuppliers, COUNTRIES, INCOTERMS,
  SHIPPING_MODES, PAKISTAN_PORTS, type Supplier,
} from "@/lib/useProcurement";
import { useLookups, toOptions } from "@/lib/useLookups";
import { UomPicker } from "@/components/ui/UomPicker";
import { currencyOptions, money } from "@/lib/currency";
import { api } from "@/lib/api";
import { openPdf } from "@/lib/openPdf";

const STATUSES = [
  "Draft", "Pending Approval", "Approved", "Sent", "Acknowledged", "Open", "Partially Received",
  "Fully Received", "Partially Invoiced", "Fully Invoiced", "Closed", "Cancelled",
];

const PRIORITY_STYLE: Record<string, string> = {
  Urgent: "bg-rose/15 text-rose",
  High: "bg-amber/15 text-amber",
  Medium: "bg-sky/15 text-sky",
  Low: "bg-hover text-muted",
};

const STATUS_STYLE: Record<string, string> = {
  Draft: "bg-hover text-muted",
  "Pending Approval": "bg-amber/15 text-amber",
  Approved: "bg-success/15 text-success",
  Open: "bg-sky/15 text-sky",
  Sent: "bg-sky/15 text-sky",
  Acknowledged: "bg-violet/15 text-violet",
  "Partially Received": "bg-amber/15 text-amber",
  "Fully Received": "bg-success/15 text-success",
  "Partially Invoiced": "bg-violet/15 text-violet",
  "Fully Invoiced": "bg-violet/15 text-violet",
  Closed: "bg-hover text-muted",
  Cancelled: "bg-rose/15 text-rose",
};

interface PoRow {
  id: string;
  doc_number: string;
  doc_date: string;
  purchase_type: string;
  supplier_id: string;
  supplier: string | null;
  supplier_country: string | null;
  country_of_origin: string | null;
  warehouse: string | null;
  in_house_order_id: string | null;
  status: string;
  po_status: string;
  purchaser: string | null;
  currency: string;
  exchange_rate: number;
  incoterm: string | null;
  lc_number: string | null;
  expected_delivery_date: string | null;
  priority?: string | null;
  expected_arrival_date: string | null;
  payment_terms: string | null;
  remarks: string | null;
  excluding_tax_value: number;
  sales_tax_value: number;
  gross_amount: number;
  discount_amount: number;
  freight_amount: number;
  net_payable: number;
  net_payable_base: number;
  total_items: number;
}

interface PoLine {
  id: string;
  line_number: number;
  in_house_order_line_id: string | null;
  item_id: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  hs_code: string | null;
  quantity: number;
  free_quantity: number;
  shipped_quantity: number;
  received_quantity: number;
  outstanding_quantity: number;
  unit_price: number;
  discount_percent: number;
  tax_percent: number;
  net_amount: number;
  unit_weight: number | null;
  unit_volume: number | null;
  remarks: string | null;
}

interface PoDetail extends PoRow {
  warehouse_id: string | null;
  purchaser_email: string | null;
  contact_number: string | null;
  expiry_date: string | null;
  target_date: string | null;
  delivery_terms: string | null;
  shipping_terms: string | null;
  credit_days: number | null;
  supplier_quotation_number: string | null;
  supplier_quotation_date: string | null;
  shipping_mode: string | null;
  port_of_loading: string | null;
  port_of_discharge: string | null;
  expected_shipment_date: string | null;
  commercial_invoice_number: string | null;
  commercial_invoice_date: string | null;
  packing_list_number: string | null;
  bill_of_lading_number: string | null;
  airway_bill_number: string | null;
  container_number: string | null;
  lc_date: string | null;
  bank_name: string | null;
  freight_forwarder: string | null;
  clearing_agent: string | null;
  insurance_provider: string | null;
  customs_reference: string | null;
  import_reference: string | null;
  lines: PoLine[];
}

const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: PoRow) => React.ReactNode;
}[] = [
  { key: "doc_number", label: "PO No", sort: "doc_number",
    render: (r) => <span className="font-medium">{r.doc_number}</span> },
  { key: "doc_date", label: "Date", sort: "doc_date",
    render: (r) => <span className="whitespace-nowrap">{gridDate(r.doc_date)}</span> },
  { key: "purchase_type", label: "Type",
    render: (r) => (
      <span className={`whitespace-nowrap rounded-md px-2 py-0.5 text-[10.5px] font-semibold
                        ${r.purchase_type === "Import"
                          ? "bg-violet/15 text-violet" : "bg-hover text-muted"}`}>
        {r.purchase_type === "Import" && <Globe size={9} className="mr-1 inline" />}
        {r.purchase_type}
      </span>
    ) },
  { key: "supplier", label: "Supplier", render: (r) => r.supplier ?? "—" },
  { key: "supplier_country", label: "Country", render: (r) => r.supplier_country ?? "—" },
  { key: "warehouse", label: "Warehouse", render: (r) => r.warehouse ?? "—" },
  { key: "status", label: "Status", sort: "status",
    render: (r) => (
      <span className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                        ${STATUS_STYLE[r.status] ?? "bg-hover text-muted"}`}>
        {r.status}
      </span>
    ) },
  { key: "currency", label: "Currency", render: (r) => r.currency },
  { key: "exchange_rate", label: "Rate", numeric: true,
    render: (r) => (r.exchange_rate === 1 ? "—" : gridAmount(r.exchange_rate)) },
  { key: "incoterm", label: "Incoterm", render: (r) => r.incoterm ?? "—" },
  { key: "lc_number", label: "LC No", render: (r) => r.lc_number ?? "—" },
  { key: "priority", label: "Priority",
    render: (r) => (
      <span className={`rounded-md px-2 py-0.5 text-[10.5px] font-semibold ${PRIORITY_STYLE[r.priority ?? "Medium"] ?? "bg-hover text-muted"}`}>
        {r.priority ?? "Medium"}
      </span>
    ) },
  { key: "expected_delivery_date", label: "Expected Date",
    render: (r) => {
      const when = r.expected_arrival_date ?? r.expected_delivery_date;
      return when ? <span className="whitespace-nowrap">{gridDate(when)}</span> : "—";
    } },
  { key: "total_items", label: "Items", numeric: true, render: (r) => r.total_items },
  { key: "net_payable", label: "Net Payable", numeric: true, sort: "net_payable",
    render: (r) => <span className="font-semibold">{money(r.net_payable, r.currency)}</span> },
  { key: "net_payable_base", label: "Net (PKR)", numeric: true, sort: "net_payable_base",
    render: (r) => gridAmount(r.net_payable_base) },
  { key: "payment_terms", label: "Payment Terms", render: (r) => r.payment_terms ?? "—" },
  { key: "remarks", label: "Remarks", render: (r) => r.remarks ?? "—" },
];

const DEFAULT_HIDDEN = ["incoterm", "lc_number", "payment_terms", "remarks", "exchange_rate"];

const emptyLine = () => ({
  id: null as string | null,
  in_house_order_line_id: null as string | null,
  item_id: null as string | null,
  item_code: null as string | null,
  description: "",
  uom: null as string | null,
  hs_code: "",
  origin_country: "",
  quantity: "1",
  free_quantity: "0",
  unit_price: "0",
  discount_percent: "0",
  tax_percent: "0",
  unit_weight: "",
  unit_volume: "",
  received_quantity: 0,
  shipped_quantity: 0,
});

type FormLine = ReturnType<typeof emptyLine>;

const emptyHeader = () => ({
  doc_date: new Date().toISOString().slice(0, 10),
  purchase_type: "Local" as "Local" | "Import",
  supplier_id: "",
  warehouse_id: "",
  purchaser: "",
  purchaser_email: "",
  contact_number: "",
  payment_terms: "",
  delivery_terms: "",
  credit_days: "",
  expected_delivery_date: "",
  priority: "Medium",
  supplier_quotation_number: "",
  supplier_quotation_date: "",
  indent_number: "",
  remarks: "",
  currency: "PKR",
  exchange_rate: "1",
  freight_amount: "0",
  document_discount: "0",
  // import block
  supplier_country: "",
  country_of_origin: "",
  incoterm: "",
  shipping_mode: "",
  port_of_loading: "",
  port_of_discharge: "",
  expected_shipment_date: "",
  expected_arrival_date: "",
  commercial_invoice_number: "",
  commercial_invoice_date: "",
  packing_list_number: "",
  bill_of_lading_number: "",
  airway_bill_number: "",
  container_number: "",
  lc_number: "",
  lc_date: "",
  bank_name: "",
  freight_forwarder: "",
  clearing_agent: "",
  insurance_provider: "",
  customs_reference: "",
  import_reference: "",
  // Import Purchase Order template
  purchase_category: "",
  buyer_designation: "",
  supplier_contact: "",
  supplier_contact_designation: "",
  ship_to_address: "",
  bill_to_address: "",
  incoterm_edition: "",
  named_place: "",
  partial_shipment: "",
  transshipment: "",
  packing_marks: "",
  country_of_export: "",
  payment_method: "",
  balance_trigger: "",
  bank_charges: "",
  payment_reference: "",
  goods_condition: "",
  warranty_terms: "",
  defect_remedy: "",
  special_packing: "",
  pre_shipment_inspection: "",
  special_instructions: "",
  packing_amount: "0",
  insurance_amount: "0",
  other_charges: "0",
  advance_amount: "0",
  advance_percent: "0",
});

const TEMPLATE_TEXT = ["purchase_category", "buyer_designation", "supplier_contact", "supplier_contact_designation", "ship_to_address", "bill_to_address", "incoterm_edition", "named_place", "partial_shipment", "transshipment", "packing_marks", "country_of_export", "payment_method", "balance_trigger", "bank_charges", "payment_reference", "goods_condition", "warranty_terms", "defect_remedy", "special_packing", "pre_shipment_inspection", "special_instructions"] as const;
const TEMPLATE_AMOUNTS = ["packing_amount", "insurance_amount", "other_charges", "advance_amount", "advance_percent"] as const;

type FormHeader = ReturnType<typeof emptyHeader>;

/** Live totals while typing. The server recalculates and its answer is kept. */
function computeTotals(lines: FormLine[], freight: string, discount: string) {
  const num = (v: string) => (Number.isFinite(Number(v)) ? Number(v) : 0);
  const perLine = lines.map((l) => {
    const gross = num(l.quantity) * num(l.unit_price);
    const disc = Math.min((gross * num(l.discount_percent)) / 100, gross);
    const taxable = gross - disc;
    const tax = (taxable * num(l.tax_percent)) / 100;
    return { gross, disc, taxable, tax, net: taxable + tax };
  });
  const excluding = perLine.reduce((s, l) => s + l.taxable, 0);
  const tax = perLine.reduce((s, l) => s + l.tax, 0);
  return {
    perLine,
    excluding,
    tax,
    gross: excluding + tax,
    net: excluding + tax + num(freight) - num(discount),
  };
}

/** What a number box keeps of what was typed: digits and one decimal point; empty is zero. */
const typedNumber = (raw: string) => {
  const kept = raw.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1");
  return kept === "" ? "0" : kept;
};
export default function PurchaseOrdersPage() {
  const list = useProcurementList<PoRow>("/procurement/purchase-orders");
  const { locations, uoms } = useLookups();
  const suppliers = useSuppliers();

  const [typeFilter, setTypeFilter] = useState<"" | "Local" | "Import">("");
  const [isOpen, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [header, setHeader] = useState<FormHeader>(emptyHeader());
  const [lines, setLines] = useState<FormLine[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [revision, setRevision] = useState(0);

  const columnState = useHiddenColumns("purchase-orders.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));
  const isImport = header.purchase_type === "Import";

  const rows = typeFilter
    ? list.rows.filter((r) => r.purchase_type === typeFilter)
    : list.rows;

  const totals = useMemo(
    () => computeTotals(lines, String((Number(header.freight_amount) || 0) + (Number(header.packing_amount) || 0)
      + (Number(header.insurance_amount) || 0) + (Number(header.other_charges) || 0)), header.document_discount),
    [lines, header.freight_amount, header.document_discount, header.packing_amount, header.insurance_amount, header.other_charges]);

  const supplier = suppliers.find((s) => s.id === header.supplier_id);

  const exportQuery = new URLSearchParams([
    ...(list.search ? [["search", list.search]] : []),
    ...list.statuses.map((s) => ["status", s] as [string, string]),
  ]).toString();

  const setH = (patch: Partial<FormHeader>) => setHeader((h) => ({ ...h, ...patch }));
  const setLine = (index: number, patch: Partial<FormLine>) =>
    setLines((ls) => ls.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  /** Picking a supplier decides whether this is an import, and in what money. */
  const pickSupplier = (id: string) => {
    const chosen = suppliers.find((s) => s.id === id);
    if (!chosen) { setH({ supplier_id: id }); return; }
    setH({
      supplier_id: id,
      purchase_type: chosen.is_international ? "Import" : "Local",
      currency: chosen.currency || (chosen.is_international ? "USD" : "PKR"),
      exchange_rate: chosen.is_international ? header.exchange_rate : "1",
      payment_terms: header.payment_terms || chosen.payment_terms || "",
      credit_days: header.credit_days || (chosen.credit_days?.toString() ?? ""),
      supplier_country: chosen.country ?? "",
      country_of_origin: chosen.country_of_origin ?? chosen.country ?? "",
      incoterm: chosen.incoterm ?? "",
      bank_name: chosen.bank_name ?? "",
    });
  };

  const openNew = () => {
    setEditingId(null);
    setReadOnly(false);
    setHeader(emptyHeader());
    setLines([emptyLine()]);
    setRevision(0);
    setFormError(null);
    setOpen(true);
  };

  const openEdit = async (id: string) => {
    setFormError(null);
    try {
      const doc = await api.get<PoDetail>(`/procurement/purchase-orders/${id}`);
      setEditingId(id);
      setReadOnly(["Fully Received", "Fully Invoiced", "Closed", "Cancelled"]
        .includes(doc.status));
      setHeader({
        ...emptyHeader(),
        doc_date: doc.doc_date,
        purchase_type: doc.purchase_type === "Import" ? "Import" : "Local",
        supplier_id: doc.supplier_id,
        warehouse_id: doc.warehouse_id ?? "",
        purchaser: doc.purchaser ?? "",
        purchaser_email: doc.purchaser_email ?? "",
        contact_number: doc.contact_number ?? "",
        payment_terms: doc.payment_terms ?? "",
        delivery_terms: doc.delivery_terms ?? "",
        credit_days: doc.credit_days?.toString() ?? "",
        expected_delivery_date: doc.expected_delivery_date ?? "",
        priority: doc.priority ?? "Medium",
        supplier_quotation_number: doc.supplier_quotation_number ?? "",
        supplier_quotation_date: doc.supplier_quotation_date ?? "",
        remarks: doc.remarks ?? "",
        currency: doc.currency,
        exchange_rate: String(doc.exchange_rate),
        freight_amount: String(doc.freight_amount),
        document_discount: String(doc.discount_amount),
        supplier_country: doc.supplier_country ?? "",
        country_of_origin: doc.country_of_origin ?? "",
        incoterm: doc.incoterm ?? "",
        shipping_mode: doc.shipping_mode ?? "",
        port_of_loading: doc.port_of_loading ?? "",
        port_of_discharge: doc.port_of_discharge ?? "",
        expected_shipment_date: doc.expected_shipment_date ?? "",
        expected_arrival_date: doc.expected_arrival_date ?? "",
        commercial_invoice_number: doc.commercial_invoice_number ?? "",
        commercial_invoice_date: doc.commercial_invoice_date ?? "",
        packing_list_number: doc.packing_list_number ?? "",
        bill_of_lading_number: doc.bill_of_lading_number ?? "",
        airway_bill_number: doc.airway_bill_number ?? "",
        container_number: doc.container_number ?? "",
        lc_number: doc.lc_number ?? "",
        lc_date: doc.lc_date ?? "",
        bank_name: doc.bank_name ?? "",
        freight_forwarder: doc.freight_forwarder ?? "",
        clearing_agent: doc.clearing_agent ?? "",
        insurance_provider: doc.insurance_provider ?? "",
        customs_reference: doc.customs_reference ?? "",
        import_reference: doc.import_reference ?? "",
        ...Object.fromEntries(TEMPLATE_TEXT.map((k) => [k, ((doc as unknown as Record<string, unknown>)[k] as string | null) ?? ""])),
        ...Object.fromEntries(TEMPLATE_AMOUNTS.map((k) => [k, String(((doc as unknown as Record<string, unknown>)[k] as number | null) ?? 0)])),
      });
      setRevision(((doc as unknown as Record<string, unknown>).revision as number) ?? 0);
      setLines(doc.lines.map((l) => ({
        id: l.id,
        in_house_order_line_id: l.in_house_order_line_id,
        item_id: l.item_id,
        item_code: l.item_code,
        description: l.description,
        uom: l.uom,
        hs_code: l.hs_code ?? "",
        origin_country: (l as { origin_country?: string | null }).origin_country ?? "",
        quantity: String(l.quantity),
        free_quantity: String(l.free_quantity),
        unit_price: String(l.unit_price),
        discount_percent: String(l.discount_percent),
        tax_percent: String(l.tax_percent),
        unit_weight: l.unit_weight != null ? String(l.unit_weight) : "",
        unit_volume: l.unit_volume != null ? String(l.unit_volume) : "",
        received_quantity: l.received_quantity,
        shipped_quantity: l.shipped_quantity,
      })));
      setOpen(true);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not open the order.");
      setOpen(true);
    }
  };

  const save = async () => {
    if (!header.supplier_id) { setFormError("Choose a supplier."); return; }
    if (lines.length === 0) { setFormError("Add at least one product line."); return; }
    if (lines.some((l) => !l.description.trim() && !l.item_id)) {
      setFormError("Every line needs a product or a description."); return;
    }
    if (lines.some((l) => Number(l.quantity) <= 0)) {
      setFormError("Every line needs a quantity greater than zero."); return;
    }
    if (isImport && header.currency === "PKR") {
      setFormError("An import order in PKR will be refused — set the supplier's "
        + "currency and the exchange rate, or make this a local purchase.");
      return;
    }

    setSaving(true);
    setFormError(null);
    try {
      const body = {
        ...header,
        credit_days: header.credit_days ? Number(header.credit_days) : null,
        warehouse_id: header.warehouse_id || null,
        expected_delivery_date: header.expected_delivery_date || null,
        priority: header.priority || "Medium",
        supplier_quotation_date: header.supplier_quotation_date || null,
        expected_shipment_date: header.expected_shipment_date || null,
        expected_arrival_date: header.expected_arrival_date || null,
        commercial_invoice_date: header.commercial_invoice_date || null,
        lc_date: header.lc_date || null,
        ...Object.fromEntries(TEMPLATE_TEXT.map((k) => [k, header[k].trim() || null])),
        ...Object.fromEntries(TEMPLATE_AMOUNTS.map((k) => [k, header[k] || "0"])),
        lines: lines.map((l) => ({
          id: l.id,
          in_house_order_line_id: l.in_house_order_line_id,
          item_id: l.item_id,
          item_code: l.item_code,
          description: l.description || null,
          uom: l.uom,
          hs_code: l.hs_code || null,
          origin_country: l.origin_country || null,
          quantity: l.quantity,
          free_quantity: l.free_quantity || "0",
          unit_price: l.unit_price || "0",
          discount_percent: l.discount_percent || "0",
          tax_percent: l.tax_percent || "0",
          unit_weight: l.unit_weight || null,
          unit_volume: l.unit_volume || null,
        })),
      };
      if (editingId) await api.put(`/procurement/purchase-orders/${editingId}`, body);
      else await api.post("/procurement/purchase-orders", body);
      setOpen(false);
      await list.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the order.");
    } finally {
      setSaving(false);
    }
  };

  const move = async (id: string, status: string) => {
    try {
      await api.post(`/procurement/purchase-orders/${id}/status`, { status });
      await list.reload();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not change the status.");
    }
  };

  return (
    <AppShell title="Purchase Orders">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Purchase Orders</h1>
        <div className="flex gap-1.5">
          {(["", "Local", "Import"] as const).map((t) => (
            <button key={t || "all"} onClick={() => setTypeFilter(t)}
              className={`rounded-lg px-3 py-1.5 text-[11.5px] font-medium transition-colors
                          ${typeFilter === t
                            ? "bg-primary text-on-primary" : "bg-hover text-muted hover:text-text"}`}>
              {t || "All"}
            </button>
          ))}
        </div>
        <button onClick={openNew}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br
                     from-primary to-primary-dark px-3.5 py-2 text-[12.8px]
                     font-medium text-on-primary">
          <Plus size={14} strokeWidth={2.4} /> Create Purchase Order
        </button>
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.total} onReset={list.reset} resettable={list.dirty} />

        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={list.search} onChange={(e) => list.setSearch(e.target.value)}
              placeholder="Search number, item, LC, invoice…"
              className="w-56 border-none bg-transparent text-[12.8px] outline-none
                         placeholder:text-faint" />
          </div>
          <div className="ml-auto order-3 flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset="purchase-orders" query={exportQuery} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Draft", "Open", "Partially Received", "Fully Received"].map((s) => (
              <button key={s} onClick={() => list.toggleStatus(s)}
                className={`rounded-lg px-2.5 py-1.5 text-[11.5px] font-medium
                            transition-colors ${list.statuses.includes(s)
                              ? "bg-primary text-on-primary"
                              : "bg-hover text-muted hover:text-text"}`}>
                {s}
              </button>
            ))}
          </div>
        </div>

        {list.error && (
          <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">
            {list.error}
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left"
                 style={{ minWidth: `${250 + visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Edit</GridTh>
                <GridTh>Actions</GridTh>
                <GridTh>Print</GridTh>
                {visible.map((c) => (
                  <GridTh key={c.key} numeric={c.numeric} sortKey={c.sort}
                          sort={list.sort} direction={list.direction}
                          onSort={list.toggleSort}>
                    {c.label}
                  </GridTh>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.loading && (
                <tr><td colSpan={visible.length + 3} className="px-5 py-12 text-center">
                  <Loader2 size={18} className="mx-auto animate-spin text-primary" />
                </td></tr>
              )}
              {!list.loading && rows.length === 0 && (
                <tr><td colSpan={visible.length + 3}
                        className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No purchase orders match these filters. Raise one from an approved
                  in-house order, or create it directly.
                </td></tr>
              )}
              {!list.loading && rows.map((row, index) => (
                <tr key={row.id} className={`align-top ${gridRowClass(index)}`}>
                  <td className={gridCellClass()}>
                    <button onClick={() => openEdit(row.id)} aria-label="Edit" title="Edit"
                      className="rounded-md p-1.5 text-muted hover:bg-primary/10
                                 hover:text-primary">
                      <Pencil size={14} />
                    </button>
                  </td>
                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1">
                      {["Draft", "Pending Approval"].includes(row.status) && (
                        <button onClick={() => move(row.id, "Approved")}
                          title="Approve — opens it for receiving" aria-label="Approve"
                          className="rounded-md p-1.5 text-muted hover:bg-primary/10
                                     hover:text-primary">
                          <CheckCircle2 size={14} />
                        </button>
                      )}
                      {["Approved", "Open"].includes(row.status) && (
                        <button onClick={() => move(row.id, "Sent")} title="Mark as sent to the supplier"
                          className="whitespace-nowrap rounded-md bg-sky/10 px-2 py-1 text-[10.5px] font-medium text-sky hover:bg-sky/20">
                          Sent
                        </button>
                      )}
                      {row.status === "Sent" && (
                        <button onClick={() => move(row.id, "Acknowledged")} title="The supplier has acknowledged the order"
                          className="whitespace-nowrap rounded-md bg-amber/10 px-2 py-1 text-[10.5px] font-medium text-amber hover:bg-amber/20">
                          Acknowledged
                        </button>
                      )}
                      {row.purchase_type === "Import"
                        && ["Approved", "Sent", "Acknowledged", "Open", "Partially Received"].includes(row.status) && (
                        <Link href={`/inventory/inhouse-orders/shipments?po=${row.id}`}
                          title="Record a shipment against this order"
                          className="whitespace-nowrap rounded-md bg-violet/10 px-2 py-1
                                     text-[10.5px] font-medium text-violet hover:bg-violet/20">
                          <Ship size={11} className="mr-1 inline" />Ship
                        </Link>
                      )}
                      {row.purchase_type === "Local"
                        && ["Approved", "Sent", "Acknowledged", "Open", "Partially Received"].includes(row.status) && (
                        <Link href={`/inventory/inhouse-orders/goods-receipts?po=${row.id}`}
                          title="Receive goods against this order"
                          className="whitespace-nowrap rounded-md bg-primary/10 px-2 py-1
                                     text-[10.5px] font-medium text-primary hover:bg-primary/20">
                          <PackageCheck size={11} className="mr-1 inline" />Receive
                        </Link>
                      )}
                    </div>
                  </td>
                  <td className={gridCellClass()}>
                    <button onClick={() => openPdf(`/documents/purchase-orders/${row.id}.pdf`)}
                      title="Print purchase order" aria-label="Print purchase order"
                      className="rounded-full bg-sky p-1.5 text-white shadow-sm hover:bg-sky/85">
                      <Printer size={13} />
                    </button>
                  </td>
                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "remarks" ? "max-w-[200px] truncate text-muted" : "")}
                        title={c.key === "remarks" ? row.remarks ?? "" : undefined}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{list.total.toLocaleString()} purchase orders</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">
              Previous
            </button>
            <span className="px-2">Page {list.page} of {pages}</span>
            <button disabled={list.page >= pages} onClick={() => list.setPage(list.page + 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">
              Next
            </button>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- the form */}
      <Modal
        title={editingId
          ? `${readOnly ? "" : "Edit "}${isImport ? "Import" : "Local"} Purchase Order`
          : `Create ${isImport ? "Import" : "Local"} Purchase Order`}
        open={isOpen} saving={saving} error={formError} width="xl"
        onClose={() => setOpen(false)}
        onSave={readOnly ? undefined : save}
        saveLabel={editingId ? "Save" : "Create"}
      >
        {readOnly && (
          <div className="mb-4 rounded-lg border border-line bg-hover px-3.5 py-2.5
                          text-[12.5px] text-muted">
            This order is closed to changes. The quantities below show what was
            ordered, shipped and received.
          </div>
        )}

        <div className="grid grid-cols-4 gap-4 max-sm:grid-cols-1">
          <div className="col-span-2 max-sm:col-span-1">
            <Labelled label="Supplier" required>
              <Combobox value={header.supplier_id} disabled={readOnly}
                options={suppliers.map((s) => ({
                  value: s.id,
                  label: `${s.name}${s.code ? ` — ${s.code}` : ""}`
                    + (s.is_international ? `  (import${s.country ? `, ${s.country}` : ""})` : ""),
                  short: s.name,
                }))}
                placeholder="Type a supplier name or code…"
                emptyMessage="No supplier matches. Tick Supplier on the account first."
                onChange={pickSupplier} />
            </Labelled>
            {supplier && <SupplierCard supplier={supplier} />}
          </div>
          <Labelled label="Purchase Type" required>
            <Select value={header.purchase_type} disabled={readOnly}
              options={[{ value: "Local", label: "Local — supplier in Pakistan" },
                        { value: "Import", label: "Import — international supplier" }]}
              onChange={(e) => setH({
                purchase_type: e.target.value as "Local" | "Import",
                currency: e.target.value === "Import"
                  ? (header.currency === "PKR" ? "USD" : header.currency) : "PKR",
                exchange_rate: e.target.value === "Import" ? header.exchange_rate : "1",
              })} />
          </Labelled>
          <Labelled label="Date" required>
            <TextInput type="date" value={header.doc_date} disabled={readOnly}
              onChange={(e) => setH({ doc_date: e.target.value })} />
          </Labelled>

          <Labelled label="Deliver to Warehouse">
            <Combobox value={header.warehouse_id} options={toOptions(locations)}
              disabled={readOnly} placeholder="Pick a warehouse…"
              onChange={(v) => setH({ warehouse_id: v })} />
          </Labelled>
          <Labelled label="Currency" required>
            <Combobox value={header.currency} options={currencyOptions} allowCustom
              disabled={readOnly} placeholder="PKR"
              emptyMessage="Not a listed currency — it will be saved as typed."
              onChange={(v) => setH({
                currency: v.toUpperCase(),
                exchange_rate: v.toUpperCase() === "PKR" ? "1" : header.exchange_rate,
              })} />
          </Labelled>
          <Labelled label={`Exchange Rate (1 ${header.currency} = ? PKR)`}>
            <TextInput inputMode="decimal" value={header.exchange_rate}
              disabled={readOnly || header.currency === "PKR"} onFocus={(e) => e.target.select()}
              onChange={(e) => setH({ exchange_rate: e.target.value.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1") })} />
          </Labelled>
          <Labelled label="Buyer">
            <TextInput value={header.purchaser} disabled={readOnly}
              onChange={(e) => setH({ purchaser: e.target.value })} />
          </Labelled>

          <Labelled label="Payment Terms">
            <TextInput value={header.payment_terms} disabled={readOnly}
              onChange={(e) => setH({ payment_terms: e.target.value })} />
          </Labelled>
          <Labelled label="Delivery Terms">
            <TextInput value={header.delivery_terms} disabled={readOnly}
              onChange={(e) => setH({ delivery_terms: e.target.value })} />
          </Labelled>
          <Labelled label="Priority">
            <Select value={header.priority} disabled={readOnly}
              options={["Urgent", "High", "Medium", "Low"].map((p) => ({ value: p, label: p }))}
              onChange={(e) => setH({ priority: e.target.value })} />
          </Labelled>
          <Labelled label="Expected Date">
            <TextInput type="date" disabled={readOnly}
              value={isImport ? header.expected_arrival_date : header.expected_delivery_date}
              onChange={(e) => setH(isImport
                ? { expected_arrival_date: e.target.value }
                : { expected_delivery_date: e.target.value })} />
          </Labelled>
          <Labelled label="Supplier Quotation No">
            <TextInput value={header.supplier_quotation_number} disabled={readOnly}
              onChange={(e) => setH({ supplier_quotation_number: e.target.value })} />
          </Labelled>
          <Labelled label="Quotation / PI Date">
            <TextInput type="date" value={header.supplier_quotation_date} disabled={readOnly}
              onChange={(e) => setH({ supplier_quotation_date: e.target.value })} />
          </Labelled>
          <Labelled label="Purchase Category">
            <Select value={header.purchase_category} disabled={readOnly} placeholder="Choose…"
              options={["Machinery", "Spare Parts", "Inks", "Consumables", "Other"].map((p) => ({ value: p, label: p }))}
              onChange={(e) => setH({ purchase_category: e.target.value })} />
          </Labelled>
          {editingId && (
            <Labelled label="Revision">
              <TextInput value={String(revision).padStart(2, "0")} disabled />
            </Labelled>
          )}
        </div>

        {/* The shipping and customs block, only where it applies. */}
        {isImport && (
          <div className="mt-5 overflow-hidden rounded-[10px] border border-violet/30">
            <div className="flex items-center gap-2 bg-violet/10 px-4 py-2.5">
              <Globe size={13} className="text-violet" />
              <h4 className="m-0 text-[13px] font-semibold text-violet">Import Information</h4>
              <span className="text-[11px] text-muted">
                Shipping, banking and customs — for the documents and the landed cost
              </span>
            </div>
            <div className="grid grid-cols-4 gap-4 p-4 max-sm:grid-cols-1">
              <Labelled label="Supplier Country">
                <Combobox value={header.supplier_country} allowCustom disabled={readOnly}
                  options={COUNTRIES.map((c) => ({ value: c, label: c }))}
                  placeholder="Where the supplier is"
                  onChange={(v) => setH({ supplier_country: v })} />
              </Labelled>
              <Labelled label="Country of Origin">
                <Combobox value={header.country_of_origin} allowCustom disabled={readOnly}
                  options={COUNTRIES.map((c) => ({ value: c, label: c }))}
                  placeholder="Where the goods are made"
                  onChange={(v) => setH({ country_of_origin: v })} />
              </Labelled>
              <Labelled label="Incoterm">
                <Combobox value={header.incoterm} allowCustom disabled={readOnly}
                  options={INCOTERMS.map((c) => ({ value: c, label: c }))}
                  placeholder="FOB, CIF, …"
                  onChange={(v) => setH({ incoterm: v })} />
              </Labelled>
              <Labelled label="Shipping Mode">
                <Select value={header.shipping_mode} disabled={readOnly}
                  options={SHIPPING_MODES.map((m) => ({ value: m, label: m }))}
                  placeholder="Sea, Air, …"
                  onChange={(e) => setH({ shipping_mode: e.target.value })} />
              </Labelled>

              <Labelled label="Port of Loading">
                <TextInput value={header.port_of_loading} disabled={readOnly}
                  onChange={(e) => setH({ port_of_loading: e.target.value })} />
              </Labelled>
              <Labelled label="Port of Discharge">
                <Combobox value={header.port_of_discharge} allowCustom disabled={readOnly}
                  options={PAKISTAN_PORTS.map((p) => ({ value: p, label: p }))}
                  placeholder="Karachi Port, …"
                  onChange={(v) => setH({ port_of_discharge: v })} />
              </Labelled>
              <Labelled label="Expected Shipment">
                <TextInput type="date" value={header.expected_shipment_date}
                  disabled={readOnly}
                  onChange={(e) => setH({ expected_shipment_date: e.target.value })} />
              </Labelled>
              <Labelled label="Container No">
                <TextInput value={header.container_number} disabled={readOnly}
                  onChange={(e) => setH({ container_number: e.target.value })} />
              </Labelled>

              <Labelled label="Commercial Invoice No">
                <TextInput value={header.commercial_invoice_number} disabled={readOnly}
                  onChange={(e) => setH({ commercial_invoice_number: e.target.value })} />
              </Labelled>
              <Labelled label="Commercial Invoice Date">
                <TextInput type="date" value={header.commercial_invoice_date}
                  disabled={readOnly}
                  onChange={(e) => setH({ commercial_invoice_date: e.target.value })} />
              </Labelled>
              <Labelled label="Packing List No">
                <TextInput value={header.packing_list_number} disabled={readOnly}
                  onChange={(e) => setH({ packing_list_number: e.target.value })} />
              </Labelled>
              <Labelled label="Bill of Lading No">
                <TextInput value={header.bill_of_lading_number} disabled={readOnly}
                  onChange={(e) => setH({ bill_of_lading_number: e.target.value })} />
              </Labelled>

              <Labelled label="Airway Bill No">
                <TextInput value={header.airway_bill_number} disabled={readOnly}
                  onChange={(e) => setH({ airway_bill_number: e.target.value })} />
              </Labelled>
              <Labelled label="LC No">
                <TextInput value={header.lc_number} disabled={readOnly}
                  onChange={(e) => setH({ lc_number: e.target.value })} />
              </Labelled>
              <Labelled label="LC Date">
                <TextInput type="date" value={header.lc_date} disabled={readOnly}
                  onChange={(e) => setH({ lc_date: e.target.value })} />
              </Labelled>
              <Labelled label="Bank">
                <TextInput value={header.bank_name} disabled={readOnly}
                  onChange={(e) => setH({ bank_name: e.target.value })} />
              </Labelled>

              <Labelled label="Freight Forwarder">
                <TextInput value={header.freight_forwarder} disabled={readOnly}
                  onChange={(e) => setH({ freight_forwarder: e.target.value })} />
              </Labelled>
              <Labelled label="Clearing Agent">
                <TextInput value={header.clearing_agent} disabled={readOnly}
                  onChange={(e) => setH({ clearing_agent: e.target.value })} />
              </Labelled>
              <Labelled label="Insurance Provider">
                <TextInput value={header.insurance_provider} disabled={readOnly}
                  onChange={(e) => setH({ insurance_provider: e.target.value })} />
              </Labelled>
              <Labelled label="Customs / GD Reference">
                <TextInput value={header.customs_reference} disabled={readOnly}
                  onChange={(e) => setH({ customs_reference: e.target.value })} />
              </Labelled>
            </div>
          </div>
        )}

        {/* Import Purchase Order template: what the supplier copy also carries. */}
        {isImport && (
          <ImportTerms header={header} setH={setH} readOnly={readOnly} />
        )}

        {/* ------------------------------------------------------ the lines */}
        <div className="mt-5 overflow-hidden rounded-[10px] border border-line">
          <div className="flex items-center gap-3 bg-primary px-4 py-2.5 text-on-primary">
            <h4 className="m-0 text-[13px] font-semibold">Products Ordered</h4>
            {!readOnly && (
              <button type="button" onClick={() => setLines([...lines, emptyLine()])}
                className="ml-auto flex items-center gap-1.5 rounded-md bg-white/20 px-2.5
                           py-1 text-[11.5px] font-medium hover:bg-white/30">
                <Plus size={13} strokeWidth={2.4} /> Add row
              </button>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1500px] border-collapse text-left">
              <thead>
                <tr className="border-b border-line bg-hover">
                  {["Item Code", "Description", "Uom", "HS Code", ...(isImport ? ["Origin"] : []), "Qty", "Free",
                    ...(isImport ? ["Wt/unit", "Vol/unit"] : []),
                    `Unit Price (${header.currency})`, "Disc %", "Tax %",
                    "Taxable", "Tax", "Line Net",
                    ...(editingId ? ["Shipped", "Received"] : []),
                    ""].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 text-[10.5px]
                                           font-semibold uppercase tracking-wide text-faint">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {lines.map((line, i) => (
                  <tr key={i} className="border-b border-line align-top last:border-0">
                    <td className="w-[180px] px-2 py-2">
                      <ProductPicker value={line.item_code} disabled={readOnly}
                        onPick={(p: PickedProduct) => setLine(i, {
                          item_id: p.id, item_code: p.item_code,
                          description: p.description, uom: p.uom,
                          // The item's own price is a starting point for what
                          // to pay, not the agreed price — it stays typeable.
                          unit_price: p.price != null ? String(p.price) : line.unit_price,
                        })} />
                    </td>
                    <td className="min-w-[240px] px-2 py-2">
                      <TextArea rows={2} value={line.description} disabled={readOnly}
                        onChange={(e) => setLine(i, { description: e.target.value })} />
                    </td>
                    <td className="w-[110px] px-2 py-2">
                      <UomPicker value={line.uom} uoms={uoms} disabled={readOnly}
                        onChange={(v) => setLine(i, { uom: v })} />
                    </td>
                    <td className="w-[110px] px-2 py-2">
                      <TextInput value={line.hs_code} disabled={readOnly}
                        onChange={(e) => setLine(i, { hs_code: e.target.value })} />
                    </td>
                    {isImport && (
                      <td className="w-[120px] px-2 py-2">
                        <TextInput value={line.origin_country} disabled={readOnly}
                          placeholder={header.country_of_origin || "Country"}
                          onChange={(e) => setLine(i, { origin_country: e.target.value })} />
                      </td>
                    )}
                    <NumCell value={line.quantity} disabled={readOnly}
                      onChange={(v) => setLine(i, { quantity: v })} />
                    <NumCell value={line.free_quantity} disabled={readOnly}
                      onChange={(v) => setLine(i, { free_quantity: v })} />
                    {isImport && (
                      <>
                        <NumCell value={line.unit_weight} disabled={readOnly}
                          onChange={(v) => setLine(i, { unit_weight: v })} />
                        <NumCell value={line.unit_volume} disabled={readOnly}
                          onChange={(v) => setLine(i, { unit_volume: v })} />
                      </>
                    )}
                    <NumCell value={line.unit_price} wide disabled={readOnly}
                      onChange={(v) => setLine(i, { unit_price: v })} />
                    <NumCell value={line.discount_percent} disabled={readOnly}
                      onChange={(v) => setLine(i, { discount_percent: v })} />
                    <NumCell value={line.tax_percent} disabled={readOnly}
                      onChange={(v) => setLine(i, { tax_percent: v })} />
                    <ReadCell>{money(totals.perLine[i]?.taxable ?? 0, header.currency)}</ReadCell>
                    <ReadCell>{money(totals.perLine[i]?.tax ?? 0, header.currency)}</ReadCell>
                    <ReadCell strong>
                      {money(totals.perLine[i]?.net ?? 0, header.currency)}
                    </ReadCell>
                    {editingId && (
                      <>
                        <ReadCell>{gridAmount(line.shipped_quantity)}</ReadCell>
                        <ReadCell strong>{gridAmount(line.received_quantity)}</ReadCell>
                      </>
                    )}
                    <td className="px-2 py-2">
                      {!readOnly && lines.length > 1 && (
                        <button type="button" aria-label="Remove line"
                          onClick={() => setLines(lines.filter((_, j) => j !== i))}
                          className="rounded-md p-1.5 text-muted hover:bg-rose/10
                                     hover:text-rose">
                          <Trash2 size={13} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* -------------------------------------------------------- totals */}
        <div className="ml-auto mt-5 w-full max-w-sm space-y-2 rounded-[10px] border
                        border-line bg-surface p-4">
          <TotalRow label="Excluding Tax" value={money(totals.excluding, header.currency)} />
          <TotalRow label="Tax" value={money(totals.tax, header.currency)} />
          <TotalRow label="Gross" value={money(totals.gross, header.currency)} />
          <div className="flex items-center gap-3 pt-1">
            <span className="flex-1 text-[12px] text-muted">Freight</span>
            <input type="text" inputMode="decimal" placeholder="0" disabled={readOnly}
              value={header.freight_amount === "0" ? "" : header.freight_amount} onFocus={(e) => e.target.select()}
              onChange={(e) => setH({ freight_amount: typedNumber(e.target.value) })}
              className="w-28 rounded-md border border-line bg-bg px-2 py-1 text-right
                         text-[12.5px] outline-none focus:border-primary" />
          </div>
          {isImport && ([["Packing / Handling", "packing_amount"], ["Insurance", "insurance_amount"],
                         ["Other Agreed Charges", "other_charges"]] as const).map(([label, key]) => (
            <div key={key} className="flex items-center gap-3">
              <span className="flex-1 text-[12px] text-muted">{label}</span>
              <input type="text" inputMode="decimal" placeholder="0" disabled={readOnly}
                value={header[key] === "0" ? "" : header[key]} onFocus={(e) => e.target.select()}
                onChange={(e) => setH({ [key]: typedNumber(e.target.value) } as Partial<FormHeader>)}
                className="w-28 rounded-md border border-line bg-bg px-2 py-1 text-right
                           text-[12.5px] outline-none focus:border-primary" />
            </div>
          ))}
          <div className="flex items-center gap-3">
            <span className="flex-1 text-[12px] text-muted">Discount</span>
            <input type="text" inputMode="decimal" placeholder="0" disabled={readOnly}
              value={header.document_discount === "0" ? "" : header.document_discount} onFocus={(e) => e.target.select()}
              onChange={(e) => setH({ document_discount: typedNumber(e.target.value) })}
              className="w-28 rounded-md border border-line bg-bg px-2 py-1 text-right
                         text-[12.5px] outline-none focus:border-primary" />
          </div>
          <div className="flex items-center gap-3 border-t border-line pt-2.5">
            <span className="flex-1 text-[13px] font-semibold">Net Payable</span>
            <span className="text-[15px] font-bold text-primary">
              {money(totals.net, header.currency)}
            </span>
          </div>
          {header.currency !== "PKR" && Number(header.exchange_rate) !== 1 && (
            <div className="flex items-center gap-3 text-[12px] text-muted">
              <span className="flex-1">In PKR at {header.exchange_rate}</span>
              <span className="tabular-nums">
                {(totals.net * Number(header.exchange_rate || 1))
                  .toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </span>
            </div>
          )}
          <p className="m-0 pt-1 text-[10.5px] leading-snug text-faint">
            Shown live as you type. The server recalculates on save and its figures
            are the ones stored. An order does not move stock — a posted goods
            receipt does.
          </p>
        </div>
      </Modal>
    </AppShell>
  );
}

function SupplierCard({ supplier }: { supplier: Supplier }) {
  return (
    <div className="mt-2 rounded-lg border border-line bg-bg px-3 py-2.5 text-[11.5px]
                    leading-relaxed">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="font-semibold text-muted">Supplier</span>
        {supplier.code && <span className="text-faint">{supplier.code}</span>}
        {supplier.is_international && (
          <span className="rounded bg-violet/15 px-1.5 py-0.5 text-[10px] font-semibold
                           text-violet">
            International
          </span>
        )}
      </div>
      <div>{supplier.name}</div>
      {supplier.address && <div className="text-muted">{supplier.address}</div>}
      <div className="flex flex-wrap gap-x-4 text-muted">
        {supplier.country && <span>{supplier.country}</span>}
        {supplier.currency && <span>Invoices in {supplier.currency}</span>}
        {supplier.incoterm && <span>{supplier.incoterm}</span>}
        {supplier.payment_terms && <span>{supplier.payment_terms}</span>}
      </div>
      {supplier.is_international && !supplier.currency && (
        <div className="mt-1 text-amber">
          No currency on this account — set one so orders default correctly.
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

function NumCell({ value, onChange, wide, disabled }: {
  value: string; onChange: (v: string) => void; wide?: boolean; disabled?: boolean;
}) {
  return (
    <td className={`px-2 py-2 ${wide ? "w-[130px]" : "w-[90px]"}`}>
      {/* Typed only, as on quotations and sales orders: no spinner arrows, a zero shows
          as an empty box to type into, and only digits and one decimal point are taken. */}
      <input type="text" inputMode="decimal" value={value === "0" ? "" : value} placeholder="0" disabled={disabled}
        onFocus={(e) => e.target.select()}
        onChange={(e) => onChange(typedNumber(e.target.value))}
        className="w-full rounded-md border border-line bg-bg px-2 py-1.5 text-right
                   text-[12.5px] outline-none transition-colors focus:border-primary
                   disabled:opacity-60" />
    </td>
  );
}

function ReadCell({ children, strong }: { children: React.ReactNode; strong?: boolean }) {
  return (
    <td className={`whitespace-nowrap px-2 py-3 text-right text-[12px] tabular-nums
                    ${strong ? "font-semibold" : "text-muted"}`}>
      {children}
    </td>
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


/** The Import Purchase Order template's terms: contacts, shipping, payment and quality. */
function ImportTerms({ header, setH, readOnly }: {
  header: FormHeader; setH: (p: Partial<FormHeader>) => void; readOnly: boolean;
}) {
  const text = (label: string, key: keyof FormHeader, placeholder?: string) => (
    <Labelled label={label}>
      <TextInput value={String(header[key] ?? "")} disabled={readOnly} placeholder={placeholder}
        onChange={(e) => setH({ [key]: e.target.value } as Partial<FormHeader>)} />
    </Labelled>
  );
  const pick = (label: string, key: keyof FormHeader, options: string[]) => (
    <Labelled label={label}>
      <Select value={String(header[key] ?? "")} disabled={readOnly} placeholder="Choose…"
        options={options.map((o) => ({ value: o, label: o }))}
        onChange={(e) => setH({ [key]: e.target.value } as Partial<FormHeader>)} />
    </Labelled>
  );
  const block = (title: string, children: React.ReactNode) => (
    <div>
      <h5 className="mb-2 mt-0 text-[11.5px] font-semibold uppercase tracking-wide text-sky">{title}</h5>
      <div className="grid grid-cols-4 gap-4 max-sm:grid-cols-1">{children}</div>
    </div>
  );
  return (
    <div className="mt-5 overflow-hidden rounded-[10px] border border-sky/30">
      <div className="flex items-center gap-2 bg-sky/10 px-4 py-2.5">
        <h4 className="m-0 text-[13px] font-semibold text-sky">Import PO Terms</h4>
        <span className="text-[11px] text-muted">Printed on the supplier copy, as in the Import Purchase Order template</span>
      </div>
      <div className="space-y-4 p-4">
        {block("Buyer & Supplier", <>
          {text("Buyer Designation", "buyer_designation")}
          {text("Supplier Contact Person", "supplier_contact")}
          {text("Supplier Contact Designation", "supplier_contact_designation")}
          {text("Ship-to Address", "ship_to_address", "Warehouse / port / final destination")}
          <div className="col-span-2 max-sm:col-span-1">{text("Bill-to Address", "bill_to_address", "If different from buyer address")}</div>
        </>)}
        {block("Delivery & Shipping", <>
          {pick("Incoterm Edition", "incoterm_edition", ["Incoterms® 2020", "Incoterms® 2010"])}
          {text("Named Place / Port", "named_place")}
          {text("Country of Export", "country_of_export")}
          {pick("Partial Shipment", "partial_shipment", ["Allowed", "Not allowed"])}
          {pick("Transshipment", "transshipment", ["Allowed", "Not allowed"])}
          <div className="col-span-3 max-sm:col-span-1">{text("Packing / Shipping Marks", "packing_marks", "Export-standard packing; PO number and carton marks")}</div>
        </>)}
        {block("Payment", <>
          {pick("Payment Method", "payment_method", ["Advance TT", "Part Advance & Balance", "Letter of Credit", "Documentary Collection", "Other"])}
          {text("Advance Amount", "advance_amount")}
          {text("Advance %", "advance_percent")}
          {pick("Bank Charges", "bank_charges", ["OUR", "SHA", "BEN"])}
          <div className="col-span-2 max-sm:col-span-1">{text("Balance Payment Trigger / Due Date", "balance_trigger", "Milestone and date")}</div>
          <div className="col-span-2 max-sm:col-span-1">{text("Payment Reference", "payment_reference", "PO number / PI number")}</div>
        </>)}
        {block("Quality, Warranty & Packing", <>
          {pick("Condition of Goods", "goods_condition", ["New", "Used", "Refurbished"])}
          {text("Warranty Period / Commencement", "warranty_terms")}
          {pick("Pre-shipment Inspection", "pre_shipment_inspection", ["Required", "Not required"])}
          {text("Special Packing", "special_packing")}
          <div className="col-span-2 max-sm:col-span-1">{text("Defective / Short-shipped Goods Remedy", "defect_remedy", "Replacement / credit / remedy")}</div>
          <div className="col-span-2 max-sm:col-span-1">{text("Additional Special Instructions", "special_instructions")}</div>
        </>)}
        <p className="m-0 text-[11px] text-faint">
          Beneficiary bank details (account title, bank, SWIFT, IBAN) are printed from the supplier&apos;s record under
          Customers &amp; Suppliers.
        </p>
      </div>
    </div>
  );
}