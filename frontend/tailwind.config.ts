import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        raised: "var(--color-raised)",
        ink: "var(--color-ink)",
        muted: "var(--color-muted)",
        line: "var(--color-line)",
        accent: "var(--color-accent)",
        "accent-ink": "var(--color-accent-ink)",
        amber: "var(--color-amber)",
        danger: "var(--color-danger)",
        good: "var(--color-good)",
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(16, 24, 20, 0.04), 0 12px 30px -24px rgba(16, 24, 20, 0.35)",
      },
    },
  },
  plugins: [],
};

export default config;
