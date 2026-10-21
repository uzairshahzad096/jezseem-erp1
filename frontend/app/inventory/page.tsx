"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { NAV_MODULES } from "@/lib/navigation";

/** Inventory landing page — lists the four sub-modules and their screens. */
export default function InventoryPage() {
  const inventory = NAV_MODULES.find((m) => m.key === "inventory")!;

  return (
    <AppShell title="Inventory">
      <h1 className="mb-5 text-[19px] font-semibold">Inventory</h1>

      <div className="grid grid-cols-2 gap-[18px] max-[900px]:grid-cols-1">
        {inventory.children.map((group) => (
          <section key={group.href} className="rounded-[14px] border border-line bg-surface shadow-panel">
            <h2 className="m-0 border-b border-line px-5 py-4 text-[15px] font-semibold">
              {group.label}
            </h2>
            {group.children ? (
              <div>
                {group.children.map((leaf) => (
                  <Link
                    key={leaf.href}
                    href={leaf.href}
                    className="flex items-center gap-2 border-b border-line px-5 py-3 text-[13px]
                               transition-colors last:border-0 hover:bg-hover hover:text-primary"
                  >
                    <span className="flex-1">{leaf.label}</span>
                    <ChevronRight size={14} className="text-faint" />
                  </Link>
                ))}
              </div>
            ) : (
              <p className="m-0 px-5 py-8 text-center text-[12.5px] text-faint">
                Screens for this sub-module have not been documented yet.
              </p>
            )}
          </section>
        ))}
      </div>
    </AppShell>
  );
}
