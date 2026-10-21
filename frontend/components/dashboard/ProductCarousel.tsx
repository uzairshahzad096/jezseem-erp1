"use client";

import { useRef } from "react";
import { ChevronLeft, ChevronRight, Package } from "lucide-react";

interface Product {
  name: string;
  category: string;
  meta: string;
  tag: string;
}

export function ProductCarousel({ products }: { products: Product[] }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const scroll = (dx: number) => trackRef.current?.scrollBy({ left: dx, behavior: "smooth" });

  if (products.length === 0) {
    return (
      <p className="px-5 py-10 text-center text-[12.5px] text-faint">
        Product movement appears once the Inventory module is built.
      </p>
    );
  }

  return (
    <div className="relative px-5 pb-5">
      <CarouselButton side="left" onClick={() => scroll(-340)} />
      <div
        ref={trackRef}
        className="flex snap-x snap-mandatory gap-3.5 overflow-x-auto pb-1
                   [scrollbar-width:thin]"
      >
        {products.map((p) => (
          <a
            key={p.name}
            href="#"
            className="w-[152px] flex-shrink-0 snap-start rounded-xl border border-line
                       bg-surface p-3 pt-[15px] text-center transition-[border-color,transform]
                       hover:-translate-y-0.5 hover:border-primary"
          >
            <span className="relative mx-auto mb-2.5 flex h-[66px] w-[66px] items-center
                             justify-center rounded-xl bg-primary-soft text-primary">
              <Package size={28} strokeWidth={1.6} />
              <span className="absolute -bottom-2 left-1/2 -translate-x-1/2 whitespace-nowrap
                               rounded-md bg-primary px-[7px] py-0.5 text-[9.5px]
                               font-semibold text-on-primary">
                {p.tag}
              </span>
            </span>
            <h4 className="mb-0.5 mt-1.5 text-[12.8px] font-semibold">{p.name}</h4>
            <div className="text-[11px] font-medium text-primary">{p.category}</div>
            <div className="mt-1.5 text-[10.5px] leading-snug text-faint">{p.meta}</div>
          </a>
        ))}
      </div>
      <CarouselButton side="right" onClick={() => scroll(340)} />
    </div>
  );
}

function CarouselButton({ side, onClick }: { side: "left" | "right"; onClick: () => void }) {
  const Icon = side === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      onClick={onClick}
      aria-label={side === "left" ? "Previous" : "Next"}
      className={`absolute top-1/2 z-10 flex h-[29px] w-[29px] -translate-y-1/2 items-center
                  justify-center rounded-full border border-line bg-surface text-muted
                  shadow-panel transition-colors hover:border-primary hover:text-primary
                  ${side === "left" ? "left-1.5" : "right-1.5"}`}
    >
      <Icon size={14} strokeWidth={2.4} />
    </button>
  );
}
