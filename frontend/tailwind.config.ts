import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#e8eee9",
        paper: "#07110f",
        brass: "#d6a24a",
        signal: "#5ad6c4",
        danger: "#e36b4f",
        night: "#0d1714"
      },
      fontFamily: {
        sans: ["Avenir Next", "ui-sans-serif", "system-ui"],
        mono: ["SFMono-Regular", "Menlo", "monospace"]
      }
    }
  },
  plugins: []
} satisfies Config;
