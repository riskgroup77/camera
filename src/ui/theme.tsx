import { useCallback, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ThemeContext, applyTheme, readStoredTheme, writeStoredTheme, type ThemeName } from './themeContext';

/** Mavzu (yorug'/qorong'i) — foydalanuvchi tanlovi localStorage'da;
 *  taqdimot rejimi vaqtincha qorong'ini majburlaydi. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreference] = useState<ThemeName>(readStoredTheme);
  const [forced, setForced] = useState<ThemeName | null>(null);
  const theme = forced ?? preference;
  // Ref'lar: setter'lar barqaror (useCallback []) bo'lib, oxirgi qiymatni ko'radi.
  const preferenceRef = useRef(preference);
  const forcedRef = useRef(forced);

  const setTheme = useCallback((next: ThemeName) => {
    writeStoredTheme(next);
    preferenceRef.current = next;
    setPreference(next);
    if (!forcedRef.current) applyTheme(next);
  }, []);

  const setForcedTheme = useCallback((next: ThemeName | null) => {
    forcedRef.current = next;
    setForced(next);
    applyTheme(next ?? preferenceRef.current);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(preferenceRef.current === 'dark' ? 'light' : 'dark');
  }, [setTheme]);

  useLayoutEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const value = useMemo(
    () => ({ theme, preference, setTheme, toggleTheme, setForcedTheme }),
    [theme, preference, setTheme, toggleTheme, setForcedTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

