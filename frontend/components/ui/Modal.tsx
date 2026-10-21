"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, Loader2, ChevronDown, Trash2 } from "lucide-react";

interface ModalProps {
  title: string;
  open: boolean;
  saving?: boolean;
  error?: string | null;
  width?: "sm" | "md" | "lg" | "xl";
  onClose: () => void;
  /** Omit for a read-only modal: the Save button disappears and Cancel
   *  becomes Close. */
  onSave?: () => void;
  saveLabel?: string;
  /** A second action beside Save, e.g. save as draft next to save-and-post. */
  onAlt?: () => void;
  altLabel?: string;
  /** Destructive action, shown apart from the others on the left. */
  onDelete?: () => void;
  deleteLabel?: string;
  children: React.ReactNode;
}

// xl is for the sales document forms, whose line grid carries fourteen
// columns and needs the full width of the screen to stay typeable.
const WIDTH = { sm: "max-w-md", md: "max-w-2xl", lg: "max-w-5xl", xl: "max-w-[1600px]" };

export function Modal({
  title, open, saving, error, width = "sm", onClose, onSave, saveLabel = "Save",
  onAlt, altLabel, onDelete, deleteLabel, children,
}: ModalProps) {
  // Rendered into <body>, never where it was written. A `fixed` element is
  // positioned against the nearest ancestor carrying a transform, and the
  // product cards lift on hover — a dialog opened from one was being confined
  // to the card, then thrown back to full screen as the pointer left it.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Hold the page still underneath, so a long form does not scroll the list
  // behind it and lose the reader's place.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [open]);

  if (!open || !mounted) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 py-10">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${WIDTH[width]} rounded-[14px] border border-line bg-surface shadow-xl`}
      >
        <div className="flex items-center gap-3 border-b border-line px-5 py-4">
          <h3 className="m-0 text-[15px] font-semibold">{title}</h3>
          <button
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded-md p-1.5 text-muted transition-colors hover:bg-hover hover:text-text"
          >
            <X size={17} />
          </button>
        </div>

        <div className="px-5 py-5">
          {error && (
            <p className="mb-4 rounded-lg bg-rose/10 px-3.5 py-2.5 text-[12.5px] text-rose">{error}</p>
          )}
          {children}
        </div>

        <div className="flex items-center gap-2.5 border-t border-line px-5 py-4">
          {onDelete && (
            // Kept to the left, away from Save, so it is not hit by accident.
            <button
              onClick={onDelete}
              disabled={saving}
              className="mr-auto flex items-center gap-1.5 rounded-lg bg-rose/10 px-4 py-2
                         text-[12.8px] font-medium text-rose transition-colors
                         hover:bg-rose/20 disabled:opacity-50"
            >
              <Trash2 size={14} />
              {deleteLabel ?? "Delete"}
            </button>
          )}
          <button
            onClick={onClose}
            className="ml-auto rounded-lg bg-hover px-4 py-2 text-[12.8px] font-medium text-muted"
          >
            {onSave ? "Cancel" : "Close"}
          </button>
          {onAlt && (
            <button
              onClick={onAlt}
              disabled={saving}
              className="rounded-lg bg-text/80 px-4 py-2 text-[12.8px] font-medium text-surface
                         transition-opacity hover:bg-text disabled:opacity-50"
            >
              {altLabel ?? "Save"}
            </button>
          )}
          {onSave && (
            <button
              onClick={onSave}
              disabled={saving}
              className="flex items-center gap-2 rounded-lg bg-gradient-to-br from-primary
                         to-primary-dark px-4 py-2 text-[12.8px] font-medium text-on-primary
                         transition-opacity disabled:opacity-50"
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {saveLabel}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ---------- form field primitives ----------

export function Field({
  label, required, children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11.5px] font-medium text-muted">
        {label} {required && <span className="text-rose">*</span>}
      </span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-line bg-bg px-3.5 py-2.5 text-[13px] outline-none " +
  "transition-colors focus:border-primary disabled:opacity-60";

// `className` is merged rather than overwritten: spreading props first and
// then setting className made every caller's class silently do nothing, so a
// validation border or a width could not be added from outside.
export function TextInput(
  { className = "", ...props }: React.InputHTMLAttributes<HTMLInputElement>,
) {
  return <input {...props} className={`${inputClass} ${className}`} />;
}

export function TextArea(
  { className = "", ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>,
) {
  return <textarea rows={3} {...props} className={`${inputClass} resize-y ${className}`} />;
}

export function Select({
  options, placeholder, className = "", ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & {
  options: { value: string; label: string }[];
  placeholder?: string;
}) {
  return (
    <select {...props} className={`${inputClass} ${className}`}>
      <option value="">{placeholder ?? "Select…"}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

/**
 * Type-to-search dropdown for lists too long to scroll — racks, say, where
 * a plain <select> means hunting through hundreds of entries. Typing filters;
 * clicking the chevron shows everything. The value stored is still the id.
 */
export function Combobox({
  value, options, onChange, placeholder, disabled, emptyMessage, allowCustom,
}: {
  value: string;
  /** `short` is what the closed box shows when this option is picked. Without
   *  it the box shows the full label, which is right for a rack or a location
   *  but not for something like a currency, where the list wants to read
   *  "$  USD — US Dollar" and the box only "USD". */
  options: { value: string; label: string; short?: string }[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  emptyMessage?: string;
  /** Accept text that matches no option, storing what was typed. For a field
   *  whose column holds the text itself rather than an id — so a value from
   *  before the list existed still shows, and a one-off can still be typed. */
  allowCustom?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  // Whether the query is something the user typed, or just the current value
  // sitting in the box. Filtering on the latter would open the list showing
  // only what is already chosen.
  const [typed, setTyped] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  // Where the list should be drawn. It is rendered into <body> rather than
  // beside the input, because inside a scrolling table an absolutely
  // positioned list is clipped by the container and only its first row shows.
  const [box, setBox] = useState<{ left: number; top: number; width: number } | null>(null);

  const selected = options.find((o) => o.value === value);
  // With free text allowed, an unmatched value is still worth showing.
  const display = selected ? (selected.short ?? selected.label) : (allowCustom ? value : "");

  // Close on an outside click, so the list cannot sit over the rest of the form.
  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as Node;
      // The list lives in <body> now, so it is not inside the wrapper —
      // without checking it too, clicking an option would close the list
      // before the click landed on it.
      const inside = wrapper.current?.contains(target) || listRef.current?.contains(target);
      if (!inside) {
        setOpen(false);
        setQuery("");
        setTyped(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  // Follow the input: a fixed list would otherwise stay put while the table
  // beneath it scrolls away.
  useEffect(() => {
    if (!open) { setBox(null); return; }
    const place = () => {
      const rect = wrapper.current?.getBoundingClientRect();
      if (rect) setBox({ left: rect.left, top: rect.bottom + 4, width: rect.width });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  const needle = typed ? query.trim().toLowerCase() : "";
  const matches = needle
    ? options.filter((o) =>
        o.label.toLowerCase().includes(needle) || o.value.toLowerCase().includes(needle))
    : options;

  const choose = (next: string) => {
    onChange(next);
    setQuery("");
    setTyped(false);
    setOpen(false);
  };

  return (
    <div ref={wrapper} className="relative">
      <div className="relative">
        <input
          // While the list is open the box belongs to the search text; closed,
          // it shows what is actually selected.
          value={open ? query : display}
          onChange={(e) => {
            setQuery(e.target.value);
            setTyped(true);
            setOpen(true);
            // Typing is the value when free text is allowed, so nothing is
            // lost if the box is left without picking from the list.
            if (allowCustom) onChange(e.target.value);
          }}
          // Editing starts from the stored value, not from the descriptive
          // label — with free text allowed, whatever is in the box can end up
          // being what is saved.
          onFocus={() => { setQuery(allowCustom ? value : ""); setTyped(false); setOpen(true); }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && matches.length > 0) {
              e.preventDefault();
              choose(matches[0].value);
            }
            if (e.key === "Escape") { setOpen(false); setQuery(""); setTyped(false); }
          }}
          disabled={disabled}
          placeholder={placeholder ?? "Type to search or pick from the list…"}
          className={`${inputClass} pr-16`}
        />
        <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-0.5">
          {value && !disabled && (
            <button
              type="button"
              onClick={() => choose("")}
              aria-label="Clear"
              className="rounded p-1 text-muted transition-colors hover:bg-hover hover:text-text"
            >
              <X size={13} />
            </button>
          )}
          <button
            type="button"
            onClick={() => { setQuery(""); setTyped(false); setOpen((v) => !v); }}
            disabled={disabled}
            aria-label="Show all"
            className="rounded p-1 text-muted transition-colors hover:bg-hover hover:text-text"
          >
            <ChevronDown size={14} />
          </button>
        </div>
      </div>

      {open && box && createPortal(
        <ul
          ref={listRef}
          role="listbox"
          style={{ left: box.left, top: box.top, width: Math.max(box.width, 180) }}
          // Above the modal it is opened from, and never clipped by a table.
          className="fixed z-[70] max-h-56 list-none overflow-y-auto rounded-lg
                     border border-line bg-surface p-1 shadow-xl"
        >
          {matches.length === 0 && (
            <li className="px-3 py-2 text-[12px] text-faint">
              {emptyMessage ?? "No match."}
            </li>
          )}
          {matches.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                role="option"
                aria-selected={o.value === value}
                onClick={() => choose(o.value)}
                className={`w-full rounded-md px-3 py-2 text-left text-[12.8px] transition-colors
                            hover:bg-primary/10 hover:text-primary
                            ${o.value === value ? "bg-primary/10 font-medium text-primary" : ""}`}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>,
        document.body,
      )}
    </div>
  );
}

export function Toggle({
  checked, onChange, label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <div>
      <span className="mb-1.5 block text-[11.5px] font-medium text-muted">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 rounded-full transition-colors
                    ${checked ? "bg-primary" : "bg-line"}`}
      >
        <span
          className={`absolute left-0 top-0.5 h-5 w-5 rounded-full bg-white transition-transform
                      ${checked ? "translate-x-[22px]" : "translate-x-0.5"}`}
        />
      </button>
    </div>
  );
}
