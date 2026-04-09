/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
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
