"use client";

import { Combobox } from "@/components/ui/Modal";
import type { UomLookup } from "@/lib/useLookups";

/**
 * Type or pick a unit of measure.
 *
 * The list reads "PCS — Pieces" like the old ERP's UOM lookup, so searching
 * works on either the code or the word; the box shows only the code, which
 * is what goes on the document. Free text is still accepted, because a
 * one-off unit on a single purchase should not require a master-data change
 * first — but the common case now comes from the list, which is what stops
 * "Pcs", "PCS" and "pieces" becoming three units in a report.
 */
export function UomPicker({
  value, uoms, onChange, disabled, placeholder = "PCS",
}: {
  value: string | null | undefined;
  uoms: UomLookup[];
  onChange: (code: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  return (
    <Combobox
      value={value ?? ""}
      options={uomOptions(uoms)}
      allowCustom
      disabled={disabled}
      placeholder={placeholder}
      emptyMessage="Not a listed unit — it will be saved as typed. Add it on Units of Measure to offer it everywhere."
      // Units are codes, so a stray lower-case entry would read as a
      // different unit from the same one typed properly.
      onChange={(v) => onChange(v.toUpperCase())}
    />
  );
}

/** Options for a UOM picker: code in the box, code and meaning in the list. */
export function uomOptions(uoms: UomLookup[]) {
  return uoms.map((u) => ({
    value: u.code,
    short: u.code,
    label: u.description && u.description !== u.code
      ? `${u.code} — ${u.description}`
      : u.code,
  }));
}
