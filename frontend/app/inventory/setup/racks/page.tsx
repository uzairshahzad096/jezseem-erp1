"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { DataTable } from "@/components/ui/DataTable";
import { DownloadMenu } from "@/components/ui/TableTools";
import { Modal, Field, TextInput, Toggle } from "@/components/ui/Modal";
import { useCrud } from "@/lib/useCrud";

interface Rack { id: string; rack_name: string; is_active: boolean; item_count: number; }
interface RackItem {
  id: string;
  item_code: string;
  description: string;
  uom: string | null;
  item_status: string;
}

export default function ItemRacksPage() {
  const crud = useCrud<Rack>("/inventory/racks", 25);
  const [editing, setEditing] = useState<Rack | null>(null);
  const [viewing, setViewing] = useState<Rack | null>(null);
  const [isOpen, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [active, setActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const openNew = () => { setEditing(null); setName(""); setActive(true); setFormError(null); setOpen(true); };
  const openEdit = (r: Rack) => { setEditing(r); setName(r.rack_name); setActive(r.is_active); setFormError(null); setOpen(true); };

  const save = async () => {
    if (!name.trim()) { setFormError("Rack name is required."); return; }
    setSaving(true); setFormError(null);
    try {
      const body = { rack_name: name.trim(), is_active: active };
      if (editing) await crud.update(editing.id, body); else await crud.create(body);
      setOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the rack.");
    } finally { setSaving(false); }
  };

  const remove = async (r: Rack) => {
    if (!confirm(`Delete rack "${r.rack_name}"?`)) return;
    try { await crud.remove(r.id); }
    catch (err) { alert(err instanceof Error ? err.message : "Could not delete."); }
  };

  return (
    <AppShell title="Item Racks">
      <h1 className="mb-5 text-[19px] font-semibold">Item Racks</h1>
      <DataTable<Rack>
        title="Item Racks"
        createLabel="Create"
        emptyMessage="No racks yet. Use Create to add one."
        columns={[
          { key: "rack_name", header: "Rack Name" },
          { key: "item_count", header: "Products",
            render: (r) =>
              r.item_count > 0 ? (
                <button
                  onClick={() => setViewing(r)}
                  className="rounded-md bg-hover px-2.5 py-1 text-[11.5px] font-semibold
                             text-muted transition-colors hover:bg-primary/10 hover:text-primary"
                >
                  {r.item_count.toLocaleString()} {r.item_count === 1 ? "product" : "products"}
                </button>
              ) : (
                <span className="text-faint">—</span>
              ) },
          { key: "is_active", header: "Status",
            render: (r) => (
              <span className={`rounded-md px-2.5 py-1 text-[10.5px] font-semibold ${r.is_active ? "bg-success/15 text-success" : "bg-rose/15 text-rose"}`}>
                {r.is_active ? "Active" : "Inactive"}
              </span>
            ) },
        ]}
        rows={crud.rows} total={crud.total} page={crud.page} pageSize={crud.pageSize} onPageSize={crud.setPageSize}
        loading={crud.loading} error={crud.error} search={crud.search}
        onSearch={crud.onSearch} onPage={crud.setPage}
        toolbar={<DownloadMenu dataset="racks" />}
        columnsKey="racks.columns"
        onCreate={openNew} onEdit={openEdit} onDelete={remove}
      />

      <Modal title="Item Racks" open={isOpen} saving={saving} error={formError}
        onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Save" : "Create"}>
        <div className="space-y-4">
          <Field label="Rack Name" required>
            <TextInput value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </Field>
          <Toggle label="Active" checked={active} onChange={setActive} />
        </div>
      </Modal>

      {viewing && (
        <Modal
          title={`Rack ${viewing.rack_name} — products`}
          open
          width="lg"
          onClose={() => setViewing(null)}
        >
          <RackProducts rackId={viewing.id} />
        </Modal>
      )}
    </AppShell>
  );
}

/** The products assigned to one rack. Mounted only while its modal is open,
 *  so the fetch happens on demand rather than with the rack listing. */
function RackProducts({ rackId }: { rackId: string }) {
  const items = useCrud<RackItem>(`/inventory/racks/${rackId}/items`, 10);

  return (
    <DataTable<RackItem>
      title="Products on this rack"
      emptyMessage="No products are assigned to this rack yet."
      columns={[
        { key: "item_code", header: "Item Code", className: "whitespace-nowrap" },
        { key: "description", header: "Description" },
        { key: "uom", header: "UOM" },
        { key: "item_status", header: "Status",
          render: (i) => (
            <span className={`rounded-md px-2.5 py-1 text-[10.5px] font-semibold ${
              i.item_status === "ACTIVE" ? "bg-success/15 text-success" : "bg-hover text-muted"
            }`}>
              {i.item_status}
            </span>
          ) },
      ]}
      rows={items.rows} total={items.total} page={items.page} pageSize={items.pageSize} onPageSize={items.setPageSize}
      loading={items.loading} error={items.error} search={items.search}
      onSearch={items.onSearch} onPage={items.setPage}
    />
  );
}
