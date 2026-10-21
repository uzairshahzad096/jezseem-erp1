"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";

/**
 * Thin ECharts wrapper. Re-applies options when they change, resizes with the
 * container, and disposes on unmount so theme switches don't leak instances.
 */
export function EChart({
  option,
  height,
  themeKey,
}: {
  option: echarts.EChartsOption;
  height: number;
  /** Change this when the colour theme flips so the chart re-initialises. */
  themeKey: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);

    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option, themeKey]);

  return <div ref={ref} style={{ height, width: "100%" }} />;
}
