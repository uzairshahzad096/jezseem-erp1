"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { DataTable } from "@/components/ui/DataTable";
import { DownloadMenu } from "@/components/ui/TableTools";
import { Modal, Field, TextInput, TextArea } from "@/components/ui/Modal";
import { useCrud } from "@/lib/useCrud";

interface MainProduct { id: string; description: string; remarks: string | null; is_active: boolean; }

export default function MainProductsPage() {
  const crud = useCrud<MainProduct>("/inventory/main-products", 50);
  const [editing, setEditing] = useState<MainProduct | null>(null);
  const [isOpen, setOpen] = useState(false);
  const [description, setDescription] = useState("");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const openNew = () => { setEditing(null); setDescription(""); setRemarks(""); setFormError(null); setOpen(true); };
  const openEdit = (p: MainProduct) => {
    setEditing(p); setDescription(p.description); setRemarks(p.remarks ?? ""); setFormError(null); setOpen(true);
  };

  const save = async () => {
    if (!description.trim()) { setFormError("Description is required."); return; }
    setSaving(true); setFormError(null);
    try {
      const body = { description: description.trim(), remarks: remarks.trim() || null, is_active: true };
      if (editing) await crud.update(editing.id, body); else await crud.create(body);
      setOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the main product.");
    } finally { setSaving(false); }
  };

  const remove = async (p: MainProduct) => {
    if (!confirm(`Delete main product "${p.description}"?`)) return;
    try { await crud.remove(p.id); }
    catch (err) { alert(err instanceof Error ? err.message : "Could not delete."); }
  };

  return (
    <AppShell title="Main Products">
      <h1 className="mb-5 text-[19px] font-semibold">Main Product</h1>
      <DataTable<MainProduct>
        title="Main Product"
        createLabel="New Main Product"
        emptyMessage="No main products yet. Import the legacy data or add one."
        columns={[
          { key: "description", header: "Description" },
          { key: "remarks", header: "Remarks", render: (p) => p.remarks ?? "—" },
        ]}
        rows={crud.rows} total={crud.total} page={crud.page} pageSize={crud.pageSize} onPageSize={crud.setPageSize}
        loading={crud.loading} error={crud.error} search={crud.search}
        onSearch={crud.onSearch} onPage={crud.setPage}
        toolbar={<DownloadMenu dataset="main-products" />}
        columnsKey="main-products.columns"
        onCreate={openNew} onEdit={openEdit} onDelete={remove}
      />

      <Modal title="Main Product" open={isOpen} saving={saving} error={formError}
        onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Save" : "Create"}>
        <div className="space-y-4">
          <Field label="Description" required>
            <TextInput value={description} onChange={(e) => setDescription(e.target.value)} autoFocus />
          </Field>
          <Field label="Remarks">
            <TextArea value={remarks} onChange={(e) => setRemarks(e.target.value)} />
          </Field>
        </div>
      </Modal>
    </AppShell>
  );
}
