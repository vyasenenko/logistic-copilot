const defaultTheme = require("tailwindcss/defaultTheme");

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    // Default Tailwind `xl` is 1280px — iPad landscape (1024+) stayed on “mobile” layouts. Align `xl` with
    // `lg` so tablets get the same multi-column / thread-rail chrome as compact desktops.
    screens: {
      ...defaultTheme.screens,
      xl: "1024px",
    },
    extend: {
      keyframes: {
        "org-drawer-refresh-bar": {
          "0%": { transform: "translateX(-120%)" },
          "100%": { transform: "translateX(320%)" },
        },
      },
      animation: {
        "org-drawer-refresh-bar": "org-drawer-refresh-bar 1.15s ease-in-out infinite",
      },
      colors: {
        agent: {
          bg: "#0a0a0a",
          surface: "#141414",
          border: "#262626",
          text: "#ededed",
          muted: "#888888",
          accent: "#3b82f6",
          "accent-hover": "#2563eb",
        },
      },
    },
  },
  plugins: [],
};
