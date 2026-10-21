import type { LucideIcon } from "lucide-react";

export type StatTone = "rose" | "green" | "sky" | "violet";

const TONE: Record<StatTone, string> = {
  rose:   "from-[#FF9A8B] to-[#F8626C] text-white shadow-[0_7px_18px_rgba(248,98,108,.28)]",
  green:  "from-[#5BE584] to-[#26B04D] text-white shadow-[0_7px_18px_rgba(38,176,77,.28)]",
  sky:    "from-[#7FC4FD] to-[#4A90E2] text-white shadow-[0_7px_18px_rgba(74,144,226,.28)]",
  violet: "from-[#D48BFF] to-[#9C4DF4] text-white shadow-[0_7px_18px_rgba(156,77,244,.28)]",
};

interface StatCardProps {
  label: string;
  /** Preformatted for display, or null while the figure is unavailable. */
  value: string | null;
  delta?: string | null;
  tone: StatTone;
  icon: LucideIcon;
  /** Leave the icon out below 2xl, for a row of long figures. */
  roomy?: boolean;
}

export function StatCard({ label, value, delta, tone, icon: Icon, roomy }: StatCardProps) {
  // A row of long figures shares one size, so the cards read evenly.
  const long = roomy || (value ?? "").length > 17;
  return (
    <div className={`flex items-center justify-between gap-3 rounded-[14px]
                     bg-gradient-to-br p-5 ${TONE[tone]}`}>
      <div className="min-w-0">
        <div className="mb-[5px] text-[12.3px] font-medium opacity-90">{label}</div>
        {/* Long figures shrink with the screen so the value stays on one line;
            on a very narrow card it wraps after the currency rather than overflowing. */}
        <div className={`font-bold leading-tight tracking-[-0.01em]
                         ${long ? "text-[clamp(16px,1.25vw,21px)]" : "text-[clamp(17px,1.4vw,25px)]"}`}>
          {value ?? "—"}
        </div>
        {delta && <div className="mt-1 text-[11.5px] font-medium opacity-90">{delta}</div>}
      </div>
      {/* A long figure needs the icon's room on a laptop-width card. */}
      <span className={`flex h-[50px] w-[50px] flex-shrink-0 items-center justify-center
                       rounded-full bg-white/20 ${roomy ? "max-2xl:hidden" : ""}`}>
        <Icon size={23} strokeWidth={1.7} />
      </span>
    </div>
  );
}
