import { describe, expect, it } from 'vitest';
import type { AnalyticsDaily, Counts, FacultyCounts, KafedraStat } from '../lib/situationApi';
import {
  addCounts,
  breakdown,
  EMPTY_COUNTS,
  filterUnits,
  mergeDaily,
  pct,
  rateOf,
  rowsForScope,
  staffUnitRows,
  studentUnitRows,
  trendValues,
  worstFirst,
  type UnitRow,
} from './attendance';
import { nextScopeParams, parseScope } from './consoleFilter';

function counts(patch: Partial<Counts>): Counts {
  const base = { ...EMPTY_COUNTS, ...patch };
  return { ...base, rate: rateOf(base) };
}

describe('rateOf', () => {
  it('backend formulasi: present / (present + absent + notYet)', () => {
    expect(rateOf({ present: 9, absent: 1, notYet: 0 })).toBe(90);
    expect(rateOf({ present: 1, absent: 1, notYet: 2 })).toBe(25);
  });

  it("o'lchanmagan kun — null, nol emas", () => {
    expect(rateOf({ present: 0, absent: 0, notYet: 0 })).toBeNull();
  });

  it("noData va dam olish foizga kirmaydi (chaqiruvchi ularni uzatmaydi)", () => {
    expect(rateOf({ present: 10, absent: 0, notYet: 0 })).toBe(100);
  });
});

describe('addCounts', () => {
  it('foizni qayta hisoblaydi, o‘rtachalamaydi', () => {
    const staff = counts({ total: 10, present: 10 });
    const students = counts({ total: 90, present: 45, absent: 45 });
    const all = addCounts(staff, students);
    expect(all.present).toBe(55);
    expect(all.rate).toBe(55);
    // Foizlarning o'rtachasi (100 + 50) / 2 = 75 bo'lardi — noto'g'ri.
    expect(all.rate).not.toBe(75);
  });
});

describe('breakdown', () => {
  it("bo'laklar yig'indisi jamiga teng", () => {
    const c = counts({ total: 100, present: 60, late: 10, absent: 20, notYet: 5, noData: 10, dayOff: 5 });
    const parts = breakdown(c);
    const sum = parts.reduce((acc, part) => acc + part.value, 0);
    expect(sum).toBe(60 + 20 + 5 + 10 + 5);
    expect(parts.map((p) => p.value)).toEqual([50, 10, 20, 20]);
    expect(parts.reduce((acc, p) => acc + p.share, 0)).toBeCloseTo(100, 1);
  });

  it("bo'sh kunda ulush 0 — nolga bo'linish yo'q", () => {
    expect(breakdown(EMPTY_COUNTS).every((part) => part.share === 0)).toBe(true);
  });
});

describe('mergeDaily', () => {
  const day = (date: string, present: number, expected: number): AnalyticsDaily => ({
    date,
    present,
    late: 0,
    absent: expected - present,
    expected,
    rate: expected ? Math.round((present / expected) * 1000) / 10 : null,
    avgArrival: null,
  });

  it('bir sanadagi ikki turni qo‘shib, foizni qayta hisoblaydi', () => {
    const merged = mergeDaily([day('2026-09-01', 10, 10)], [day('2026-09-01', 30, 90)]);
    expect(merged).toHaveLength(1);
    expect(merged[0].present).toBe(40);
    expect(merged[0].expected).toBe(100);
    expect(merged[0].rate).toBe(40);
  });

  it('sanalar tartibda va to‘liq qoladi', () => {
    const merged = mergeDaily([day('2026-09-02', 1, 1)], [day('2026-09-01', 1, 2)]);
    expect(merged.map((row) => row.date)).toEqual(['2026-09-01', '2026-09-02']);
  });
});

describe('trendValues', () => {
  it("14 kunga to'g'rilaydi, yo'q kun — null (uzilish)", () => {
    const values = trendValues(
      [{ date: '2026-09-20', present: 1, late: 0, absent: 0, expected: 1, rate: 100, avgArrival: null }],
      '2026-09-21',
      3,
    );
    expect(values).toEqual([null, 100, null]);
  });

  it('standart uzunlik — 14', () => {
    expect(trendValues([], '2026-09-21')).toHaveLength(14);
  });
});

describe("bo'linma qatorlari", () => {
  const kafedra = (id: string, name: string, rate: number | null): KafedraStat => ({
    id,
    name,
    kind: 'kafedra',
    building: null,
    unassigned: false,
    staffTotal: 10,
    enrolled: 10,
    present: 8,
    late: 1,
    absent: 2,
    dayOff: 0,
    notYet: 0,
    noData: 0,
    rate,
    lessonsToday: 0,
    teacherLateLessons: 0,
    teacherMissedLessons: 0,
  });
  const faculty = (id: string | null, name: string, rate: number | null): FacultyCounts => ({
    ...EMPTY_COUNTS,
    id,
    name,
    total: 100,
    present: 50,
    rate,
  });

  it('kalitlar tur bilan ajratiladi — bir xil id to‘qnashmaydi', () => {
    const staff = staffUnitRows([kafedra('a', 'Fizika', 80)], () => 'Kafedra');
    const students = studentUnitRows([faculty('a', 'Fizika fakulteti', 70)]);
    expect(staff[0].key).not.toBe(students[0].key);
    expect(students[0].kindLabel).toBe('Fakultet');
  });

  it('fakultetsiz (id null) ham kalitga ega', () => {
    expect(studentUnitRows([faculty(null, 'Fakultetsiz', null)])[0].key).toBe('talaba:fakultetsiz');
  });

  it('rowsForScope filtrga mos qatorni beradi', () => {
    const staff = staffUnitRows([kafedra('a', 'A', 80)], () => 'Kafedra');
    const students = studentUnitRows([faculty('b', 'B', 70)]);
    expect(rowsForScope(staff, students, 'xodim')).toHaveLength(1);
    expect(rowsForScope(staff, students, 'talaba')[0].type).toBe('talaba');
    expect(rowsForScope(staff, students, 'hammasi')).toHaveLength(2);
  });

  it("worstFirst: past foiz birinchi, o'lchanmagan oxirida", () => {
    const rows = studentUnitRows([faculty('a', 'A', 90), faculty('b', 'B', null), faculty('c', 'C', 40)]);
    expect(worstFirst(rows).map((row) => row.name)).toEqual(['C', 'A', 'B']);
  });

  it('filterUnits apostrof turlarini farqlamaydi', () => {
    const rows: UnitRow[] = studentUnitRows([faculty('a', "Bo‘lim", 50)]);
    expect(filterUnits(rows, "bo'l")).toHaveLength(1);
    expect(filterUnits(rows, 'xxx')).toHaveLength(0);
    expect(filterUnits(rows, '  ')).toHaveLength(1);
  });
});

describe('pct', () => {
  it("o'lchanmaganni chiziqcha qiladi", () => {
    expect(pct(null)).toBe('—');
    expect(pct(Number.NaN)).toBe('—');
    expect(pct(87.4)).toBe('87%');
  });
});

describe('konsol filtri', () => {
  it('noma‘lum qiymat — hammasi', () => {
    expect(parseScope('xodim')).toBe('xodim');
    expect(parseScope('shaxs')).toBe('hammasi');
    expect(parseScope(null)).toBe('hammasi');
  });

  it('standart qiymat manzilda qolmaydi', () => {
    expect(nextScopeParams(new URLSearchParams('kim=xodim'), 'hammasi').toString()).toBe('');
    expect(nextScopeParams(new URLSearchParams('sana=2026-09-01'), 'talaba').get('sana')).toBe('2026-09-01');
  });
});
