import { describe, expect, it } from 'vitest';
import { nextViewDateParams, parseViewDate, withViewDate } from './viewDate';

const TODAY = '2026-09-19';

describe('parseViewDate', () => {
  it('defaults to today for missing, invalid or future dates', () => {
    expect(parseViewDate(null, TODAY)).toBe(TODAY);
    expect(parseViewDate('2026-02-30', TODAY)).toBe(TODAY);
    expect(parseViewDate('bugun', TODAY)).toBe(TODAY);
    expect(parseViewDate('2026-09-20', TODAY)).toBe(TODAY);
    expect(parseViewDate('2026-09-01', TODAY)).toBe('2026-09-01');
  });
});

describe('withViewDate', () => {
  it('adds ?sana= only for past dates and keeps existing query and hash', () => {
    expect(withViewDate('/talabalar/guruh/D-101', TODAY, TODAY)).toBe('/talabalar/guruh/D-101');
    expect(withViewDate('/talabalar/guruh/D-101', '2026-09-01', TODAY)).toBe('/talabalar/guruh/D-101?sana=2026-09-01');
    expect(withViewDate('/shaxs/5?tab=kalendar#top', '2026-09-01', TODAY)).toBe('/shaxs/5?tab=kalendar&sana=2026-09-01#top');
    expect(withViewDate('/shaxs/5?sana=2026-01-01', TODAY, TODAY)).toBe('/shaxs/5');
  });
});

describe('nextViewDateParams', () => {
  it('removes the param for today and clamps future dates', () => {
    const current = new URLSearchParams('tab=jurnal&sana=2026-09-01');
    expect(nextViewDateParams(current, TODAY, TODAY).toString()).toBe('tab=jurnal');
    expect(nextViewDateParams(current, '2026-12-31', TODAY).toString()).toBe('tab=jurnal');
    expect(nextViewDateParams(current, '2026-09-10', TODAY).toString()).toBe('tab=jurnal&sana=2026-09-10');
  });
});
