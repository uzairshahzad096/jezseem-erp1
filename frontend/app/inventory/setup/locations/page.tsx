"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { DataTable } from "@/components/ui/DataTable";
import { DownloadMenu } from "@/components/ui/TableTools";
import { Modal, Field, TextArea, Toggle } from "@/components/ui/Modal";
import { useCrud } from "@/lib/useCrud";

interface Location { id: string; location: string; is_active: boolean; }

export default function ItemLocationsPage() {
  const crud = useCrud<Location>("/inventory/locations", 25);
  const [editing, setEditing] = useState<Location | null>(null);
  const [isOpen, setOpen] = useState(false);
  const [location, setLocation] = useState("");
  const [active, setActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const openNew = () => { setEditing(null); setLocation(""); setActive(true); setFormError(null); setOpen(true); };
  const openEdit = (l: Location) => { setEditing(l); setLocation(l.location); setActive(l.is_active); setFormError(null); setOpen(true); };

  const save = async () => {
    if (!location.trim()) { setFormError("Location is required."); return; }
    setSaving(true); setFormError(null);
    try {
      const body = { location: location.trim(), is_active: active };
      if (editing) await crud.update(editing.id, body); else await crud.create(body);
      setOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the location.");
    } finally { setSaving(false); }
  };

  const remove = async (l: Location) => {
    if (!confirm("Delete this location?")) return;
    try { await crud.remove(l.id); }
    catch (err) { alert(err instanceof Error ? err.message : "Could not delete."); }
  };

  return (
    <AppShell title="Item Locations">
      <h1 className="mb-5 text-[19px] font-semibold">Item Locations</h1>
      <DataTable<Location>
        title="Item Locations"
        emptyMessage="No locations yet. Use Create to add one."
        columns={[
          { key: "location", header: "Location" },
          { key: "is_active", header: "Status",
            render: (l) => (
              <span className={`rounded-md px-2.5 py-1 text-[10.5px] font-semibold ${l.is_active ? "bg-success/15 text-success" : "bg-rose/15 text-rose"}`}>
                {l.is_active ? "Active" : "Inactive"}
              </span>
            ) },
        ]}
        rows={crud.rows} total={crud.total} page={crud.page} pageSize={crud.pageSize} onPageSize={crud.setPageSize}
        loading={crud.loading} error={crud.error} search={crud.search}
        onSearch={crud.onSearch} onPage={crud.setPage}
        toolbar={<DownloadMenu dataset="locations" />}
        columnsKey="locations.columns"
        onCreate={openNew} onEdit={openEdit} onDelete={remove}
      />

      <Modal title="Item Location" open={isOpen} saving={saving} error={formError}
        onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Save" : "Create"}>
        <div className="space-y-4">
          <Field label="Location" required>
            <TextArea value={location} onChange={(e) => setLocation(e.target.value)} autoFocus />
          </Field>
          <Toggle label="Active" checked={active} onChange={setActive} />
        </div>
      </Modal>
    </AppShell>
  );
}
