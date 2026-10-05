import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { detectPreset, isIsoDate, rangeForPreset, type DateRangeValue } from '../../ui';
import type { FixedPreset } from '../../lib/reportPeriods';
import { todayInTashkent } from '../../lib/uzDate';

/** Tahlil tablari uchun davr tanlovlari. */
export const ANALYTICS_PRESETS: readonly FixedPreset[] = ['last7', 'last30', 'month', 'lastMonth'];

/** Tahlil davri URL'da (`?dan=&gacha=`) — Tahlil / Reyting / Takror kechikkan
 *  tablari orasida umumiy, havola bilan ulashiladi. Standart: 30 kun. */
export function useAnalyticsPeriod(): [DateRangeValue, (value: DateRangeValue) => void] {
  const [params, setParams] = useSearchParams();
  const today = todayInTashkent();
  const from = params.get('dan');
  const to = params.get('gacha');
  const custom = params.get('davr') === 'oraliq';

  const value = useMemo<DateRangeValue>(() => {
    if (isIsoDate(from) && isIsoDate(to) && from <= to) {
      return { from, to, preset: custom ? 'custom' : detectPreset({ from, to }, ANALYTICS_PRESETS, today) };
    }
    return rangeForPreset('last30', today);
  }, [from, to, custom, today]);

  const setValue = useCallback(
    (next: DateRangeValue) => {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.set('dan', next.from);
          p.set('gacha', next.to);
          if (next.preset === 'custom') p.set('davr', 'oraliq');
          else p.delete('davr');
          return p;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  return [value, setValue];
}

/** Kichik tanlovni (reyting turi, bo'linma turi, chegara) URL'da saqlaydi.
 *  Yaroqsiz yoki eskirgan qiymat `fallback`ka tushadi — sahifa hech qachon
 *  bo'sh panel ko'rsatmaydi. `allowed = null` — har qanday matn. */
export function useUrlChoice<T extends string>(
  param: string,
  allowed: readonly T[] | null,
  fallback: T,
): [T, (value: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(param);
  const value = allowed ? (allowed.find((item) => item === raw) ?? fallback) : ((raw as T | null) ?? fallback);

  const setValue = useCallback(
    (next: T) => {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          if (next === fallback) p.delete(param);
          else p.set(param, next);
          return p;
        },
        { replace: true },
      );
    },
    [setParams, param, fallback],
  );
  return [value, setValue];
}

/** CSV fayl nomi uchun davr qo'shimchasi. */
export function periodSuffix(range: { from: string; to: string }): string {
  return range.from === range.to ? range.from : `${range.from}_${range.to}`;
}
