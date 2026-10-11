/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./*.html",
    "./*.js",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: 'var(--brand-primary, #3b82f6)',
          accent:  'var(--brand-accent,  #f59e0b)',
        },
      },
    },
  },
  plugins: [],
};
