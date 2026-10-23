import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0f",
        panel: "rgba(255,255,255,0.03)",
        line: "rgba(255,255,255,0.08)",
        accent: "#76b900",
        accent2: "#4f9cf9",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        glass: "0 8px 32px rgba(0,0,0,0.4)",
      },
    },
  },
  plugins: [],
};

export default config;
