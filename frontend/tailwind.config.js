/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#0f1115",
          panel: "#161922",
          elev: "#1a1d24",
        },
        border: { DEFAULT: "#2a2e36" },
        accent: { DEFAULT: "#5b8def", hover: "#4a7bdf" },
        ok: "#3fb950",
        warn: "#d29922",
        err: "#f85149",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
    },
  },
  plugins: [],
};
