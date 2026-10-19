/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17312d",
        quiet: "#4d625d",
        line: "#d8e6e1",
        mint: "#e9f7f2",
        teal: {
          50: "#eefbf7",
          100: "#d5f3ea",
          500: "#1d9a8c",
          600: "#0e766d",
          700: "#075d57",
        },
        amber: {
          50: "#fff8e8",
          100: "#ffefc4",
          600: "#8a5200",
          700: "#6e3f00",
        },
        coral: {
          50: "#fff1f1",
          100: "#ffdfe1",
          600: "#963844",
          700: "#762b35",
        },
      },
      boxShadow: {
        panel: "0 14px 40px rgba(24, 61, 52, 0.055)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Consolas", "Liberation Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
