"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { GridActionChips, GridActionView, GridActions, useGridActions } from "@/components/ui/GridActions";
import { usePageSize } from "@/lib/usePageSize";
import {
  Package, Search, Loader2, Plus, RotateCcw, Upload, Trash2,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Modal, Field, TextInput, TextArea, Select, Combobox } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { useLookups, toOptions } from "@/lib/useLookups";
import { DownloadMenu } from "@/components/ui/TableTools";
import { ItemActions } from "@/components/inventory/ItemActions";
import { UomPicker } from "@/components/ui/UomPicker";

interface Item {
  id: string;
  item_code: string;
  description: string;
  uom: string | null;
  sku: string | null;
  barcode: string | null;
  item_status: string;
  price: number | null;
  currency: string | null;
  opening_stock: number;
  image_path: string | null;
  image_url: string | null;
  main_product_name: string | null;
  sub_category_name: string | null;
  sub_detail_category_name: string | null;
  rack_name: string | null;
  main_product_id: string | null;
  sub_category_id: string | null;
  sub_detail_category_id: string | null;
  rack_id: string | null;
  location_id: string | null;
}

interface Bucket { id: string | null; label: string; count: number }
interface Facets {
  main_categories: Bucket[];
  sub_categories: Bucket[];
  sub_detail_categories: Bucket[];
  racks: Bucket[];
  item_statuses: Bucket[];
}

type FilterKey = "main_category" | "sub_category" | "sub_detail_category" | "rack" | "item_status";

/** Stock quantity bounds, as typed. Blank means unbounded on that side. */
interface StockRange { from: string; to: string }

const EMPTY_ITEM = {
  item_code: "", description: "", main_product_id: "", sub_category_id: "",
  sub_detail_category_id: "", rack_id: "", location_id: "", uom: "", market_name: "", market_uom: "",
  sku: "", barcode: "", item_status: "ACTIVE", currency: "", price: "",
  min_level: "", max_level: "", re_order_qty: "",
};

const DEFAULT_PAGE_SIZE = 24;

/** The product fields the Actions menu can filter, sort, group and chart. */
const PRODUCT_COLUMNS = [
  { key: "description", label: "Description" },
  { key: "item_code", label: "Item Code" },
  { key: "sku", label: "SKU" },
  { key: "uom", label: "UOM" },
  { key: "main_product_name", label: "Main Category" },
  { key: "sub_category_name", label: "Sub Category" },
  { key: "sub_detail_category_name", label: "Sub Dtl Category" },
  { key: "rack_name", label: "Rack" },
  { key: "item_status", label: "Item Status" },
  { key: "opening_stock", label: "Stock", numeric: true },
  { key: "price", label: "Price", numeric: true },
  { key: "currency", label: "Currency" },
];
export default function ProductDetailsPage() {
  const lookups = useLookups();
  const locationOptions = lookups.locations;
  const [items, setItems] = useState<Item[]>([]);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [PAGE_SIZE, setPageSize] = usePageSize("/inventory/items", DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Record<FilterKey, string[]>>({
    main_category: [], sub_category: [], sub_detail_category: [], rack: [], item_status: [],
  });
  // The Actions menu over the loaded products.
  const actions = useGridActions<Item>("products", PRODUCT_COLUMNS);
  const shown = actions.apply(items);
  /** Show only products whose stock falls in this range. Empty means any. */
  const [range, setRange] = useState<StockRange>({ from: "", to: "" });

  const [isOpen, setOpen] = useState(false);
  const [editing, setEditing] = useState<Item | null>(null);
  const [form, setForm] = useState({ ...EMPTY_ITEM });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [dropImage, setDropImage] = useState(false);

  const query = useMemo(() => {
    const qs = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (search) qs.set("search", search);
    (Object.keys(filters) as FilterKey[]).forEach((key) =>
      filters[key].forEach((v) => qs.append(key, v)),
    );
    if (range.from) qs.set("stock_from", range.from);
    if (range.to) qs.set("stock_to", range.to);
    return qs.toString();
  }, [page, search, filters, range, PAGE_SIZE]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<{ items: Item[]; total: number }>(`/inventory/items?${query}`);
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load products.");
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  useEffect(() => {
    api.get<Facets>("/inventory/items/facets").then(setFacets).catch(() => setFacets(null));
  }, []);

  const toggleFilter = (key: FilterKey, value: string) => {
    setFilters((f) => ({
      ...f,
      [key]: f[key].includes(value) ? f[key].filter((v) => v !== value) : [...f[key], value],
    }));
    setPage(1);
  };

  const resetFilters = () => {
    setFilters({ main_category: [], sub_category: [], sub_detail_category: [], rack: [], item_status: [] });
    setRange({ from: "", to: "" });
    setSearch("");
    setPage(1);
  };

  const applyRange = (next: StockRange) => {
    setRange(next);
    setPage(1);
  };

  const activeCount =
    Object.values(filters).reduce((n, arr) => n + arr.length, 0) +
    (range.from || range.to ? 1 : 0);

  // The export mirrors the search and status facets shown on screen.
  const exportQuery = new URLSearchParams([
    ...(search ? [["search", search]] : []),
    ...filters.item_status.map((s) => ["status", s] as [string, string]),
  ]).toString();
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // ---------- form ----------
  const set = (key: keyof typeof EMPTY_ITEM, value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const subOptions = useMemo(
    () => toOptions(lookups.subCategories.filter((s) => s.parentId === form.main_product_id)),
    [lookups.subCategories, form.main_product_id],
  );
  const detailOptions = useMemo(
    () => toOptions(lookups.detailCategories.filter((d) => d.parentId === form.sub_category_id)),
    [lookups.detailCategories, form.sub_category_id],
  );

  const nextCode = useNextItemCode(
    isOpen && !editing ? form.sub_category_id : "",
    form.sub_detail_category_id,
  );

  const openNew = () => {
    setEditing(null);
    setForm({ ...EMPTY_ITEM });
    setImageFile(null);
    setImageUrl(null);
    setDropImage(false);
    setFormError(null);
    setOpen(true);
  };
  const openEdit = (item: Item) => {
    setEditing(item);
    setImageFile(null);
    setImageUrl(item.image_url);
    setDropImage(false);
    setForm({
      item_code: item.item_code,
      description: item.description,
      main_product_id: item.main_product_id ?? "",
      sub_category_id: item.sub_category_id ?? "",
      sub_detail_category_id: item.sub_detail_category_id ?? "",
      rack_id: item.rack_id ?? "",
      location_id: item.location_id ?? "",
      uom: item.uom ?? "",
      market_name: "", market_uom: "",
      sku: item.sku ?? "",
      barcode: item.barcode ?? "",
      item_status: item.item_status,
      currency: item.currency ?? "",
      price: item.price != null ? String(item.price) : "",
      min_level: "", max_level: "", re_order_qty: "",
    });
    setFormError(null);
    setOpen(true);
  };

  const save = async () => {
    if (!form.main_product_id) { setFormError("Product Main Category is required."); return; }
    if (!form.sub_category_id) { setFormError("Product Sub Category is required."); return; }
    if (!form.description.trim()) { setFormError("Description is required."); return; }

    setSaving(true); setFormError(null);
    const num = (v: string) => (v.trim() === "" ? null : Number(v));
    try {
      const body = {
        // No item_code: the server allocates it on create and keeps the
        // existing one on edit. Sending a guess would only be ignored.
        description: form.description.trim(),
        main_product_id: form.main_product_id || null,
        sub_category_id: form.sub_category_id || null,
        sub_detail_category_id: form.sub_detail_category_id || null,
        rack_id: form.rack_id || null,
        location_id: form.location_id || null,
        uom: form.uom.trim() || null,
        market_name: form.market_name.trim() || null,
        market_uom: form.market_uom.trim() || null,
        sku: form.sku.trim() || null,
        barcode: form.barcode.trim() || null,
        item_status: form.item_status,
        currency: form.currency.trim() || null,
        price: num(form.price),
        min_level: num(form.min_level),
        max_level: num(form.max_level),
        re_order_qty: num(form.re_order_qty),
        uom_conversions: [],
      } as Record<string, unknown>;
      if (editing) {
        // The edit form does not load these, so a blank one means "not touched":
        // leave the product's stored value alone rather than clearing it.
        for (const k of ["market_name", "market_uom", "min_level", "max_level", "re_order_qty"] as const) {
          if (form[k].trim() === "") delete body[k];
        }
        delete body.uom_conversions;
      }
      // The record has to exist before a file can belong to it, so a new
      // product is created first and its picture uploaded second.
      let itemId = editing?.id;
      if (editing) {
        await api.put(`/inventory/items/${editing.id}`, body);
      } else {
        const created = await api.post<{ id: string }>("/inventory/items", body);
        itemId = created.id;
      }

      if (itemId && imageFile) {
        await api.upload(`/inventory/items/${itemId}/image`, imageFile);
      } else if (itemId && dropImage) {
        await api.del(`/inventory/items/${itemId}/image`);
      }

      setOpen(false);
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the product.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell title="Product Details">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="m-0 text-[19px] font-semibold">Products Details</h1>
        <div className="ml-auto flex items-center gap-2.5">
          {activeCount > 0 && (
            <button
              onClick={resetFilters}
              className="flex items-center gap-1.5 rounded-lg bg-hover px-3.5 py-2
                         text-[12.8px] font-medium text-muted"
            >
              <RotateCcw size={14} /> Reset ({activeCount})
            </button>
          )}
          <GridActions state={actions} pageSize={PAGE_SIZE} onPageSize={(n) => { setPageSize(n); setPage(1); }} />
          <DownloadMenu dataset="items" query={exportQuery} />
          <button
            onClick={openNew}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-primary
                       to-primary-dark px-3.5 py-2 text-[12.8px] font-medium text-on-primary"
          >
            <Plus size={14} strokeWidth={2.4} /> Add Product
          </button>
        </div>
      </div>

      <div className="grid grid-cols-[250px_1fr] gap-[18px] max-[1100px]:grid-cols-1">
        {/* ---------- filter panel ---------- */}
        <aside className="rounded-[14px] border border-line bg-surface p-4 shadow-panel
                          max-[1100px]:order-2">
          <div className="mb-4 flex items-center gap-2 rounded-full border border-line bg-bg px-3.5 py-2">
            <Search size={14} className="text-faint" />
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder="Search products…"
              className="w-full border-none bg-transparent text-[12.8px] outline-none placeholder:text-faint"
            />
          </div>

          <RangeFilter applied={range} onApply={applyRange} />

          {!facets && <p className="text-[12px] text-faint">Loading filters…</p>}

          {facets && (
            <>
              <FacetGroup title="Main Category" buckets={facets.main_categories}
                selected={filters.main_category} onToggle={(v) => toggleFilter("main_category", v)} />
              <FacetGroup title="Sub Category" buckets={facets.sub_categories}
                selected={filters.sub_category} onToggle={(v) => toggleFilter("sub_category", v)} />
              <FacetGroup title="Sub Dtl Category" buckets={facets.sub_detail_categories}
                selected={filters.sub_detail_category} onToggle={(v) => toggleFilter("sub_detail_category", v)} />
              <FacetGroup title="Racks" buckets={facets.racks}
                selected={filters.rack} onToggle={(v) => toggleFilter("rack", v)} />
              <FacetGroup title="Item Status" buckets={facets.item_statuses}
                selected={filters.item_status} onToggle={(v) => toggleFilter("item_status", v)} />
            </>
          )}
        </aside>

        {/* ---------- results ---------- */}
        <div className="max-[1100px]:order-1">
          {error && (
            <p className="mb-4 rounded-lg bg-rose/10 px-4 py-3 text-[12.8px] text-rose">{error}</p>
          )}

          <p className="mb-3 text-[12.5px] text-muted">
            {loading ? "Loading…" : `${total.toLocaleString()} product${total === 1 ? "" : "s"}`}
            {!loading && shown.length !== items.length && ` · ${shown.length.toLocaleString()} shown after the Actions filters`}
          </p>
          <div className="mb-3 overflow-hidden rounded-[12px] border border-line bg-surface empty:hidden">
            <GridActionChips state={actions} />
            <GridActionView state={actions} rows={shown} total={total} />
          </div>

          {/* Only the very first load blanks the page. A refresh after an
              opening or an adjustment leaves the cards where they are — they
              host the action dialogs, and unmounting them closes one mid-use. */}
          {loading && items.length === 0 && (
            <div className="flex justify-center py-20">
              <Loader2 size={22} className="animate-spin text-primary" />
            </div>
          )}

          {!loading && items.length === 0 && (
            <div className="rounded-[14px] border border-line bg-surface p-12 text-center
                            text-[12.8px] text-faint shadow-panel">
              No products match these filters. Import the legacy data with{" "}
              <code className="text-primary">python -m app.inventory.import_legacy</code>, or add one.
            </div>
          )}

          {items.length > 0 && (
            <div className={`grid grid-cols-4 gap-[14px] transition-opacity max-[1500px]:grid-cols-3
                            max-[900px]:grid-cols-2 max-[520px]:grid-cols-1
                            ${loading ? "opacity-60" : ""}`}>
              {shown.map((item, index) => (
                <Fragment key={item.id}>
                {actions.breakBefore(shown, index) && (
                  <h4 className="col-span-full m-0 mt-1 rounded-lg bg-primary/10 px-3 py-2 text-[12.5px] font-semibold text-primary">
                    {actions.breakBefore(shown, index)}</h4>
                )}
                <article
                  style={actions.rowStyle(item)}
                  className="flex flex-col rounded-[12px] border border-line bg-surface p-3.5
                             shadow-panel transition-[border-color,transform] hover:-translate-y-0.5
                             hover:border-primary"
                >
                  <h3 className="m-0 mb-1 line-clamp-3 min-h-[3.4em] text-[12.5px] font-semibold uppercase leading-snug">
                    {item.description}
                  </h3>
                  <p className="m-0 mb-2.5 text-[11px] text-faint">{item.uom ?? "—"}</p>

                  {/* The picture fills the card's width (owner, 19-Oct-2026: it was too small). */}
                  <div className="mb-2.5 flex h-44 items-center justify-center overflow-hidden rounded-lg bg-hover">
                    {item.image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={item.image_url} alt="" className="h-full w-full rounded-lg object-contain" />
                    ) : (
                      <Package size={40} strokeWidth={1.4} className="text-faint" />
                    )}
                  </div>

                  <div className="mb-1 flex items-baseline justify-between gap-2">
                    <p className={`m-0 text-[11.5px] font-semibold
                                   ${item.opening_stock > 0 ? "text-success" : "text-rose"}`}>
                      Stock-{item.opening_stock ?? 0}
                    </p>
                    {/* The product's price, opposite the stock, as set on the product. */}
                    {item.price != null ? (
                      <p className="m-0 truncate text-[10.5px] font-medium tabular-nums text-[#222] dark:text-text" title="Price">
                        {item.currency || "PKR"}{" "}
                        {Number(item.price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </p>
                    ) : (
                      <p className="m-0 text-[11px] text-faint">No price</p>
                    )}
                  </div>
                  {/* SKU is the number staff quote day to day; the 12-digit
                      detail code stays in the tooltip and the search index. */}
                  <p
                    className="m-0 mb-3 truncate text-[11px] text-muted"
                    title={`SKU ${item.sku ?? "—"} · Code ${item.item_code}`}
                  >
                    {item.sku ?? <span className="text-faint">No SKU</span>}
                  </p>

                  <ItemActions
                    item={{
                      id: item.id,
                      item_code: item.item_code,
                      description: item.description,
                      uom: item.uom,
                      currency: item.currency,
                      price: item.price,
                      location_id: item.location_id,
                    }}
                    locations={locationOptions}
                    onEdit={() => openEdit(item)}
                    onChanged={load}
                  />
                </article>
                </Fragment>
              ))}
            </div>
          )}

          {items.length > 0 && total > PAGE_SIZE && (
            <div className="mt-5 flex items-center justify-center gap-2 text-[12.3px] text-muted">
              <button
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40"
              >
                Previous
              </button>
              <span className="px-2">Page {page} of {pages}</span>
              <button
                disabled={page >= pages}
                onClick={() => setPage(page + 1)}
                className="rounded-lg bg-hover px-3 py-1.5 font-medium disabled:opacity-40"
              >
                Next
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ---------- item form ---------- */}
      <Modal
        title="Inventory Items" open={isOpen} saving={saving} error={formError} width="lg"
        onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? "Update" : "Create"}
      >
        <div className="grid grid-cols-3 gap-4 max-sm:grid-cols-1">
          <Field label="Product Main Category" required>
            <Select value={form.main_product_id} options={toOptions(lookups.mainProducts)}
              onChange={(e) => {
                set("main_product_id", e.target.value);
                set("sub_category_id", "");
                set("sub_detail_category_id", "");
              }} />
          </Field>
          <Field label="Product Sub Category" required>
            <Select value={form.sub_category_id} options={subOptions}
              disabled={!form.main_product_id}
              placeholder={form.main_product_id ? "Select…" : "Choose a main category first"}
              onChange={(e) => { set("sub_category_id", e.target.value); set("sub_detail_category_id", ""); }} />
          </Field>
          <Field label="Product Family">
            <Select value={form.sub_detail_category_id} options={detailOptions}
              disabled={!form.sub_category_id}
              placeholder={form.sub_category_id ? "Select…" : "Choose a sub category first"}
              onChange={(e) => set("sub_detail_category_id", e.target.value)} />
          </Field>

          <Field label="Product Detail Code">
            {/* Given by the system, never typed: the 12 digits are the sub
                category's code, the family's block and the product's number
                within it. On an existing product it is fixed — documents,
                barcodes and the old reports all quote it. */}
            <CodeField
              value={editing ? form.item_code : nextCode.code}
              state={editing ? "fixed" : nextCode.state}
              message={nextCode.message}
            />
          </Field>
          <Field label="Rack Name">
            <Combobox value={form.rack_id} options={toOptions(lookups.racks)}
              placeholder="Type a rack name or pick from the list…"
              emptyMessage="No rack matches that name."
              onChange={(v) => set("rack_id", v)} />
          </Field>
          <Field label="Location">
            {/* A real link to Item Locations: the item stores location_id. */}
            <Combobox value={form.location_id} options={toOptions(lookups.locations)}
              placeholder="Type a location or pick from the list…"
              emptyMessage="No location matches that name."
              onChange={(v) => set("location_id", v)} />
          </Field>
          <Field label="Status">
            <Select value={form.item_status}
              options={[{ value: "ACTIVE", label: "ACTIVE" }, { value: "INACTIVE", label: "INACTIVE" }]}
              placeholder="ACTIVE"
              onChange={(e) => set("item_status", e.target.value)} />
          </Field>

          <div className="col-span-3 max-sm:col-span-1">
            <Field label="Description" required>
              <TextArea value={form.description} onChange={(e) => set("description", e.target.value)} rows={2} />
            </Field>
          </div>

          <Field label="Uom">
            <UomPicker value={form.uom} uoms={lookups.uoms}
              onChange={(v) => set("uom", v)} />
          </Field>
          <Field label="SKU">
            <TextInput value={form.sku} onChange={(e) => set("sku", e.target.value)} />
          </Field>
          <Field label="Barcode #">
            <TextInput value={form.barcode} onChange={(e) => set("barcode", e.target.value)} />
          </Field>

          <Field label="Market Name">
            <TextInput value={form.market_name} onChange={(e) => set("market_name", e.target.value)} />
          </Field>
          <Field label="Mkt Uom">
            {/* The unit the market quotes this in, which is not always the
                unit it is stocked in. */}
            <UomPicker value={form.market_uom} uoms={lookups.uoms}
              placeholder="Same as Uom"
              onChange={(v) => set("market_uom", v)} />
          </Field>
          <Field label="Currency">
            <TextInput value={form.currency} onChange={(e) => set("currency", e.target.value)} placeholder="PKR" />
          </Field>

          <Field label="Price">
            <TextInput type="number" step="0.01" value={form.price} onChange={(e) => set("price", e.target.value)} />
          </Field>
          <Field label="Minlevel">
            <TextInput type="number" step="0.01" value={form.min_level} onChange={(e) => set("min_level", e.target.value)} />
          </Field>
          <Field label="Maxlevel">
            <TextInput type="number" step="0.01" value={form.max_level} onChange={(e) => set("max_level", e.target.value)} />
          </Field>

          <Field label="Re Order Qty">
            <TextInput type="number" step="0.01" value={form.re_order_qty}
              onChange={(e) => set("re_order_qty", e.target.value)} />
          </Field>
        </div>

        <div className="mt-5 border-t border-line pt-4">
          <Field label="Product Image">
            <ImagePicker
              file={imageFile}
              currentUrl={dropImage ? null : imageUrl}
              onPick={(f) => { setImageFile(f); setDropImage(false); }}
              onRemove={() => { setImageFile(null); setDropImage(true); }}
            />
          </Field>
          {!editing && (
            <p className="mt-2 text-[11.5px] text-faint">
              The picture uploads once the product has been created.
            </p>
          )}
        </div>

        <p className="mt-4 border-t border-line pt-4 text-[11.5px] text-faint">
          The Conversions Uoms grid is stored by the API but has no UI yet.
        </p>
      </Modal>
    </AppShell>
  );
}

type CodeState = "idle" | "loading" | "ready" | "error" | "fixed";

/**
 * The code the product being added will be given.
 *
 * Asked of the server rather than worked out here: the rule reads the codes
 * already in use, and only the server can see them all. It is a preview —
 * nothing is reserved — so the code is allocated again on save, and two
 * people adding products at the same moment still get different numbers.
 */
function useNextItemCode(subCategoryId: string, familyId: string) {
  const [state, setState] = useState<{ code: string; state: CodeState; message: string }>({
    code: "", state: "idle", message: "Choose a Product Sub Category first.",
  });

  useEffect(() => {
    if (!subCategoryId) {
      setState({ code: "", state: "idle",
                 message: "Choose a Product Sub Category first." });
      return;
    }
    let live = true;
    setState((s) => ({ ...s, state: "loading", message: "Allocating…" }));
    const qs = new URLSearchParams({ sub_category_id: subCategoryId });
    if (familyId) qs.set("sub_detail_category_id", familyId);

    api.get<{ item_code: string }>(`/inventory/items/next-code?${qs}`)
      .then((d) => live && setState({
        code: d.item_code, state: "ready",
        message: "Given by the system when this product is created.",
      }))
      .catch((err) => live && setState({
        code: "", state: "error",
        message: err instanceof Error ? err.message : "Could not work out a code.",
      }));
    return () => { live = false; };
  }, [subCategoryId, familyId]);

  return state;
}

/** The code, shown but not typeable. */
function CodeField({ value, state, message }: {
  value: string; state: CodeState; message?: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 rounded-lg border border-line bg-hover px-3.5 py-2.5">
        {state === "loading" && <Loader2 size={13} className="animate-spin text-primary" />}
        <span className={`text-[13px] tabular-nums ${value ? "font-medium" : "text-faint"}`}>
          {value || (state === "loading" ? "…" : "—")}
        </span>
        {state === "fixed" && (
          <span className="ml-auto text-[10.5px] text-faint">cannot be changed</span>
        )}
      </div>
      {message && (
        <p className={`mt-1 text-[10.5px] ${state === "error" ? "text-rose" : "text-faint"}`}>
          {state === "fixed"
            ? "Documents and barcodes quote this code, so it stays as issued."
            : message}
        </p>
      )}
    </div>
  );
}

/**
 * "Show products with stock 1 to 500" — filters on the quantity shown on
 * each card, so `Stock-0` rows drop out as soon as the lower bound is 1.
 *
 * Either side may be left blank: "from 1" alone is everything in stock,
 * "to 0" alone is everything out of stock. Bounds apply on Apply or Enter
 * rather than per keystroke, since a half-typed "50" would otherwise fire a
 * request for the wrong range.
 */
function RangeFilter({
  applied, onApply,
}: {
  applied: StockRange;
  onApply: (range: StockRange) => void;
}) {
  const [from, setFrom] = useState(applied.from);
  const [to, setTo] = useState(applied.to);

  // Follow the applied range when Reset clears it from outside.
  useEffect(() => { setFrom(applied.from); setTo(applied.to); }, [applied.from, applied.to]);

  const dirty = from !== applied.from || to !== applied.to;
  const isSet = applied.from !== "" || applied.to !== "";

  const apply = () => onApply({ from: from.trim(), to: to.trim() });

  return (
    <div className="mb-5 border-b border-line pb-4">
      <h3 className="m-0 mb-2.5 text-[12.8px] font-semibold">Stock Quantity</h3>

      <div className="flex items-center gap-1.5">
        <input
          type="number" min={0} value={from} placeholder="min"
          onChange={(e) => setFrom(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && apply()}
          aria-label="Minimum stock"
          className="w-full rounded-lg border border-line bg-bg px-2.5 py-1.5 text-[12px]
                     outline-none transition-colors focus:border-primary"
        />
        <span className="text-[11.5px] text-faint">to</span>
        <input
          type="number" min={0} value={to} placeholder="max"
          onChange={(e) => setTo(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && apply()}
          aria-label="Maximum stock"
          className="w-full rounded-lg border border-line bg-bg px-2.5 py-1.5 text-[12px]
                     outline-none transition-colors focus:border-primary"
        />
      </div>

      <div className="mt-2 flex items-center gap-1.5">
        <button
          onClick={apply}
          disabled={!dirty}
          className="rounded-lg bg-primary/10 px-3 py-1.5 text-[11.5px] font-medium
                     text-primary transition-opacity disabled:opacity-40"
        >
          Apply
        </button>
        {isSet && (
          <button
            onClick={() => onApply({ from: "", to: "" })}
            className="rounded-lg bg-hover px-3 py-1.5 text-[11.5px] font-medium text-muted"
          >
            Clear
          </button>
        )}
      </div>

      {isSet && (
        <p className="mt-2 text-[11.5px] text-muted">
          {applied.from && applied.to
            ? `Stock between ${applied.from} and ${applied.to}.`
            : applied.from
              ? `Stock of ${applied.from} or more.`
              : `Stock of ${applied.to} or less.`}
        </p>
      )}
    </div>
  );
}

/** Product photo chooser: preview, replace, remove. */
function ImagePicker({
  file, currentUrl, onPick, onRemove,
}: {
  file: File | null;
  currentUrl: string | null;
  onPick: (file: File | null) => void;
  onRemove: () => void;
}) {
  // Object URLs are revoked when the chosen file changes or the form closes,
  // so previewing several pictures in a row does not leak them.
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const shown = preview ?? currentUrl;

  return (
    <div className="flex items-center gap-4">
      <div className="flex h-24 w-24 flex-shrink-0 items-center justify-center overflow-hidden
                      rounded-lg border border-line bg-hover">
        {shown ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={shown} alt="" className="max-h-full max-w-full object-contain" />
        ) : (
          <Package size={26} strokeWidth={1.4} className="text-faint" />
        )}
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <label
            className="flex cursor-pointer items-center gap-1.5 rounded-lg bg-hover px-3 py-2
                       text-[12px] font-medium text-muted transition-colors
                       hover:bg-primary/10 hover:text-primary"
          >
            <Upload size={13} />
            {shown ? "Replace" : "Choose image"}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(e) => {
                onPick(e.target.files?.[0] ?? null);
                // Clear the input so choosing the same file again after a
                // Remove still fires a change event.
                e.target.value = "";
              }}
              className="hidden"
            />
          </label>

          {shown && (
            <button
              type="button"
              onClick={onRemove}
              className="flex items-center gap-1.5 rounded-lg bg-hover px-3 py-2 text-[12px]
                         font-medium text-muted transition-colors hover:bg-rose/10 hover:text-rose"
            >
              <Trash2 size={13} /> Remove
            </button>
          )}
        </div>

        <p className="mt-1.5 text-[11px] text-faint">
          {file ? file.name : "JPEG, PNG or WebP."}
        </p>
      </div>
    </div>
  );
}

function FacetGroup({
  title, buckets, selected, onToggle,
}: {
  title: string;
  buckets: Bucket[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  if (buckets.length === 0) return null;
  const visible = showAll ? buckets : buckets.slice(0, 7);

  return (
    <div className="mb-5 border-b border-line pb-4 last:mb-0 last:border-0 last:pb-0">
      <h3 className="m-0 mb-2.5 text-[12.8px] font-semibold">{title}</h3>
      <div className="space-y-1.5">
        {visible.map((b) => (
          <label
            key={b.id ?? b.label}
            className="flex cursor-pointer items-start gap-2 text-[11.8px] leading-snug text-muted"
          >
            <input
              type="checkbox"
              checked={selected.includes(b.id ?? "")}
              onChange={() => onToggle(b.id ?? "")}
              className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 accent-[--primary]"
            />
            <span className="min-w-0 flex-1">
              {b.label} <span className="text-faint">({b.count.toLocaleString()})</span>
            </span>
          </label>
        ))}
      </div>
      {buckets.length > 7 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="mt-2 text-[11.5px] font-medium text-primary"
        >
          {showAll ? "Show less" : `Show all (${buckets.length})`}
        </button>
      )}
    </div>
  );
}
