import { isValidElement, useEffect, useRef, useState, type ReactNode } from 'react';
import { easeOut, formatLike, parseDisplayNumber } from './numberTween';

/** Animatsiya o'chiq: prefers-reduced-motion yoki test muhiti (jsdom). */
function prefersReducedMotion(): boolean {
  try {
    if (typeof window === 'undefined' || typeof navigator === 'undefined' || /jsdom/i.test(navigator.userAgent)) return true;
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
  } catch {
    return false;
  }
}

/** Sonni silliq sanab o'zgartiradi (birinchi ko'rinishda 0 dan, keyin eski
 *  qiymatdan yangisiga). Matn formatini saqlaydi ("1 234", "87,5%").
 *  Son bo'lmagan qiymat va prefers-reduced-motion — animatsiyasiz. */
export function CountUp({ value, duration = 700 }: { value: ReactNode; duration?: number }) {
  const text = typeof value === 'number' ? String(value) : typeof value === 'string' ? value : null;
  const parsed = text !== null && !isValidElement(value) ? parseDisplayNumber(text) : null;
  const target = parsed?.value ?? null;

  const [shown, setShown] = useState<number | null>(() => (target === null || prefersReducedMotion() ? target : 0));
  const shownRef = useRef<number | null>(shown);
  shownRef.current = shown;

  useEffect(() => {
    if (target === null) return;
    if (prefersReducedMotion() || typeof requestAnimationFrame === 'undefined') {
      setShown(target);
      return;
    }
    const from = shownRef.current ?? 0;
    if (from === target) return;
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = easeOut((now - start) / duration);
      setShown(from + (target - from) * t);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  if (!parsed || shown === null || shown === target) return <>{value}</>;
  return (
    <>
      <span aria-hidden="true">{formatLike(shown, parsed)}</span>
      <span className="sr-only">{text}</span>
    </>
  );
}
