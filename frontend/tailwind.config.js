/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Secondary text on white and #f0f4f8 (>=5:1); #6A89A7 measured 3.3-3.6:1.
        muted: "#4f6b85",
      },
      animation: {
        shimmer: "shimmer 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
}
