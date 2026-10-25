/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Tokens from DESIGN.md. muted is >=5:1 on white and paper.
        muted: "#4f6b85",
        ink: "#384959",
        paper: "#f0f4f8",
        line: "#d3dde7",
        field: "#6f88a0",
        accent: { DEFAULT: "#1f5f99", hover: "#184d7d" },
        tint: "#e8f1fa",
      },
      animation: {
        shimmer: "shimmer 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
}
