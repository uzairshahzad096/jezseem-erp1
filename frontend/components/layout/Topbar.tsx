"use client";

import { Menu, Bell, MessageSquare, Moon, ChevronDown } from "lucide-react";

interface TopbarProps {
  title: string;
  userInitials: string;
  userName: string;
  notificationCount?: number;
  messageCount?: number;
  onToggleNav: () => void;
  onToggleTheme: () => void;
}

export function Topbar({
  title,
  userInitials,
  userName,
  notificationCount = 0,
  messageCount = 0,
  onToggleNav,
  onToggleTheme,
}: TopbarProps) {
  return (
    <header className="fixed inset-x-0 top-0 z-30 flex h-[62px] items-center gap-4
                       border-b border-line bg-topbar px-6 transition-[left] duration-200
                       lg:left-62 max-sm:gap-2.5 max-sm:px-4">
      <button
        onClick={onToggleNav}
        aria-label="Toggle navigation"
        className="flex h-[34px] w-[34px] items-center justify-center rounded-lg
                   text-primary transition-colors hover:bg-hover"
      >
        <Menu size={20} strokeWidth={2} />
      </button>

      <h1 className="m-0 text-[17px] font-semibold">{title}</h1>

      <div className="ml-auto flex items-center gap-[11px]">
        <PillIcon label="Notifications" count={notificationCount}>
          <Bell size={17} strokeWidth={1.9} />
        </PillIcon>
        <PillIcon label="Messages" count={messageCount}>
          <MessageSquare size={17} strokeWidth={1.9} />
        </PillIcon>
        <PillIcon label="Switch theme" onClick={onToggleTheme}>
          <Moon size={17} strokeWidth={1.9} />
        </PillIcon>

        <button className="flex items-center gap-2.5 rounded-3xl bg-primary-soft
                           py-1 pl-1 pr-3.5 transition-[filter] hover:brightness-95
                           max-lg:pr-1">
          <span className="flex h-[31px] w-[31px] flex-shrink-0 items-center justify-center
                           rounded-full bg-gradient-to-br from-primary to-primary-dark
                           text-[11.5px] font-semibold text-on-primary">
            {userInitials}
          </span>
          <span className="whitespace-nowrap text-[12.8px] font-medium max-lg:hidden">
            Hello, {userName}
          </span>
          <ChevronDown size={13} strokeWidth={2.2} className="max-lg:hidden" />
        </button>
      </div>
    </header>
  );
}

function PillIcon({
  label, count = 0, onClick, children,
}: {
  label: string;
  count?: number;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      className="relative flex h-[38px] w-[38px] items-center justify-center rounded-full
                 bg-primary-soft text-primary transition-[filter] hover:brightness-95"
    >
      {children}
      {count > 0 && (
        <span className="absolute -right-0.5 -top-0.5 min-w-[17px] rounded-[9px]
                         border-2 border-topbar bg-rose px-1 text-center text-[10px]
                         font-semibold leading-[17px] text-white">
          {count}
        </span>
      )}
    </button>
  );
}
