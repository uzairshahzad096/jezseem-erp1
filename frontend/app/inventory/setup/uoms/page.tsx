"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { DataTable } from "@/components/ui/DataTable";
import { Modal, Field, TextInput, Select, Toggle } from "@/components/ui/Modal";
import { useCrud } from "@/lib/useCrud";

interface Uom {
  id: string;
  code: string;
  description: string;
  category: string | null;
  base_uom_code: string | null;
  conversion_to_base: number | null;
  decimal_places: number;
  is_active: boolean;
  sort_order: number;
}

/** Loose groupings, useful in a picker and not worth a second table. */
const CATEGORIES = ["Count", "Weight", "Length", "Area", "Volume", "Time", "Other"];

const EMPTY = {
  code: "", description: "", category: "", base_uom_code: "",
  conversion_to_base: "", decimal_places: "0", sort_order: "100",
};

export default function UomsPage() {
  const crud = useCrud<Uom>("/inventory/uoms", 50);
  const [editing, setEditing] = useState<Uom | null>(null);
  const [isOpen, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [isActive, setIsActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const set = (key: keyof typeof EMPTY, value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const openNew = () => {
    setEditing(null);
    setForm({ ...EMPTY });
    setIsActive(true);
    setFormError(null);
    setOpen(true);
  };

  const openEdit = (row: Uom) => {
    setEditing(row);
    setForm({
      code: row.code,
      description: row.description,
      category: row.category ?? "",
      base_uom_code: row.base_uom_code ?? "",
      conversion_to_base: row.conversion_to_base != null
        ? String(row.conversion_to_base) : "",
      decimal_places: String(row.decimal_places),
      sort_order: String(row.sort_order),
    });
    setIsActive(row.is_active);
    setFormError(null);
    setOpen(true);
  };

  const save = async () => {
    if (!form.code.trim()) { setFormError("A code is required — PCS, KG, MT."); return; }
    if (!form.description.trim()) {
      setFormError("A description is required, so the picker can be searched by word.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const body = {
        code: form.code.trim().toUpperCase(),
        description: form.description.trim(),
        category: form.category || null,
        base_uom_code: form.base_uom_code.trim().toUpperCase() || null,
        conversion_to_base: form.conversion_to_base || null,
        decimal_places: Number(form.decimal_places || 0),
        sort_order: Number(form.sort_order || 0),
        is_active: isActive,
      };
      if (editing) await crud.update(editing.id, body);
      else await crud.create(body);
      setOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the unit.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell title="Units of Measure">
      <div className="mb-5 flex flex-wrap items-baseline gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Units of Measure</h1>
        <p className="m-0 text-[12px] text-muted">
          What every form offers when it asks for a UOM. Anything can still be
          typed on a document; adding it here offers it everywhere.
        </p>
      </div>

      <DataTable<Uom>
        title="Units"
        columns={[
          { key: "code", header: "UOM",
            render: (r) => <span className="font-medium">{r.code}</span> },
          { key: "description", header: "Description" },
          { key: "category", header: "Category", render: (r) => r.category ?? "—" },
          { key: "decimal_places", header: "Decimals",
            render: (r) => (r.decimal_places === 0
              ? <span className="text-muted">whole numbers</span>
              : `${r.decimal_places}`) },
          { key: "base", header: "Converts To",
            render: (r) => (r.base_uom_code && r.conversion_to_base
              ? `1 ${r.code} = ${r.conversion_to_base} ${r.base_uom_code}`
              : "—") },
          { key: "is_active", header: "Active",
            render: (r) => (r.is_active
              ? <span className="text-primary">Yes</span>
              : <span className="text-faint">Retired</span>) },
        ]}
        rows={crud.rows}
        total={crud.total}
        page={crud.page}
        pageSize={crud.pageSize} onPageSize={crud.setPageSize}
        loading={crud.loading}
        error={crud.error}
        search={crud.search}
        createLabel="Add Unit"
        emptyMessage="No units yet — add PCS to start."
        onSearch={crud.onSearch}
        onPage={crud.setPage}
        onCreate={openNew}
        onEdit={openEdit}
        onDelete={async (row) => {
          if (!confirm(`Delete ${row.code}? Units already used by products cannot `
            + "be deleted — turn Active off instead.")) return;
          try {
            await crud.remove(row.id);
          } catch (err) {
            alert(err instanceof Error ? err.message : "Could not delete the unit.");
          }
        }}
      />

      <Modal
        title={editing ? `Unit ${editing.code}` : "Add Unit of Measure"}
        open={isOpen} saving={saving} error={formError} width="md"
        onClose={() => setOpen(false)} onSave={save}
        saveLabel={editing ? "Save" : "Create"}
      >
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="UOM Code" required>
            <TextInput value={form.code}
              placeholder="PCS"
              onChange={(e) => set("code", e.target.value.toUpperCase())} />
          </Field>
          <Field label="Description" required>
            <TextInput value={form.description} placeholder="Pieces"
              onChange={(e) => set("description", e.target.value)} />
          </Field>
          <Field label="Category">
            <Select value={form.category}
              options={CATEGORIES.map((c) => ({ value: c, label: c }))}
              placeholder="Ungrouped"
              onChange={(e) => set("category", e.target.value)} />
          </Field>
          <Field label="Decimal places">
            {/* Pieces are whole things; a quantity of 2.5 of them is a typo,
                so the unit says how precise it can sensibly be. */}
            <Select value={form.decimal_places}
              options={[0, 1, 2, 3, 4].map((n) => ({
                value: String(n),
                label: n === 0 ? "0 — whole numbers only" : `${n}`,
              }))}
              placeholder="0"
              onChange={(e) => set("decimal_places", e.target.value)} />
          </Field>

          <Field label="Equivalent in">
            <TextInput value={form.base_uom_code} placeholder="e.g. PCS"
              onChange={(e) => set("base_uom_code", e.target.value.toUpperCase())} />
          </Field>
          <Field label="How many">
            <TextInput type="number" step="0.000001"
              value={form.conversion_to_base} placeholder="e.g. 12"
              onChange={(e) => set("conversion_to_base", e.target.value)} />
          </Field>

          <Field label="Sort order">
            <TextInput type="number" value={form.sort_order}
              onChange={(e) => set("sort_order", e.target.value)} />
          </Field>
          <Toggle label="Active" checked={isActive} onChange={setIsActive} />
        </div>

        <p className="mt-4 text-[11px] leading-snug text-faint">
          The two Equivalent fields record that a bigger pack is so many of a
          smaller unit — 1 SET = 12 PCS. They are for reference on the unit;
          quantities are not converted automatically, because a document says
          what was actually counted.
          {editing && (
            <> A code already used by products cannot be changed, since documents
            hold the text rather than a link — retire it and add the new one.</>
          )}
        </p>
      </Modal>
    </AppShell>
  );
}
