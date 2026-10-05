import { describe, expect, it } from 'vitest';
import { MAX_RANGE_DAYS, isFixedPreset, resolvePreset, validateRange } from './reportPeriods';
import { addDays, daysBetweenInclusive, todayInTashkent } from './uzDate';

// 2026-09-15 — seshanba.
const TODAY = '2026-09-15';

describe('resolvePreset', () => {
  it('bugun va kecha', () => {
    expect(resolvePreset('today', TODAY)).toEqual({ from: TODAY, to: TODAY });
    expect(resolvePreset('yesterday', TODAY)).toEqual({ from: '2026-09-14', to: '2026-09-14' });
  });

  it('hafta dushanbadan boshlanadi', () => {
    expect(resolvePreset('week', TODAY)).toEqual({ from: '2026-09-14', to: TODAY });
    expect(resolvePreset('week', '2026-09-14')).toEqual({ from: '2026-09-14', to: '2026-09-14' });
    expect(resolvePreset('week', '2026-09-20')).toEqual({ from: '2026-09-14', to: '2026-09-20' });
  });

  it('oylar va sirpanuvchi oynalar', () => {
    expect(resolvePreset('month', TODAY)).toEqual({ from: '2026-09-01', to: TODAY });
    expect(resolvePreset('lastMonth', TODAY)).toEqual({ from: '2026-08-01', to: '2026-08-31' });
    expect(resolvePreset('lastMonth', '2026-03-10')).toEqual({ from: '2026-02-01', to: '2026-02-28' });
    expect(resolvePreset('lastMonth', '2026-01-05')).toEqual({ from: '2025-12-01', to: '2025-12-31' });
    expect(resolvePreset('last7', TODAY)).toEqual({ from: '2026-09-09', to: TODAY });
    expect(daysBetweenInclusive(resolvePreset('last30', TODAY).from, TODAY)).toBe(30);
  });
});

describe('validateRange', () => {
  it('to\'g\'ri oraliq', () => {
    expect(validateRange('2026-09-01', '2026-09-15')).toBeNull();
    expect(validateRange('2026-01-01', addDays('2026-01-01', MAX_RANGE_DAYS - 1))).toBeNull();
  });

  it('xatolar tushunarli matn bilan', () => {
    expect(validateRange('', '2026-09-15')).toMatch(/sanani/);
    expect(validateRange('2026-09-16', '2026-09-15')).toMatch(/keyin/);
    expect(validateRange('2026-01-01', addDays('2026-01-01', MAX_RANGE_DAYS))).toMatch(/92/);
  });
});

describe('yordamchilar', () => {
  it('preset nomlarini tanish', () => {
    expect(isFixedPreset('month')).toBe(true);
    expect(isFixedPreset('custom')).toBe(false);
    expect(isFixedPreset(null)).toBe(false);
  });

  it('Toshkent sanasi brauzer mintaqasiga bog\'liq emas', () => {
    // 2026-09-15 01:30 UTC = 2026-09-15 06:30 Toshkent — yangi ish kuni
    expect(todayInTashkent(new Date(Date.UTC(2026, 8, 15, 1, 30)))).toBe('2026-09-15');
  });

  it('ish kuni 06:00 da almashadi', () => {
    // 2026-09-14 20:30 UTC = 2026-09-15 01:30 Toshkent — hali kechagi ish kuni
    expect(todayInTashkent(new Date(Date.UTC(2026, 8, 14, 20, 30)))).toBe('2026-09-14');
    // 00:59 UTC = 05:59 Toshkent — kechagi; 01:00 UTC = 06:00 — bugungi
    expect(todayInTashkent(new Date(Date.UTC(2026, 8, 15, 0, 59)))).toBe('2026-09-14');
    expect(todayInTashkent(new Date(Date.UTC(2026, 8, 15, 1, 0)))).toBe('2026-09-15');
  });
});
