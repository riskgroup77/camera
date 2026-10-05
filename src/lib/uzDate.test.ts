import { describe, expect, it } from 'vitest';
import { addDays, daysBetweenInclusive, formatMinutes, relativeTime } from './uzDate';

const NOW = new Date('2026-09-15T12:00:00+05:00');

describe('relativeTime', () => {
  it('yaqin vaqtlar', () => {
    expect(relativeTime('2026-09-15T11:59:40+05:00', NOW)).toBe('hozirgina');
    expect(relativeTime('2026-09-15T12:00:30+05:00', NOW)).toBe('hozirgina'); // soat farqi
    expect(relativeTime('2026-09-15T11:48:00+05:00', NOW)).toBe('12 daq oldin');
    expect(relativeTime('2026-09-15T09:00:00+05:00', NOW)).toBe('3 soat oldin');
  });

  it('uzoq vaqtlar', () => {
    expect(relativeTime('2026-09-13T12:00:00+05:00', NOW)).toBe('2 kun oldin');
    expect(relativeTime('2026-09-01T12:00:00+05:00', NOW)).toBe('2026-09-01');
    expect(relativeTime('yaroqsiz', NOW)).toBe('');
  });
});

describe('formatMinutes', () => {
  it('daqiqa, soat va kunlar', () => {
    expect(formatMinutes(null)).toBe('—');
    expect(formatMinutes(0.4)).toBe('1 daq dan kam');
    expect(formatMinutes(45)).toBe('45 daq');
    expect(formatMinutes(150)).toBe('2,5 soat');
    expect(formatMinutes(60 * 72)).toBe('3 kun');
  });
});

describe('sana arifmetikasi', () => {
  it('oy va yil chegaralari', () => {
    expect(addDays('2026-02-28', 1)).toBe('2026-03-01');
    expect(addDays('2026-01-01', -1)).toBe('2025-12-31');
    expect(daysBetweenInclusive('2026-09-01', '2026-09-15')).toBe(15);
  });
});
