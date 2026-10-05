import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { addDays, parseIsoDate, todayInTashkent } from './uzDate';

/** Global "ko'rilayotgan sana" URL parametri — barcha davomat sahifalari
 *  (Situatsion markaz, Talabalar, O'qituvchilar, Darslar, Shaxs) shu
 *  sanani ko'rsatadi. Yuqori paneldagi sana tanlagich uni o'zgartiradi. */
export const VIEW_DATE_PARAM = 'sana';

const ISO = /^\d{4}-\d{2}-\d{2}$/;

function isRealDate(value: string): boolean {
  if (!ISO.test(value)) return false;
  const date = parseIsoDate(value);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

/** URL qiymatini tekshiradi: yaroqsiz yoki kelajakdagi sana → bugun. */
export function parseViewDate(raw: string | null | undefined, today: string): string {
  if (!raw || !isRealDate(raw)) return today;
  return raw > today ? today : raw;
}

/** `path`ga `?sana=` qo'shadi (bugun bo'lsa — qo'shmaydi, toza manzil). */
export function withViewDate(path: string, date: string, today: string): string {
  const [base, hash = ''] = path.split('#');
  const [pathname, query = ''] = base.split('?');
  const params = new URLSearchParams(query);
  if (date === today) params.delete(VIEW_DATE_PARAM);
  else params.set(VIEW_DATE_PARAM, date);
  const search = params.toString();
  return `${pathname}${search ? `?${search}` : ''}${hash ? `#${hash}` : ''}`;
}

/** Parametrlarni yangi sana bilan qaytaradi (bugun — parametrsiz). */
export function nextViewDateParams(current: URLSearchParams, date: string, today: string): URLSearchParams {
  const next = new URLSearchParams(current);
  const value = parseViewDate(date, today);
  if (value === today) next.delete(VIEW_DATE_PARAM);
  else next.set(VIEW_DATE_PARAM, value);
  return next;
}

/** Toshkent bo'yicha bugun; yarim tunda o'zi yangilanadi (devor ekrani
 *  kechasi ochiq qolsa ham ertasi kuni yangi sanani ko'rsatadi). */
export function useToday(): string {
  const [today, setToday] = useState(() => todayInTashkent());
  useEffect(() => {
    const id = window.setInterval(() => {
      const now = todayInTashkent();
      setToday((current) => (current === now ? current : now));
    }, 60_000);
    return () => window.clearInterval(id);
  }, []);
  return today;
}

export interface ViewDate {
  /** Ko'rilayotgan sana, "YYYY-MM-DD" (standart — bugun). */
  date: string;
  today: string;
  isToday: boolean;
  setDate: (date: string) => void;
  /** Kun qo'shish/ayirish (kelajakka o'tmaydi). */
  shift: (days: number) => void;
  /** Ichki havolaga joriy sanani qo'shish: `withDate('/talabalar/guruh/D-101')`. */
  withDate: (path: string) => string;
}

export function useViewDate(): ViewDate {
  const [params, setParams] = useSearchParams();
  const today = useToday();
  const date = parseViewDate(params.get(VIEW_DATE_PARAM), today);

  const setDate = useCallback(
    (next: string) => setParams((prev) => nextViewDateParams(prev, next, today), { replace: true }),
    [setParams, today],
  );
  const shift = useCallback((days: number) => setDate(addDays(date, days)), [setDate, date]);
  const withDate = useCallback((path: string) => withViewDate(path, date, today), [date, today]);

  return { date, today, isToday: date === today, setDate, shift, withDate };
}
