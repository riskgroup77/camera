import { describe, expect, it } from 'vitest';
import type { Counts, GroupStat, GroupStudent } from './situationApi';
import {
  applyArrival,
  averageRate,
  computeRate,
  countSegments,
  countsFromStudents,
  filterStudents,
  groupsToCourses,
  lessonRate,
  monthsInRange,
  normalizeText,
  sortGroups,
  sortStudents,
  sumCounts,
  toClock,
  visitsByDate,
} from './studentAttendance';

const counts = (over: Partial<Counts> = {}): Counts => ({
  total: 10, enrolled: 10, present: 6, late: 2, absent: 2, dayOff: 0, notYet: 2, noData: 0, rate: 60, ...over,
});

const student = (id: string, fullName: string, status: GroupStudent['status'], checkIn: string | null = null): GroupStudent => ({
  id, fullName, photoUrl: null, initials: '', status, checkIn, checkOut: null, biometricsStatus: 'tasdiqlangan',
});

const group = (name: string, rate: number | null, course: number | null = 1): GroupStat => ({
  ...counts({ rate }), name, facultyId: null, faculty: null, course, curator: null,
});

describe('studentAttendance', () => {
  it('computeRate follows server rule and returns null for empty base', () => {
    expect(computeRate(6, 2, 2)).toBe(60);
    expect(computeRate(1, 2, 0)).toBe(33.3);
    expect(computeRate(0, 0, 0)).toBeNull();
  });

  it('sumCounts adds and recomputes rate', () => {
    const s = sumCounts([counts(), counts({ present: 10, late: 0, absent: 0, notYet: 0 })]);
    expect(s.total).toBe(20);
    expect(s.present).toBe(16);
    expect(s.rate).toBe(80);
  });

  it('countSegments splits on-time from late', () => {
    const seg = countSegments(counts());
    // Keldi, kech keldi, kelmadi, hali kelmagan, ma'lumot yo'q, dam olish.
    // Dam olish alohida: u o'lchanmagan kun emas, o'lchanishi shart bo'lmagan kun.
    expect(seg.map((x) => x.value)).toEqual([4, 2, 2, 2, 0, 0]);
    expect(seg.map((x) => x.label)).toEqual(['Keldi', 'Kech keldi', 'Kelmadi', 'Hali kelmagan', "Ma'lumot yo'q", 'Dam olish']);
  });

  it('countSegments keeps a day off out of the unknown segment', () => {
    const seg = countSegments({ ...counts(), noData: 1, dayOff: 3 });
    expect(seg[4]).toMatchObject({ label: "Ma'lumot yo'q", value: 1 });
    expect(seg[5]).toMatchObject({ label: 'Dam olish', value: 3 });
  });

  it('countsFromStudents tallies statuses', () => {
    const c = countsFromStudents([student('1', 'A', 'keldi'), student('2', 'B', 'kech_keldi'), student('3', 'C', 'kutilmoqda')]);
    expect(c).toMatchObject({ total: 3, present: 2, late: 1, notYet: 1, rate: 66.7 });
  });

  it('applyArrival updates only matching student and keeps identity otherwise', () => {
    const list = [student('1', 'A', 'kutilmoqda'), student('2', 'B', 'kelmadi')];
    expect(applyArrival(list, { personId: 'x', status: 'keldi', checkIn: '08:00' })).toBe(list);
    const next = applyArrival(list, { personId: '2', status: 'kech_keldi', checkIn: '09:10' });
    expect(next[1]).toMatchObject({ status: 'kech_keldi', checkIn: '09:10' });
    expect(applyArrival(next, { personId: '2', status: 'kech_keldi', checkIn: '09:10' })).toBe(next);
  });

  it('filterStudents matches apostrophe variants case-insensitively', () => {
    const list = [student('1', "G'ulomov Ali", 'keldi'), student('2', 'Karimova Nodira', 'kelmadi')];
    expect(filterStudents(list, 'all', 'gʻulom').map((s) => s.id)).toEqual(['1']);
    expect(filterStudents(list, 'kelmadi', '').map((s) => s.id)).toEqual(['2']);
    expect(normalizeText('  A  B ')).toBe('a b');
  });

  it('sortStudents by status puts absent first, by arrival earliest first', () => {
    const list = [student('1', 'B', 'keldi', '08:30'), student('2', 'A', 'kelmadi'), student('3', 'C', 'keldi', '07:50')];
    expect(sortStudents(list, 'status').map((s) => s.id)).toEqual(['2', '1', '3']);
    expect(sortStudents(list, 'arrival').map((s) => s.id)).toEqual(['3', '1', '2']);
  });

  it('sortGroups keeps null rates last', () => {
    const list = [group('B', null), group('A', 90), group('C', 50)];
    expect(sortGroups(list, 'rate-asc').map((g) => g.name)).toEqual(['C', 'A', 'B']);
    expect(sortGroups(list, 'rate-desc').map((g) => g.name)).toEqual(['A', 'C', 'B']);
  });

  it('groupsToCourses groups by course with null last', () => {
    const blocks = groupsToCourses([group('X', 50, null), group('B', 50, 2), group('A', 50, 2), group('C', 50, 1)]);
    expect(blocks.map((b) => b.label)).toEqual(['1-kurs', '2-kurs', "Kurs ko'rsatilmagan"]);
    expect(blocks[1].groups.map((g) => g.name)).toEqual(['A', 'B']);
    expect(blocks[1].totals.total).toBe(20);
  });

  it('lessonRate uses seen before finalization', () => {
    expect(lessonRate({ expected: 20, present: 15, seen: 10, finalized: true })).toBe(75);
    expect(lessonRate({ expected: 20, present: 0, seen: 10, finalized: false })).toBe(50);
    expect(lessonRate({ expected: 0, present: 0, seen: 0, finalized: true })).toBeNull();
  });

  it('toClock converts ISO to Tashkent time', () => {
    expect(toClock('2026-09-19T03:12:00Z')).toBe('08:12');
    expect(toClock('9:05:30')).toBe('09:05');
    expect(toClock(null)).toBeNull();
  });

  it('monthsInRange spans years and limits', () => {
    expect(monthsInRange('2025-11-20', '2026-02-01')).toEqual(['2025-11', '2025-12', '2026-01', '2026-02']);
    expect(monthsInRange('2026-01-01', '2026-06-01', 2)).toEqual(['2026-05', '2026-06']);
    expect(monthsInRange('2026-02-01', '2026-01-01')).toEqual([]);
  });

  it('averageRate skips null days', () => {
    expect(averageRate([{ rate: 80 }, { rate: null }, { rate: 90 }])).toBe(85);
    expect(averageRate([{ rate: null }])).toBeNull();
  });

  it('visitsByDate groups newest first', () => {
    const v = (id: string, date: string, firstSeen: string) => ({ id, date, camera: 'c', building: null, zone: null, firstSeen, lastSeen: firstSeen, durationMinutes: 5, sightings: 1 });
    const out = visitsByDate([v('1', '2026-09-18', '08:00'), v('2', '2026-09-19', '08:00'), v('3', '2026-09-19', '10:00')]);
    expect(out.map((d) => d.date)).toEqual(['2026-09-19', '2026-09-18']);
    expect(out[0].visits.map((x) => x.id)).toEqual(['3', '2']);
    expect(out[0].minutes).toBe(10);
  });
});

import {
  daysBetween,
  enrollPace,
  enrolledPct,
  hasAttendanceData,
  neededPerDay,
  personKpis,
  previousRange,
  projectCompletion,
  recordSnapshot,
  weekdayPattern,
} from './studentAttendance';
import type { CalendarDay } from './situationApi';

describe('yuz topshirish yordamchilari', () => {
  it('enrolledPct / hasAttendanceData', () => {
    expect(enrolledPct({ total: 0, enrolled: 0 })).toBeNull();
    expect(enrolledPct({ total: 3, enrolled: 1 })).toBe(33.3);
    expect(hasAttendanceData({ total: 20, enrolled: 9 })).toBe(false);
    expect(hasAttendanceData({ total: 20, enrolled: 10 })).toBe(true);
  });

  it('recordSnapshot: shu kunni almashtiradi, tartiblaydi, 60 tadan oshmaydi', () => {
    let list = recordSnapshot([], '2026-09-10', 5);
    list = recordSnapshot(list, '2026-09-08', 1);
    list = recordSnapshot(list, '2026-09-10', 7);
    expect(list).toEqual([
      { date: '2026-09-08', confirmed: 1 },
      { date: '2026-09-10', confirmed: 7 },
    ]);
    const many = Array.from({ length: 70 }, (_, i) => ({ date: `2026-0${i < 30 ? 6 : 7}-${String((i % 30) + 1).padStart(2, '0')}`, confirmed: i }));
    expect(recordSnapshot(many, '2026-09-19', 100)).toHaveLength(60);
  });

  it('enrollPace va prognoz', () => {
    expect(enrollPace([{ date: '2026-09-19', confirmed: 2 }], '2026-09-19')).toBeNull();
    const pace = enrollPace(
      [
        { date: '2026-09-01', confirmed: 0 },
        { date: '2026-09-15', confirmed: 10 },
        { date: '2026-09-19', confirmed: 50 },
      ],
      '2026-09-19',
    );
    expect(pace).toEqual({ perDay: 10, days: 4 });
    expect(projectCompletion(95, 10, '2026-09-19')).toBe('2026-09-29');
    expect(projectCompletion(10, 0, '2026-09-19')).toBeNull();
    expect(projectCompletion(0, 0, '2026-09-19')).toBe('2026-09-19');
  });

  it('neededPerDay / daysBetween / previousRange', () => {
    expect(daysBetween('2026-09-19', '2026-10-01')).toBe(12);
    expect(neededPerDay(120, '2026-09-19', '2026-10-01')).toBe(10);
    expect(neededPerDay(120, '2026-09-19', '2026-09-01')).toBe(120);
    expect(neededPerDay(120, '2026-09-19', '')).toBeNull();
    expect(previousRange('2026-09-10', '2026-09-19')).toEqual({ from: '2026-08-31', to: '2026-09-09' });
  });
});

describe('shaxs KPI', () => {
  const day = (date: string, status: CalendarDay['status'], checkIn: string | null = null): CalendarDay => ({ date, status, checkIn, checkOut: null });
  const cal = [
    day('2026-09-14', 'kech_keldi', '09:20'), // Du
    day('2026-09-15', 'keldi', '08:40'),
    day('2026-09-16', 'kelmadi'),
    day('2026-09-17', 'keldi', '08:50'),
    day('2026-09-18', 'malumot_yoq'),
    day('2026-09-19', 'keldi', '08:30'), // Sha
  ];
  it('personKpis', () => {
    const k = personKpis(cal);
    expect(k.presentDays).toBe(4);
    expect(k.lateDays).toBe(1);
    expect(k.absentDays).toBe(1);
    expect(k.rate).toBe(80);
    expect(k.avgArrivalMinutes).toBe(Math.round((560 + 520 + 530 + 510) / 4));
    expect(k.onTimeStreak).toBe(2);
    expect(k.punctualPct).toBe(75);
  });
  it('weekdayPattern', () => {
    const w = weekdayPattern(cal);
    expect(w).toHaveLength(6);
    expect(w[0]).toMatchObject({ label: 'Du', late: 1, avgArrivalMinutes: 560 });
    expect(w[2]).toMatchObject({ label: 'Cho', absent: 1, avgArrivalMinutes: null });
    expect(w[5]).toMatchObject({ label: 'Sha', present: 1 });
  });
});

import { LATE_CUTOFF_MINUTES as POLICY_DEFAULT_LATE, lateAfterMinutes } from './studentAttendance';

describe('lateAfterMinutes', () => {
  it("attendance_policy chegarasini daqiqaga o'giradi, standart — 08:10", () => {
    expect(lateAfterMinutes('08:10')).toBe(490);
    expect(lateAfterMinutes('09:40')).toBe(580);
    expect(lateAfterMinutes(undefined)).toBe(POLICY_DEFAULT_LATE);
    expect(POLICY_DEFAULT_LATE).toBe(490);
  });
});

import { countsByStatus, matchesFilter } from './studentAttendance';

describe("«Ma'lumot yo'q» filtri plitkadagi son bilan bir xil", () => {
  // Plitka noData + dayOff ni ko'rsatadi, demak filtri ham ikkalasini olishi
  // kerak — aks holda "Ma'lumot yo'q: 3" bosilganda setkada 2 ta talaba qolardi.
  const list = [
    student('a', 'Aliyev A', 'malumot_yoq'),
    student('b', 'Botirov B', 'dam_olish'),
    student('c', 'Choriyev C', 'keldi'),
  ];

  it('dam_olish ham kiradi', () => {
    expect(filterStudents(list, 'malumot_yoq', '').map((s) => s.id)).toEqual(['a', 'b']);
    expect(matchesFilter('dam_olish', 'malumot_yoq')).toBe(true);
    expect(matchesFilter('keldi', 'malumot_yoq')).toBe(false);
  });

  it("filtrlangan soni plitkadagi son bilan teng", () => {
    const tally = countsByStatus(countsFromStudents(list));
    expect(filterStudents(list, 'malumot_yoq', '')).toHaveLength(tally.malumot_yoq + tally.dam_olish);
  });

  it("boshqa filtrlar o'zgarmaydi", () => {
    expect(filterStudents(list, 'keldi', '').map((s) => s.id)).toEqual(['c']);
    expect(filterStudents(list, 'dam_olish', '').map((s) => s.id)).toEqual(['b']);
    expect(filterStudents(list, 'all', '')).toHaveLength(3);
  });
});


describe("«Kelish vaqti» saralashi to'ldirilmagan soatni ham to'g'ri joylaydi", () => {
  it("\"9:05\" \"10:05\" dan oldin turadi", () => {
    // Ilgari satrlar solishtirilardi: "9:05" > "10:05" chiqib, kech kelgan
    // talaba ro'yxat boshiga tushardi.
    const list = [
      student('late', 'Zokirov Z', 'kech_keldi', '10:05'),
      student('early', 'Aliyev A', 'keldi', '9:05'),
    ];
    expect(sortStudents(list, 'arrival').map((s) => s.id)).toEqual(['early', 'late']);
  });

  it("kelmaganlar hamisha oxirida, diqqat tartibida", () => {
    const list = [
      student('absent', 'Bekov B', 'kelmadi'),
      student('waiting', 'Aliyev A', 'kutilmoqda'),
      student('came', 'Choriyev C', 'keldi', '08:30'),
    ];
    expect(sortStudents(list, 'arrival').map((s) => s.id)).toEqual(['came', 'absent', 'waiting']);
  });
});
