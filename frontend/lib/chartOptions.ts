import * as echarts from "echarts";

/** Reads a CSS custom property so charts follow the active theme. */
const cssVar = (name: string) =>
  typeof window === "undefined"
    ? ""
    : getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const axisBase = () => ({
  axisLine: { lineStyle: { color: `rgb(${cssVar("--grid-line")})` } },
  axisTick: { show: false },
  axisLabel: { color: `rgb(${cssVar("--text-faint")})`, fontSize: 11 },
});

export interface Series {
  name: string;
  data: number[];
}

export function barOption(categories: string[], series: Series[]): echarts.EChartsOption {
  const colors = ["#2BC155", "#4A90E2"];
  return {
    grid: { left: 38, right: 10, top: 12, bottom: 42 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: {
      bottom: 0, itemWidth: 9, itemHeight: 9, itemGap: 16,
      textStyle: { color: `rgb(${cssVar("--text-muted")})`, fontSize: 11 },
    },
    xAxis: { type: "category", data: categories, ...axisBase() },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: `rgb(${cssVar("--grid-line")})` } },
      axisLabel: { color: `rgb(${cssVar("--text-faint")})`, fontSize: 11 },
    },
    series: series.map((s, i) => ({
      name: s.name, type: "bar", data: s.data, barWidth: 9,
      itemStyle: { color: colors[i % colors.length], borderRadius: [5, 5, 0, 0] },
    })),
  };
}

export function lineOption(categories: string[], series: Series[]): echarts.EChartsOption {
  const colors = ["#2BC155", "#F8626C"];
  const fades = ["rgba(43,193,85,", "rgba(248,98,108,"];
  return {
    grid: { left: 42, right: 18, top: 18, bottom: 48 },
    tooltip: { trigger: "axis" },
    legend: {
      bottom: 0, itemWidth: 9, itemHeight: 9, itemGap: 20,
      textStyle: { color: `rgb(${cssVar("--text-muted")})`, fontSize: 11 },
    },
    xAxis: { type: "category", data: categories, boundaryGap: false, ...axisBase() },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: `rgb(${cssVar("--grid-line")})` } },
      axisLabel: { color: `rgb(${cssVar("--text-faint")})`, fontSize: 11 },
    },
    series: series.map((s, i) => ({
      name: s.name, type: "line", data: s.data, symbol: "circle", symbolSize: 7,
      lineStyle: { color: colors[i % colors.length], width: 2 },
      itemStyle: { color: colors[i % colors.length] },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: `${fades[i % fades.length]}.22)` },
          { offset: 1, color: `${fades[i % fades.length]}0)` },
        ]),
      },
    })),
  };
}
