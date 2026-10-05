import { describe, expect, it } from 'vitest';
import type { AttendanceDay } from '../types';
import {
  buildMonthGrid,
  dayLabel,
  isValidMonth,
  keyboardTarget,
  leadingBlanks,
  monthLabel,
  monthStats,
  presenceMinutes,
  shiftMonth,
  shortMonthLabel,
} from './attendanceCalendar';

const RECORDS: AttendanceDay[] = [
  { date: '2026-09-01', status: 'keldi', checkIn: '08:30', checkOut: '17:30' },
  { date: '2026-09-02', status: 'kech_keldi', checkIn: '09:30', checkOut: '13:00', earlyLeave: true },
  { date: '2026-09-06', status: 'dam_olish' },
];
const MONDAY_TO_SATURDAY = [1, 2, 3, 4, 5, 6];

describe('month helpers', () => {
  it('shifts across year boundaries', () => {
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
    expect(shiftMonth('2026-09', -12)).toBe('2025-09');
  });

  it('accepts only YYYY-MM', () => {
    expect(isValidMonth('2026-09')).toBe(true);
    expect(isValidMonth('2026-13')).toBe(false);
    expect(isValidMonth('2026-9')).toBe(false);
    expect(isValidMonth(null)).toBe(false);
  });

  it('formats Uzbek labels', () => {
    expect(monthLabel('2026-09')).toBe('Sentabr 2026');
    expect(shortMonthLabel('2026-06')).toBe('Iyn');
    expect(shortMonthLabel('2026-07')).toBe('Iyl');
    expect(dayLabel('2026-09-15')).toBe('15-sentabr 2026, seshanba');
  });
});

describe('buildMonthGrid', () => {
  const cells = buildMonthGrid(RECORDS, '2026-09', '2026-09-15', MONDAY_TO_SATURDAY);
  const cell = (date: string) => {
    const found = cells.find((c) => c.date === date);
    if (!found) throw new Error(`no cell ${date}`);
    return found;
  };

  it('covers every day and starts weeks on Monday', () => {
    expect(cells).toHaveLength(30);
    expect(leadingBlanks('2026-09')).toBe(1); // 1-sentabr — seshanba
  });

  it('never turns a day without a record into an absence', () => {
    expect(cell('2026-09-05').status).toBe('malumot_yoq'); // shanba — ish kuni
    expect(cell('2026-09-13').status).toBe('dam_olish'); // yakshanba
    expect(cell('2026-09-16').status).toBe('kelajak');
    expect(cell('2026-09-15')).toMatchObject({ isToday: true, status: 'malumot_yoq' });
  });

  it('derives time in the building from check-in and check-out', () => {
    expect(cell('2026-09-01').presenceMinutes).toBe(540);
    expect(presenceMinutes('09:00', '08:00')).toBeNull();
    expect(presenceMinutes('09:00', null)).toBeNull();
  });

  it('computes month stats with the same rules as the server summary', () => {
    expect(monthStats(cells)).toEqual({
      recordedDays: 2,
      present: 1,
      late: 1,
      absent: 0,
      earlyLeave: 1,
      rate: 100,
      avgArrival: '09:00',
      avgPresenceMinutes: 375,
      missingWorkDays: 11,
    });
  });

  it('moves keyboard focus by day and by week', () => {
    expect(keyboardTarget('2026-09-15', 'ArrowDown')).toBe('2026-09-22');
    expect(keyboardTarget('2026-09-01', 'ArrowLeft')).toBe('2026-08-31');
    expect(keyboardTarget('2026-09-15', 'Enter')).toBeNull();
  });
});
