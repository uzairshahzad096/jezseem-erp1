"use client";

import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Topbar } from "@/components/layout/Topbar";
import { useTheme } from "@/lib/useTheme";

/** Sidebar + top bar wrapper shared by every page inside the ERP. */
export function AppShell({
  title, children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const { toggle } = useTheme();
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="min-h-screen bg-bg text-text">
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      {navOpen && (
        <div onClick={() => setNavOpen(false)} className="fixed inset-0 z-35 bg-black/40 lg:hidden" />
      )}
      <Topbar
        title={title}
        userName="Admin"
        userInitials="AD"
        onToggleNav={() => setNavOpen((v) => !v)}
        onToggleTheme={toggle}
      />
      <main className="px-6 pb-9 pt-[86px] lg:ml-62 max-sm:px-4">{children}</main>
    </div>
  );
}
