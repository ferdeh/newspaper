import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#15385b",
        paper: "#fbfaf8",
        petrol: "#0b73bf",
        coral: "#ea4a43",
        lime: "#77b82a",
        cloud: "#eef5f9",
      },
      fontFamily: {
        sans: ["Arial", "Helvetica", "sans-serif"],
        serif: ["Arial", "Helvetica", "sans-serif"],
      },
      boxShadow: { card: "0 18px 40px rgba(21,56,91,.10)" },
    },
  },
  plugins: [],
} satisfies Config;
