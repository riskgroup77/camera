/** @type {import('tailwindcss').Config} */

/** Dizayn tokenlari src/index.css'dagi CSS o'zgaruvchilarida ("R G B"
 *  ko'rinishida) — shu sababli `bg-primary/10` kabi shaffoflik ishlaydi,
 *  qorong'i mavzu esa faqat o'zgaruvchilarni almashtiradi. */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

const semantic = (name) => ({
  DEFAULT: token(name),
  fg: token(`${name}-fg`),
  soft: token(`${name}-soft`),
});

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        // Raqam, kod, sana, birlik va yorliqlar — barchasi shu yuzda
        // (src/index.css: --font-intel). `.intel-code` qo'shimcha ravishda
        // tabular raqamlarni yoqadi.
        mono: ['var(--font-intel)'],
      },
      colors: {
        bg: token('bg'),
        surface: {
          DEFAULT: token('surface'),
          2: token('surface-2'),
          3: token('surface-3'),
        },
        border: {
          DEFAULT: token('border'),
          strong: token('border-strong'),
        },
        fg: token('fg'),
        muted: token('muted'),
        subtle: token('subtle'),
        primary: semantic('primary'),
        success: semantic('success'),
        warning: semantic('warning'),
        danger: semantic('danger'),
        info: semantic('info'),
        // Eski sahifalar uchun (migratsiyagacha) — tokenlarga bog'langan.
        canvas: token('bg'),
        ink: token('fg'),
      },
      borderColor: {
        DEFAULT: token('border'),
      },
      ringColor: {
        DEFAULT: token('primary'),
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        pop: 'var(--shadow-pop)',
        hover: 'var(--shadow-hover)',
        // Eski sinflar (glass) — migratsiyagacha ishlashi uchun.
        glass: 'var(--shadow-card)',
        'glass-green': 'var(--shadow-card)',
        'glass-red': 'var(--shadow-card)',
        'glass-amber': 'var(--shadow-card)',
        btn: '0 1px 2px 0 rgb(16 24 40 / 0.06)',
      },
      // Yangi tizim: sokin yumaloq qirralar. Bu umumiy tokenlar barcha
      // sahifani bir xil, yengil mahsulot ko'rinishiga olib keladi.
      borderRadius: {
        card: '20px',
        control: '12px',
      },
      keyframes: {
        'ui-fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'ui-slide-in-right': { from: { transform: 'translateX(24px)', opacity: '0' }, to: { transform: 'translateX(0)', opacity: '1' } },
        'ui-slide-in-left': { from: { transform: 'translateX(-24px)', opacity: '0' }, to: { transform: 'translateX(0)', opacity: '1' } },
        'ui-pop-in': { from: { transform: 'translateY(4px) scale(0.98)', opacity: '0' }, to: { transform: 'none', opacity: '1' } },
      },
      animation: {
        'fade-in': 'ui-fade-in 150ms ease-out',
        'slide-in-right': 'ui-slide-in-right 200ms cubic-bezier(0.2, 0.8, 0.2, 1)',
        'slide-in-left': 'ui-slide-in-left 200ms cubic-bezier(0.2, 0.8, 0.2, 1)',
        'pop-in': 'ui-pop-in 160ms cubic-bezier(0.2, 0.8, 0.2, 1)',
      },
    },
  },
  plugins: [],
}
