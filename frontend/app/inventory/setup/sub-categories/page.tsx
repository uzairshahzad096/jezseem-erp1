"use client";

import { useMemo, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { DataTable } from "@/components/ui/DataTable";
import { DownloadMenu } from "@/components/ui/TableTools";
import { Modal, Field, TextInput, TextArea, Select } from "@/components/ui/Modal";
import { useCrud } from "@/lib/useCrud";
import { useLookups, toOptions } from "@/lib/useLookups";

interface SubCategory {
  id: string;
  main_product_id: string;
  main_product_name: string | null;
  sub_code: string | null;
  description: string;
  remarks: string | null;
  detailcode_purchase_local: string | null;
  detailcode_purchase_import: string | null;
}

const EMPTY = {
  main_product_id: "", sub_code: "", description: "", remarks: "",
  detailcode_purchase_local: "", detailcode_purchase_import: "",
};

export default function SubCategoriesPage() {
  const crud = useCrud<SubCategory>("/inventory/sub-categories", 25);
  const { mainProducts } = useLookups();
  const [editing, setEditing] = useState<SubCategory | null>(null);
  const [isOpen, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const set = (key: keyof typeof EMPTY, value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const openNew = () => { setEditing(null); setForm({ ...EMPTY }); setFormError(null); setOpen(true); };
  const openEdit = (r: SubCategory) => {
    setEditing(r);
    setForm({
      main_product_id: r.main_product_id,
      sub_code: r.sub_code ?? "",
      description: r.description,
      remarks: r.remarks ?? "",
      detailcode_purchase_local: r.detailcode_purchase_local ?? "",
      detailcode_purchase_import: r.detailcode_purchase_import ?? "",
    });
    setFormError(null); setOpen(true);
  };

  const save = async () => {
    if (!form.main_product_id) { setFormError("Main product is required."); return; }
    if (!form.description.trim()) { setFormError("Description is required."); return; }
    setSaving(true); setFormError(null);
    try {
      const body = {
        main_product_id: form.main_product_id,
        sub_code: form.sub_code.trim() || null,
        description: form.description.trim(),
        remarks: form.remarks.trim() || null,
        detailcode_purchase_local: form.detailcode_purchase_local.trim() || null,
        detailcode_purchase_import: form.detailcode_purchase_import.trim() || null,
        is_active: true,
      };
      if (editing) await crud.update(editing.id, body); else await crud.create(body);
      setOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the sub category.");
    } finally { setSaving(false); }
  };

  const remove = async (r: SubCategory) => {
    if (!confirm(`Delete sub category "${r.description}"?`)) return;
    try { await crud.remove(r.id); }
    catch (err) { alert(err instanceof Error ? err.message : "Could not delete."); }
  };

  const mainOptions = useMemo(() => toOptions(mainProducts), [mainProducts]);

  return (
    <AppShell title="Inventory Sub Category">
      <h1 className="mb-5 text-[19px] font-semibold">Inventory Sub Category</h1>
      <DataTable<SubCategory>
        title="Inventory Sub Category"
        createLabel="Add Inventory Sub Category"
        emptyMessage="No sub categories yet. Import the legacy data or add one."
        columns={[
          { key: "main_product_name", header: "Main Product", render: (r) => r.main_product_name ?? "—" },
          { key: "sub_code", header: "Sub Code", render: (r) => r.sub_code ?? "—" },
          { key: "description", header: "Description" },
          { key: "remarks", header: "Remarks", render: (r) => r.remarks ?? "—" },
        ]}
        rows={crud.rows} total={crud.total} page={crud.page} pageSize={crud.pageSize} onPageSize={crud.setPageSize}
        loading={crud.loading} error={crud.error} search={crud.search}
        onSearch={crud.onSearch} onPage={crud.setPage}
        toolbar={<DownloadMenu dataset="sub-categories" />}
        columnsKey="sub-categories.columns"
        onCreate={openNew} onEdit={openEdit} onDelete={remove}
      />

      <Modal title="Inventory Sub Category" open={isOpen} saving={saving} error={formError}
        width="md" onClose={() => setOpen(false)} onSave={save}
        saveLabel={editing ? "Save" : "Create"}>
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="Main Product" required>
            <Select value={form.main_product_id} options={mainOptions}
              onChange={(e) => set("main_product_id", e.target.value)} />
          </Field>
          <Field label="Sub Product Code">
            <TextInput value={form.sub_code} onChange={(e) => set("sub_code", e.target.value)} />
          </Field>
          <div className="col-span-2 max-sm:col-span-1">
            <Field label="Description" required>
              <TextInput value={form.description} onChange={(e) => set("description", e.target.value)} />
            </Field>
          </div>
          <Field label="Local Purchase A/C">
            <TextInput value={form.detailcode_purchase_local}
              onChange={(e) => set("detailcode_purchase_local", e.target.value)} />
          </Field>
          <Field label="Import Purchase A/C">
            <TextInput value={form.detailcode_purchase_import}
              onChange={(e) => set("detailcode_purchase_import", e.target.value)} />
          </Field>
          <div className="col-span-2 max-sm:col-span-1">
            <Field label="Remarks">
              <TextArea value={form.remarks} onChange={(e) => set("remarks", e.target.value)} />
            </Field>
          </div>
        </div>
        <p className="mt-4 text-[11.5px] text-faint">
          Account fields are stored as plain codes until the Finance module defines
          a chart of accounts, at which point they become proper account links.
        </p>
      </Modal>
    </AppShell>
  );
}
