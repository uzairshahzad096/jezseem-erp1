"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Printer, Pencil, Plus, Search, Loader2, CheckCircle2, X,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal, Field, TextInput, TextArea, Select, Combobox } from "@/components/ui/Modal";
import { ColumnPicker, DownloadMenu, useHiddenColumns } from "@/components/ui/TableTools";
import { GridActionChips, GridActionView, GridActions, useGridActions } from "@/components/ui/GridActions";
import { Fragment } from "react";
import {
  GridHeader, GridTh, gridRowClass, gridCellClass, gridDate,
} from "@/components/ui/grid";
import {
  useGatePasses, openGatePassPdf, emptyLine,
  type GatePassSummary, type GatePassDetail, type GatePassLine,
} from "@/lib/useGatePasses";
import { api } from "@/lib/api";
import { UomPicker } from "@/components/ui/UomPicker";
import { useLookups } from "@/lib/useLookups";

const STATUSES = ["Draft", "Approved", "Closed", "Cancelled"];

const STATUS_STYLE: Record<string, string> = {
  Draft: "bg-hover text-muted",
  Approved: "bg-success/15 text-success",
  Closed: "bg-violet/15 text-violet",
  Cancelled: "bg-rose/15 text-rose",
};

/** The issue types the old system uses. Free text is still accepted.
 *  Returnable and Repair are expected back and are settled by inward passes;
 *  the rest leave for good. */
const ISSUE_TYPES = ["Returnable", "Repair", "Sale", "Foc", "Sample", "Replacement"];
const RETURNABLE = ["returnable", "repair"];
const isReturnable = (type: string | null | undefined) => RETURNABLE.includes((type ?? "").trim().toLowerCase());

const RETURN_STYLE: Record<string, string> = {
  "Pending return": "bg-amber/15 text-amber",
  "Partly returned": "bg-sky/15 text-sky",
  "Fully returned": "bg-success/15 text-success",
};

const money = (n: number, currency = "PKR") =>
  `${currency} ${n.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

/** Every column from the OGP/IGP mapping, in its order. */
function buildColumns(passType: "outward" | "inward") {
  const columns: {
    key: string; label: string; numeric?: boolean; sort?: string;
    render: (g: GatePassSummary) => React.ReactNode;
  }[] = [
    { key: "doc_number", label: passType === "outward" ? "OGP No" : "IGP No", sort: "doc_number",
      render: (g) => <span className="font-medium">{g.doc_number}</span> },
    { key: "doc_date", label: "Date", sort: "doc_date",
      render: (g) => <span className="whitespace-nowrap">{gridDate(g.doc_date)}</span> },
    { key: "party_name", label: "Party", render: (g) => g.party_name ?? g.issue_to ?? "—" },
    { key: "vehicle_number", label: "Vehicle No", render: (g) => g.vehicle_number ?? "—" },
    { key: "driver", label: "Driver", render: (g) => g.driver ?? "—" },
    { key: "issue_type", label: "Type", render: (g) => g.issue_type ?? "—" },
    { key: "remarks", label: "Remarks", render: (g) => g.remarks ?? "—" },
    { key: "status", label: "Status", sort: "status",
      render: (g) => (
        <span className={`rounded-md px-2.5 py-1 text-[10.5px] font-semibold
                          ${STATUS_STYLE[g.status] ?? "bg-hover text-muted"}`}>
          {g.status}
        </span>
      ) },
    { key: "location", label: "Location", render: (g) => g.location ?? "—" },
    { key: "dc_number", label: "DC No", render: (g) => g.dc_number ?? "—" },
    { key: "challan_number", label: "Challan No", render: (g) => g.challan_number ?? "—" },
    { key: "ntn", label: "NTN", render: (g) => g.ntn ?? "—" },
    { key: "gst_number", label: "GST No", render: (g) => g.gst_number ?? "—" },
    { key: "container_number", label: "Container No", render: (g) => g.container_number ?? "—" },
    { key: "total_items", label: "Total Items", numeric: true, sort: "total_items",
      render: (g) => g.total_items },
    { key: "item_description", label: "Total Items Desc",
      render: (g) => (g.item_description
        ? <span className="line-clamp-2">{g.item_description}</span>
        : <span className="text-faint">—</span>) },
    { key: "total_quantity", label: "Total Qty", numeric: true,
      render: (g) => g.total_quantity.toLocaleString() },
    { key: "currency", label: "Currency", render: (g) => g.currency },
    { key: "excluding_tax_value", label: "Excluding Tax Value", numeric: true,
      render: (g) => money(g.excluding_tax_value, g.currency) },
    { key: "sales_tax_value", label: "Sale Tax Value", numeric: true,
      render: (g) => money(g.sales_tax_value, g.currency) },
    { key: "gross_amount", label: "Gross Amount", numeric: true,
      render: (g) => money(g.gross_amount, g.currency) },
    { key: "discount_amount", label: "Discount", numeric: true,
      render: (g) => money(g.discount_amount, g.currency) },
    { key: "freight_amount", label: "Freight", numeric: true,
      render: (g) => money(g.freight_amount, g.currency) },
    { key: "total_amount", label: "Net Receivable", numeric: true,
      render: (g) => <span className="font-semibold">{money(g.total_amount, g.currency)}</span> },
    { key: "payment_status", label: "Payment Status", render: (g) => g.payment_status ?? "—" },
    { key: "payment_reference", label: "Payment Reference",
      render: (g) => g.payment_reference ?? "—" },
    { key: "po_number", label: "PO No", render: (g) => g.po_number ?? "—" },
    { key: "reference_number", label: "Reference No", render: (g) => g.reference_number ?? "—" },
    { key: "is_approved", label: "Is Approved",
      render: (g) => (g.is_approved
        ? <CheckCircle2 size={14} className="text-primary" />
        : <span className="text-faint">—</span>) },
  ];

  if (passType === "outward") {
    const at = columns.findIndex((c) => c.key === "status") + 1;
    columns.splice(at, 0,
      { key: "return_status", label: "Return Status",
        render: (g) => (g.return_status
          ? <span className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[10.5px] font-semibold ${RETURN_STYLE[g.return_status] ?? "bg-hover text-muted"}`}>
              {g.return_status}{g.return_status === "Partly returned" ? ` · ${g.pending_quantity.toLocaleString()} out` : ""}
            </span>
          : <span className="text-faint">—</span>) },
      { key: "expected_return_date", label: "Expected Return",
        render: (g) => {
          if (!g.expected_return_date) return <span className="text-faint">—</span>;
          const late = g.pending_quantity > 0 && g.status === "Approved"
            && g.expected_return_date < new Date().toISOString().slice(0, 10);
          return <span className={`whitespace-nowrap ${late ? "font-semibold text-rose" : ""}`}
            title={late ? "Overdue: not all of it has come back" : undefined}>{gridDate(g.expected_return_date)}</span>;
        } });
  }

  if (passType === "inward") {
    columns.splice(3, 0, {
      key: "reference_gate_pass_number", label: "OGP No",
      render: (g) => g.reference_gate_pass_number ?? <span className="text-faint">—</span>,
    });
  }
  return columns;
}

// The grid is wide; the money and reference columns start hidden and are one
// click away in the Columns menu.
const DEFAULT_HIDDEN = [
  "challan_number", "ntn", "gst_number", "container_number", "currency",
  "excluding_tax_value", "sales_tax_value", "gross_amount", "discount_amount",
  "freight_amount", "total_amount", "payment_status", "payment_reference",
  "po_number", "reference_number",
];

export function GatePassScreen({ passType }: { passType: "outward" | "inward" }) {
  const isOutward = passType === "outward";
  const title = isOutward ? "Outward Gate Pass" : "Inward Gate Pass";

  const list = useGatePasses(passType, 25);
  const COLUMNS = useMemo(() => buildColumns(passType), [passType]);
  const columnState = useHiddenColumns(`${passType}-gate-passes.columns`, DEFAULT_HIDDEN);
  const visible = COLUMNS.filter((c) => !columnState.hidden.has(c.key));
  // The Actions menu: filters, highlights, control breaks and summaries over the loaded rows.
  const actions = useGridActions<(typeof list.rows)[number]>(`${passType}-gate-passes`, COLUMNS);
  const shown = actions.apply(list.rows);

  const [parties, setParties] = useState<{ id: string; name: string; code?: string }[]>([]);
  const [locations, setLocations] = useState<{ id: string; location: string }[]>([]);
  const [openPasses, setOpenPasses] = useState<GatePassSummary[]>([]);

  const [isOpen, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [header, setHeader] = useState(emptyHeader());
  const [lines, setLines] = useState<GatePassLine[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const all: { id: string; name: string; code?: string }[] = [];
      try {
        for (let page = 1; ; page += 1) {
          const d = await api.get<{ items: typeof all; total: number }>(
            `/partners?page=${page}&page_size=500`);
          all.push(...d.items);
          if (d.items.length === 0 || all.length >= d.total) break;
        }
        setParties(all);
      } catch { setParties([]); }

      try {
        setLocations((await api.get<{ items: typeof locations }>(
          "/gate-passes/locations")).items);
      } catch { setLocations([]); }

    })();
  }, [isOutward]);

  /** Outward passes with goods still out, for the chosen party (all parties when none is chosen). */
  const loadOpen = async (partyId: string) => {
    if (isOutward) return;
    try {
      setOpenPasses((await api.get<{ items: GatePassSummary[] }>(
        `/gate-passes/outward/open${partyId ? `?party_id=${partyId}` : ""}`)).items);
    } catch { setOpenPasses([]); }
  };

  /** An inward return starts from its outward pass: party, references and
   *  every item still out, at the quantity still out. */
  const pickOutward = async (outwardId: string) => {
    if (!outwardId) { setH("reference_gate_pass_id", ""); return; }
    try {
      const o = await api.get<GatePassDetail>(`/gate-passes/outward/${outwardId}/returnable`);
      setHeader((h) => ({
        ...h,
        reference_gate_pass_id: o.id,
        party_id: o.party_id ?? h.party_id,
        location: o.location ?? h.location,
        issue_type: o.issue_type || "Returnable",
        po_number: o.po_number ?? h.po_number,
        dc_number: o.dc_number ?? h.dc_number,
        reference_number: o.doc_number,
      }));
      const out = o.lines.filter((l) => l.pending_quantity > 0);
      setLines(out.map((l) => ({
        item_id: l.item_id, item_code: l.item_code, description: l.description, uom: l.uom,
        hs_code: l.hs_code, quantity: String(l.pending_quantity), unit_price: "0", remarks: null,
        reference_line_id: l.id ?? null, sent: l.quantity, returned: l.returned_quantity,
        still_out: l.pending_quantity,
      })));
      if (o.party_id && !openPasses.some((p) => p.id === o.id)) await loadOpen(o.party_id);
      setFormError(out.length ? null : `Everything on ${o.doc_number} has already come back.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not load that outward pass.");
    }
  };

  // Arriving from an outward pass's "Receive back" button: open a return against it.
  useEffect(() => {
    if (isOutward || typeof window === "undefined") return;
    const from = new URLSearchParams(window.location.search).get("from_ogp");
    if (!from) return;
    setEditingId(null);
    setHeader(emptyHeader());
    setLines([]);
    setOpen(true);
    void pickOutward(from);
    window.history.replaceState(null, "", window.location.pathname);
  }, [isOutward]); // eslint-disable-line react-hooks/exhaustive-deps

  const setH = (key: string, value: string) =>
    setHeader((h) => ({ ...h, [key]: value }));

  const openNew = () => {
    setEditingId(null);
    setHeader(emptyHeader());
    setLines(isOutward ? [emptyLine()] : []);
    setFormError(null);
    void loadOpen("");
    setOpen(true);
  };

  const openEdit = async (id: string) => {
    setFormError(null);
    try {
      const gp = await api.get<GatePassDetail>(`/gate-passes/${passType}/${id}`);
      setEditingId(id);
      setHeader({
        doc_date: gp.doc_date,
        party_id: gp.party_id ?? "",
        vehicle_number: gp.vehicle_number ?? "",
        driver: gp.driver ?? "",
        issue_type: gp.issue_type ?? "",
        issue_to: gp.issue_to ?? "",
        location: gp.location ?? "",
        dc_number: gp.dc_number ?? "",
        challan_number: gp.challan_number ?? "",
        container_number: gp.container_number ?? "",
        po_number: gp.po_number ?? "",
        reference_number: gp.reference_number ?? "",
        ntn: gp.ntn ?? "",
        gst_number: gp.gst_number ?? "",
        currency: gp.currency,
        payment_status: gp.payment_status ?? "",
        payment_reference: gp.payment_reference ?? "",
        remarks: gp.remarks ?? "",
        status: gp.status,
        reference_gate_pass_id: gp.reference_gate_pass_id ?? "",
        expected_return_date: gp.expected_return_date ?? "",
      });
      void loadOpen(gp.party_id ?? "");
      setLines(gp.lines.map((l) => ({
        item_id: l.item_id, item_code: l.item_code, description: l.description,
        uom: l.uom, hs_code: l.hs_code, quantity: String(l.quantity),
        unit_price: String(l.unit_price), remarks: l.remarks,
        reference_line_id: l.reference_line_id ?? null,
      })));
      setOpen(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not open this gate pass.");
    }
  };

  const save = async (status: "Draft" | "Approved") => {
    if (lines.length === 0) { setFormError("Add at least one item."); return; }
    if (isOutward && !header.party_id) { setFormError("Choose the party the goods are going to."); return; }
    if (status === "Approved" && !confirm(
      `Approve this pass?\n\nThe goods go through the gate and the stock moves ${isOutward ? "out of" : "into"} ` +
      `${header.location || "no location"}. An approved pass can no longer be edited.`)) return;
    if (lines.some((l) => !l.description.trim())) {
      setFormError("Every line needs a description."); return;
    }
    if (lines.some((l) => Number(l.quantity) <= 0)) {
      setFormError("Every line needs a quantity greater than zero."); return;
    }

    setSaving(true);
    setFormError(null);
    try {
      const body = {
        ...header,
        status,
        party_id: header.party_id || null,
        reference_gate_pass_id: header.reference_gate_pass_id || null,
        expected_return_date: isOutward && isReturnable(header.issue_type) && header.expected_return_date
          ? header.expected_return_date : null,
        lines: lines.map((l) => ({
          item_id: l.item_id, item_code: l.item_code, description: l.description,
          uom: l.uom, hs_code: l.hs_code, quantity: l.quantity,
          unit_price: l.unit_price || "0", remarks: l.remarks,
          reference_line_id: l.reference_line_id || null,
        })),
      };
      if (editingId) await api.put(`/gate-passes/${passType}/${editingId}`, body);
      else await api.post(`/gate-passes/${passType}`, body);
      setOpen(false);
      await list.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the gate pass.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!editingId) {
      if (!confirm("Discard this gate pass? Nothing has been saved yet.")) return;
      setOpen(false);
      return;
    }
    if (!confirm("Delete this gate pass permanently? This cannot be undone.")) return;
    setSaving(true);
    try {
      await api.del(`/gate-passes/${passType}/${editingId}`);
      setOpen(false);
      await list.reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not delete this gate pass.");
    } finally {
      setSaving(false);
    }
  };

  const setStatus = async (gp: GatePassSummary, status: string) => {
    const verb = status === "Approved"
      ? `Approve ${gp.doc_number}?\n\nThis sends the goods through the gate and moves the ` +
        `stock ${isOutward ? "out of" : "into"} ${gp.location || "no location"}.`
      : `Set ${gp.doc_number} to ${status}?`;
    if (!confirm(verb)) return;
    try {
      await api.post(`/gate-passes/${passType}/${gp.id}/status`, { status });
      await list.reload();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not change the status.");
    }
  };

  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));
  const exportQuery = new URLSearchParams([
    ...(list.search ? [["search", list.search]] : []),
    ...list.statuses.map((s) => ["status", s] as [string, string]),
  ]).toString();

  return (
    <AppShell title={title}>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">{title}</h1>
        <button
          onClick={openNew}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary
                     to-primary-dark px-3.5 py-2 text-[12.8px] font-medium text-on-primary"
        >
          <Plus size={14} strokeWidth={2.4} /> Create
        </button>
      </div>

      <section className="rounded-[14px] border border-line bg-surface shadow-panel">
        <GridHeader count={list.total} onReset={list.reset} resettable={list.dirty} />

        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 pb-4 pt-2">
          <div className="flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input
              value={list.search}
              onChange={(e) => list.setSearch(e.target.value)}
              placeholder="Search number, item, vehicle, remarks…"
              className="w-64 border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint"
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => list.toggleStatus(s)}
                className={`rounded-lg px-2.5 py-1.5 text-[11.5px] font-medium transition-colors
                            ${list.statuses.includes(s)
                              ? "bg-primary text-on-primary"
                              : "bg-hover text-muted hover:text-text"}`}
              >
                {s}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2.5">
            <ColumnPicker columns={COLUMNS} hidden={columnState.hidden}
              onToggle={columnState.toggle} onReset={columnState.reset} />
            <GridActions state={actions} pageSize={list.pageSize} onPageSize={list.setPageSize}
              hidden={columnState.hidden} onToggleColumn={columnState.toggle} onShowAllColumns={columnState.reset} />
            <DownloadMenu dataset={`${passType}-gate-passes`} query={exportQuery} />
          </div>
        </div>

        <GridActionChips state={actions} />
        <GridActionView state={actions} rows={shown} total={list.total} />

        {list.error && (
          <p className="m-5 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{list.error}</p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left"
                 style={{ minWidth: `${260 + visible.length * 130}px` }}>
            <thead>
              <tr className="border-b border-line">
                <GridTh>Edit</GridTh>
                <GridTh>Print</GridTh>
                {visible.map((c) => (
                  <GridTh key={c.key} numeric={c.numeric} sortKey={c.sort}
                          sort={list.sort} direction={list.direction}
                          onSort={list.toggleSort}>
                    {c.label}
                  </GridTh>
                ))}
                <GridTh> </GridTh>
              </tr>
            </thead>
            <tbody>
              {list.loading && (
                <tr><td colSpan={visible.length + 3} className="px-5 py-12 text-center">
                  <Loader2 size={18} className="mx-auto animate-spin text-primary" />
                </td></tr>
              )}
              {!list.loading && shown.length === 0 && (
                <tr><td colSpan={visible.length + 3}
                        className="px-5 py-12 text-center text-[12.8px] text-faint">
                  No gate passes yet. Use Create to raise one.
                </td></tr>
              )}
              {!list.loading && shown.map((g, index) => (
                <Fragment key={g.id}>
                {actions.breakBefore(shown, index) && (
                  <tr className="border-b border-line bg-primary/5">
                    <td colSpan={visible.length + 3} className="px-4 py-2 text-[12px] font-semibold text-primary">
                      {actions.breakBefore(shown, index)}</td>
                  </tr>
                )}
                <tr className={`align-top ${gridRowClass(index)}`} style={actions.rowStyle(g)}>
                  <td className={gridCellClass()}>
                    <button onClick={() => openEdit(g.id)} aria-label="Edit" title="Edit"
                      className="rounded-md p-1.5 text-muted hover:bg-primary/10 hover:text-primary">
                      <Pencil size={14} />
                    </button>
                  </td>
                  <td className={gridCellClass()}>
                    <button onClick={() => openGatePassPdf(g.id)} title="Print gate pass"
                      aria-label="Print gate pass"
                      className="rounded-full bg-sky/15 p-1.5 text-sky transition-colors hover:bg-sky/25">
                      <Printer size={13} />
                    </button>
                  </td>

                  {visible.map((c) => (
                    <td key={c.key}
                        className={gridCellClass(c.numeric,
                          c.key === "item_description" ? "max-w-[280px]"
                            : c.key === "remarks" ? "max-w-[180px] truncate text-muted" : "")}
                        title={c.key === "remarks" ? g.remarks ?? "" : undefined}>
                      {c.render(g)}
                    </td>
                  ))}

                  <td className={gridCellClass()}>
                    <div className="flex items-center gap-1.5">
                      {g.status === "Draft" && (
                        <button onClick={() => setStatus(g, "Approved")}
                          title="Approve — moves the stock"
                          className="whitespace-nowrap rounded-md bg-primary/10 px-2 py-1.5
                                     text-[11px] font-medium text-primary hover:bg-primary/20">
                          Approve
                        </button>
                      )}
                      {isOutward && g.status === "Approved" && g.pending_quantity > 0 && (g.returnable || g.returned_quantity > 0) && (
                        <a href={`/inventory/transactions/inward-gate-pass?from_ogp=${g.id}`}
                          title="Raise an inward pass for the goods coming back"
                          className="whitespace-nowrap rounded-md bg-sky/10 px-2 py-1.5 text-[11px] font-medium text-sky hover:bg-sky/20">
                          Receive back
                        </a>
                      )}
                      {g.status === "Approved" && (
                        <button onClick={() => setStatus(g, "Cancelled")}
                          title="Cancel — reverses the stock movement"
                          className="whitespace-nowrap rounded-md bg-rose/10 px-2 py-1.5
                                     text-[11px] font-medium text-rose hover:bg-rose/20">
                          Cancel
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 px-5 py-3.5 text-[12.3px] text-muted">
          <span>{list.total.toLocaleString()} gate passes</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button disabled={list.page <= 1} onClick={() => list.setPage(list.page - 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
            <span className="px-2">Page {list.page} of {pages}</span>
            <button disabled={list.page >= pages} onClick={() => list.setPage(list.page + 1)}
              className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
          </div>
        </div>
      </section>

      <Modal
        title={editingId ? `Edit ${title}` : title}
        open={isOpen} saving={saving} error={formError} width="xl"
        onClose={() => setOpen(false)}
        onSave={(!editingId || header.status === "Draft") ? () => save("Approved") : undefined} saveLabel="Save & Approve"
        onAlt={(!editingId || header.status === "Draft") ? () => save("Draft") : undefined} altLabel={editingId ? "Apply Changes" : "Save Draft"}
        onDelete={(!editingId || header.status === "Draft") ? remove : undefined} deleteLabel={editingId ? "Delete" : "Discard"}
      >
        <div className="space-y-5">
          {!(!editingId || header.status === "Draft") && (
            <p className="m-0 rounded-lg bg-sky/10 px-3.5 py-2.5 text-[12.5px] text-sky">
              This pass is {header.status.toLowerCase()} and its goods have gone through the gate, so it can only be read.
              {isOutward ? " To undo it, cancel it from the list; goods coming back go on an inward pass." : " To undo it, cancel it from the list."}
            </p>
          )}
          <div className="grid grid-cols-3 gap-4 max-sm:grid-cols-1">
            <Field label="Date" required>
              <TextInput type="date" value={header.doc_date}
                onChange={(e) => setH("doc_date", e.target.value)} />
            </Field>

            <div className="col-span-2 max-sm:col-span-1">
              <Field label="Party" required={isOutward}>
                <Combobox
                  value={header.party_id}
                  options={parties.map((p) => ({
                    value: p.id, label: p.code ? `${p.name} — ${p.code}` : p.name }))}
                  placeholder="Type a party name or code, or pick from the list…"
                  emptyMessage="No party matches that name or code."
                  onChange={(v) => {
                    setH("party_id", v);
                    if (!isOutward) {
                      // A different customer: their own open outward passes, and
                      // a return chosen for someone else no longer applies.
                      void loadOpen(v);
                      const chosen = openPasses.find((o) => o.id === header.reference_gate_pass_id);
                      if (chosen && chosen.party_id !== v) {
                        setH("reference_gate_pass_id", "");
                        setLines([]);
                      }
                    }
                  }}
                />
              </Field>
            </div>

            {!isOutward && (
              <div className="col-span-3 max-sm:col-span-1">
                <Field label="Against Outward Gate Pass (OGP No)">
                  <Combobox
                    value={header.reference_gate_pass_id}
                    options={openPasses.map((o) => ({
                      value: o.id,
                      label: `${o.doc_number} · ${gridDate(o.doc_date)} — ${o.party_name ?? "—"} · ${o.pending_quantity.toLocaleString()} still out (${o.item_description ?? `${o.total_items} items`})`,
                    }))}
                    placeholder={header.party_id
                      ? "Pick the customer's outward pass these goods are returning against…"
                      : "Choose the party first, or pick any open outward pass…"}
                    emptyMessage={header.party_id ? "This party has nothing out on an approved outward pass." : "No approved outward pass has goods still out."}
                    onChange={(v) => void pickOutward(v)}
                  />
                </Field>
                <p className="m-0 mt-1.5 text-[11.5px] text-faint">
                  Picking an OGP fills in the party, location, references and every item still out. Lower a quantity
                  for a part return, or remove a row for goods not coming back now.
                </p>
              </div>
            )}

            <Field label="Vehicle No">
              <TextInput value={header.vehicle_number}
                onChange={(e) => setH("vehicle_number", e.target.value)} />
            </Field>
            <Field label="Driver">
              <TextInput value={header.driver}
                onChange={(e) => setH("driver", e.target.value)} />
            </Field>
            <Field label="Type">
              <Combobox
                value={header.issue_type}
                options={ISSUE_TYPES.map((t) => ({ value: t, label: t }))}
                placeholder="Foc, Returnable, Sale…"
                emptyMessage="Not a standard type — it will be saved as typed."
                allowCustom
                onChange={(v) => setH("issue_type", v)}
              />
            </Field>

            <Field label="Location">
              <Combobox
                value={header.location}
                options={locations.map((l) => ({ value: l.location, label: l.location }))}
                placeholder="Type a location or pick from Item Locations…"
                emptyMessage="Not in Item Locations — stock will not be attributed."
                allowCustom
                onChange={(v) => setH("location", v)}
              />
            </Field>
            <Field label="DC No">
              <TextInput value={header.dc_number}
                onChange={(e) => setH("dc_number", e.target.value)} />
            </Field>
            <Field label="Challan No">
              <TextInput value={header.challan_number}
                onChange={(e) => setH("challan_number", e.target.value)} />
            </Field>

            <Field label="Container No">
              <TextInput value={header.container_number}
                onChange={(e) => setH("container_number", e.target.value)} />
            </Field>
            <Field label="PO No">
              <TextInput value={header.po_number}
                onChange={(e) => setH("po_number", e.target.value)} />
            </Field>
            <Field label="Reference No">
              <TextInput value={header.reference_number}
                onChange={(e) => setH("reference_number", e.target.value)} />
            </Field>

            {isOutward && isReturnable(header.issue_type) ? (
              <Field label="Expected Return Date">
                <TextInput type="date" value={header.expected_return_date}
                  onChange={(e) => setH("expected_return_date", e.target.value)} />
              </Field>
            ) : (
              <Field label="Status">
                <TextInput value={header.status} disabled />
              </Field>
            )}
            <Field label="Payment Status">
              <Select value={header.payment_status} placeholder="Not applicable"
                options={["PENDING", "PARTIAL", "PAID"].map((s) => ({ value: s, label: s }))}
                onChange={(e) => setH("payment_status", e.target.value)} />
            </Field>
            <Field label="Payment Reference">
              <TextInput value={header.payment_reference}
                onChange={(e) => setH("payment_reference", e.target.value)} />
            </Field>

            <div className="col-span-3 max-sm:col-span-1">
              <Field label="Remarks">
                <TextArea rows={2} value={header.remarks}
                  onChange={(e) => setH("remarks", e.target.value)} />
              </Field>
            </div>
          </div>

          <GatePassLines lines={lines} onLines={setLines} isOutward={isOutward}
            returning={!isOutward && Boolean(header.reference_gate_pass_id)} />
        </div>
      </Modal>
    </AppShell>
  );
}

function emptyHeader() {
  return {
    doc_date: new Date().toISOString().slice(0, 10),
    party_id: "", vehicle_number: "", driver: "", issue_type: "", issue_to: "",
    location: "", dc_number: "", challan_number: "", container_number: "",
    po_number: "", reference_number: "", ntn: "", gst_number: "",
    currency: "PKR", payment_status: "", payment_reference: "", remarks: "",
    status: "Draft", reference_gate_pass_id: "", expected_return_date: "",
  };
}

/** The goods on the pass. Prices are optional — plenty of passes carry none.
 *  On a return against an outward pass each row is one of that pass's items,
 *  with how many went out, have come back and are still out. */
function GatePassLines({
  lines, onLines, isOutward, returning,
}: {
  lines: GatePassLine[];
  onLines: (l: GatePassLine[]) => void;
  isOutward: boolean;
  returning: boolean;
}) {
  const { uoms } = useLookups();
  const setLine = (index: number, patch: Partial<GatePassLine>) =>
    onLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  const input =
    "w-full rounded-md border border-line bg-bg px-2.5 py-1.5 text-[12.5px] outline-none " +
    "transition-colors focus:border-primary";
  const qtyInput = (line: GatePassLine, i: number, warn: string | null) => (
    <>
      <input type="text" inputMode="decimal" className={`${input} text-right ${warn ? "border-rose" : ""}`}
        value={line.quantity} onFocus={(e) => e.target.select()}
        onChange={(e) => setLine(i, { quantity: e.target.value.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1") })} />
      {warn && <p className="m-0 mt-1 text-[10.5px] font-medium leading-tight text-rose">{warn}</p>}
    </>
  );
  const fmt = (n: number | null | undefined) => (n ?? 0).toLocaleString();

  const totalQty = lines.reduce((sum, l) => sum + (Number(l.quantity) || 0), 0);
  const headers = returning
    ? ["Item Code", "Description of Goods", "UOM", "Sent", "Already Returned", "Still Out", "Qty Returning", ""]
    : isOutward
      ? ["Item Code", "Description of Goods", "UOM", "Stock", "HS Code", "Qty", "Unit Price", ""]
      : ["Item Code", "Description of Goods", "UOM", "HS Code", "Qty", "Unit Price", ""];

  return (
    <div className="overflow-hidden rounded-[10px] border border-line">
      <div className="flex items-center gap-3 bg-primary px-4 py-2.5 text-on-primary">
        <h4 className="m-0 text-[13px] font-semibold">{returning ? "Goods coming back" : "Goods on this pass"}</h4>
        <span className="text-[11.5px] opacity-90">
          Total quantity {totalQty.toLocaleString()}
        </span>
        {!returning && (
          <button type="button" onClick={() => onLines([...lines, emptyLine()])}
            className="ml-auto flex items-center gap-1.5 rounded-md bg-white/20 px-2.5 py-1
                       text-[11.5px] font-medium transition-colors hover:bg-white/30">
            <Plus size={13} strokeWidth={2.4} /> Add row
          </button>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[880px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line bg-hover">
              {headers.map((h, n) => (
                <th key={`${h}-${n}`} className={`whitespace-nowrap px-2.5 py-2 text-[10.5px] font-semibold
                                       uppercase tracking-wide text-faint ${["Sent", "Already Returned", "Still Out", "Stock"].includes(h) ? "text-right" : ""}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((line, i) => {
              const qty = Number(line.quantity) || 0;
              const remove = (
                <td className="px-2.5 py-2">
                  <button type="button" onClick={() => onLines(lines.filter((_, x) => x !== i))}
                    aria-label="Remove line"
                    className="rounded-md p-1.5 text-muted transition-colors hover:bg-rose/10 hover:text-rose">
                    <X size={14} />
                  </button>
                </td>
              );
              if (returning) {
                const over = line.still_out != null && qty > line.still_out;
                return (
                  <tr key={i} className="border-b border-line align-top last:border-0">
                    <td className="w-[150px] px-2.5 py-2 text-[12px] text-muted">{line.item_code ?? "—"}</td>
                    <td className="min-w-[280px] px-2.5 py-2 text-[12.5px]">{line.description}</td>
                    <td className="w-[80px] px-2.5 py-2 text-[12px] text-muted">{line.uom ?? "—"}</td>
                    <td className="w-[80px] px-2.5 py-2 text-right text-[12.5px] tabular-nums">{fmt(line.sent)}</td>
                    <td className="w-[110px] px-2.5 py-2 text-right text-[12.5px] tabular-nums text-muted">{fmt(line.returned)}</td>
                    <td className="w-[90px] px-2.5 py-2 text-right text-[12.5px] font-semibold tabular-nums">{fmt(line.still_out)}</td>
                    <td className="w-[120px] px-2.5 py-2">
                      {qtyInput(line, i, over ? `Only ${fmt(line.still_out)} still out` : null)}
                    </td>
                    {remove}
                  </tr>
                );
              }
              const short = isOutward && line.stocked && line.stock != null && qty > line.stock;
              return (
                <tr key={i} className="border-b border-line align-top last:border-0">
                  <td className="w-[150px] px-2.5 py-2">
                    <ItemPicker
                      value={line.item_code}
                      onPick={(item) => setLine(i, {
                        item_id: item.id, item_code: item.item_code,
                        description: item.description, uom: item.uom,
                        stock: item.opening_stock ?? null,
                        stocked: !["SERVICES", "SOFTWARE", "CAD"].includes((item.main_product_name ?? "").trim().toUpperCase()),
                      })}
                    />
                  </td>
                  <td className="min-w-[300px] px-2.5 py-2">
                    <textarea rows={2} className={`${input} resize-y leading-snug`}
                      value={line.description}
                      onChange={(e) => setLine(i, { description: e.target.value })} />
                  </td>
                  <td className="w-[110px] px-2.5 py-2">
                    <UomPicker value={line.uom} uoms={uoms}
                      onChange={(v) => setLine(i, { uom: v })} />
                  </td>
                  {isOutward && (
                    <td className="w-[80px] px-2.5 py-2 text-right text-[12.5px] tabular-nums text-muted">
                      {line.stock != null ? fmt(line.stock) : "—"}
                    </td>
                  )}
                  <td className="w-[110px] px-2.5 py-2">
                    <input className={input} value={line.hs_code ?? ""}
                      onChange={(e) => setLine(i, { hs_code: e.target.value })} />
                  </td>
                  <td className="w-[110px] px-2.5 py-2">
                    {qtyInput(line, i, short ? `Only ${fmt(Math.max(line.stock ?? 0, 0))} in stock` : null)}
                  </td>
                  <td className="w-[110px] px-2.5 py-2">
                    <input type="text" inputMode="decimal" className={`${input} text-right`}
                      value={line.unit_price === "0" ? "" : line.unit_price} placeholder="0"
                      onChange={(e) => setLine(i, { unit_price: e.target.value.replace(/[^0-9.]/g, "") || "0" })} />
                  </td>
                  {remove}
                </tr>
              );
            })}
            {lines.length === 0 && (
              <tr><td colSpan={headers.length} className="px-4 py-8 text-center text-[12.5px] text-faint">
                {isOutward ? <>No items yet. Use &ldquo;Add row&rdquo; to start.</>
                  : <>Pick the outward gate pass above and its items appear here, or use &ldquo;Add row&rdquo; for goods arriving without one.</>}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {!isOutward && !returning && lines.length === 0 && (
        <div className="border-t border-line px-4 py-2.5">
          <button type="button" onClick={() => onLines([emptyLine()])}
            className="text-[12px] font-medium text-primary hover:underline">+ Add a row for goods arriving without an outward pass</button>
        </div>
      )}
    </div>
  );
}
interface ItemOption {
  id: string; item_code: string; description: string; uom: string | null;
  opening_stock?: number | null; main_product_name?: string | null;
}

/** Type-ahead product lookup, the same one the sales form uses. */
function ItemPicker({ value, onPick }: {
  value: string | null;
  onPick: (item: ItemOption) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ItemOption[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || query.trim().length < 2) { setResults([]); return; }
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const data = await api.get<{ items: ItemOption[] }>(
          `/inventory/items?search=${encodeURIComponent(query)}&page_size=15`);
        setResults(data.items);
      } catch { setResults([]); } finally { setBusy(false); }
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
                {busy && <p className="py-6 text-center">
                  <Loader2 size={16} className="mx-auto animate-spin text-primary" /></p>}
                {!busy && query.length >= 2 && results.length === 0 && (
                  <p className="py-6 text-center text-[12.5px] text-faint">No matching products.</p>
                )}
                {results.map((item) => (
                  <button key={item.id} type="button"
                    onClick={() => { onPick(item); setOpen(false); setQuery(""); }}
                    className="block w-full border-b border-line px-2 py-2.5 text-left
                               last:border-0 hover:bg-hover">
                    <div className="text-[12.5px] font-medium">{item.description}</div>
                    <div className="text-[11px] text-faint">
                      {item.item_code} · {item.uom ?? "—"}
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

