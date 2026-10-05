import { describe, expect, it } from 'vitest';
import { clampIsoDate, detectPreset, formatUzDate, formatUzRange, isIsoDate, rangeForPreset, relativeDayLabel } from './dates';

describe('date helpers', () => {
  it('validates real ISO dates', () => {
    expect(isIsoDate('2026-09-19')).toBe(true);
    expect(isIsoDate('2026-02-30')).toBe(false);
    expect(isIsoDate('19.09.2026')).toBe(false);
    expect(isIsoDate(null)).toBe(false);
  });

  it('formats Uzbek dates', () => {
    expect(formatUzDate('2026-09-19')).toBe('19-sentabr, 2026');
    expect(formatUzDate('2026-09-19', { year: false })).toBe('19-sentabr');
    expect(formatUzDate('2026-09-19', { weekday: true })).toBe('Shanba, 19-sentabr, 2026');
  });

  it('formats ranges compactly', () => {
    expect(formatUzRange('2026-09-01', '2026-09-19')).toBe('1–19-sentabr, 2026');
    expect(formatUzRange('2026-08-28', '2026-09-03')).toBe('28-avgust – 3-sentabr, 2026');
    expect(formatUzRange('2026-09-19', '2026-09-19')).toBe('19-sentabr, 2026');
  });

  it('labels today and yesterday', () => {
    expect(relativeDayLabel('2026-09-19', '2026-09-19')).toBe('Bugun');
    expect(relativeDayLabel('2026-09-18', '2026-09-19')).toBe('Kecha');
    expect(relativeDayLabel('2026-09-10', '2026-09-19')).toBeNull();
  });

  it('clamps to bounds', () => {
    expect(clampIsoDate('2026-10-01', undefined, '2026-09-19')).toBe('2026-09-19');
    expect(clampIsoDate('2026-01-01', '2026-02-01')).toBe('2026-02-01');
  });

  it('resolves and detects presets (week starts on Monday)', () => {
    const today = '2026-09-19'; // shanba
    expect(rangeForPreset('week', today)).toEqual({ preset: 'week', from: '2026-09-14', to: today });
    expect(rangeForPreset('month', today)).toEqual({ preset: 'month', from: '2026-09-01', to: today });
    expect(detectPreset({ from: '2026-09-14', to: today }, ['today', 'week', 'month'], today)).toBe('week');
    expect(detectPreset({ from: '2026-09-02', to: today }, ['today', 'week', 'month'], today)).toBe('custom');
  });
});
