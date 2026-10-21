import type { ActivityItem } from "@/lib/api";

const STATUS: Record<ActivityItem["status"], { label: string; className: string }> = {
  pending:  { label: "Pending",     className: "bg-amber/15 text-amber" },
  progress: { label: "In Progress", className: "bg-sky/15 text-sky" },
  rejected: { label: "Rejected",    className: "bg-rose/15 text-rose" },
  done:     { label: "Completed",   className: "bg-success/15 text-success" },
};

const AVATAR_COLORS = ["#F8626C", "#4A90E2", "#9C4DF4", "#26B04D", "#FFAA2B", "#5A9BF6"];

export function ActivityList({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) {
    return (
      <p className="px-5 py-10 text-center text-[12.5px] text-faint">
        Activity appears here as transactions are posted.
      </p>
    );
  }

  return (
    <>
      {items.map((item, i) => {
        const status = STATUS[item.status] ?? STATUS.pending;
        const initials = item.title.split(" ").slice(0, 2).map((w) => w[0]).join("").toUpperCase();
        return (
          <div key={item.id} className="flex items-center gap-[11px] px-5 py-[11px] transition-colors hover:bg-hover">
            <span
              style={{ background: AVATAR_COLORS[i % AVATAR_COLORS.length] }}
              className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full
                         text-[11.5px] font-semibold text-white"
            >
              {initials}
            </span>
            <div className="min-w-0 flex-1">
              <h5 className="m-0 truncate text-[12.8px] font-semibold">{item.title}</h5>
              <span className="text-[11px] text-faint">{item.subtitle}</span>
            </div>
            <span className={`flex-shrink-0 whitespace-nowrap rounded-[7px] px-2.5 py-1
                              text-[10.5px] font-semibold ${status.className}`}>
              {status.label}
            </span>
          </div>
        );
      })}
    </>
  );
}
