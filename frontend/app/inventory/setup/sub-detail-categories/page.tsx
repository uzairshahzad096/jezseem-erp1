"use client";

import { useMemo, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { DataTable } from "@/components/ui/DataTable";
import { DownloadMenu } from "@/components/ui/TableTools";
import { Modal, Field, TextInput, TextArea, Select } from "@/components/ui/Modal";
import { useCrud } from "@/lib/useCrud";
import { useLookups, toOptions } from "@/lib/useLookups";

interface DetailCategory {
  id: string;
  main_product_id: string;
  main_product_name: string | null;
  sub_category_id: string;
  sub_category_name: string | null;
  description: string;
  remarks: string | null;
}

const EMPTY = { main_product_id: "", sub_category_id: "", description: "", remarks: "" };

export default function SubDetailCategoriesPage() {
  const crud = useCrud<DetailCategory>("/inventory/sub-detail-categories", 25);
  const { mainProducts, subCategories } = useLookups();
  const [editing, setEditing] = useState<DetailCategory | null>(null);
  const [isOpen, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const set = (key: keyof typeof EMPTY, value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  // Sub Product choices follow the selected Main Product, so an invalid
  // combination cannot be submitted in the first place.
  const subOptions = useMemo(
    () => toOptions(subCategories.filter((s) => s.parentId === form.main_product_id)),
    [subCategories, form.main_product_id],
  );

  const openNew = () => { setEditing(null); setForm({ ...EMPTY }); setFormError(null); setOpen(true); };
  const openEdit = (r: DetailCategory) => {
    setEditing(r);
    setForm({
      main_product_id: r.main_product_id,
      sub_category_id: r.sub_category_id,
      description: r.description,
      remarks: r.remarks ?? "",
    });
    setFormError(null); setOpen(true);
  };

  const save = async () => {
    if (!form.main_product_id) { setFormError("Main product is required."); return; }
    if (!form.sub_category_id) { setFormError("Sub product is required."); return; }
    if (!form.description.trim()) { setFormError("Description is required."); return; }
    setSaving(true); setFormError(null);
    try {
      const body = {
        main_product_id: form.main_product_id,
        sub_category_id: form.sub_category_id,
        description: form.description.trim(),
        remarks: form.remarks.trim() || null,
        is_active: true,
      };
      if (editing) await crud.update(editing.id, body); else await crud.create(body);
      setOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the detail category.");
    } finally { setSaving(false); }
  };

  const remove = async (r: DetailCategory) => {
    if (!confirm(`Delete "${r.description}"?`)) return;
    try { await crud.remove(r.id); }
    catch (err) { alert(err instanceof Error ? err.message : "Could not delete."); }
  };

  return (
    <AppShell title="Inventory Sub Detail Category">
      <h1 className="mb-5 text-[19px] font-semibold">Inventory Sub Detail Category</h1>
      <DataTable<DetailCategory>
        title="Inventory Sub Detail Category"
        createLabel="Add Category"
        emptyMessage="No detail categories yet. Import the legacy data or add one."
        columns={[
          { key: "main_product_name", header: "Main Category", render: (r) => r.main_product_name ?? "—" },
          { key: "sub_category_name", header: "Sub Category", render: (r) => r.sub_category_name ?? "—" },
          { key: "description", header: "Description" },
          { key: "remarks", header: "Remarks", render: (r) => r.remarks ?? "—" },
        ]}
        rows={crud.rows} total={crud.total} page={crud.page} pageSize={crud.pageSize} onPageSize={crud.setPageSize}
        loading={crud.loading} error={crud.error} search={crud.search}
        onSearch={crud.onSearch} onPage={crud.setPage}
        toolbar={<DownloadMenu dataset="sub-detail-categories" />}
        columnsKey="sub-detail-categories.columns"
        onCreate={openNew} onEdit={openEdit} onDelete={remove}
      />

      <Modal title="Inventory Sub Detail Category" open={isOpen} saving={saving} error={formError}
        width="md" onClose={() => setOpen(false)} onSave={save}
        saveLabel={editing ? "Save" : "Create"}>
        <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
          <Field label="Main Product" required>
            <Select value={form.main_product_id} options={toOptions(mainProducts)}
              onChange={(e) => { set("main_product_id", e.target.value); set("sub_category_id", ""); }} />
          </Field>
          <Field label="Sub Product" required>
            <Select value={form.sub_category_id} options={subOptions}
              disabled={!form.main_product_id}
              placeholder={form.main_product_id ? "Select…" : "Choose a main product first"}
              onChange={(e) => set("sub_category_id", e.target.value)} />
          </Field>
          <div className="col-span-2 max-sm:col-span-1">
            <Field label="Description" required>
              <TextInput value={form.description} onChange={(e) => set("description", e.target.value)} />
            </Field>
          </div>
          <div className="col-span-2 max-sm:col-span-1">
            <Field label="Remarks">
              <TextArea value={form.remarks} onChange={(e) => set("remarks", e.target.value)} />
            </Field>
          </div>
        </div>
      </Modal>
    </AppShell>
  );
}
