import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "rgb(var(--rgb-paper) / <alpha-value>)",
        night: "rgb(var(--rgb-night) / <alpha-value>)",
        ink: "rgb(var(--rgb-ink) / <alpha-value>)",
        signal: "rgb(var(--rgb-signal) / <alpha-value>)",
        brass: "rgb(var(--rgb-brass) / <alpha-value>)",
        danger: "rgb(var(--rgb-danger) / <alpha-value>)",
        violet: "rgb(var(--rgb-violet) / <alpha-value>)",
        accent: "rgb(var(--rgb-accent) / <alpha-value>)"
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "PingFang SC",
          "Helvetica Neue",
          "Microsoft YaHei",
          "Noto Sans SC",
          "Segoe UI",
          "sans-serif"
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"]
      }
    }
  },
  plugins: []
} satisfies Config;
