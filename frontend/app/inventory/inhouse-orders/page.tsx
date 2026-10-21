"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Plus, Search, Loader2, Pencil, Trash2, ShoppingCart, CheckCircle2, Send,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal, Field, TextInput, TextArea, Select, Combobox } from "@/components/ui/Modal";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate, gridAmount,
} from "@/components/ui/grid";
import {
  ProductPicker, AvailabilityStrip, fetchAvailability,
  type Availability, type PickedProduct,
} from "@/components/procurement/ProductPicker";
import { useProcurementList, useSuppliers } from "@/lib/useProcurement";
import { useLookups, toOptions } from "@/lib/useLookups";
import { UomPicker } from "@/components/ui/UomPicker";
import { api } from "@/lib/api";

const STATUSES = [
  "Draft", "Submitted", "Pending Approval", "Approved", "Pending Procurement",
  "Partially Ordered", "Fully Ordered", "Partially Received", "Fully Received",
  "Closed", "Cancelled", "Rejected",
];

const SOURCES = [
  "Manual", "Reorder", "Sales Demand", "Production",
  "Branch Request", "Warehouse Request", "Stock Shortage",
];

const PRIORITIES = ["Low", "Normal", "High", "Urgent"];

const FULFILMENT = [
  "Existing Stock", "Internal Transfer", "Local Purchase",
  "Import Purchase", "Production",
];

const STATUS_STYLE: Record<string, string> = {
  Draft: "bg-hover text-muted",
  Submitted: "bg-sky/15 text-sky",
  "Pending Approval": "bg-amber/15 text-amber",
  Approved: "bg-success/15 text-success",
  "Pending Procurement": "bg-violet/15 text-violet",
  "Partially Ordered": "bg-amber/15 text-amber",
  "Fully Ordered": "bg-sky/15 text-sky",
  "Partially Received": "bg-amber/15 text-amber",
  "Fully Received": "bg-success/15 text-success",
  Closed: "bg-hover text-muted",
  Cancelled: "bg-rose/15 text-rose",
  Rejected: "bg-rose/15 text-rose",
};

const PRIORITY_STYLE: Record<string, string> = {
  Low: "text-muted",
  Normal: "text-text",
  High: "text-amber",
  Urgent: "text-rose font-semibold",
};

interface IhoRow {
  id: string;
  doc_number: string;
  doc_date: string;
  warehouse: string | null;
  warehouse_id: string | null;
  department: string | null;
  requested_by: string | null;
  required_date: string | null;
  priority: string;
  source: string;
  status: string;
  purpose: string | null;
  remarks: string | null;
  total_items: number;
}

interface IhoLine {
  /** The detail endpoint returns `id`; the outstanding endpoint returns
   *  `line_id` for the same row, so both are accepted. */
  id: string;
  line_id?: string;
  line_number: number;
  item_id: string | null;
  item_code: string | null;
  description: string;
  uom: string | null;
  stock_on_hand: number;
  reserved_stock: number;
  available_stock: number;
  stock_other_warehouses: number;
  stock_on_order: number;
  goods_in_transit: number;
  reorder_level: number | null;
  requested_quantity: number;
  approved_quantity: number;
  ordered_quantity: number;
  received_quantity: number;
  outstanding_quantity: number;
  fulfilment_source: string | null;
  required_date: string | null;
  destination_warehouse_id: string | null;
  remarks: string | null;
}

interface IhoDetail extends IhoRow { lines: IhoLine[] }

const COLUMNS: {
  key: string; label: string; numeric?: boolean; sort?: string;
  render: (r: IhoRow) => React.ReactNode;
}[] = [
  { key: "doc_number", label: "IHO No", sort: "doc_number",
    render: (r) => <span className="font-medium">{r.doc_number}</span> },
  { key: "doc_date", label: "Date", sort: "doc_date",
    render: (r) => <span className="whitespace-nowrap">{gridDate(r.doc_date)}</span> },
  { key: "warehouse", label: "Warehouse", render: (r) => r.warehouse ?? "—" },
  { key: "requested_by", label: "Requested By", render: (r) => r.requested_by ?? "—" },
  { key: "department", label: "Department", render: (r) => r.department ?? "—" },
  { key: "priority", label: "Priority", sort: "priority",
    render: (r) => <span className={PRIORITY_STYLE[r.priority] ?? ""}>{r.priority}</span> },
  { key: "source", label: "Source", render: (r) => r.source },
  { key: "required_date", label: "Required", sort: "required_date",
    render: (r) => (r.required_date
      ? <span className="whitespace-nowrap">{gridDate(r.required_date)}</span> : "—") },
  { key: "status", label: "Status", sort: "status",
    render: (r) => (
      <span className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                        ${STATUS_STYLE[r.status] ?? "bg-hover text-muted"}`}>
        {r.status}
      </span>
    ) },
  { key: "total_items", label: "Items", numeric: true, render: (r) => r.total_items },
  { key: "purpose", label: "Purpose", render: (r) => r.purpose ?? "—" },
  { key: "remarks", label: "Remarks", render: (r) => r.remarks ?? "—" },
];

const DEFAULT_HIDDEN = ["department", "remarks"];

/** A blank line in the form. */
const emptyLine = () => ({
  id: null as string | null,
  item_id: null as string | null,
  item_code: null as string | null,
  description: "",
  uom: null as string | null,
  requested_quantity: "",
  approved_quantity: "",
  fulfilment_source: "",
  remarks: "",
  picture: null as Availability | null,
  /** Only set on a saved requirement: how far this line has actually got. */
  progress: null as { ordered: number; received: number; outstanding: number } | null,
});

type FormLine = ReturnType<typeof emptyLine>;

const emptyHeader = () => ({
  doc_date: new Date().toISOString().slice(0, 10),
  warehouse_id: "",
  department: "",
  requested_by: "",
  required_date: "",
  priority: "Normal",
  purpose: "",
  source: "Manual",
  remarks: "",
});

export default function InHouseOrdersPage() {
  const list = useProcurementList<IhoRow>("/procurement/in-house-orders");
  const { locations, uoms } = useLookups();
  const suppliers = useSuppliers();
  // Departments as set up in HRMS; the order keeps the department's name.
  const [departments, setDepartments] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    api.get<{ items: { id: string; name: string }[] }>("/procurement/departments")
      .then((d) => setDepartments(d.items)).catch(() => setDepartments([]));
  }, []);

  const [isOpen, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [header, setHeader] = useState(emptyHeader());
  const [lines, setLines] = useState<FormLine[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState(false);

  /** The requirement a purchase order is being raised from. */
  const [converting, setConverting] = useState<IhoDetail | null>(null);

  const columnState = useHiddenColumns("in-house-orders.columns", DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));

  const exportQuery = new URLSearchParams([
    ...(list.search ? [["search", list.search]] : []),
    ...list.statuses.map((s) => ["status", s] as [string, string]),
  ]).toString();

  const setH = (key: keyof ReturnType<typeof emptyHeader>, value: string) =>
    setHeader((h) => ({ ...h, [key]: value }));

  const setLine = (index: number, patch: Partial<FormLine>) =>
    setLines((ls) => ls.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  const openNew = () => {
    setEditingId(null);
    setReadOnly(false);
    setHeader(emptyHeader());
    setLines([emptyLine()]);
    setFormError(null);
    setOpen(true);
  };

  const openEdit = async (id: string) => {
    setFormError(null);
    try {
      const doc = await api.get<IhoDetail>(`/procurement/in-house-orders/${id}`);
      setEditingId(id);
      // Once orders have been raised, the lines are history — the form opens
      // to be read, not rewritten.
      setReadOnly(!["Draft", "Submitted", "Pending Approval", "Rejected"]
        .includes(doc.status));
      setHeader({
        doc_date: doc.doc_date,
        warehouse_id: doc.warehouse_id ?? "",
        department: doc.department ?? "",
        requested_by: doc.requested_by ?? "",
        required_date: doc.required_date ?? "",
        priority: doc.priority,
        purpose: doc.purpose ?? "",
        source: doc.source,
        remarks: doc.remarks ?? "",
      });
      setLines(doc.lines.map((l) => ({
        id: l.id,
        item_id: l.item_id,
        item_code: l.item_code,
        description: l.description,
        uom: l.uom,
        requested_quantity: String(l.requested_quantity),
        approved_quantity: String(l.approved_quantity),
        fulfilment_source: l.fulfilment_source ?? "",
        remarks: l.remarks ?? "",
        progress: {
          ordered: l.ordered_quantity,
          received: l.received_quantity,
          outstanding: l.outstanding_quantity,
        },
        // The saved snapshot, shown as it was recorded.
        picture: {
          item_id: l.item_id ?? "", item_code: l.item_code,
          description: l.description, uom: l.uom,
          stock_on_hand: l.stock_on_hand, reserved_stock: l.reserved_stock,
          available_stock: l.available_stock,
          stock_other_warehouses: l.stock_other_warehouses,
          stock_on_order: l.stock_on_order, goods_in_transit: l.goods_in_transit,
          expected_stock: l.available_stock + l.stock_on_order + l.goods_in_transit,
          reorder_level: l.reorder_level, min_level: null, max_level: null,
          required_quantity: l.requested_quantity,
          shortfall: Math.max(0, l.requested_quantity
            - (l.available_stock + l.stock_on_order + l.goods_in_transit)),
          needs_purchase: false, transfer_options: [],
        },
      })));
      setOpen(true);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not open it.");
      setOpen(true);
    }
  };

  /** Picking a product fetches its live stock picture for this warehouse. */
  const pickProduct = async (index: number, product: PickedProduct) => {
    setLine(index, {
      item_id: product.id,
      item_code: product.item_code,
      description: product.description,
      uom: product.uom,
    });
    const picture = await fetchAvailability(
      product.id, header.warehouse_id || null,
      lines[index]?.requested_quantity || 0);
    setLine(index, { picture });
  };

  /** Re-asks for the shortfall as the quantity changes. */
  const refreshPicture = async (index: number, quantity: string) => {
    const line = lines[index];
    if (!line?.item_id) return;
    const picture = await fetchAvailability(
      line.item_id, header.warehouse_id || null, quantity || 0);
    setLine(index, { picture });
  };

  const save = async () => {
    if (lines.length === 0) { setFormError("Add at least one line."); return; }
    if (lines.some((l) => !l.description.trim() && !l.item_id)) {
      setFormError("Every line needs a product or a description."); return;
    }
    if (lines.some((l) => Number(l.requested_quantity) <= 0)) {
      setFormError("Every line needs a quantity greater than zero."); return;
    }

    setSaving(true);
    setFormError(null);
    try {
      const body = {
        doc_date: header.doc_date,
        warehouse_id: header.warehouse_id || null,
        department: header.department || null,
        requested_by: header.requested_by || null,
        required_date: header.required_date || null,
        priority: header.priority,
        purpose: header.purpose || null,
        source: header.source,
        remarks: header.remarks || null,
        lines: lines.map((l) => ({
          id: l.id,
          item_id: l.item_id,
          item_code: l.item_code,
          description: l.description || null,
          uom: l.uom,
          requested_quantity: l.requested_quantity,
          approved_quantity: l.approved_quantity || null,
          fulfilment_source: l.fulfilment_source || null,
          remarks: l.remarks || null,
        })),
      };
      if (editingId) await api.put(`/procurement/in-house-orders/${editingId}`, body);
      else await api.post("/procurement/in-house-orders", body);
      setOpen(false);
      await list.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save it.");
    } finally {
      setSaving(false);
    }
  };

  const move = async (id: string, status: string) => {
    try {
      await api.post(`/procurement/in-house-orders/${id}/status`, { status });
      await list.reload();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not change the status.");
    }
  };

  const startConvert = async (id: string) => {
    try {
      const doc = await api.get<IhoDetail>(`/procurement/in-house-orders/${id}`);
      const outstanding = await api.get<{ lines: IhoLine[] }>(
        `/procurement/in-house-orders/${id}/outstanding`);
      setConverting({ ...doc, lines: outstanding.lines });
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not open that requirement.");
    }
  };

  return (
    <AppShell title="In-House Orders">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">In-House Orders</h1>
        <p className="m-0 text-[12px] text-muted">
          What the business needs — approved here, then bought or transferred.
        </p>
        <button onClick={openNew}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br
                     from-primary to-primary-dark px-3.5 py-2 text-[12.8px]
                     font-medium text-on-primary">
          <Plus size={14} strokeWidth={2.4} /> Create Requirement
        </button>
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.total} onReset={list.reset} resettable={list.dirty} />

        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input value={list.search} onChange={(e) => list.setSearch(e.target.value)}
              placeholder="Search number, item, purpose…"
              className="w-56 border-none bg-transparent text-[12.8px] outline-none
                         placeholder:text-faint" />
          </div>
          <div className="ml-auto order-3 flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <DownloadMenu dataset="in-house-orders" query={exportQuery} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Draft", "Pending Procurement", "Partially Ordered", "Fully Received"]
              .map((s) => (
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
                 style={{ minWidth: `${220 + visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Edit</GridTh>
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
                <tr><td colSpan={visible.length + 1} className="px-5 py-12 text-center">
                  <Loader2 size={18} className="mx-auto animate-spin text-primary" />
                </td></tr>
              )}
              {!list.loading && list.rows.length === 0 && (
                <tr><td colSpan={visible.length + 1}
                        className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No requirements match these filters. Create one when a warehouse,
                  a branch or production needs stock.
                </td></tr>
              )}
              {!list.loading && list.rows.map((row, index) => (
                <tr key={row.id} className={`align-top ${gridRowClass(index)}`}>
                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1">
                      <button onClick={() => openEdit(row.id)} aria-label="Open"
                        title="Open"
                        className="rounded-md p-1.5 text-muted hover:bg-primary/10
                                   hover:text-primary">
                        <Pencil size={14} />
                      </button>
                      {row.status === "Draft" && (
                        <button onClick={() => move(row.id, "Submitted")}
                          title="Submit for approval" aria-label="Submit"
                          className="rounded-md p-1.5 text-muted hover:bg-sky/10 hover:text-sky">
                          <Send size={14} />
                        </button>
                      )}
                      {["Submitted", "Pending Approval"].includes(row.status) && (
                        <button onClick={() => move(row.id, "Approved")}
                          title="Approve" aria-label="Approve"
                          className="rounded-md p-1.5 text-muted hover:bg-primary/10
                                     hover:text-primary">
                          <CheckCircle2 size={14} />
                        </button>
                      )}
                      {["Pending Procurement", "Partially Ordered", "Fully Ordered",
                        "Partially Received"].includes(row.status) && (
                        <button onClick={() => startConvert(row.id)}
                          title="Create a purchase order for what is outstanding"
                          className="whitespace-nowrap rounded-md bg-primary/10 px-2 py-1
                                     text-[10.5px] font-medium text-primary
                                     hover:bg-primary/20">
                          <ShoppingCart size={11} className="mr-1 inline" />
                          Order
                        </button>
                      )}
                    </div>
                  </td>
                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "purpose" || c.key === "remarks"
                            ? "max-w-[220px] truncate text-muted" : "")}
                        title={c.key === "purpose" ? row.purpose ?? "" : undefined}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{list.total.toLocaleString()} requirements</span>
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
        title={editingId ? (readOnly ? "In-House Order" : "Edit In-House Order")
                         : "Create In-House Order"}
        open={isOpen} saving={saving} error={formError} width="xl"
        onClose={() => setOpen(false)}
        onSave={readOnly ? undefined : save}
        saveLabel={editingId ? "Save" : "Create"}
      >
        {readOnly && (
          <div className="mb-4 rounded-lg border border-line bg-hover px-3.5 py-2.5
                          text-[12.5px] text-muted">
            Purchase orders have been raised against this requirement, so its lines
            can no longer be changed. The quantities below track what has been
            ordered and received.
          </div>
        )}

        <div className="grid grid-cols-4 gap-4 max-sm:grid-cols-1">
          <Labelled label="Date" required>
            <TextInput type="date" value={header.doc_date} disabled={readOnly}
              onChange={(e) => setH("doc_date", e.target.value)} />
          </Labelled>
          <Labelled label="Requesting Warehouse">
            <Combobox value={header.warehouse_id} options={toOptions(locations)}
              disabled={readOnly}
              placeholder="Type a warehouse or pick from Item Locations…"
              emptyMessage="No warehouse matches that name."
              onChange={(v) => setH("warehouse_id", v)} />
          </Labelled>
          <Labelled label="Requested By">
            <TextInput value={header.requested_by} disabled={readOnly}
              onChange={(e) => setH("requested_by", e.target.value)} />
          </Labelled>
          <Labelled label="Department">
            <Combobox value={header.department} disabled={readOnly}
              options={[...departments.map((d) => ({ value: d.name, label: d.name })),
                // An older order's department that is not in HRMS still shows as it was saved.
                ...(header.department && !departments.some((d) => d.name === header.department)
                  ? [{ value: header.department, label: header.department }] : [])]}
              placeholder={departments.length ? "Pick the department…" : "No departments in HRMS yet"}
              emptyMessage="No department matches. Add it under HRMS → Departments."
              onChange={(v) => setH("department", v)} />
          </Labelled>

          <Labelled label="Required Date">
            <TextInput type="date" value={header.required_date} disabled={readOnly}
              onChange={(e) => setH("required_date", e.target.value)} />
          </Labelled>
          <Labelled label="Priority">
            <Select value={header.priority} disabled={readOnly}
              options={PRIORITIES.map((p) => ({ value: p, label: p }))}
              placeholder="Normal"
              onChange={(e) => setH("priority", e.target.value)} />
          </Labelled>
          <Labelled label="Source of the requirement">
            <Select value={header.source} disabled={readOnly}
              options={SOURCES.map((s) => ({ value: s, label: s }))}
              placeholder="Manual"
              onChange={(e) => setH("source", e.target.value)} />
          </Labelled>
          <Labelled label="Purpose">
            <TextInput value={header.purpose} disabled={readOnly}
              placeholder="Why this stock is needed"
              onChange={(e) => setH("purpose", e.target.value)} />
          </Labelled>

          <div className="col-span-4 max-sm:col-span-1">
            <Labelled label="Remarks">
              <TextArea rows={2} value={header.remarks} disabled={readOnly}
                onChange={(e) => setH("remarks", e.target.value)} />
            </Labelled>
          </div>
        </div>

        {/* ------------------------------------------------------ the lines */}
        <div className="mt-5 overflow-hidden rounded-[10px] border border-line">
          <div className="flex items-center gap-3 bg-primary px-4 py-2.5 text-on-primary">
            <h4 className="m-0 text-[13px] font-semibold">Items Required</h4>
            {!readOnly && (
              <button type="button" onClick={() => setLines([...lines, emptyLine()])}
                className="ml-auto flex items-center gap-1.5 rounded-md bg-white/20 px-2.5
                           py-1 text-[11.5px] font-medium hover:bg-white/30">
                <Plus size={13} strokeWidth={2.4} /> Add row
              </button>
            )}
          </div>

          <div className="divide-y divide-line">
            {lines.map((line, i) => (
              <div key={i} className="p-3.5">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="w-[230px]">
                    <FieldLabel>Item</FieldLabel>
                    <ProductPicker value={line.item_code} disabled={readOnly}
                      onPick={(p) => void pickProduct(i, p)} />
                  </div>
                  <div className="min-w-[240px] flex-1">
                    <FieldLabel>Description</FieldLabel>
                    <TextInput value={line.description} disabled={readOnly}
                      onChange={(e) => setLine(i, { description: e.target.value })} />
                  </div>
                  <div className="w-[120px]">
                    <FieldLabel>Uom</FieldLabel>
                    <UomPicker value={line.uom} uoms={uoms} disabled={readOnly}
                      onChange={(v) => setLine(i, { uom: v })} />
                  </div>
                  <div className="w-[110px]">
                    <FieldLabel>Requested</FieldLabel>
                    <TextInput type="number" step="0.01" min="0" disabled={readOnly}
                      value={line.requested_quantity}
                      onChange={(e) => setLine(i, { requested_quantity: e.target.value })}
                      onBlur={(e) => void refreshPicture(i, e.target.value)} />
                  </div>
                  <div className="w-[110px]">
                    <FieldLabel>Approved</FieldLabel>
                    <TextInput type="number" step="0.01" min="0" disabled={readOnly}
                      value={line.approved_quantity}
                      placeholder={line.requested_quantity || "—"}
                      onChange={(e) => setLine(i, { approved_quantity: e.target.value })} />
                  </div>
                  <div className="w-[160px]">
                    <FieldLabel>Fulfil from</FieldLabel>
                    <Select value={line.fulfilment_source} disabled={readOnly}
                      options={FULFILMENT.map((f) => ({ value: f, label: f }))}
                      placeholder="Decide later"
                      onChange={(e) => setLine(i, { fulfilment_source: e.target.value })} />
                  </div>
                  {!readOnly && lines.length > 1 && (
                    <button type="button" aria-label="Remove line"
                      onClick={() => setLines(lines.filter((_, j) => j !== i))}
                      className="rounded-md p-2 text-muted hover:bg-rose/10 hover:text-rose">
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>

                {line.picture && (
                  <div className="mt-2.5">
                    <AvailabilityStrip picture={line.picture} />
                  </div>
                )}

                {readOnly && line.progress && (
                  // On a requirement that has been acted on, what matters is
                  // how far it has got, not what can still be typed.
                  <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-muted">
                    <span>Ordered{" "}
                      <b className="tabular-nums text-text">
                        {gridAmount(line.progress.ordered)}
                      </b></span>
                    <span>Received{" "}
                      <b className="tabular-nums text-primary">
                        {gridAmount(line.progress.received)}
                      </b></span>
                    <span>Outstanding{" "}
                      <b className="tabular-nums text-rose">
                        {gridAmount(line.progress.outstanding)}
                      </b></span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <p className="mt-3 text-[11px] text-faint">
          The stock figures are recorded as they stand now, so the reason this
          quantity was asked for stays on the record. Approving the requirement
          releases it to procurement; it does not buy anything or move stock.
        </p>
      </Modal>

      {converting && (
        <ConvertToPurchaseOrder
          requirement={converting}
          suppliers={suppliers}
          locations={locations}
          onClose={() => setConverting(null)}
          onDone={async () => { setConverting(null); await list.reload(); }}
        />
      )}
    </AppShell>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1 block text-[11px] font-medium text-muted">{children}</span>
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

/**
 * Raise a purchase order for what a requirement still needs.
 *
 * Only the outstanding quantities are offered, and only lines that are
 * actually to be bought — a line marked for transfer or production is not a
 * purchase. One requirement can produce several orders, which is why the
 * quantities are editable here rather than taken wholesale.
 */
function ConvertToPurchaseOrder({
  requirement, suppliers, locations, onClose, onDone,
}: {
  requirement: IhoDetail;
  suppliers: ReturnType<typeof useSuppliers>;
  locations: { id: string; label: string }[];
  onClose: () => void;
  onDone: () => void;
}) {
  const buyable = requirement.lines.filter((l) => l.outstanding_quantity > 0);

  const [purchaseType, setPurchaseType] = useState<"Local" | "Import">("Local");
  const [supplierId, setSupplierId] = useState("");
  const [docDate, setDocDate] = useState(new Date().toISOString().slice(0, 10));
  const [currency, setCurrency] = useState("PKR");
  const [rate, setRate] = useState("1");
  const [warehouseId, setWarehouseId] = useState(requirement.warehouse_id ?? "");
  const [chosen, setChosen] = useState<Record<string, { quantity: string; price: string }>>(
    Object.fromEntries(buyable.map((l) => [
      l.line_id ?? l.id,
      { quantity: String(l.outstanding_quantity), price: "" },
    ])),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const supplier = suppliers.find((s) => s.id === supplierId);

  // Choosing the supplier decides how the order is written: an international
  // account means an import, in that supplier's currency.
  useEffect(() => {
    if (!supplier) return;
    if (supplier.is_international) {
      setPurchaseType("Import");
      setCurrency(supplier.currency || "USD");
    } else {
      setPurchaseType("Local");
      setCurrency(supplier.currency || "PKR");
      setRate("1");
    }
  }, [supplier]);

  const total = useMemo(
    () => Object.values(chosen).reduce(
      (sum, c) => sum + Number(c.quantity || 0) * Number(c.price || 0), 0),
    [chosen],
  );

  const save = async () => {
    if (!supplierId) { setError("Choose a supplier."); return; }
    const lines = Object.entries(chosen)
      .filter(([, c]) => Number(c.quantity) > 0)
      .map(([lineId, c]) => ({
        line_id: lineId,
        quantity: c.quantity,
        unit_price: c.price || "0",
      }));
    if (lines.length === 0) { setError("Choose at least one line to order."); return; }

    setSaving(true);
    setError(null);
    try {
      const order = await api.post<{ doc_number: string }>(
        `/procurement/in-house-orders/${requirement.id}/purchase-orders`,
        {
          purchase_type: purchaseType,
          supplier_id: supplierId,
          doc_date: docDate,
          currency,
          exchange_rate: rate || "1",
          warehouse_id: warehouseId || null,
          lines,
        });
      setCreated(order.doc_number);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not raise the order.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`Create Purchase Order from ${requirement.doc_number}`}
      open width="xl" saving={saving} error={error}
      onClose={created ? onDone : onClose}
      onSave={created ? undefined : save}
      saveLabel="Create Purchase Order"
    >
      {created ? (
        <div className="rounded-lg bg-primary/10 px-4 py-3.5 text-[12.8px] text-primary">
          Purchase order <b>{created}</b> raised. It is a draft — approve it on the
          Purchase Orders screen before goods can be received against it.
        </div>
      ) : (
        <>
          {buyable.length === 0 && (
            <p className="rounded-lg bg-hover px-4 py-3 text-[12.8px] text-muted">
              Nothing is outstanding on this requirement. Either everything has been
              ordered already, or the lines are being met by transfer or production.
            </p>
          )}

          <div className="grid grid-cols-4 gap-4 max-sm:grid-cols-1">
            <div className="col-span-2 max-sm:col-span-1">
              <Labelled label="Supplier" required>
                <Combobox
                  value={supplierId}
                  options={suppliers.map((s) => ({
                    value: s.id,
                    label: `${s.name}${s.code ? ` — ${s.code}` : ""}`
                      + (s.is_international ? `  (import${s.country ? `, ${s.country}` : ""})` : ""),
                    short: s.name,
                  }))}
                  placeholder="Type a supplier name or code…"
                  emptyMessage="No supplier matches. Tick Supplier on the account first."
                  onChange={setSupplierId}
                />
              </Labelled>
            </div>
            <Labelled label="Purchase Type">
              <Select value={purchaseType}
                options={[{ value: "Local", label: "Local" },
                          { value: "Import", label: "Import" }]}
                onChange={(e) => setPurchaseType(e.target.value as "Local" | "Import")} />
            </Labelled>
            <Labelled label="Date">
              <TextInput type="date" value={docDate}
                onChange={(e) => setDocDate(e.target.value)} />
            </Labelled>

            <Labelled label="Currency">
              <TextInput value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
            </Labelled>
            <Labelled label={`Exchange Rate (1 ${currency} = ? PKR)`}>
              <TextInput type="number" step="0.000001" value={rate}
                disabled={currency === "PKR"}
                onChange={(e) => setRate(e.target.value)} />
            </Labelled>
            <div className="col-span-2 max-sm:col-span-1">
              <Labelled label="Deliver to Warehouse">
                <Combobox value={warehouseId}
                  options={locations.map((l) => ({ value: l.id, label: l.label }))}
                  placeholder="Pick a warehouse…"
                  onChange={setWarehouseId} />
              </Labelled>
            </div>
          </div>

          {purchaseType === "Import" && currency === "PKR" && (
            <p className="mt-3 rounded-lg bg-amber/10 px-3.5 py-2.5 text-[12px] text-amber">
              An import order in PKR will be refused. Set the supplier&apos;s currency and
              the rate, or make this a local purchase.
            </p>
          )}

          {buyable.length > 0 && (
            <div className="mt-5 overflow-hidden rounded-[10px] border border-line">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-line">
                    {["Item", "Uom", "Approved", "Ordered", "Outstanding",
                      "Order Now", `Unit Price (${currency})`, "Line Total"].map((h, i) => (
                      <GridTh key={h} numeric={i >= 2}>{h}</GridTh>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {buyable.map((line, index) => {
                    const key = line.line_id ?? line.id;
                    const entry = chosen[key] ?? { quantity: "", price: "" };
                    return (
                      <tr key={key} className={gridRowClass(index)}>
                        <td className={gridCellClass(false, "max-w-[280px]")}>
                          <div className="text-[12.5px]">{line.description}</div>
                          <div className="text-[11px] text-faint">{line.item_code}</div>
                        </td>
                        <td className={gridCellClass()}>{line.uom ?? "—"}</td>
                        <td className={gridCellClass(true)}>
                          {gridAmount(line.approved_quantity)}
                        </td>
                        <td className={gridCellClass(true)}>
                          {gridAmount(line.ordered_quantity)}
                        </td>
                        <td className={gridCellClass(true)}>
                          <b>{gridAmount(line.outstanding_quantity)}</b>
                        </td>
                        <td className={gridCellClass(true, "w-[120px]")}>
                          <TextInput type="number" step="0.01" min="0"
                            value={entry.quantity}
                            onChange={(e) => setChosen((c) => ({
                              ...c, [key]: { ...entry, quantity: e.target.value } }))} />
                        </td>
                        <td className={gridCellClass(true, "w-[130px]")}>
                          <TextInput type="number" step="0.0001" min="0"
                            value={entry.price}
                            onChange={(e) => setChosen((c) => ({
                              ...c, [key]: { ...entry, price: e.target.value } }))} />
                        </td>
                        <td className={gridCellClass(true)}>
                          {(Number(entry.quantity || 0) * Number(entry.price || 0))
                            .toLocaleString("en-US", { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {total > 0 && (
            <div className="mt-3 flex items-center gap-3 text-[13px]">
              <span className="ml-auto text-muted">Order value</span>
              <b className="tabular-nums">
                {currency} {total.toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </b>
              {currency !== "PKR" && Number(rate) > 1 && (
                <span className="text-[12px] text-muted">
                  ≈ PKR {(total * Number(rate)).toLocaleString("en-US",
                    { minimumFractionDigits: 2 })}
                </span>
              )}
            </div>
          )}

          <p className="mt-3 text-[11px] text-faint">
            Ordering less than the outstanding quantity leaves the rest on the
            requirement, so it can be met by a second order — a local one for what
            is available here, an import for what is not.
          </p>
        </>
      )}
    </Modal>
  );
}
