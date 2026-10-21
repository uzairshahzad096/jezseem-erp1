"use client";

import Link from "next/link";
import { Info } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";

/**
 * Material Receiving Note
 *
 * The database tables and REST endpoints for this module exist (see
 * app/procurement/models.py). The listing and form screens are the
 * next piece of work — nothing is stubbed here so the UI cannot imply
 * functionality that is not wired up.
 */
export default function Page() {
  return (
    <AppShell title="Material Receiving Note">
      <h1 className="mb-3 text-[19px] font-semibold">Material Receiving Note</h1>
      <div className="rounded-[14px] border border-line bg-surface p-8 shadow-panel">
        <div className="mb-3 flex items-center gap-2 text-primary">
          <Info size={16} />
          <p className="m-0 text-[13px] font-semibold">Screens coming next</p>
        </div>
        <p className="m-0 mb-4 max-w-2xl text-[12.8px] leading-relaxed text-muted">
          The material_receiving_notes and mrn_lines tables are in place, tracking ordered, received and remaining quantity against each purchase order line. Posting an MRN will write inward stock ledger entries. The listing, the convert-from-purchase-order flow and the MRN document follow next.
        </p>
        <p className="m-0 text-[12.5px] text-faint">
          The API is live at <code className="text-primary">/api/v1/procurement/mrn</code> and visible in the{" "}
          <Link href="http://localhost:8000/api/docs" className="text-primary underline">
            OpenAPI docs
          </Link>.
        </p>
      </div>
    </AppShell>
  );
}
