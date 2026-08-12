/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"SF Pro Display"',
          '"SF Pro Text"',
          '"Plus Jakarta Sans"',
          'Inter',
          'system-ui',
          'sans-serif',
        ],
      },
      colors: {
        canvas: '#E8EDFF',
        ink: '#0F172A',
      },
      boxShadow: {
        glass: '0 8px 32px 0 rgba(99,102,241,0.10), 0 2px 8px 0 rgba(15,23,42,0.05)',
        'glass-green': '0 8px 32px 0 rgba(34,197,94,0.10), 0 2px 8px 0 rgba(15,23,42,0.05)',
        'glass-red': '0 8px 32px 0 rgba(239,68,68,0.10), 0 2px 8px 0 rgba(15,23,42,0.05)',
        'glass-amber': '0 8px 32px 0 rgba(245,158,11,0.10), 0 2px 8px 0 rgba(15,23,42,0.05)',
        btn: '0 2px 14px 0 rgba(15,23,42,0.07), 0 1px 4px 0 rgba(15,23,42,0.04), inset 0 1px 0 0 rgba(255,255,255,0.92)',
      },
      borderRadius: {
        card: '20px',
      },
    },
  },
  plugins: [],
}
