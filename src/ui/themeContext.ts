import { createContext, useContext } from 'react';

export type ThemeName = 'light' | 'dark';

const STORAGE_KEY = 'ui-theme';

export function readStoredTheme(): ThemeName {
  // Tizim faqat yorug' ishlaydi (2026-09-21) — saqlangan eski tanlov
  // e'tiborsiz qoldiriladi.
  return 'light';
}

export function writeStoredTheme(theme: ThemeName) {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* saqlab bo'lmadi — faqat shu seans uchun */
  }
}

const THEME_COLOR: Record<ThemeName, string> = { light: '#f5f6f8', dark: '#0a0d14' };

/** Mavzuni DARHOL hujjatga yozadi. Effektda emas: grafiklar
 *  (useChartTheme) CSS o'zgaruvchilarini render paytida o'qiydi — atribut
 *  kechiksa, ular eski mavzu ranglarini olib qolardi. */
export function applyTheme(theme: ThemeName) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (root.dataset.theme !== theme) root.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  meta?.setAttribute('content', THEME_COLOR[theme]);
}

// Modul yuklanishi bilan — birinchi chizishdan oldin (oq "chaqnash" bo'lmasin).
applyTheme(readStoredTheme());

export interface ThemeContextValue {
  /** Hozir ko'rinayotgan mavzu (taqdimot rejimi majburlashi mumkin). */
  theme: ThemeName;
  /** Foydalanuvchi tanlovi (localStorage'da). */
  preference: ThemeName;
  setTheme: (theme: ThemeName) => void;
  toggleTheme: () => void;
  /** Vaqtincha majburlash (taqdimot rejimi → dark). `null` — bekor qilish. */
  setForcedTheme: (theme: ThemeName | null) => void;
}

const noop = () => {};

export const ThemeContext = createContext<ThemeContextValue>({
  theme: 'light',
  preference: 'light',
  setTheme: noop,
  toggleTheme: noop,
  setForcedTheme: noop,
});

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
