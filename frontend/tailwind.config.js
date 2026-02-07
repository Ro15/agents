/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          blue: "#0F4C81",
          teal: "#1F9AAD",
          yellow: "#F5C518",
        },
      },
    },
  },
  plugins: [],
};
