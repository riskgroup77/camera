import { describe, expect, it } from 'vitest';
import {
  arrivalBars,
  barTitle,
  bucketsFromPeople,
  clockMinutes,
  formatClock,
  tashkentMinutes,
  timeFraction,
  visibleBars,
  type HourBucket,
} from './arrivals';

const buckets: HourBucket[] = [
  { hour: 6, students: 0, staff: 0, studentsLate: 0, staffLate: 0 },
  { hour: 7, students: 12, staff: 4, studentsLate: 0, staffLate: 0 },
  { hour: 8, students: 64, staff: 3, studentsLate: 49, staffLate: 1 },
  { hour: 9, students: 58, staff: 1, studentsLate: 58, staffLate: 1 },
  { hour: 10, students: 0, staff: 0, studentsLate: 0, staffLate: 0 },
  { hour: 11, students: 0, staff: 0, studentsLate: 0, staffLate: 0 },
  { hour: 19, students: 0, staff: 0, studentsLate: 0, staffLate: 0 },
];

describe('arrivalBars', () => {
  it('splits each hour into on-time and late for the chosen population', () => {
    const students = arrivalBars(buckets, 'talaba');
    expect(students.find((b) => b.hour === 8)).toEqual({ hour: 8, total: 64, late: 49, onTime: 15 });
    const staff = arrivalBars(buckets, 'xodim');
    expect(staff.find((b) => b.hour === 8)).toEqual({ hour: 8, total: 3, late: 1, onTime: 2 });
  });

  it('treats a missing late split (older server) as on time and never goes negative', () => {
    const bars = arrivalBars([{ hour: 8, students: 5, staff: 0 }, { hour: 9, students: 2, staff: 0, studentsLate: 9 }], 'talaba');
    expect(bars[0]).toEqual({ hour: 8, total: 5, late: 0, onTime: 5 });
    expect(bars[1]).toEqual({ hour: 9, total: 2, late: 2, onTime: 0 });
  });
});

describe('visibleBars', () => {
  const bars = arrivalBars(buckets, 'talaba');

  it('runs from 07:00 to the current hour today, trailing empty hours trimmed', () => {
    expect(visibleBars(bars, { isToday: true, nowHour: 13 }).map((b) => b.hour)).toEqual([7, 8, 9, 10, 11, 12, 13]);
  });

  it('stops at 18:00 in the evening unless someone arrived later', () => {
    expect(visibleBars(bars, { isToday: true, nowHour: 23 }).map((b) => b.hour).at(-1)).toBe(18);
    const late = arrivalBars([{ hour: 8, students: 3, staff: 0 }, { hour: 20, students: 1, staff: 0 }], 'talaba');
    expect(visibleBars(late, { isToday: true, nowHour: 23 }).map((b) => b.hour).at(-1)).toBe(20);
  });

  it('ends at the last arrival on a past day', () => {
    expect(visibleBars(bars, { isToday: false, nowHour: 23 }).map((b) => b.hour)).toEqual([7, 8, 9]);
  });

  it('starts earlier when someone came before 07:00 and is empty when nobody came', () => {
    const early = arrivalBars([{ hour: 6, students: 1, staff: 0 }, { hour: 8, students: 3, staff: 0 }], 'talaba');
    expect(visibleBars(early, { isToday: false, nowHour: 0 }).map((b) => b.hour)).toEqual([6, 7, 8]);
    expect(visibleBars(arrivalBars([{ hour: 8, students: 0, staff: 0 }], 'talaba'), { isToday: true, nowHour: 9 })).toEqual([]);
  });
});

describe('time helpers', () => {
  it('parses and formats clock strings', () => {
    expect(clockMinutes('08:10')).toBe(490);
    expect(clockMinutes('8:05')).toBe(485);
    expect(clockMinutes('25:00')).toBeNull();
    expect(clockMinutes(null)).toBeNull();
    expect(formatClock(490)).toBe('08:10');
  });

  it('places a time on the visible axis', () => {
    const bars = visibleBars(arrivalBars(buckets, 'talaba'), { isToday: false, nowHour: 0 }); // 07..09
    expect(timeFraction(clockMinutes('08:10'), bars)).toBeCloseTo((70 / 180), 5);
    expect(timeFraction(clockMinutes('06:00'), bars)).toBeNull();
    expect(timeFraction(clockMinutes('11:00'), bars)).toBeNull();
  });

  it('reads Tashkent time regardless of the browser zone', () => {
    // 2026-10-05 08:40 UTC = 13:40 Toshkent (UTC+5)
    expect(tashkentMinutes(Date.UTC(2026, 9, 5, 8, 40))).toBe(13 * 60 + 40);
  });

  it('describes a bar in plain words', () => {
    expect(barTitle({ hour: 8, total: 64, late: 49, onTime: 15 })).toBe('08:00–08:59 · 64 kishi keldi, shundan 49 tasi kech');
    expect(barTitle({ hour: 7, total: 12, late: 0, onTime: 12 })).toBe('07:00–07:59 · 12 kishi keldi, hammasi o‘z vaqtida');
  });
});

describe('bucketsFromPeople (guruh grafigi)', () => {
  it('splits a group by arrival hour, late part from the record status, untimed apart', () => {
    const { buckets, untimed } = bucketsFromPeople([
      { checkIn: '08:05', status: 'keldi' },
      { checkIn: '08:40', status: 'kech_keldi' },
      { checkIn: '13:00', status: 'keldi' },
      { checkIn: null, status: 'keldi' },
      { checkIn: null, status: 'kelmadi' },
      { checkIn: null, status: 'kutilmoqda' },
    ]);
    expect(buckets).toEqual([
      { hour: 8, students: 2, staff: 0, studentsLate: 1, staffLate: 0 },
      { hour: 13, students: 1, staff: 0, studentsLate: 0, staffLate: 0 },
    ]);
    expect(untimed).toBe(1);
  });
});
