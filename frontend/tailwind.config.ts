import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111513",
        paper: "#f5f3ee",
        brass: "#b8893b",
        signal: "#16a085",
        danger: "#c74732",
        night: "#202738"
      },
      fontFamily: {
        sans: ["Avenir Next", "ui-sans-serif", "system-ui"],
        mono: ["SFMono-Regular", "Menlo", "monospace"]
      }
    }
  },
  plugins: []
} satisfies Config;

