/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#f2fbf8",
        quiet: "#a9c6bf",
        line: "#294841",
        mint: "#0c2d29",
        teal: {
          50: "#092d2a",
          100: "#124b43",
          500: "#28d7bd",
          600: "#13b39d",
          700: "#65f1dc",
        },
        amber: {
          50: "#2b210b",
          100: "#5a430e",
          600: "#ffc857",
          700: "#ffdc80",
        },
        coral: {
          50: "#32151b",
          100: "#67232f",
          600: "#ff7180",
          700: "#ff9ca8",
        },
        surface: "#10231f",
        surfaceMuted: "#142c27",
        borderStrong: "#3b5f57",
      },
      boxShadow: {
        panel: "0 18px 48px rgba(0, 0, 0, 0.28)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Consolas", "Liberation Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
