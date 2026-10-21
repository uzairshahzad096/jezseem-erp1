import type { Config } from "tailwindcss";

const c = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: c("primary"), dark: c("primary-dark"), soft: c("primary-soft") },
        // Text and icons placed on a primary fill.
        "on-primary": c("on-primary"),
        // `secondary` for solid fills and `success` for good states: the same green as primary in this scheme.
        secondary: c("secondary"),
        success: c("success"),
        bg: c("bg"),
        surface: c("surface"),
        sidebar: c("sidebar"),
        topbar: c("topbar"),
        text: c("text"),
        muted: c("text-muted"),
        faint: c("text-faint"),
        line: c("line"),
        hover: c("hover"),
        amber: c("amber"),
        rose: c("rose"),
        sky: c("sky"),
        violet: c("violet"),
      },
      // `text-primary` is the primary colour tuned to read as text (deeper on
      // light, lighter on dark); `bg-primary`, borders and rings stay the true colour.
      textColor: { primary: { DEFAULT: c("primary-ink") } },
      spacing: { "62": "15.5rem" },
      boxShadow: { panel: "0 4px 16px rgba(42,53,71,.06)" },
      fontFamily: { sans: ["var(--font-poppins)", "system-ui", "sans-serif"] },
      zIndex: { "35": "35" },
    },
  },
  plugins: [],
};
export default config;
