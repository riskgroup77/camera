import { useCallback, useEffect, useRef, useState } from 'react';
import { useTheme } from '../../ui';

/** Taqdimot rejimi — institut devor ekrani uchun: qorong'i mavzu, yon
 *  panelsiz, to'liq ekran va biroz kattaroq shrift. `?taqdimot=1` bilan
 *  ochilsa darhol yoqiladi (to'liq ekran brauzer talabiga ko'ra faqat
 *  foydalanuvchi bosganda). To'liq ekrandan (Esc) chiqilsa — rejim ham
 *  o'chadi. */
export function usePresentation() {
  const { setForcedTheme } = useTheme();
  const [active, setActive] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('taqdimot') === '1';
    } catch {
      return false;
    }
  });
  const enteredFullscreen = useRef(false);

  const enter = useCallback(() => {
    setActive(true);
    const root = document.documentElement;
    if (!document.fullscreenElement && typeof root.requestFullscreen === 'function') {
      root
        .requestFullscreen()
        .then(() => {
          enteredFullscreen.current = true;
        })
        .catch(() => {
          /* ruxsat berilmadi — rejim to'liq ekransiz ham ishlaydi */
        });
    }
  }, []);

  const exit = useCallback(() => {
    setActive(false);
    if (document.fullscreenElement && typeof document.exitFullscreen === 'function') {
      document.exitFullscreen().catch(() => {});
    }
    enteredFullscreen.current = false;
  }, []);

  const toggle = useCallback(() => (active ? exit() : enter()), [active, enter, exit]);

  useEffect(() => {
    function onFullscreenChange() {
      if (!document.fullscreenElement && enteredFullscreen.current) {
        enteredFullscreen.current = false;
        setActive(false);
      }
    }
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, []);

  useEffect(() => {
    if (!active) return;
    setForcedTheme(null); // qorong'i mavzu olib tashlandi
    document.documentElement.dataset.presentation = 'true';
    return () => {
      setForcedTheme(null);
      delete document.documentElement.dataset.presentation;
    };
  }, [active, setForcedTheme]);

  return { active, enter, exit, toggle };
}
