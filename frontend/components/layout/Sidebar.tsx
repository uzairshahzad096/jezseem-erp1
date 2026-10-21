"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Hexagon } from "lucide-react";
import { NAV_MODULES, type NavChild } from "@/lib/navigation";

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const pathname = usePathname();
  const [openModule, setOpenModule] = useState<string | null>(null);
  const [openGroups, setOpenGroups] = useState<string[]>([]);

  // Expand whichever branch contains the current route, so a deep link such
  // as /inventory/setup/racks opens with its parents already unfolded.
  useEffect(() => {
    for (const module of NAV_MODULES) {
      const inModule =
        pathname === module.href ||
        module.children.some(
          (c) =>
            pathname === c.href ||
            (c.href !== "/" && pathname.startsWith(c.href)) ||
            c.children?.some((g) => pathname.startsWith(g.href)),
        );
      if (inModule) {
        setOpenModule(module.key);
        const group = module.children.find((c) =>
          c.children?.some((g) => pathname.startsWith(g.href)),
        );
        if (group) setOpenGroups((prev) => (prev.includes(group.href) ? prev : [...prev, group.href]));
        break;
      }
    }
  }, [pathname]);

  const toggleGroup = (href: string) =>
    setOpenGroups((prev) =>
      prev.includes(href) ? prev.filter((h) => h !== href) : [...prev, href],
    );

  return (
    <aside
      className={`fixed inset-y-0 left-0 z-40 flex w-62 flex-col overflow-y-auto
                  border-r border-line bg-sidebar transition-transform duration-200
                  ${open ? "translate-x-0" : "-translate-x-full"} lg:translate-x-0`}
    >
      <div className="flex flex-shrink-0 items-center gap-2.5 px-[22px] py-[19px]">
        <span className="flex h-[30px] w-[30px] items-center justify-center rounded-[9px]
                         bg-gradient-to-br from-primary to-primary-dark text-on-primary">
          <Hexagon size={17} strokeWidth={2.1} />
        </span>
        <span className="text-[19px] font-bold tracking-[0.02em] text-primary">JEZSEEM</span>
      </div>

      <nav className="flex-1 px-3.5 pt-1">
        {NAV_MODULES.map((module) => {
          const Icon = module.icon;
          const isOpen = openModule === module.key;
          const isActive =
            pathname === module.href ||
            module.children.some(
              (c) =>
                (c.href !== "/" && pathname.startsWith(c.href)) ||
                c.children?.some((g) => pathname.startsWith(g.href)),
            );

          const linkClass = `mb-[3px] flex w-full items-center gap-[11px] rounded-[9px]
                            px-[13px] py-2.5 text-left text-[13.5px] font-medium
                            transition-colors duration-150
                            ${isActive
                              ? "bg-gradient-to-br from-primary to-primary-dark text-on-primary shadow-[0_5px_14px_rgba(43,193,85,.32)]"
                              : "text-muted hover:bg-hover hover:text-text"}`;

          // A module without submodules (Dashboard) opens straight away.
          if (module.children.length === 0) {
            return (
              <Link key={module.key} href={module.href} onClick={() => { setOpenModule(null); onClose(); }}
                className={linkClass}>
                <Icon size={17} strokeWidth={1.8} className="flex-shrink-0" />
                <span className="min-w-0 flex-1 truncate">{module.label}</span>
              </Link>
            );
          }

          return (
            <div key={module.key}>
              <button
                onClick={() => setOpenModule(isOpen ? null : module.key)}
                aria-expanded={isOpen}
                className={`mb-[3px] flex w-full items-center gap-[11px] rounded-[9px]
                            px-[13px] py-2.5 text-left text-[13.5px] font-medium
                            transition-colors duration-150
                            ${isActive
                              ? "bg-gradient-to-br from-primary to-primary-dark text-on-primary shadow-[0_5px_14px_rgba(43,193,85,.32)]"
                              : "text-muted hover:bg-hover hover:text-text"}`}
              >
                <Icon size={17} strokeWidth={1.8} className="flex-shrink-0" />
                <span className="min-w-0 flex-1 truncate">{module.label}</span>
                <ChevronRight
                  size={13}
                  strokeWidth={2.3}
                  className={`flex-shrink-0 transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`}
                />
              </button>

              {isOpen && (
                <div className="pb-[7px] pl-[18px]">
                  {module.children.map((child) =>
                    child.children ? (
                      <NavGroup
                        key={child.href}
                        group={child}
                        pathname={pathname}
                        open={openGroups.includes(child.href)}
                        onToggle={() => toggleGroup(child.href)}
                        onNavigate={onClose}
                      />
                    ) : (
                      <NavLeaf key={child.href} item={child} pathname={pathname} onNavigate={onClose} />
                    ),
                  )}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="m-3.5 flex-shrink-0 rounded-[13px] bg-gradient-to-br
                      from-[#FF8A65] to-[#F4511E] p-[17px] text-white">
        <h4 className="m-0 mb-1.5 text-[13px] font-semibold leading-tight">Financial year closing</h4>
        <p className="m-0 mb-3 text-[11.5px] leading-snug opacity-90">
          Review open entries before FY 2026&ndash;27 closes.
        </p>
        <button className="rounded-[7px] bg-white/20 px-3 py-[5px] text-[11.5px]
                           font-medium transition-colors hover:bg-white/30">
          Open checklist
        </button>
      </div>

      <div className="px-[22px] pb-5 text-[10.5px] leading-relaxed text-faint">
        Jezseem ERP &copy; 2026
        <br />
        Version 0.1.0
      </div>
    </aside>
  );
}

function NavGroup({
  group, pathname, open, onToggle, onNavigate,
}: {
  group: NavChild;
  pathname: string;
  open: boolean;
  onToggle: () => void;
  onNavigate: () => void;
}) {
  const active = group.children?.some((g) => pathname.startsWith(g.href));
  return (
    <div>
      <button
        onClick={onToggle}
        aria-expanded={open}
        className={`flex w-full items-center gap-2 rounded-lg px-[13px] py-[7px]
                    text-left text-[12.8px] font-medium transition-colors
                    ${active ? "text-primary" : "text-muted hover:text-text"}`}
      >
        <span className="min-w-0 flex-1 truncate">{group.label}</span>
        <ChevronRight
          size={12}
          strokeWidth={2.4}
          className={`flex-shrink-0 transition-transform duration-200 ${open ? "rotate-90" : ""}`}
        />
      </button>
      {open && (
        <div className="border-l border-line pl-3 ml-[13px]">
          {group.children!.map((leaf) => (
            <NavLeaf key={leaf.href} item={leaf} pathname={pathname} onNavigate={onNavigate} />
          ))}
        </div>
      )}
    </div>
  );
}

function NavLeaf({
  item, pathname, onNavigate,
}: {
  item: NavChild;
  pathname: string;
  onNavigate: () => void;
}) {
  const active = pathname === item.href;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      title={item.label}
      className={`block truncate rounded-lg px-[13px] py-[6px] text-[12.5px] transition-colors
                  ${active ? "font-medium text-primary" : "text-faint hover:text-primary"}`}
    >
      {item.label}
    </Link>
  );
}
